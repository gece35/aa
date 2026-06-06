"""Backtest motoru — TDO v2 (Trend Devamlılığı Onayı v2).

Strateji üç katmanlı:

1) GİRİŞ (Çoklu filtre)
   - Skor ≥ 7 ve önceki gün skoru ≥ 7 (2 ardışık gün onayı)
   - Trend alt-skoru ≥ 2 (toplam 7 olsa bile EMA dizilimi bozuksa giriş yok)
   - Hacim ≥ 20-gün SMA (düşük hacimli kırılımları eler)
   - Endeks > EMA200 ve Endeks > EMA50 VEYA 20-gün getirisi > -%3 (dual rejim)
   - Kapanış ≥ 52-hafta yüksek × 0.85

2) ÇIKIŞ (3 aşamalı ATR trailing + kısmi TP + skor + zaman)
   - Aşama 1 (giriş → %4 kâr): sabit ATR stop = giriş − 2.5 × ATR
   - Aşama 2 (%4 → %6 kâr): break-even taşıma (entry × 1.005)
   - Aşama 3 (%6+ kâr): Chandelier trailing = max(highest_high(10), prev_stop) − 3 × ATR
   - Kısmi TP: %8'de pozisyonun %50'si satılır
   - Skor crash: tek günde -3 puan → kısmi (sadece partial alınmadıysa)
   - 3-bar düşük skor: 3 ardışık gün skor ≤ 4 → tam çıkış
   - Dead money: 20. günde getiri < +%1 ve skor ≤ 5 → tam çıkış
   - Zaman: 60 gün (zayıfsa kapatılır), 90 gün (zorunlu)

3) PORTFÖY DİSİPLİNİ
   - Eşzamanlı pozisyon: BIST 8, US 10
   - Aynı sektörde maks 3 pozisyon
   - ATR-bazlı pozisyon boyutu (sermayenin %1'i risk altında)
   - Maks tek pozisyon = portföyün %10'u
   - Drawdown freeze (aylık -%8): 14 gün yeni giriş yok
   - Drawdown halt (aylık -%15): tüm pozisyonlar kapatılır, 30 gün durur

Dönem: son 252 işlem günü (~1 yıl). Veri ısınma için 500 gün indirilir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .data_fetcher import download_ohlcv
from .scoring import compute_score_frame
from .sectors import get_sector
from .tickers import get_tickers

logger = logging.getLogger(__name__)

# ── Strateji sabitleri ────────────────────────────────────────────────────────

# Giriş
MIN_SCORE              = 7
ENTRY_CONSEC_DAYS      = 2
MIN_TREND_SUBSCORE     = 2
REQUIRE_VOLUME_ENTRY   = True
HIGH52W_FLOOR          = 0.85

# Rejim
USE_DUAL_REGIME        = True
REGIME_EMA_SHORT       = 50
REGIME_RECENT_DAYS     = 20
REGIME_RECENT_FLOOR    = -0.03

# ATR & trailing stop
ATR_PERIOD_BIST        = 20
ATR_PERIOD_US          = 14
ATR_INITIAL_MULT       = 2.5
ATR_TRAIL_MULT         = 3.0
TRAIL_LOOKBACK_DAYS    = 10
TRAILING_TRIGGER       = 0.06

# Kar realizasyonu
PARTIAL_TP_PCT         = 0.08
PARTIAL_TP_RATIO       = 0.50
BREAK_EVEN_TRIGGER     = 0.04
BREAK_EVEN_OFFSET      = 0.005

# Skor bazlı çıkış
EXIT_SCORE_THRESHOLD   = 4
EXIT_SCORE_CONSEC      = 3
SCORE_CRASH_DROP       = 3

# Zaman
MAX_HOLD_DAYS          = 60
HOLD_EXTENSION_DAYS    = 30
DEAD_MONEY_DAYS        = 20
DEAD_MONEY_RETURN      = 0.01

# Portföy
MAX_OPEN_POSITIONS_BIST = 8
MAX_OPEN_POSITIONS_US   = 10
MAX_PER_SECTOR          = 3
RISK_PER_TRADE          = 0.01
MAX_POSITION_PCT        = 0.10
DD_FREEZE_THRESHOLD     = 0.08
DD_FREEZE_DAYS          = 14
DD_HALT_THRESHOLD       = 0.15
DD_HALT_DAYS            = 30
DD_LOOKBACK_DAYS        = 21

# Genel
INITIAL_EQUITY          = 100000.0
BACKTEST_DAYS           = 252
MIN_HISTORY             = 250

MARKET_INDICES: Dict[str, str] = {
    "bist": "XU100.IS",
    "us":   "^GSPC",
}


# ── Pozisyon veri yapısı ─────────────────────────────────────────────────────

@dataclass
class Position:
    symbol: str
    sector: str
    entry_date: pd.Timestamp
    entry_price: float
    entry_atr: float
    qty_initial: float
    qty_current: float
    trailing_stop: float
    breakeven_taken: bool = False
    partial_taken: bool = False
    hold_days: int = 0


# ── Yardımcılar ──────────────────────────────────────────────────────────────

def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder'ın ATR'ini hesaplar."""
    high = df["High"].astype(float)
    low  = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _regime_series(index_df: pd.DataFrame) -> pd.Series:
    """Endeks > EMA200 → bullish (uzun vadeli rejim)."""
    close = index_df["Close"].astype(float)
    ema200 = close.ewm(span=200, adjust=False).mean()
    return close > ema200


