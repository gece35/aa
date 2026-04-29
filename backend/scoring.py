"""Teknik gosterge bazli 10 puanlik puanlama motoru.

4 ana gostergeden + hacim filtresinden olusur, toplam 0-10 puan:

  1. TREND (EMA20/50/200) - max 3 puan:
     - Fiyat > EMA20 > EMA50 > EMA200 dizilimi (guclu trend): +3
     - Fiyat sadece EMA50 ve EMA200 ustunde: +2
     - Fiyat EMA200 altinda: 0

  2. MOMENTUM (MACD) - max 3 puan:
     - MACD sinyali sifir cizgisi altinda yukari kesti (taze donus): +3
     - MACD > sinyal VE histogram artiyor: +2
     - MACD < sinyal: 0

  3. RSI (14) - max 2 puan:
     - RSI 30 yukari kesisi (asiri satimdan cikis): +2
     - RSI 45-65 arasi VE yukari egim: +1
     - RSI > 70 (asiri alim/duzeltme riski): -1 (ceza)

  4. VOLATILITE (Bollinger 20,2) - max 2 puan:
     - Alt banda dokup ici yesil kapanis: +2
     - Orta band yukari yonlu kirilim: +1
     - Ust band disinda: 0

  5. HACIM ONAYI (filtre):
     MACD veya BB tam puan aldi VE gunluk hacim < 20-gunluk ortalama
     ise -1 (sahte kirilim filtresi).

Toplam puan clamp(0, 10) ile sinirlanir.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List

import numpy as np
import pandas as pd

from backend.patterns import detect_patterns


@dataclass
class IndicatorResult:
    name: str
    key: str
    score: int
    max_score: int
    signal: bool = False  # Geriye uyum: score > 0 ise True
    value: float | None = None
    detail: str = ""

    def __post_init__(self):
        self.signal = self.score > 0


@dataclass
class ScoreResult:
    symbol: str
    score: int
    price: float
    change_pct: float
    indicators: List[IndicatorResult]
    sparkline: List[float]
    volume: float = 0.0
    change_week_pct: float = 0.0
    change_month_pct: float = 0.0
    high_52w: float | None = None
    low_52w: float | None = None
    volume_spike: bool = False
    near_peak: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "price": round(self.price, 4),
            "change_pct": round(self.change_pct, 2),
            "change_week_pct": round(self.change_week_pct, 2),
            "change_month_pct": round(self.change_month_pct, 2),
            "volume": int(self.volume),
            "high_52w": round(self.high_52w, 4) if self.high_52w else None,
            "low_52w": round(self.low_52w, 4) if self.low_52w else None,
            "sparkline": [round(float(v), 4) for v in self.sparkline],
            "indicators": [asdict(ind) for ind in self.indicators],
            "volume_spike": self.volume_spike,
            "near_peak": self.near_peak,
        }


# --- saf pandas indikatör hesaplamalari ---

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=length - 1, min_periods=length).mean()
    avg_loss = loss.ewm(com=length - 1, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _bbands(close: pd.Series, length=20, std_mult=2.0):
    mid = _sma(close, length)
    std = close.rolling(window=length).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def _safe_last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


# --- yardimci ---

def _crossed_above(a: pd.Series, b, lookback: int = 3) -> bool:
    """Son `lookback` barda a serisi b'yi (sayi veya seri) yukari kesti mi?"""
    if len(a) < 2:
        return False
    pairs = min(lookback, len(a) - 1)
    for i in range(pairs):
        a_now = a.iloc[-(i + 1)]
        a_prev = a.iloc[-(i + 2)]
        if isinstance(b, (int, float)):
            b_now = b_prev = float(b)
        else:
            if len(b) < i + 2:
                continue
            b_now = b.iloc[-(i + 1)]
            b_prev = b.iloc[-(i + 2)]
        if any(pd.isna(v) for v in [a_now, a_prev, b_now, b_prev]):
            continue
        if float(a_prev) <= float(b_prev) and float(a_now) > float(b_now):
            return True
    return False


