"""Backtest motoru — vektörleştirilmiş gösterge hesaplaması.

Strateji parametreleri:
  - Giriş : skor >= 7 olan ilk gün VE piyasa rejimi bullish (endeks > EMA200)
             → ertesi gün açılışta al
  - Çıkış (ilk tetiklenen):
      1. Stop-loss  : giriş fiyatının %5 altı
      2. Take-profit: giriş fiyatının %10 üstü
      3. Skor düşüşü: skor ≤ 3 olunca
      4. Süre limiti: 45 işlem günü
  - Dönem : son 252 işlem günü (≈ 1 yıl)
  - Rejim filtresi: BIST → XU100.IS, US → ^GSPC endeksi EMA200 üzerindeyse bullish
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .data_fetcher import download_ohlcv
from .tickers import get_tickers

logger = logging.getLogger(__name__)

# ── Strateji sabitleri ────────────────────────────────────────────────────────
MIN_SCORE      = 8
SL_PCT         = 0.05   # %5 stop-loss
TP_PCT         = 0.10   # %10 take-profit
MAX_HOLD_DAYS  = 45
BACKTEST_DAYS  = 252    # ~1 yıl işlem günü
MIN_HISTORY    = 250    # gösterge ısınması için minimum veri

# Piyasa rejim filtresi için endeks sembolleri
MARKET_INDICES: Dict[str, str] = {
    "bist": "XU100.IS",
    "us":   "^GSPC",
}


# ── Piyasa rejim serisi (endeks EMA200 filtresi) ──────────────────────────────

def _regime_series(index_df: pd.DataFrame) -> pd.Series:
    """Endeks EMA200 üzerindeyse True (bullish), altındaysa False döner."""
    close = index_df["Close"].astype(float)
    ema200 = close.ewm(span=200, adjust=False).mean()
    return close > ema200


# ── Vektörleştirilmiş skor serisi ────────────────────────────────────────────

def _score_series(df: pd.DataFrame) -> pd.Series:
    """Tüm DataFrame için günlük skor serisini hesaplar (look-ahead yok)."""
    close  = df["Close"].astype(float)
    open_  = df["Open"].astype(float) if "Open" in df.columns else close
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(0.0, index=df.index)

    # ── Trend (EMA20/50/200) ──────────────────────────────────────────────────
    ema20  = close.ewm(span=20,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    trend = pd.Series(0, index=df.index, dtype=int)
    trend = trend.where(~(close > ema200), 0)
    above_50_200 = (close > ema50) & (close > ema200)
    trend[above_50_200] = 2
    full_align = (close > ema20) & (ema20 > ema50) & (ema50 > ema200)
    trend[full_align] = 3

    # ── Momentum (MACD 12/26/9) ───────────────────────────────────────────────
    ema12       = close.ewm(span=12, adjust=False).mean()
    ema26       = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram   = macd_line - signal_line

    macd_above_sig = macd_line > signal_line
    hist_rising    = histogram > histogram.shift(1)
    cross_up = (
        macd_above_sig
        & ~macd_above_sig.shift(1).fillna(False)
        & (macd_line < 0)
    )
    cross_up_3 = cross_up | cross_up.shift(1).fillna(False) | cross_up.shift(2).fillna(False)

    momentum = pd.Series(0, index=df.index, dtype=int)
    momentum[(macd_above_sig) & hist_rising] = 2
    momentum[cross_up_3] = 3

    # ── RSI (14) ──────────────────────────────────────────────────────────────
    delta    = close.diff()
    avg_gain = delta.clip(lower=0).ewm(com=13, min_periods=14, adjust=False).mean()
    avg_loss = (-delta).clip(lower=0).ewm(com=13, min_periods=14, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    rsi_cross30   = (rsi > 30) & (rsi.shift(1) <= 30)
    rsi_cross30_3 = rsi_cross30 | rsi_cross30.shift(1).fillna(False) | rsi_cross30.shift(2).fillna(False)
    rsi_mid = (rsi >= 45) & (rsi <= 65) & (rsi > rsi.shift(1))
    rsi_ob  = rsi > 70

    rsi_score = pd.Series(0, index=df.index, dtype=int)
    rsi_score[rsi_mid]       = 1
    rsi_score[rsi_cross30_3] = 2
    rsi_score[rsi_ob]        = -1

    # ── Bollinger (20, 2) ─────────────────────────────────────────────────────
    bb_mid   = close.rolling(20).mean()
    bb_std   = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    above_upper = close > bb_upper
    mid_break   = (close > bb_mid) & (close.shift(1) <= bb_mid.shift(1))
    mid_break_3 = mid_break | mid_break.shift(1).fillna(False) | mid_break.shift(2).fillna(False)
    lower_touch = (open_.shift(1) <= bb_lower.shift(1) * 1.01) & (close > open_)

    bb_score = pd.Series(0, index=df.index, dtype=int)
    bb_score[mid_break_3] = 1
    bb_score[lower_touch] = 2
    bb_score[above_upper] = 0

    # ── Hacim filtresi ────────────────────────────────────────────────────────
    vol_sma20  = volume.rolling(20).mean()
    low_volume = volume < vol_sma20
    momentum[(momentum == 3) & low_volume] = 2
    bb_score[(bb_score == 2) & low_volume] = 1

    raw = trend + momentum + rsi_score + bb_score
    return raw.clip(0, 10).fillna(0).astype(int)


# ── Tek hisse işlem simülasyonu ───────────────────────────────────────────────

def _simulate(symbol: str, df: pd.DataFrame, regime: Optional[pd.Series]) -> List[dict]:
    if df is None or len(df) < MIN_HISTORY:
        return []

    scores = _score_series(df)
    close  = df["Close"].astype(float)
    open_  = df["Open"].astype(float) if "Open" in df.columns else close

    # Rejim serisini hisse tarihleriyle hizala (eksik günler önceki değerle doldurulur)
    if regime is not None:
        regime_aligned = regime.reindex(df.index, method="ffill").fillna(False)
    else:
        regime_aligned = pd.Series(True, index=df.index)

    start  = max(len(df) - BACKTEST_DAYS, 200)
    trades: List[dict] = []

    in_pos      = False
    entry_price = 0.0
    entry_date  = None
    hold_days   = 0

    for i in range(start, len(df) - 1):
        price = float(close.iloc[i])
        score = int(scores.iloc[i])

        if not in_pos:
            prev_score = int(scores.iloc[i - 1]) if i > 0 else 0
            if score >= MIN_SCORE and prev_score >= MIN_SCORE and bool(regime_aligned.iloc[i]):
                next_open = float(open_.iloc[i + 1])
                if next_open <= 0 or pd.isna(next_open):
                    continue
                entry_price = next_open
                entry_date  = df.index[i + 1]
                in_pos      = True
                hold_days   = 0
        else:
            hold_days += 1
            exit_reason: Optional[str] = None

            if   price <= entry_price * (1 - SL_PCT):  exit_reason = "stop_loss"
            elif price >= entry_price * (1 + TP_PCT):  exit_reason = "take_profit"
            elif score <= 5:                            exit_reason = "skor_dustu"
            elif hold_days >= MAX_HOLD_DAYS:            exit_reason = "sure_doldu"

            if exit_reason:
                ret = (price - entry_price) / entry_price * 100
                trades.append({
                    "sembol":       symbol,
                    "giris_tarihi": str(entry_date.date()),
                    "cikis_tarihi": str(df.index[i].date()),
                    "giris_fiyati": round(entry_price, 4),
                    "cikis_fiyati": round(price, 4),
                    "getiri_pct":   round(ret, 2),
                    "sure_gun":     hold_days,
                    "cikis_nedeni": exit_reason,
                    "kazandi":      ret > 0,
                })
                in_pos = False

    if in_pos:
        last_price = float(close.iloc[-1])
        ret = (last_price - entry_price) / entry_price * 100
        trades.append({
            "sembol":       symbol,
            "giris_tarihi": str(entry_date.date()),
            "cikis_tarihi": str(df.index[-1].date()),
            "giris_fiyati": round(entry_price, 4),
            "cikis_fiyati": round(last_price, 4),
            "getiri_pct":   round(ret, 2),
            "sure_gun":     hold_days,
            "cikis_nedeni": "acik_pozisyon",
            "kazandi":      ret > 0,
        })

    return trades


# ── Özet istatistikler ────────────────────────────────────────────────────────

def _stats(trades: List[dict]) -> dict:
    if not trades:
        return {}
    returns  = [t["getiri_pct"] for t in trades]
    wins     = [r for r in returns if r > 0]
    losses   = [r for r in returns if r <= 0]
    hold_avg = sum(t["sure_gun"] for t in trades) / len(trades)

    exit_dist: Dict[str, int] = {}
    for t in trades:
        exit_dist[t["cikis_nedeni"]] = exit_dist.get(t["cikis_nedeni"], 0) + 1

    return {
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
    }


# ── Ana backtest fonksiyonu ───────────────────────────────────────────────────

def run_backtest(market: str) -> dict:
    """Seçilen market'teki tüm sembolleri backteste tabi tutar."""
    tickers = get_tickers(market)
    if not tickers:
        return {"hata": f"Bilinmeyen market: {market}"}

    logger.info("Backtest başladı: market=%s sembol_sayısı=%d", market, len(tickers))

    # Endeks verisini ayrıca çek (rejim filtresi için)
    index_symbol = MARKET_INDICES.get(market)
    regime: Optional[pd.Series] = None
    if index_symbol:
        try:
            idx_data = download_ohlcv([index_symbol], period="500d", interval="1d")
            idx_df   = idx_data.get(index_symbol)
            if idx_df is not None and not idx_df.empty:
                regime = _regime_series(idx_df)
                bullish_days = int(regime.sum())
                total_days   = len(regime)
                logger.info(
                    "Rejim filtresi: %s — %d/%d gün bullish (%.0f%%)",
                    index_symbol, bullish_days, total_days,
                    bullish_days / total_days * 100 if total_days else 0,
                )
        except Exception:
            logger.exception("Endeks verisi alınamadı: %s — filtre devre dışı", index_symbol)

    # 500 gün veri çek — ilk 250 bar ısınma, son 252 bar test
    data: Dict[str, pd.DataFrame] = download_ohlcv(tickers, period="500d", interval="1d")

    all_trades: List[dict] = []
    hisse_sonuclari: List[dict] = []

    for symbol in tickers:
        df = data.get(symbol)
        if df is None or df.empty:
            continue
        try:
            trades = _simulate(symbol, df, regime)
        except Exception:
            logger.exception("Backtest hatası: %s", symbol)
            continue

        if not trades:
            continue

        sym_stats = _stats(trades)
        hisse_sonuclari.append({
            "sembol":            symbol,
            "islem_sayisi":      sym_stats["toplam_islem"],
            "kazanma_orani_pct": sym_stats["kazanma_orani_pct"],
            "toplam_getiri_pct": sym_stats["toplam_getiri_pct"],
            "islemler":          trades,
        })
        all_trades.extend(trades)

    hisse_sonuclari.sort(key=lambda x: x["toplam_getiri_pct"], reverse=True)

    genel_stats = _stats(all_trades)
    genel_stats["test_edilen_hisse"]  = len([s for s in tickers if s in data])
    genel_stats["sinyal_veren_hisse"] = len(hisse_sonuclari)

    logger.info(
        "Backtest tamamlandı: %d hisse, %d işlem, kazanma=%s%%",
        len(hisse_sonuclari),
        len(all_trades),
        genel_stats.get("kazanma_orani_pct", "—"),
    )

    return {
        "market":    market,
        "donem":     "Son 1 yıl (~252 işlem günü)",
        "parametreler": {
            "min_skor":          MIN_SCORE,
            "stop_loss_pct":     SL_PCT * 100,
            "take_profit_pct":   TP_PCT * 100,
            "max_sure_gun":      MAX_HOLD_DAYS,
            "rejim_filtresi":    index_symbol or "kapalı",
        },
        "ozet":      genel_stats,
        "hisseler":  hisse_sonuclari,
    }
