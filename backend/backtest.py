"""Backtest motoru — vektörleştirilmiş gösterge hesaplaması.

Strateji parametreleri:
  - Giriş : skor >= 6 olan ilk gün → ertesi gün açılışta al
  - Çıkış (ilk tetiklenen):
      1. Stop-loss  : giriş fiyatının %5 altı
      2. Take-profit: giriş fiyatının %10 üstü
      3. Skor düşüşü: skor ≤ 3 olunca
      4. Süre limiti: 45 işlem günü
  - Dönem : son 252 işlem günü (≈ 1 yıl)
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
MIN_SCORE      = 6
SL_PCT         = 0.05   # %5 stop-loss
TP_PCT         = 0.10   # %10 take-profit
MAX_HOLD_DAYS  = 45
BACKTEST_DAYS  = 252    # ~1 yıl işlem günü
MIN_HISTORY    = 250    # gösterge ısınması için minimum veri


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
    trend = trend.where(~(close > ema200), 0)           # EMA200 altı = 0 (zaten)
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
    # MACD sinyal çizgisini sıfırın altında yukarı kesti (son 3 bar)
    cross_up = (
        macd_above_sig
        & ~macd_above_sig.shift(1).fillna(False)
        & (macd_line < 0)
    )
    # 3 bar geriye bak
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

    rsi_cross30 = (rsi > 30) & (rsi.shift(1) <= 30)
    rsi_cross30_3 = rsi_cross30 | rsi_cross30.shift(1).fillna(False) | rsi_cross30.shift(2).fillna(False)
    rsi_mid   = (rsi >= 45) & (rsi <= 65) & (rsi > rsi.shift(1))
    rsi_ob    = rsi > 70

    rsi_score = pd.Series(0, index=df.index, dtype=int)
    rsi_score[rsi_mid]      = 1
    rsi_score[rsi_cross30_3] = 2
    rsi_score[rsi_ob]       = -1

    # ── Bollinger (20, 2) ─────────────────────────────────────────────────────
    bb_mid   = close.rolling(20).mean()
    bb_std   = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    # Üst band dışı = 0 puan
    above_upper = close > bb_upper
    # Orta band kırılımı (+1) — son 3 bar
    mid_break   = (close > bb_mid) & (close.shift(1) <= bb_mid.shift(1))
    mid_break_3 = mid_break | mid_break.shift(1).fillna(False) | mid_break.shift(2).fillna(False)
    # Alt band dokunuşu + yeşil mum (+2)
    lower_touch = (open_.shift(1) <= bb_lower.shift(1) * 1.01) & (close > open_)

    bb_score = pd.Series(0, index=df.index, dtype=int)
    bb_score[mid_break_3]  = 1
    bb_score[lower_touch]  = 2
    bb_score[above_upper]  = 0  # üst band dışı sıfırlar

    # ── Hacim filtresi ────────────────────────────────────────────────────────
    vol_sma20  = volume.rolling(20).mean()
    low_volume = volume < vol_sma20
    # MACD 3 puan + düşük hacim → 2'ye indir
    momentum[(momentum == 3) & low_volume] = 2
    # BB 2 puan + düşük hacim → 1'e indir
    bb_score[(bb_score == 2) & low_volume] = 1

    raw = trend + momentum + rsi_score + bb_score
    return raw.clip(0, 10).fillna(0).astype(int)


# ── Tek hisse işlem simülasyonu ───────────────────────────────────────────────

def _simulate(symbol: str, df: pd.DataFrame) -> List[dict]:
    if df is None or len(df) < MIN_HISTORY:
        return []

    scores = _score_series(df)
    close  = df["Close"].astype(float)
    open_  = df["Open"].astype(float) if "Open" in df.columns else close

    # Son 252 günü test et; ilk 200 bar gösterge ısınması için kullanılıyor
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
            if score >= MIN_SCORE:
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
            elif score <= 3:                            exit_reason = "skor_dustu"
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

    # Dönem sonunda açık pozisyonu kapat
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

    # Çıkış nedenlerine göre dağılım
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

    # 500 gün veri çek — ilk 250 bar ısınma, son 252 bar test
    data: Dict[str, pd.DataFrame] = download_ohlcv(tickers, period="500d", interval="1d")

    all_trades: List[dict] = []
    hisse_sonuclari: List[dict] = []

    for symbol in tickers:
        df = data.get(symbol)
        if df is None or df.empty:
            continue
        try:
            trades = _simulate(symbol, df)
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

    # En iyi hisselere göre sırala
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
        },
        "ozet":      genel_stats,
        "hisseler":  hisse_sonuclari,
    }