# --- indikator skorlama (10'luk sistem) ---

def _score_trend(close: pd.Series) -> IndicatorResult:
    """TREND (EMA20/50/200) - max 3 puan."""
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)
    price = _safe_last(close)
    e20 = _safe_last(ema20)
    e50 = _safe_last(ema50)
    e200 = _safe_last(ema200)

    if price is None or e50 is None or e200 is None:
        return IndicatorResult(
            name="Trend (EMA)", key="trend", score=0, max_score=3,
            value=None, detail="veri yok",
        )

    if e20 is not None and price > e20 > e50 > e200:
        return IndicatorResult(
            name="Trend (EMA)", key="trend", score=3, max_score=3,
            value=round(e50, 4),
            detail="guclu trend: fiyat > EMA20 > EMA50 > EMA200",
        )
    if price > e50 and price > e200:
        return IndicatorResult(
            name="Trend (EMA)", key="trend", score=2, max_score=3,
            value=round(e50, 4),
            detail="fiyat EMA50 ve EMA200 uzerinde",
        )
    if price < e200:
        return IndicatorResult(
            name="Trend (EMA)", key="trend", score=0, max_score=3,
            value=round(e200, 4),
            detail="fiyat EMA200 altinda — trend bozuk",
        )
    return IndicatorResult(
        name="Trend (EMA)", key="trend", score=0, max_score=3,
        value=round(e50, 4),
        detail="karma trend: dizilim bozuk",
    )


def _score_momentum(close: pd.Series) -> IndicatorResult:
    """MOMENTUM (MACD) - max 3 puan."""
    macd_line, signal_line = _macd(close)
    macd_now = _safe_last(macd_line)
    sig_now = _safe_last(signal_line)
    if macd_now is None or sig_now is None or len(macd_line) < 3:
        return IndicatorResult(
            name="Momentum (MACD)", key="momentum", score=0, max_score=3,
            value=None, detail="veri yok",
        )

    # Histogram = MACD - Signal
    hist = macd_line - signal_line
    hist_now = float(hist.iloc[-1]) if not pd.isna(hist.iloc[-1]) else None
    hist_prev = float(hist.iloc[-2]) if not pd.isna(hist.iloc[-2]) else None

    # +3: Sinyal cizgisini sifirin altinda yukari kesti (taze donus)
    cross_below_zero = _crossed_above(macd_line, signal_line, lookback=3) and macd_now < 0
    if cross_below_zero:
        return IndicatorResult(
            name="Momentum (MACD)", key="momentum", score=3, max_score=3,
            value=round(macd_now, 4),
            detail="dipten taze donus: sifir altinda yukari kesis",
        )

    # +2: MACD > Sinyal VE histogram artiyor
    if macd_now > sig_now and hist_now is not None and hist_prev is not None and hist_now > hist_prev:
        return IndicatorResult(
            name="Momentum (MACD)", key="momentum", score=2, max_score=3,
            value=round(macd_now, 4),
            detail="sinyal uzerinde, histogram artisi devam",
        )

    # 0: MACD < Sinyal
    if macd_now < sig_now:
        return IndicatorResult(
            name="Momentum (MACD)", key="momentum", score=0, max_score=3,
            value=round(macd_now, 4),
            detail="sinyal altinda — momentum zayif",
        )

    # MACD > Sinyal ama histogram dusus halinde
    return IndicatorResult(
        name="Momentum (MACD)", key="momentum", score=0, max_score=3,
        value=round(macd_now, 4),
        detail="sinyal uzerinde ama histogram zayifliyor",
    )


