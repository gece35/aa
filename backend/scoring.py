"""Teknik gosterge bazli puanlama motoru.

5 gostergeden olusur, her AL sinyali +1 puan verir:
  - RSI (14)          : Son 3 barda 30 yukari kesis veya sinyal cizgisi kesisi
  - MACD (12, 26, 9)  : Son 3 barda MACD cizgisi sinyali yukari yonlu keser
  - Bollinger (20, 2) : Son 3 barda alt banda dokup yukari donmus olmali
  - EMA (50)          : Fiyat EMA50 uzerinde VE 52h zirvesinin %3 altinda
  - Stochastic        : Son 3 barda %K %D'yi yukari keser, K < 80 (asiri alim degil)

pandas_ta yerine saf pandas/numpy ile hesaplama yapilir.
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
    signal: bool
    value: float | None = None
    detail: str = ""


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


def _stoch(high: pd.Series, low: pd.Series, close: pd.Series, k=14, d=3, smooth_k=3) -> tuple:
    lowest = low.rolling(window=k).min()
    highest = high.rolling(window=k).max()
    denom = (highest - lowest).replace(0, np.nan)
    raw_k = 100 * (close - lowest) / denom
    k_line = raw_k.rolling(window=smooth_k).mean()
    d_line = k_line.rolling(window=d).mean()
    return k_line, d_line


def _safe_last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _crosses_above_within(series_a: pd.Series, series_b, n: int = 3) -> bool:
    """Son n barda series_a, series_b'yi en az bir kez yukari gecti mi?

    n=3 → son 3 mum gecisini (3 art arda bar ciftini) kontrol eder.
    """
    if len(series_a) < 2:
        return False
    pairs = min(n, len(series_a) - 1)
    for i in range(pairs):
        a_now = series_a.iloc[-(i + 1)]
        a_prev = series_a.iloc[-(i + 2)]
        if isinstance(series_b, (int, float)):
            b_now = b_prev = float(series_b)
        else:
            if len(series_b) < i + 2:
                continue
            b_now = series_b.iloc[-(i + 1)]
            b_prev = series_b.iloc[-(i + 2)]
        if any(pd.isna(v) for v in [a_now, a_prev, b_now, b_prev]):
            continue
        if float(a_prev) <= float(b_prev) and float(a_now) > float(b_now):
            return True
    return False


# --- indikatör değerlendirmeleri ---

def _evaluate_rsi(close: pd.Series) -> IndicatorResult:
    rsi = _rsi(close, 14)
    if rsi.dropna().empty:
        return IndicatorResult("RSI", "rsi", False, None, "veri yok")

    signal_line = _sma(rsi, 9)
    rsi_now = _safe_last(rsi)

    # Son 3 barda 30 cizgisini yukari gecti mi? (asiri satimdan kurtulus)
    cross_30 = _crosses_above_within(rsi, 30, n=3)
    # Son 3 barda sinyal cizgisini yukari gecti mi?
    cross_signal = _crosses_above_within(rsi, signal_line, n=3)

    signal = bool(cross_30 or cross_signal)
    reason = []
    if cross_30:
        reason.append("son 3 barda 30 yukari kesis")
    if cross_signal:
        reason.append("sinyal kesisi")

    detail = ", ".join(reason) if reason else (f"RSI={rsi_now:.1f}" if rsi_now else "notr")
    return IndicatorResult(
        name="RSI", key="rsi", signal=signal,
        value=round(rsi_now, 2) if rsi_now is not None else None,
        detail=detail,
    )


def _evaluate_macd(close: pd.Series) -> IndicatorResult:
    macd_line, signal_line = _macd(close)
    if macd_line.dropna().empty:
        return IndicatorResult("MACD", "macd", False, None, "veri yok")

    # Son 3 barda MACD, sinyal cizgisini yukari gecti mi?
    cross = _crosses_above_within(macd_line, signal_line, n=3)
    macd_now = _safe_last(macd_line)

    return IndicatorResult(
        name="MACD", key="macd", signal=bool(cross),
        value=round(macd_now, 4) if macd_now is not None else None,
        detail="son 3 barda yukari kesis" if cross else "kesis yok",
    )


def _evaluate_bbands(close: pd.Series) -> IndicatorResult:
    upper, middle, lower = _bbands(close)
    price = _safe_last(close)
    lower_now = _safe_last(lower)

    if price is None or lower_now is None:
        return IndicatorResult("BBands", "bbands", False, None, "veri yok")

    # Son 3 barda alt banda dokup yukari donmus mu?
    bounced = False
    n_check = min(3, len(close) - 1)
    for i in range(n_check):
        try:
            c_now = float(close.iloc[-(i + 1)])
            c_prev = float(close.iloc[-(i + 2)])
            l_now = float(lower.iloc[-(i + 1)])
            l_prev = float(lower.iloc[-(i + 2)])
            if any(pd.isna(v) for v in [c_now, c_prev, l_now, l_prev]):
                continue
            # Onceki mum alt bant bolgesi icindeydi (alt band * 1.01 altinda)
            touched = c_prev <= l_prev * 1.01
            # Simdi alt bandin uzerinde ve yukseliyor
            bouncing = c_now > l_now and c_now > c_prev
            if touched and bouncing:
                bounced = True
                break
        except (IndexError, ValueError):
            continue

    return IndicatorResult(
        name="BBands", key="bbands", signal=bounced,
        value=round(lower_now, 4),
        detail="son 3 barda alt banttan donus" if bounced else "notr",
    )


def _evaluate_ema(close: pd.Series, high_52w: float | None = None) -> IndicatorResult:
    ema = _ema(close, 50)
    if ema.dropna().empty:
        return IndicatorResult("EMA50", "ema50", False, None, "veri yok")
    price = _safe_last(close)
    ema_now = _safe_last(ema)
    if price is None or ema_now is None:
        return IndicatorResult("EMA50", "ema50", False, None, "veri yok")

    above_ema = bool(price > ema_now)
    # 52 haftalik zirvenin %3 icindeyse "tepe noktasina yakin" sayilir
    near_peak = bool(high_52w and high_52w > 0 and price >= high_52w * 0.97)

    signal = above_ema and not near_peak

    parts = []
    if above_ema:
        parts.append("fiyat EMA uzerinde")
    else:
        parts.append("fiyat EMA altinda")
    if near_peak:
        parts.append("52h zirveye yakin — sinyal yok")

    return IndicatorResult(
        name="EMA50", key="ema50", signal=signal,
        value=round(ema_now, 4),
        detail=", ".join(parts),
    )


def _evaluate_stoch(high: pd.Series, low: pd.Series, close: pd.Series) -> IndicatorResult:
    k_line, d_line = _stoch(high, low, close)
    if k_line.dropna().empty:
        return IndicatorResult("Stoch", "stoch", False, None, "veri yok")

    # Son 3 barda %K, %D'yi yukari gecti mi?
    cross = _crosses_above_within(k_line, d_line, n=3)
    k_now = _safe_last(k_line)

    # Asiri alim bolgesinde degil mi? (K >= 80 → asiri alim, sinyal gecersiz)
    not_overbought = k_now is None or k_now < 80
    signal = bool(cross and not_overbought)

    detail = "kesis yok"
    if cross:
        if k_now is not None and k_now >= 80:
            detail = "asiri alim bolgesinde kesis — sinyal yok"
        elif k_now is not None and k_now < 30:
            detail = "asiri satimdan yukari kesis"
        else:
            detail = "son 3 barda yukari kesis"

    return IndicatorResult(
        name="Stoch", key="stoch", signal=signal,
        value=round(k_now, 2) if k_now is not None else None,
        detail=detail,
    )


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
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    last_close = float(close.iloc[-1])
    if len(close) >= 2 and not pd.isna(close.iloc[-2]) and close.iloc[-2] != 0:
        change_pct = (last_close - float(close.iloc[-2])) / float(close.iloc[-2]) * 100.0
    else:
        change_pct = 0.0

    # 52 haftalik yuksek/dusuk — EMA indikatoru icin onceden hesaplanmali
    high_series = high.tail(252).dropna()
    low_series = low.tail(252).dropna()
    high_52 = float(high_series.max()) if not high_series.empty else None
    low_52 = float(low_series.min()) if not low_series.empty else None

    indicators = [
        _evaluate_rsi(close),
        _evaluate_macd(close),
        _evaluate_bbands(close),
        _evaluate_ema(close, high_52w=high_52),
        _evaluate_stoch(high, low, close),
    ]

    score = sum(1 for ind in indicators if ind.signal)
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
