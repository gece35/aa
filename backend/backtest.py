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
   - Genişleme kısmi çıkış: ext_penalty < -2.0 AND kâr varsa → %50 sat (breakout muafiyetli)
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

# Giriş — olay-tabanlı (kesişim tetikleyici + trend yönü onayı)
MIN_SCORE              = 6
ENTRY_CONSEC_DAYS      = 2
MIN_TREND_SUBSCORE     = 1.2  # ema_align max 2.0; 1.2 = %60 doluluk esigi
REQUIRE_VOLUME_ENTRY   = True
HIGH52W_FLOOR          = 0.85
MIN_SCORE_EVENT        = 6    # olay-tabanlı girişte istenen min skor (2-gün-7 yerine)
ENTRY_TRIGGER_LOOKBACK = 2    # taze kesişim penceresi (bar): tetikleyici son N bar içinde olmalı
MIN_HOLD_SIGNAL_EXIT_US = 5   # ABD: sinyal_kirilim ilk N barda ateşlenemiyor (çırpınma koruması)

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

# Genişleme riski çıkışı
EXT_PEAK_EXIT          = -2.0   # ext_penalty bu eşiğin altında ve kâr varsa kısmi çıkış

# Kar realizasyonu
PARTIAL_TP_PCT         = 0.08
PARTIAL_TP_RATIO       = 0.50
BREAK_EVEN_TRIGGER     = 0.04
BREAK_EVEN_OFFSET      = 0.005

# Skor bazlı çıkış
EXIT_SCORE_THRESHOLD   = 4
EXIT_SCORE_CONSEC      = 3
SCORE_CRASH_DROP       = 4  # decay dogal dususe yol actigi icin esik yukseltildi

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


# ── Sembol başına sinyal verisi inşası ──────────────────────────────────────