def _score_rsi(close: pd.Series) -> IndicatorResult:
    """RSI (14) - max 2 puan, asiri alim cezasi -1."""
    rsi = _rsi(close, 14)
    rsi_now = _safe_last(rsi)
    if rsi_now is None or len(rsi) < 3:
        return IndicatorResult(
            name="RSI", key="rsi", score=0, max_score=2,
            value=None, detail="veri yok",
        )

    rsi_prev = float(rsi.iloc[-2]) if not pd.isna(rsi.iloc[-2]) else None

    # +2: RSI 30 cizgisini yukari kesti (son 3 barda)
    if _crossed_above(rsi, 30, lookback=3):
        return IndicatorResult(
            name="RSI", key="rsi", score=2, max_score=2,
            value=round(rsi_now, 2),
            detail=f"RSI {rsi_now:.0f} — asiri satimdan cikis",
        )

    # -1: RSI > 70 (asiri alim cezasi)
    if rsi_now > 70:
        return IndicatorResult(
            name="RSI", key="rsi", score=-1, max_score=2,
            value=round(rsi_now, 2),
            detail=f"RSI {rsi_now:.0f} — asiri alim, duzeltme riski",
        )

    # +1: RSI 45-65 arasi VE yukari egim
    if 45 <= rsi_now <= 65 and rsi_prev is not None and rsi_now > rsi_prev:
        return IndicatorResult(
            name="RSI", key="rsi", score=1, max_score=2,
            value=round(rsi_now, 2),
            detail=f"RSI {rsi_now:.0f} — pozitif egim, saglikli bolge",
        )

    # 0: diger durumlar
    return IndicatorResult(
        name="RSI", key="rsi", score=0, max_score=2,
        value=round(rsi_now, 2),
        detail=f"RSI {rsi_now:.0f} — notr",
    )


def _score_bbands(open_: pd.Series, close: pd.Series) -> IndicatorResult:
    """VOLATILITE (Bollinger 20,2) - max 2 puan."""
    upper, middle, lower = _bbands(close)
    price = _safe_last(close)
    upper_now = _safe_last(upper)
    middle_now = _safe_last(middle)
    lower_now = _safe_last(lower)

    if price is None or upper_now is None or middle_now is None or lower_now is None:
        return IndicatorResult(
            name="Bollinger", key="bbands", score=0, max_score=2,
            value=None, detail="veri yok",
        )

    # 0 puan: ust band disinda
    if price > upper_now:
        return IndicatorResult(
            name="Bollinger", key="bbands", score=0, max_score=2,
            value=round(upper_now, 4),
            detail="fiyat ust band uzerinde — geri cekilme riski",
        )

    # +2: alt banda dokup ici yesil kapanis
    open_now = _safe_last(open_)
    if (open_now is not None and price > open_now and lower_now is not None
            and open_now <= lower_now * 1.01):
        return IndicatorResult(
            name="Bollinger", key="bbands", score=2, max_score=2,
            value=round(lower_now, 4),
            detail="alt banttan yesil donus",
        )

    # +1: orta band yukari kirilim (son 3 barda)
    if _crossed_above(close, middle, lookback=3) and price > middle_now:
        return IndicatorResult(
            name="Bollinger", key="bbands", score=1, max_score=2,
            value=round(middle_now, 4),
            detail="orta band yukari kirilim",
        )

    # 0: diger durumlar
    return IndicatorResult(
        name="Bollinger", key="bbands", score=0, max_score=2,
        value=round(middle_now, 4),
        detail="bant ici notr seyir",
    )