def _regime_short_series(index_df: pd.DataFrame) -> pd.Series:
    """Endeks > EMA50 VEYA son 20-gün getirisi > -%3 (kısa vadeli rejim)."""
    close = index_df["Close"].astype(float)
    ema50 = close.ewm(span=REGIME_EMA_SHORT, adjust=False).mean()
    above_ema50 = close > ema50
    ret_20 = close.pct_change(REGIME_RECENT_DAYS)
    not_falling = ret_20 > REGIME_RECENT_FLOOR
    return above_ema50 | not_falling


def _score_series(df: pd.DataFrame, index_close: Optional[pd.Series] = None) -> Tuple[pd.Series, pd.Series]:
    """Birlesik puanlama motorundan (toplam_int, trend_sub) serilerini doner.

    Canli tarayici ile ayni `compute_score_frame` motorunu kullanir — backtest
    ekranda gosterilen puandan farkli bir sistemi test etmez.
    """
    frame = compute_score_frame(df, index_close)
    total = frame["total"].round().clip(0, 10).fillna(0).astype(int)
    trend = frame["trend"].fillna(0)
    return total, trend


# ── Sembol başına sinyal verisi inşası ──────────────────────────────────────

def _build_signals(symbol: str, df: pd.DataFrame, atr_period: int,
                   master_timeline: pd.DatetimeIndex,
                   index_close: Optional[pd.Series] = None) -> Optional[Dict[str, pd.Series]]:
    """Bir sembolün tüm sinyallerini hesaplar ve master timeline'a hizalar."""
    if df is None or df.empty or len(df) < MIN_HISTORY:
        return None
    try:
        total, trend = _score_series(df, index_close)
        atr = _atr_series(df, atr_period)
        high52w = df["Close"].rolling(252, min_periods=60).max()
        vol_sma20 = df["Volume"].rolling(20).mean() if "Volume" in df.columns else pd.Series(0.0, index=df.index)
    except Exception:
        logger.exception("Sinyal hesabı başarısız: %s", symbol)
        return None

    out = {
        "score":     total.reindex(master_timeline),
        "trend_sub": trend.reindex(master_timeline),
        "atr":       atr.reindex(master_timeline),
        "high52w":   high52w.reindex(master_timeline),
        "volume":    df["Volume"].reindex(master_timeline) if "Volume" in df.columns else pd.Series(0.0, index=master_timeline),
        "vol_sma20": vol_sma20.reindex(master_timeline),
        "open":      df["Open"].reindex(master_timeline),
        "high":      df["High"].reindex(master_timeline),
        "low":       df["Low"].reindex(master_timeline),
        "close":     df["Close"].reindex(master_timeline),
    }
    return out


# ── İşlem kaydı yardımcıları ─────────────────────────────────────────────────