def _build_signals(symbol: str, df: pd.DataFrame, atr_period: int,
                   master_timeline: pd.DatetimeIndex,
                   index_close: Optional[pd.Series] = None,
                   market: str = "bist") -> Optional[Dict[str, pd.Series]]:
    """Bir sembolün tüm sinyallerini hesaplar ve master timeline'a hizalar."""
    if df is None or df.empty or len(df) < MIN_HISTORY:
        return None
    try:
        frame       = compute_score_frame(df, index_close)
        total       = frame["total"].round().clip(0, 10).fillna(0).astype(int)
        trend       = frame["trend"].fillna(0)
        ext_penalty = frame["ext_penalty"].fillna(0)
        atr         = _atr_series(df, atr_period)
        high52w     = df["Close"].rolling(252, min_periods=60).max()
        vol_sma20   = df["Volume"].rolling(20).mean() if "Volume" in df.columns else pd.Series(0.0, index=df.index)

        # ── kesişim olay serileri (canlı skorlama motorundan) ──
        ema50_val  = frame["ema50_val"]
        ema200_val = frame["ema200_val"]
        # Trend yönü onayı: hiyerarşi yukarı (kapanış > EMA200 ve EMA50 > EMA200)
        trend_ok = ((df["Close"] > ema200_val) & (ema50_val > ema200_val)).astype(float)

        if market == "us":
            # ABD: daha katı boğa tetikleyici — en az 2 eş zamanlı yukarı kesişim
            # Tek kesişim S&P 500 büyük-cap hisselerinde gürültülü, çift onay kaliteyi artırır
            bull_count = (
                frame["x_macd_up"].fillna(False).astype(int)
                + frame["x_price_ema50_up"].fillna(False).astype(int)
                + frame["x_di_up"].fillna(False).astype(int)
                + frame["x_rsi50_up"].fillna(False).astype(int)
            )
            bull_trigger = (bull_count >= 2).astype(float).rolling(ENTRY_TRIGGER_LOOKBACK, min_periods=1).max()
            # ABD: ayı tetikleyici çift onay — MACD + ek sinyal VEYA EMA200 kırılımı (önemli seviye)
            bear_trigger = (
                (frame["x_macd_dn"].fillna(False)
                 & (frame["x_price_ema50_dn"].fillna(False) | frame["x_di_dn"].fillna(False)))
                | frame["x_price_ema200_dn"].fillna(False)
            ).astype(float)
            # Göreli güç: hissenin 20-günlük getirisi S&P 500'ü geçmeli (endeks lideri filtresi)
            if index_close is not None:
                idx_ret20   = index_close.reindex(df.index, method="ffill").pct_change(20)
                stock_ret20 = df["Close"].astype(float).pct_change(20)
                rel_strength = (stock_ret20 > idx_ret20).astype(float)
            else:
                rel_strength = pd.Series(1.0, index=df.index)
        else:
            # BIST: tek kesişim yeterli, gürültü daha az (daha az verimli piyasa)
            bull_trigger = (
                frame["x_macd_up"].fillna(False)
                | frame["x_price_ema50_up"].fillna(False)
                | frame["x_di_up"].fillna(False)
                | frame["x_rsi50_up"].fillna(False)
            ).astype(float).rolling(ENTRY_TRIGGER_LOOKBACK, min_periods=1).max()
            bear_trigger = (
                frame["x_macd_dn"].fillna(False)
                | frame["x_price_ema50_dn"].fillna(False)
                | frame["x_di_dn"].fillna(False)
                | frame["x_price_ema200_dn"].fillna(False)
            ).astype(float)
            rel_strength = pd.Series(1.0, index=df.index)  # BIST: göreli güç filtresi yok
    except Exception:
        logger.exception("Sinyal hesabı başarısız: %s", symbol)
        return None

    return {
        "score":       total.reindex(master_timeline),
        "trend_sub":   trend.reindex(master_timeline),
        "ext_penalty": ext_penalty.reindex(master_timeline),
        "atr":         atr.reindex(master_timeline),
        "high52w":     high52w.reindex(master_timeline),
        "volume":      df["Volume"].reindex(master_timeline) if "Volume" in df.columns else pd.Series(0.0, index=master_timeline),
        "vol_sma20":   vol_sma20.reindex(master_timeline),
        "open":        df["Open"].reindex(master_timeline),
        "high":        df["High"].reindex(master_timeline),
        "low":         df["Low"].reindex(master_timeline),
        "close":       df["Close"].reindex(master_timeline),
        # ── olay-tabanlı giriş/çıkış serileri ──
        "bull_trigger":  bull_trigger.reindex(master_timeline),
        "bear_trigger":  bear_trigger.reindex(master_timeline),
        "trend_ok":      trend_ok.reindex(master_timeline),
        "rel_strength":  rel_strength.reindex(master_timeline),
    }


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
            bear_trig    = sd["bear_trigger"].iloc[d_idx]

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

            # 1a. ATR stop hit (gap-aware) — felaket koruma güvenlik ağı
            if float(low_today) <= pos.trailing_stop:
                exit_price = max(float(open_today), pos.trailing_stop)
                cash += _close_position_full(pos, exit_price, today, "trailing_stop", trades)
                sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                del positions[sym]
                continue

            # 1a-bis. Sinyal kırılımı → tam çıkış (BİRİNCİL çıkış)
            # ABD: ilk MIN_HOLD_SIGNAL_EXIT_US barda ateşlenemiyor (giriş sonrası kısa gürültü)
            signal_exit_ok = (market != "us") or (pos.hold_days >= MIN_HOLD_SIGNAL_EXIT_US)
            if signal_exit_ok and not pd.isna(bear_trig) and float(bear_trig) >= 1.0:
                cash += _close_position_full(pos, float(close_today), today, "sinyal_kirilim", trades)
                sector_count[pos.sector] = max(0, sector_count.get(pos.sector, 0) - 1)
                del positions[sym]
                continue

            # 1b. Kısmi TP
            if not pos.partial_taken and float(high_today) >= pos.entry_price * (1 + PARTIAL_TP_PCT):
                tp_price = max(float(open_today), pos.entry_price * (1 + PARTIAL_TP_PCT))
                cash += _close_position_partial(pos, tp_price, today, "kismi_tp", PARTIAL_TP_RATIO, trades)
                # Pozisyon devam eder

            # 1b-bis. Genişleme riski → kısmi çıkış (kâr varken, bir kez)
            # Breakout ile uzanan hisseler ext_penalty > -0.6 olduğundan bu kural tetiklenmez
            if not pos.partial_taken:
                ext_t = sd["ext_penalty"].iloc[d_idx]
                if (not pd.isna(ext_t) and float(ext_t) < EXT_PEAK_EXIT
                        and float(close_today) > pos.entry_price):
                    cash += _close_position_partial(pos, float(close_today), today, "ext_partial",
                                                    PARTIAL_TP_RATIO, trades)

            # 1c. Skor crash → kısmi (sadece daha önce partial alınmadıysa)
            if (not pos.partial_taken and not pd.isna(score_today) and not pd.isna(score_prev)
                    and (int(score_prev) - int(score_today)) >= SCORE_CRASH_DROP):
                cash += _close_position_partial(pos, float(close_today), today, "score_crash",
                                                PARTIAL_TP_RATIO, trades)

            # 1d. Sinyal kırılımı birincil çıkış olduğundan skor-3bar ve dead-money
            #     kuralları kaldırıldı (ters kesişim onların işini görüyor).

            # 1f. Zaman çıkışı
            gain_today = (float(close_today) - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
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
            trend_sub  = sd["trend_sub"].iloc[d_idx]
            volume_t   = sd["volume"].iloc[d_idx]
            vol_sma    = sd["vol_sma20"].iloc[d_idx]
            close_t    = sd["close"].iloc[d_idx]
            high52w    = sd["high52w"].iloc[d_idx]
            atr_t      = sd["atr"].iloc[d_idx]
            next_open  = sd["open"].iloc[d_idx + 1]
            bull_trig  = sd["bull_trigger"].iloc[d_idx]
            trend_ok   = sd["trend_ok"].iloc[d_idx]
            rel_str    = sd["rel_strength"].iloc[d_idx]

            if any(pd.isna(x) for x in [score, trend_sub, volume_t, vol_sma,
                                          close_t, high52w, atr_t, next_open,
                                          bull_trig, trend_ok]):
                continue
            if float(next_open) <= 0 or float(atr_t) <= 0:
                continue

            # Olay-tabanlı giriş: taze boğa kesişimi + trend yönü onayı + emniyet filtreleri
            # ABD: ek göreli güç filtresi (hisse endeksi 20g'de geçmeli)
            if (float(bull_trig) >= 1.0                       # son ENTRY_TRIGGER_LOOKBACK barda taze yukarı kesişim
                    and float(trend_ok) >= 1.0                # EMA hiyerarşisi yukarı (kapanış>EMA200, EMA50>EMA200)
                    and int(score) >= MIN_SCORE_EVENT
                    and float(trend_sub) >= MIN_TREND_SUBSCORE
                    and (pd.isna(rel_str) or float(rel_str) >= 1.0)  # göreli güç (BIST'te her zaman 1.0)
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
        sd = _build_signals(symbol, df, atr_period, master_timeline, index_close, market)
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
        "strateji":  "TDO v3 — Kesişim Tetikleyici + Trend Onayı (olay-tabanlı)",
        "parametreler": {
            "giris_yontemi":        "Taze boğa kesişimi (MACD/EMA50/DI+/RSI-50) + trend yönü onayı" + (" — ABD: min 2 eş zamanlı kesişim + göreli güç" if market == "us" else ""),
            "cikis_yontemi":        "Ters kesişim/trend kırılımı (birincil) + ATR trailing (güvenlik ağı)" + (f" — ABD: ilk {MIN_HOLD_SIGNAL_EXIT_US}g çırpınma koruması" if market == "us" else ""),
            "giris_skoru":          MIN_SCORE_EVENT,
            "tetik_penceresi_bar":  ENTRY_TRIGGER_LOOKBACK,
            "abd_min_hold_sinyal":  MIN_HOLD_SIGNAL_EXIT_US if market == "us" else None,
            "abd_goreceli_guc":     "20g getiri > S&P 500" if market == "us" else None,
            "abd_cift_kesisim":     "min 2 boğa kesişimi" if market == "us" else None,
            "min_trend_alt":        MIN_TREND_SUBSCORE,
            "hacim_zorunlu":        REQUIRE_VOLUME_ENTRY,
            "atr_periyodu":         atr_period,
            "atr_initial_mult":     ATR_INITIAL_MULT,
            "atr_trail_mult":       ATR_TRAIL_MULT,
            "kismi_tp_pct":         PARTIAL_TP_PCT * 100,
            "kismi_tp_oran":        PARTIAL_TP_RATIO * 100,
            "break_even_trigger":   BREAK_EVEN_TRIGGER * 100,
            "trailing_trigger":     TRAILING_TRIGGER * 100,
            "skor_crash_dusus":     SCORE_CRASH_DROP,
            "max_sure_gun":         MAX_HOLD_DAYS,
            "uzatma_gun":           HOLD_EXTENSION_DAYS,
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


# ── Sinyal isabet etüdü ──────────────────────────────────────────────────────

# Tetikleyici kesişim türleri: (frame anahtarı, görünen ad)
SIGNAL_TRIGGERS: List[Tuple[str, str]] = [
    ("x_macd_up",        "MACD × Sinyal (yukarı kesişim)"),
    ("x_price_ema50_up", "Fiyat × EMA50 (yukarı kesişim)"),
    ("x_di_up",          "DI+ × DI− (yukarı kesişim)"),
    ("x_rsi50_up",       "RSI × 50 (yukarı kesişim)"),
]

STUDY_HORIZONS = (5, 10, 20)  # ileri bakış (işlem günü)


def _study_stats(returns_by_h: Dict[int, List[float]]) -> dict:
    """Bir tetikleyici için ufuk-bazlı isabet/getiri istatistikleri."""
    base = returns_by_h.get(10, [])
    out: dict = {"olay_sayisi": len(base)}
    if not base:
        return out
    wins = [r for r in base if r > 0]
    losses = [r for r in base if r <= 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    out["isabet_pct_10g"]     = round(len(wins) / len(base) * 100, 1)
    out["ort_kazanc_pct_10g"] = round(sum(wins) / len(wins), 2) if wins else 0.0
    out["ort_kayip_pct_10g"]  = round(sum(losses) / len(losses), 2) if losses else 0.0
    out["profit_factor_10g"]  = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
    for h in STUDY_HORIZONS:
        rs = returns_by_h.get(h, [])
        out[f"ort_getiri_pct_{h}g"] = round(sum(rs) / len(rs), 2) if rs else 0.0
    return out


def run_signal_study(market: str) -> dict:
    """Her kesişim tetikleyicisinin (trend onaylı) tarihsel ileri getirisini ölçer.

    Portföy kurgusundan bağımsız 'sinyal isabet' etüdü: bir tetikleyici kesişim
    gerçekleştikten sonra +5/+10/+20 işlem günü içinde fiyatın tarihsel davranışı.
    Yatırım tavsiyesi değildir — yalnızca geçmiş gözlem istatistiğidir.
    """
    tickers = get_tickers(market)
    if not tickers:
        return {"hata": f"Bilinmeyen market: {market}"}

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

    index_close = idx_df["Close"].astype(float)
    data: Dict[str, pd.DataFrame] = download_ohlcv(tickers, period="500d", interval="1d")
    max_h = max(STUDY_HORIZONS)

    # Tetikleyici başına ufuk-bazlı getiri havuzları
    pools: Dict[str, Dict[int, List[float]]] = {
        key: {h: [] for h in STUDY_HORIZONS} for key, _ in SIGNAL_TRIGGERS
    }
    tested = 0

    for symbol in tickers:
        df = data.get(symbol)
        if df is None or df.empty or len(df) < MIN_HISTORY:
            continue
        try:
            frame = compute_score_frame(df, index_close)
        except Exception:
            logger.exception("Etüt sinyal hesabı başarısız: %s", symbol)
            continue

        close  = df["Close"].astype(float).values
        ema50  = frame["ema50_val"].values
        ema200 = frame["ema200_val"].values
        n = len(close)
        if n < MIN_HISTORY:
            continue
        tested += 1

        # Trend onayı: kapanış > EMA200 ve EMA50 > EMA200
        trend_ok = (close > ema200) & (ema50 > ema200)
        # Yalnızca son ~1 yıllık pencere içindeki olaylar (warm-up hariç)
        start = max(MIN_HISTORY, n - BACKTEST_DAYS - 1)
        last_eval = n - max_h  # ileri getiriyi hesaplayabileceğimiz son bar

        for key, _name in SIGNAL_TRIGGERS:
            flag = frame[key].fillna(False).values.astype(bool)
            for i in range(start, last_eval):
                if not flag[i] or not trend_ok[i]:
                    continue
                base_px = close[i]
                if not np.isfinite(base_px) or base_px <= 0:
                    continue
                for h in STUDY_HORIZONS:
                    fut = close[i + h]
                    if np.isfinite(fut):
                        pools[key][h].append(float((fut - base_px) / base_px * 100.0))

    tetikleyiciler: List[dict] = []
    all_10g: List[float] = []
    for key, name in SIGNAL_TRIGGERS:
        stats = _study_stats(pools[key])
        stats["ad"] = name
        stats["key"] = key
        tetikleyiciler.append(stats)
        all_10g.extend(pools[key][10])

    ozet: dict = {"toplam_olay": len(all_10g), "test_edilen_hisse": tested}
    if all_10g:
        wins = [r for r in all_10g if r > 0]
        ozet["isabet_pct_10g"]   = round(len(wins) / len(all_10g) * 100, 1)
        ozet["ort_getiri_pct_10g"] = round(float(sum(all_10g) / len(all_10g)), 2)

    logger.info(
        "Sinyal etüdü tamamlandı: market=%s test=%d olay=%d",
        market, tested, len(all_10g),
    )

    return {
        "market":        market,
        "tip":           "sinyal_etudu",
        "donem":         "Son 1 yıl (~252 işlem günü)",
        "aciklama":      "Trend onaylı kesişim sonrası tarihsel ileri getiri gözlemi (yatırım tavsiyesi değildir).",
        "ufuklar_gun":   list(STUDY_HORIZONS),
        "ozet":          ozet,
        "tetikleyiciler": tetikleyiciler,
    }