def _apply_volume_filter(volume: pd.Series, momentum: IndicatorResult,
                         bbands: IndicatorResult) -> tuple:
    """MACD veya BB tam puan aldi VE gunluk hacim < SMA20 ise -1.

    Geri donus: (momentum, bbands, filtre_uygulandi: bool, hacim_detayi: str)
    """
    if volume is None or volume.empty or len(volume) < 21:
        return momentum, bbands, False, "hacim verisi yok"

    vol_clean = volume.dropna()
    if len(vol_clean) < 21:
        return momentum, bbands, False, "hacim verisi yok"

    last_vol = float(vol_clean.iloc[-1])
    avg_20 = float(vol_clean.iloc[-21:-1].mean())
    if avg_20 <= 0:
        return momentum, bbands, False, "hacim verisi yok"

    ratio = last_vol / avg_20
    detail = f"hacim 20g ortalamanin %{(ratio - 1) * 100:+.0f}'inde"

    if last_vol >= avg_20:
        return momentum, bbands, False, f"{detail} — onayli"

    # Hacim yetersiz — tam puan alanlardan -1 dus
    applied = False
    if momentum.score == momentum.max_score:
        momentum = IndicatorResult(
            name=momentum.name, key=momentum.key,
            score=momentum.score - 1, max_score=momentum.max_score,
            value=momentum.value,
            detail=momentum.detail + " (hacim teyitsiz: -1)",
        )
        applied = True
    if bbands.score == bbands.max_score:
        bbands = IndicatorResult(
            name=bbands.name, key=bbands.key,
            score=bbands.score - 1, max_score=bbands.max_score,
            value=bbands.value,
            detail=bbands.detail + " (hacim teyitsiz: -1)",
        )
        applied = True

    suffix = " — sahte kirilim filtresi devrede" if applied else ""
    return momentum, bbands, applied, f"{detail}{suffix}"


# --- destek / direnc seviyeleri ---

def _find_sr_levels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 120,
    window: int = 5,
    cluster_pct: float = 0.015,
) -> dict:
    """Pivot noktalariyla destek ve direnc seviyelerini tespit eder."""
    if len(close) < window * 2 + 1:
        return {"supports": [], "resistances": []}

    h = high.tail(n).reset_index(drop=True)
    l = low.tail(n).reset_index(drop=True)
    n_actual = len(h)

    raw_sups: list[float] = []
    raw_ress: list[float] = []

    for i in range(window, n_actual - window):
        lo = float(l.iloc[i])
        hi = float(h.iloc[i])
        if pd.isna(lo) or pd.isna(hi):
            continue

        neighbors_l = [
            float(l.iloc[i + j])
            for j in range(-window, window + 1)
            if j != 0 and not pd.isna(l.iloc[i + j])
        ]
        if neighbors_l and lo <= min(neighbors_l):
            raw_sups.append(lo)

        neighbors_h = [
            float(h.iloc[i + j])
            for j in range(-window, window + 1)
            if j != 0 and not pd.isna(h.iloc[i + j])
        ]
        if neighbors_h and hi >= max(neighbors_h):
            raw_ress.append(hi)

    def cluster(levels: list[float]) -> list[float]:
        if not levels:
            return []
        levels_s = sorted(levels)
        clusters: list[list[float]] = [[levels_s[0]]]
        for v in levels_s[1:]:
            if v <= clusters[-1][-1] * (1 + cluster_pct):
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [round(sum(c) / len(c), 4) for c in clusters]

    return {
        "supports": cluster(raw_sups),
        "resistances": cluster(raw_ress),
    }


def _calc_sl_tp(price: float, supports: list, resistances: list) -> tuple:
    """Destek/direnc noktalarindan stop-loss ve kar-al hedefleri hesaplar."""
    sups_below = [s for s in supports if s < price * 0.995]
    ress_above = [r for r in resistances if r > price * 1.005]

    if sups_below:
        nearest_sup = max(sups_below)
        # En yakin destegin %1.5 altini stop-loss olarak belirle
        stop_loss = round(nearest_sup * 0.985, 4)
    else:
        stop_loss = None

    take_profit = round(min(ress_above), 4) if ress_above else None
    return stop_loss, take_profit


# --- yardımcı ---

