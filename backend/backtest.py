"""Backtest motoru — vektörleştirilmiş gösterge hesaplaması.

Strateji parametreleri (kademeli giriş/çıkış):
  - 1. Giriş  : skor >= 6 → sermayenin %50'si ile giriş (ertesi gün açılışta)
  - 2. Ekleme : skor >= 8'e ulaşırsa → kalan %50 de eklenir (ertesi gün açılışta)
  - Çıkış (ilk tetiklenen):
      1. Stop-loss   : ortalama giriş fiyatının %5 altı → tamamı satılır
      2. Take-profit : ortalama giriş fiyatının %10 üstü → tamamı satılır
      3. Tek günde 2 puan düşüş → ikinci yarı satılır (varsa), ilk yarı kalır
      4. Skor ≤ 5 → tamamı satılır
      5. Süre limiti : 45 işlem günü → tamamı satılır
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
MIN_SCORE          = 6    # ilk yarı giriş eşiği
ADD_SCORE          = 8    # ikinci yarı ekleme eşiği
EXIT_SCORE         = 5    # tam çıkış eşiği (skor ≤ EXIT_SCORE)
SCORE_DROP_PARTIAL = 2    # tek günde bu kadar düşerse yarı çıkış
SL_PCT             = 0.05  # %5 stop-loss (ortalama girişe göre)
TP_PCT             = 0.10  # %10 take-profit (ortalama girişe göre)
MAX_HOLD_DAYS      = 45
BACKTEST_DAYS      = 252   # ~1 yıl işlem günü
MIN_HISTORY        = 250   # gösterge ısınması için minimum veri

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

    if regime is not None:
        regime_aligned = regime.reindex(df.index, method="ffill").fillna(False)
    else:
        regime_aligned = pd.Series(True, index=df.index)

    start  = max(len(df) - BACKTEST_DAYS, 200)
    trades: List[dict] = []

    in_half1       = False   # ilk %50 pozisyon aktif mi
    in_half2       = False   # ikinci %50 pozisyon aktif mi
    add_half2_next = False   # ertesi gün açılışında half2 eklenecek
    entry1_price   = 0.0
    entry2_price   = 0.0
    entry1_date    = None
    entry2_date    = None
    hold_days      = 0

    for i in range(start, len(df) - 1):
        price      = float(close.iloc[i])
        score      = int(scores.iloc[i])
        prev_score = int(scores.iloc[i - 1]) if i > 0 else score

        if not in_half1:
            if score >= MIN_SCORE and bool(regime_aligned.iloc[i]):
                nxt = float(open_.iloc[i + 1])
                if nxt <= 0 or pd.isna(nxt):
                    continue
                entry1_price   = nxt
                entry1_date    = df.index[i + 1]
                in_half1       = True
                add_half2_next = False
                hold_days      = 0
            continue

        hold_days += 1

        # Önceki barda tetiklenen half2 girişini bugün açılışta gerçekleştir
        if add_half2_next and not in_half2:
            entry2_price   = float(open_.iloc[i])
            entry2_date    = df.index[i]
            in_half2       = True
            add_half2_next = False

        avg_entry = (entry1_price + entry2_price) / 2 if in_half2 else entry1_price

        # ── Tam çıkış koşulları ───────────────────────────────────────────────
        full_exit: Optional[str] = None
        if   price <= avg_entry * (1 - SL_PCT): full_exit = "stop_loss"
        elif price >= avg_entry * (1 + TP_PCT): full_exit = "take_profit"
        elif score <= EXIT_SCORE:               full_exit = "skor_dustu"
        elif hold_days >= MAX_HOLD_DAYS:        full_exit = "sure_doldu"

        if full_exit:
            if in_half2:
                r1  = (price - entry1_price) / entry1_price * 100
                r2  = (price - entry2_price) / entry2_price * 100
                ret = (r1 + r2) / 2
            else:
                ret = (price - entry1_price) / entry1_price * 100
            trades.append({
                "sembol":       symbol,
                "giris_tarihi": str(entry1_date.date()),
                "cikis_tarihi": str(df.index[i].date()),
                "giris_fiyati": round(avg_entry, 4),
                "cikis_fiyati": round(price, 4),
                "getiri_pct":   round(ret, 2),
                "sure_gun":     hold_days,
                "cikis_nedeni": full_exit,
                "kazandi":      ret > 0,
            })
            in_half1 = in_half2 = add_half2_next = False
            continue

        # ── Kısmi çıkış: tek günde 2+ puan düşüş → half2 satılır ─────────────
        score_drop = prev_score - score
        if score_drop >= SCORE_DROP_PARTIAL and in_half2:
            ret2 = (price - entry2_price) / entry2_price * 100
            trades.append({
                "sembol":       symbol,
                "giris_tarihi": str(entry2_date.date()),
                "cikis_tarihi": str(df.index[i].date()),
                "giris_fiyati": round(entry2_price, 4),
                "cikis_fiyati": round(price, 4),
                "getiri_pct":   round(ret2, 2),
                "sure_gun":     hold_days,
                "cikis_nedeni": "kismi_cikis",
                "kazandi":      ret2 > 0,
            })
            in_half2       = False
            add_half2_next = False
            continue

        # ── Half2 ekleme sinyali: skor ADD_SCORE'a ulaştı ────────────────────
        if not in_half2 and not add_half2_next and score >= ADD_SCORE:
            add_half2_next = True

    # Döngü sonu — açık pozisyonları kapat
    if in_half1:
        last_price = float(close.iloc[-1])
        avg_entry  = (entry1_price + entry2_price) / 2 if in_half2 else entry1_price
        if in_half2:
            r1  = (last_price - entry1_price) / entry1_price * 100
            r2  = (last_price - entry2_price) / entry2_price * 100
            ret = (r1 + r2) / 2
        else:
            ret = (last_price - entry1_price) / entry1_price * 100
        trades.append({
            "sembol":       symbol,
            "giris_tarihi": str(entry1_date.date()),
            "cikis_tarihi": str(df.index[-1].date()),
            "giris_fiyati": round(avg_entry, 4),
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
            "giris_skoru":        MIN_SCORE,
            "ekleme_skoru":       ADD_SCORE,
            "cikis_skoru":        EXIT_SCORE,
            "kismi_cikis_dusus":  SCORE_DROP_PARTIAL,
            "stop_loss_pct":      SL_PCT * 100,
            "take_profit_pct":    TP_PCT * 100,
            "max_sure_gun":       MAX_HOLD_DAYS,
            "rejim_filtresi":     index_symbol or "kapalı",
        },
        "ozet":      genel_stats,
        "hisseler":  hisse_sonuclari,
    }
