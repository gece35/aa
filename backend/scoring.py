"""Teknik gosterge bazli puanlama motoru.

5 gostergeden olusur, her AL sinyali +1 puan verir:
  - RSI (14)          : 30 yukari kesis VEYA RSI > SMA9 VEYA RSI < 50 ve yukselisli
  - MACD (12, 26, 9)  : MACD cizgisi sinyali yukari yonlu keser
  - Bollinger (20, 2) : Alt bandi yakin/dokun sonra yukari
  - EMA (50)          : Fiyat EMA50 uzerinde
  - Stochastic        : %K %D'yi yukari keser (asiri satim bolgesinde bonus)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List

import numpy as np
import pandas as pd
import pandas_ta as ta


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
        }


def _safe_last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _crosses_above(series_a: pd.Series, series_b, lookback: int = 2) -> bool:
    if series_a is None or len(series_a) < lookback + 1:
        return False
    a_now, a_prev = series_a.iloc[-1], series_a.iloc[-2]
    if isinstance(series_b, (int, float)):
        b_now = b_prev = series_b
    else:
        if series_b is None or len(series_b) < lookback + 1:
            return False
        b_now, b_prev = series_b.iloc[-1], series_b.iloc[-2]
    if pd.isna(a_now) or pd.isna(a_prev) or pd.isna(b_now) or pd.isna(b_prev):
        return False
    return a_prev <= b_prev and a_now > b_now


def _evaluate_rsi(close: pd.Series) -> IndicatorResult:
    rsi = ta.rsi(close, length=14)
    if rsi is None or rsi.dropna().empty:
        return IndicatorResult("RSI", "rsi", False, None, "veri yok")

    signal_line = rsi.rolling(window=9).mean()
    rsi_now = _safe_last(rsi)
    sma_now = _safe_last(signal_line)

    cross_30 = _crosses_above(rsi, 30)
    cross_signal = _crosses_above(rsi, signal_line)
    rising = (
        rsi_now is not None and rsi_now < 50 and len(rsi) >= 3
        and rsi.iloc[-1] > rsi.iloc[-2] > rsi.iloc[-3]
    )

    signal = bool(cross_30 or cross_signal or rising)

    reason = []
    if cross_30:
        reason.append("30 yukari kesis")
    if cross_signal:
        reason.append("sinyal kesisi")
    if rising:
        reason.append("<50 yukselis")

    return IndicatorResult(
        name="RSI",
        key="rsi",
        signal=signal,
        value=round(rsi_now, 2) if rsi_now is not None else None,
        detail=", ".join(reason) if reason else f"RSI={rsi_now:.1f}" if rsi_now else "notr",
    )


def _evaluate_macd(close: pd.Series) -> IndicatorResult:
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is None or macd_df.dropna().empty:
        return IndicatorResult("MACD", "macd", False, None, "veri yok")

    macd_line = macd_df.iloc[:, 0]
    signal_line = macd_df.iloc[:, 2]
    cross = _crosses_above(macd_line, signal_line)
    macd_now = _safe_last(macd_line)

    return IndicatorResult(
        name="MACD",
        key="macd",
        signal=bool(cross),
        value=round(macd_now, 4) if macd_now is not None else None,
        detail="yukari kesis" if cross else "kesis yok",
    )


def _evaluate_bbands(close: pd.Series) -> IndicatorResult:
    bb = ta.bbands(close, length=20, std=2)
    if bb is None or bb.dropna().empty:
        return IndicatorResult("BBands", "bbands", False, None, "veri yok")

    lower = bb.iloc[:, 0]
    middle = bb.iloc[:, 1]

    price = _safe_last(close)
    lower_now = _safe_last(lower)
    middle_now = _safe_last(middle)

    if price is None or lower_now is None:
        return IndicatorResult("BBands", "bbands", False, None, "veri yok")

    touched = False
    if len(close) >= 3 and len(lower) >= 3:
        prev_price = close.iloc[-2]
        prev_lower = lower.iloc[-2]
        if not pd.isna(prev_price) and not pd.isna(prev_lower):
            touched = prev_price <= prev_lower and price > lower_now

    near_lower = price <= lower_now * 1.02 and (middle_now is None or price < middle_now)

    signal = bool(touched or near_lower)
    return IndicatorResult(
        name="BBands",
        key="bbands",
        signal=signal,
        value=round(lower_now, 4),
        detail="alt banttan donus" if touched else ("alt banda yakin" if near_lower else "notr"),
    )


def _evaluate_ema(close: pd.Series) -> IndicatorResult:
    ema = ta.ema(close, length=50)
    if ema is None or ema.dropna().empty:
        return IndicatorResult("EMA50", "ema50", False, None, "veri yok")
    price = _safe_last(close)
    ema_now = _safe_last(ema)
    if price is None or ema_now is None:
        return IndicatorResult("EMA50", "ema50", False, None, "veri yok")
    signal = price > ema_now
    return IndicatorResult(
        name="EMA50",
        key="ema50",
        signal=bool(signal),
        value=round(ema_now, 4),
        detail="fiyat EMA uzerinde" if signal else "fiyat EMA altinda",
    )


def _evaluate_stoch(high: pd.Series, low: pd.Series, close: pd.Series) -> IndicatorResult:
    stoch = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    if stoch is None or stoch.dropna().empty:
        return IndicatorResult("Stoch", "stoch", False, None, "veri yok")
    k_line = stoch.iloc[:, 0]
    d_line = stoch.iloc[:, 1]
    cross = _crosses_above(k_line, d_line)
    k_now = _safe_last(k_line)
    oversold_bonus = k_now is not None and k_now < 30
    signal = bool(cross and (oversold_bonus or (k_now is not None and k_now < 50)))
    detail = "yok"
    if cross and oversold_bonus:
        detail = "asiri satimdan kesis"
    elif cross:
        detail = "yukari kesis"
    return IndicatorResult(
        name="Stoch",
        key="stoch",
        signal=signal,
        value=round(k_now, 2) if k_now is not None else None,
        detail=detail,
    )


def _pct_change_back(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return 0.0
    prev = float(close.iloc[-(n + 1)])
    if prev == 0 or pd.isna(prev):
        return 0.0
    return (float(close.iloc[-1]) - prev) / prev * 100.0


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

    indicators = [
        _evaluate_rsi(close),
        _evaluate_macd(close),
        _evaluate_bbands(close),
        _evaluate_ema(close),
        _evaluate_stoch(high, low, close),
    ]

    score = sum(1 for ind in indicators if ind.signal)

    sparkline_raw = close.tail(30).dropna().tolist()
    week_change = _pct_change_back(close, 5)
    month_change = _pct_change_back(close, 21)

    high_series = high.tail(252).dropna()
    low_series = low.tail(252).dropna()
    high_52 = float(high_series.max()) if not high_series.empty else None
    low_52 = float(low_series.min()) if not low_series.empty else None

    last_volume = float(volume.iloc[-1]) if not volume.empty and not pd.isna(volume.iloc[-1]) else 0.0

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
    )


def score_symbol_detailed(symbol: str, df: pd.DataFrame) -> dict | None:
    base = score_symbol(symbol, df)
    if base is None:
        return None
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    hist = [
        {
            "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
            "close": float(val),
        }
        for idx, val in close.tail(60).items()
        if not pd.isna(val)
    ]

    avg_vol = float(volume.tail(20).mean()) if not volume.empty else 0.0

    out = base.to_dict()
    out.update({
        "history": hist,
        "avg_volume_20d": round(avg_vol, 2),
        "data_points": int(len(close)),
    })
    return out