def _make_trade_record(pos: Position, exit_price: float, exit_date: pd.Timestamp,
                       reason: str, qty: float) -> dict:
    ret_pct = (exit_price - pos.entry_price) / pos.entry_price * 100 if pos.entry_price > 0 else 0.0
    portion = qty / pos.qty_initial * 100 if pos.qty_initial > 0 else 0.0
    return {
        "sembol":       pos.symbol,
        "giris_tarihi": str(pos.entry_date.date()),
        "cikis_tarihi": str(exit_date.date()),
        "giris_fiyati": round(pos.entry_price, 4),
        "cikis_fiyati": round(exit_price, 4),
        "getiri_pct":   round(ret_pct, 2),
        "sure_gun":     pos.hold_days,
        "cikis_nedeni": reason,
        "kazandi":      ret_pct > 0,
        "miktar_pct":   round(portion, 1),
    }


def _close_position_full(pos: Position, exit_price: float, exit_date: pd.Timestamp,
                         reason: str, trades: List[dict]) -> float:
    """Pozisyonun kalan tamamını kapatır, cash iadesini döndürür."""
    qty = pos.qty_current
    cash_back = qty * exit_price
    trades.append(_make_trade_record(pos, exit_price, exit_date, reason, qty))
    pos.qty_current = 0.0
    return cash_back


def _close_position_partial(pos: Position, exit_price: float, exit_date: pd.Timestamp,
                            reason: str, ratio: float, trades: List[dict]) -> float:
    """Pozisyonun bir kısmını kapatır (qty_initial × ratio kadar), cash iadesini döndürür."""
    qty = pos.qty_initial * ratio
    qty = min(qty, pos.qty_current)
    cash_back = qty * exit_price
    trades.append(_make_trade_record(pos, exit_price, exit_date, reason, qty))
    pos.qty_current -= qty
    pos.partial_taken = True
    return cash_back


# ── Portföy seviyesi simülasyon ──────────────────────────────────────────────