def _pct_change_back(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return 0.0
    prev = float(close.iloc[-(n + 1)])
    if prev == 0 or pd.isna(prev):
        return 0.0
    return (float(close.iloc[-1]) - prev) / prev * 100.0


# --- ana puanlama ---

def score_symbol(symbol: str, df: pd.DataFrame) -> ScoreResult | None:
    if df is None or df.empty or len(df) < 60:
        return None

    close = df["Close"].astype(float)
    open_ = df["Open"].astype(float) if "Open" in df.columns else close
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    last_close = float(close.iloc[-1])
    if len(close) >= 2 and not pd.isna(close.iloc[-2]) and close.iloc[-2] != 0:
        change_pct = (last_close - float(close.iloc[-2])) / float(close.iloc[-2]) * 100.0
    else:
        change_pct = 0.0

    # 52 haftalik yuksek/dusuk
    high_series = high.tail(252).dropna()
    low_series = low.tail(252).dropna()
    high_52 = float(high_series.max()) if not high_series.empty else None
    low_52 = float(low_series.min()) if not low_series.empty else None

    # 4 ana gosterge skoru
    trend = _score_trend(close)
    momentum = _score_momentum(close)
    rsi_ind = _score_rsi(close)
    bbands = _score_bbands(open_, close)

    # Hacim onay filtresi (MACD/BB tam puanlarini -1 dusurebilir)
    momentum, bbands, _, vol_detail = _apply_volume_filter(volume, momentum, bbands)
    hacim = IndicatorResult(
        name="Hacim Onayi", key="volume", score=0, max_score=0,
        value=None, detail=vol_detail,
    )

    indicators = [trend, momentum, rsi_ind, bbands, hacim]
    raw_total = sum(ind.score for ind in indicators)
    score = max(0, min(10, raw_total))
    sparkline_raw = close.tail(30).dropna().tolist()
    week_change = _pct_change_back(close, 5)
    month_change = _pct_change_back(close, 21)

    last_volume = float(volume.iloc[-1]) if not volume.empty and not pd.isna(volume.iloc[-1]) else 0.0

    volume_spike = False
    if last_volume > 0 and len(volume) >= 12:
        avg_vol_10d = float(volume.iloc[-11:-1].dropna().mean())
        if avg_vol_10d > 0:
            volume_spike = last_volume > 1.5 * avg_vol_10d

    near_peak = bool(high_52 and high_52 > 0 and last_close >= high_52 * 0.97)

    return ScoreResult(
        symbol=symbol,
        score=score,
        price=last_close,
        change_pct=change_pct,
        change_week_pct=week_change,
        change_month_pct=month_change,
        volume=last_volume,
        high_52w=high_52,
        low_52w=low_52,
        sparkline=sparkline_raw,
        indicators=indicators,
        volume_spike=volume_spike,
        near_peak=near_peak,
    )


def score_symbol_detailed(symbol: str, df: pd.DataFrame) -> dict | None:
    base = score_symbol(symbol, df)
    if base is None:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    hist = [
        {
            "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
            "close": float(val),
        }
        for idx, val in close.tail(60).items()
        if not pd.isna(val)
    ]

    # Tam OHLCV — grafik icin son 120 bar
    ohlcv = []
    for idx, row in df.tail(120).iterrows():
        try:
            date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
            vol_val = row.get("Volume", 0)
            ohlcv.append({
                "t": date_str,
                "o": round(float(row["Open"]), 4),
                "h": round(float(row["High"]), 4),
                "l": round(float(row["Low"]), 4),
                "c": round(float(row["Close"]), 4),
                "v": int(float(vol_val)) if not pd.isna(vol_val) else 0,
            })
        except (KeyError, ValueError, TypeError):
            continue

    avg_vol = float(volume.tail(20).mean()) if not volume.empty else 0.0

    # Destek / direnc seviyeleri ve SL/TP
    sr = _find_sr_levels(high, low, close)
    stop_loss, take_profit = _calc_sl_tp(
        float(close.iloc[-1]),
        sr["supports"],
        sr["resistances"],
    )

    risk_reward = None
    price = float(close.iloc[-1])
    if stop_loss and take_profit and price > stop_loss:
        risk = price - stop_loss
        reward = take_profit - price
        if risk > 0:
            risk_reward = round(reward / risk, 2)

    # Formasyon tespiti
    patterns = detect_patterns(df)

    out = base.to_dict()
    out.update({
        "history": hist,
        "ohlcv": ohlcv,
        "patterns": patterns,
        "avg_volume_20d": round(avg_vol, 2),
        "data_points": int(len(close)),
        "supports": sr["supports"],
        "resistances": sr["resistances"],
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
    })
    return out