def _simulate_portfolio(market: str,
                        signal_data: Dict[str, Dict[str, pd.Series]],
                        regime_long: pd.Series,
                        regime_short: pd.Series,
                        master_timeline: pd.DatetimeIndex
                        ) -> Tuple[List[dict], List[Tuple[pd.Timestamp, float]], float]:
    max_open = MAX_OPEN_POSITIONS_BIST if market == "bist" else MAX_OPEN_POSITIONS_US

    cash: float = INITIAL_EQUITY
    positions: Dict[str, Position] = {}
    sector_count: Dict[str, int] = {}
    trades: List[dict] = []
    equity_curve: List[Tuple[pd.Timestamp, float]] = []

    freeze_until_idx: Optional[int] = None
    halt_until_idx: Optional[int] = None
    dd_freeze_count = 0
    dd_halt_count = 0

    n = len(master_timeline)
    start_idx = max(MIN_HISTORY, n - BACKTEST_DAYS - 1)

    for d_idx in range(start_idx, n):
        today = master_timeline[d_idx]

        # ── 1. Mevcut pozisyonları güncelle / çıkışları işle ────────────────
        for sym in list(positions.keys()):
            pos = positions[sym]
            sd = signal_data[sym]

            close_today  = sd["close"].iloc[d_idx]
            high_today   = sd["high"].iloc[d_idx]
            low_today    = sd["low"].iloc[d_idx]
            open_today   = sd["open"].iloc[d_idx]
            close_prev   = sd["close"].iloc[d_idx - 1] if d_idx > 0 else close_today
            atr_today    = sd["atr"].iloc[d_idx]
            score_today  = sd["score"].iloc[d_idx]
            score_prev   = sd["score"].iloc[d_idx - 1] if d_idx > 0 else score_today
            score_pp     = sd["score"].iloc[d_idx - 2] if d_idx > 1 else score_today

            if pd.isna(close_today) or pd.isna(open_today) or pd.isna(high_today) or pd.isna(low_today):
                continue

            pos.hold_days += 1

            # Trailing stop güncelle (önceki gün kapanışına göre)
            if not pd.isna(close_prev) and pos.entry_price > 0:
                gain_prev = (float(close_prev) - pos.entry_price) / pos.entry_price
                if not pos.breakeven_taken and gain_prev >= BREAK_EVEN_TRIGGER:
                    new_stop = pos.entry_price * (1 + BREAK_EVEN_OFFSET)
                    if new_stop > pos.trailing_stop:
                        pos.trailing_stop = new_stop
                    pos.breakeven_taken = True
                if gain_prev >= TRAILING_TRIGGER and not pd.isna(atr_today):
                    lookback_start = max(0, d_idx - TRAIL_LOOKBACK_DAYS)
                    highs_window = sd["high"].iloc[lookback_start:d_idx]
                    highs_clean = highs_window.dropna()
                    if not highs_clean.empty:
                        max_high = float(highs_clean.max())
                        new_trail = max_high - ATR_TRAIL_MULT * float(atr_today)
                        if new_trail > pos.trailing_stop:
                            pos.trailing_stop = new_trail

            # 1a. Stop hit (gap-aware)
            if float(low_today) <= pos.trailing_stop:
                exit_price = max(float(open_today), pos.trailing_stop)
                cash += _close_position_full(pos, exit_price, today, "trailing_stop", trades)
                sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                del positions[sym]
                continue

            # 1b. Kısmi TP
            if not pos.partial_taken and float(high_today) >= pos.entry_price * (1 + PARTIAL_TP_PCT):
                tp_price = max(float(open_today), pos.entry_price * (1 + PARTIAL_TP_PCT))
                cash += _close_position_partial(pos, tp_price, today, "kismi_tp", PARTIAL_TP_RATIO, trades)
                # Pozisyon devam eder

            # 1c. Skor crash → kısmi (sadece daha önce partial alınmadıysa)
            if (not pos.partial_taken and not pd.isna(score_today) and not pd.isna(score_prev)
                    and (int(score_prev) - int(score_today)) >= SCORE_CRASH_DROP):
                cash += _close_position_partial(pos, float(close_today), today, "score_crash",
                                                PARTIAL_TP_RATIO, trades)

            # 1d. 3-bar düşük skor → tam çıkış
            if (not pd.isna(score_today) and not pd.isna(score_prev) and not pd.isna(score_pp)
                    and int(score_today) <= EXIT_SCORE_THRESHOLD
                    and int(score_prev) <= EXIT_SCORE_THRESHOLD
                    and int(score_pp) <= EXIT_SCORE_THRESHOLD):
                cash += _close_position_full(pos, float(close_today), today, "score_3bar", trades)
                sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                del positions[sym]
                continue

            # 1e. Dead money @ 20. gün
            gain_today = (float(close_today) - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
            if (pos.hold_days == DEAD_MONEY_DAYS and gain_today < DEAD_MONEY_RETURN
                    and not pd.isna(score_today) and int(score_today) <= 5):
                cash += _close_position_full(pos, float(close_today), today, "dead_money", trades)
                sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                del positions[sym]
                continue

            # 1f. Zaman çıkışı
            if pos.hold_days >= MAX_HOLD_DAYS:
                if pos.hold_days < MAX_HOLD_DAYS + HOLD_EXTENSION_DAYS:
                    weak = (gain_today < 0.03) or (pd.isna(score_today) or int(score_today) < 7)
                    if weak:
                        cash += _close_position_full(pos, float(close_today), today, "time_exit", trades)
                        sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                        del positions[sym]
                        continue
                else:
                    cash += _close_position_full(pos, float(close_today), today, "time_extended", trades)
                    sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                    del positions[sym]
                    continue

        # ── 2. Bugünkü equity ───────────────────────────────────────────────
        market_value = 0.0
        for sym, pos in positions.items():
            ct = signal_data[sym]["close"].iloc[d_idx]
            if not pd.isna(ct):
                market_value += pos.qty_current * float(ct)
            else:
                market_value += pos.qty_current * pos.entry_price
        equity_today = cash + market_value
        equity_curve.append((today, equity_today))

        # ── 3. Drawdown kontrol ─────────────────────────────────────────────
        # Halt/freeze süresi doldu mu?
        if halt_until_idx is not None and d_idx >= halt_until_idx:
            halt_until_idx = None
        if freeze_until_idx is not None and d_idx >= freeze_until_idx:
            freeze_until_idx = None

        # Rolling pencerede peak (son DD_LOOKBACK_DAYS)
        recent_window = equity_curve[-DD_LOOKBACK_DAYS:]
        peak_recent = max(e[1] for e in recent_window)
        dd = (peak_recent - equity_today) / peak_recent if peak_recent > 0 else 0.0

        if halt_until_idx is None and dd >= DD_HALT_THRESHOLD:
            # Tüm pozisyonları kapat
            for sym in list(positions.keys()):
                pos = positions[sym]
                ct = signal_data[sym]["close"].iloc[d_idx]
                exit_p = float(ct) if not pd.isna(ct) else pos.entry_price
                cash += _close_position_full(pos, exit_p, today, "dd_halt", trades)
                sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                del positions[sym]
            halt_until_idx = min(d_idx + DD_HALT_DAYS, n - 1)
            dd_halt_count += 1
        elif halt_until_idx is None and freeze_until_idx is None and dd >= DD_FREEZE_THRESHOLD:
            freeze_until_idx = min(d_idx + DD_FREEZE_DAYS, n - 1)
            dd_freeze_count += 1

        # ── 4. Yeni girişler (halt/freeze veya rejim kapalıysa atla) ────────
        if halt_until_idx is not None or freeze_until_idx is not None:
            continue
        if d_idx + 1 >= n:
            continue

        regime_ok = True
        if d_idx < len(regime_long):
            rl = regime_long.iloc[d_idx] if not pd.isna(regime_long.iloc[d_idx]) else False
            regime_ok = bool(rl)
        if regime_ok and USE_DUAL_REGIME and d_idx < len(regime_short):
            rs = regime_short.iloc[d_idx] if not pd.isna(regime_short.iloc[d_idx]) else False
            regime_ok = bool(rs)
        if not regime_ok:
            continue

        # Aday hisseleri topla
        candidates: List[Tuple[str, int, int, float, float, str, float]] = []
        for sym, sd in signal_data.items():
            if sym in positions:
                continue
            score      = sd["score"].iloc[d_idx]
            score_prev = sd["score"].iloc[d_idx - 1] if d_idx > 0 else 0
            trend_sub  = sd["trend_sub"].iloc[d_idx]
            volume_t   = sd["volume"].iloc[d_idx]
            vol_sma    = sd["vol_sma20"].iloc[d_idx]
            close_t    = sd["close"].iloc[d_idx]
            high52w    = sd["high52w"].iloc[d_idx]
            atr_t      = sd["atr"].iloc[d_idx]
            next_open  = sd["open"].iloc[d_idx + 1]

            if any(pd.isna(x) for x in [score, score_prev, trend_sub, volume_t, vol_sma,
                                          close_t, high52w, atr_t, next_open]):
                continue
            if float(next_open) <= 0 or float(atr_t) <= 0:
                continue

            if (int(score) >= MIN_SCORE
                    and int(score_prev) >= MIN_SCORE
                    and int(trend_sub) >= MIN_TREND_SUBSCORE
                    and (not REQUIRE_VOLUME_ENTRY or float(volume_t) >= float(vol_sma))
                    and float(close_t) >= float(high52w) * HIGH52W_FLOOR):
                sector = get_sector(sym)
                candidates.append((sym, int(score), int(trend_sub),
                                   float(atr_t), float(close_t), sector, float(next_open)))

        # Öncelik sıralama: trend_sub ↓, atr/close ↑ (düşük volatilite önce), score ↓
        candidates.sort(key=lambda x: (-x[2], (x[3] / x[4]) if x[4] > 0 else float("inf"), -x[1]))

        for sym, score, trend_sub, atr_t, close_t, sector, next_open in candidates:
            if len(positions) >= max_open:
                break
            if sector_count.get(sector, 0) >= MAX_PER_SECTOR:
                continue
            if cash < next_open:
                continue

            atr_pct = atr_t / next_open
            if atr_pct <= 0:
                continue
            risk_amount = equity_today * RISK_PER_TRADE
            value_by_risk = risk_amount / (ATR_INITIAL_MULT * atr_pct)
            value_capped = min(value_by_risk, equity_today * MAX_POSITION_PCT, cash)
            if value_capped < next_open:
                continue
            qty = value_capped / next_open

            cash -= qty * next_open
            initial_stop = next_open - ATR_INITIAL_MULT * atr_t
            positions[sym] = Position(
                symbol=sym,
                sector=sector,
                entry_date=master_timeline[d_idx + 1],
                entry_price=next_open,
                entry_atr=atr_t,
                qty_initial=qty,
                qty_current=qty,
                trailing_stop=initial_stop,
            )
            sector_count[sector] = sector_count.get(sector, 0) + 1

    # ── Dönem sonu açık pozisyonları kapat ──────────────────────────────────
    last_idx = n - 1
    last_date = master_timeline[last_idx]
    for sym in list(positions.keys()):
        pos = positions[sym]
        ct = signal_data[sym]["close"].iloc[last_idx]
        exit_p = float(ct) if not pd.isna(ct) else pos.entry_price
        cash += _close_position_full(pos, exit_p, last_date, "acik_pozisyon", trades)

    final_equity = cash
    logger.info(
        "Portföy sim: %s — %d işlem, son equity=%.0f, dd_freeze=%d, dd_halt=%d",
        market, len(trades), final_equity, dd_freeze_count, dd_halt_count,
    )
    return trades, equity_curve, final_equity


# ── Özet istatistikler ───────────────────────────────────────────────────────

def _stats(trades: List[dict], equity_curve: Optional[List[Tuple[pd.Timestamp, float]]] = None) -> dict:
    if not trades:
        return {}
    returns = [t["getiri_pct"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    hold_avg = sum(t["sure_gun"] for t in trades) / len(trades)

    exit_dist: Dict[str, int] = {}
    for t in trades:
        exit_dist[t["cikis_nedeni"]] = exit_dist.get(t["cikis_nedeni"], 0) + 1

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    out = {
        "toplam_islem":         len(trades),
        "kazanma_orani_pct":    round(len(wins) / len(trades) * 100, 1),
        "ortalama_getiri_pct":  round(sum(returns) / len(returns), 2),
        "ortalama_kazanc_pct":  round(sum(wins) / len(wins), 2) if wins else 0.0,
        "ortalama_kayip_pct":   round(sum(losses) / len(losses), 2) if losses else 0.0,
        "en_iyi_islem_pct":     round(max(returns), 2),
        "en_kotu_islem_pct":    round(min(returns), 2),
        "toplam_getiri_pct":    round(sum(returns), 2),
        "ortalama_sure_gun":    round(hold_avg, 1),
        "cikis_dagilimlari":    exit_dist,
        "profit_factor":        profit_factor,
    }

    if equity_curve and len(equity_curve) >= 2:
        equities = [e[1] for e in equity_curve]
        peak = equities[0]
        max_dd = 0.0
        for v in equities:
            if v > peak:
                peak = v
            d = (peak - v) / peak if peak > 0 else 0
            if d > max_dd:
                max_dd = d
        out["max_drawdown_pct"] = round(max_dd * 100, 2)

        # Sharpe yaklaşımı (günlük getiriler, yıllıklaştırılmış)
        eq_arr = np.array(equities, dtype=float)
        daily_rets = np.diff(eq_arr) / eq_arr[:-1]
        if len(daily_rets) > 1 and daily_rets.std() > 0:
            sharpe = (daily_rets.mean() / daily_rets.std()) * np.sqrt(252)
            out["sharpe_approx"] = round(float(sharpe), 2)

        out["baslangic_equity"] = round(equities[0], 2)
        out["son_equity"] = round(equities[-1], 2)
        out["portfoy_getiri_pct"] = round((equities[-1] - equities[0]) / equities[0] * 100, 2)

    return out


# ── Ana backtest fonksiyonu ──────────────────────────────────────────────────

def run_backtest(market: str) -> dict:
    """Seçilen market için TDO v2 portföy backtest'i çalıştırır."""
    tickers = get_tickers(market)
    if not tickers:
        return {"hata": f"Bilinmeyen market: {market}"}

    logger.info("Backtest başladı: market=%s sembol_sayısı=%d", market, len(tickers))

    # Endeks verisini çek (rejim filtresi + master timeline)
    index_symbol = MARKET_INDICES.get(market)
    if not index_symbol:
        return {"hata": f"Endeks tanımı yok: {market}"}

    try:
        idx_data = download_ohlcv([index_symbol], period="500d", interval="1d")
        idx_df = idx_data.get(index_symbol)
    except Exception:
        logger.exception("Endeks verisi alınamadı: %s", index_symbol)
        return {"hata": f"Endeks verisi alınamadı: {index_symbol}"}

    if idx_df is None or idx_df.empty:
        return {"hata": f"Endeks verisi boş: {index_symbol}"}

    regime_long = _regime_series(idx_df)
    regime_short = _regime_short_series(idx_df)
    master_timeline = idx_df.index

    bullish_long = int(regime_long.fillna(False).sum())
    total_days = len(regime_long)
    logger.info(
        "Rejim filtresi: %s — %d/%d gün uzun-rejim bullish (%.0f%%)",
        index_symbol, bullish_long, total_days,
        bullish_long / total_days * 100 if total_days else 0,
    )

    # Tüm sembollerin verisini çek
    data: Dict[str, pd.DataFrame] = download_ohlcv(tickers, period="500d", interval="1d")
    atr_period = ATR_PERIOD_BIST if market == "bist" else ATR_PERIOD_US

    index_close = idx_df["Close"].astype(float)

    signal_data: Dict[str, Dict[str, pd.Series]] = {}
    for symbol in tickers:
        df = data.get(symbol)
        sd = _build_signals(symbol, df, atr_period, master_timeline, index_close)
        if sd is not None:
            signal_data[symbol] = sd

    if not signal_data:
        return {"hata": "Hiçbir sembol için yeterli veri yok"}

    trades, equity_curve, final_equity = _simulate_portfolio(
        market, signal_data, regime_long, regime_short, master_timeline,
    )

    # Hisse bazında gruplama
    by_symbol: Dict[str, List[dict]] = {}
    for t in trades:
        by_symbol.setdefault(t["sembol"], []).append(t)

    hisse_sonuclari: List[dict] = []
    for sym, sym_trades in by_symbol.items():
        sym_stats = _stats(sym_trades)
        hisse_sonuclari.append({
            "sembol":            sym,
            "islem_sayisi":      sym_stats["toplam_islem"],
            "kazanma_orani_pct": sym_stats["kazanma_orani_pct"],
            "toplam_getiri_pct": sym_stats["toplam_getiri_pct"],
            "islemler":          sym_trades,
        })
    hisse_sonuclari.sort(key=lambda x: x["toplam_getiri_pct"], reverse=True)

    genel_stats = _stats(trades, equity_curve)
    genel_stats["test_edilen_hisse"]  = len(signal_data)
    genel_stats["sinyal_veren_hisse"] = len(hisse_sonuclari)

    logger.info(
        "Backtest tamamlandı: %d hisse, %d işlem, kazanma=%s%%, PF=%s",
        len(hisse_sonuclari),
        len(trades),
        genel_stats.get("kazanma_orani_pct", "—"),
        genel_stats.get("profit_factor", "—"),
    )

    return {
        "market":    market,
        "donem":     "Son 1 yıl (~252 işlem günü)",
        "strateji":  "TDO v2 — Trend Devamlılığı Onayı",
        "parametreler": {
            "giris_skoru":          MIN_SCORE,
            "ardisik_gun":          ENTRY_CONSEC_DAYS,
            "min_trend_alt":        MIN_TREND_SUBSCORE,
            "hacim_zorunlu":        REQUIRE_VOLUME_ENTRY,
            "atr_periyodu":         atr_period,
            "atr_initial_mult":     ATR_INITIAL_MULT,
            "atr_trail_mult":       ATR_TRAIL_MULT,
            "kismi_tp_pct":         PARTIAL_TP_PCT * 100,
            "kismi_tp_oran":        PARTIAL_TP_RATIO * 100,
            "break_even_trigger":   BREAK_EVEN_TRIGGER * 100,
            "trailing_trigger":     TRAILING_TRIGGER * 100,
            "cikis_skoru":          EXIT_SCORE_THRESHOLD,
            "cikis_skoru_ardisik":  EXIT_SCORE_CONSEC,
            "skor_crash_dusus":     SCORE_CRASH_DROP,
            "max_sure_gun":         MAX_HOLD_DAYS,
            "uzatma_gun":           HOLD_EXTENSION_DAYS,
            "dead_money_gun":       DEAD_MONEY_DAYS,
            "max_pozisyon":         MAX_OPEN_POSITIONS_BIST if market == "bist" else MAX_OPEN_POSITIONS_US,
            "max_sektor":           MAX_PER_SECTOR,
            "risk_per_trade_pct":   RISK_PER_TRADE * 100,
            "max_pozisyon_pct":     MAX_POSITION_PCT * 100,
            "dd_freeze_pct":        DD_FREEZE_THRESHOLD * 100,
            "dd_halt_pct":          DD_HALT_THRESHOLD * 100,
            "rejim_filtresi":       index_symbol,
            "dual_rejim":           USE_DUAL_REGIME,
        },
        "ozet":      genel_stats,
        "hisseler":  hisse_sonuclari,
    }
