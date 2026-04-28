"""Teknik gosterge bazli "trend sagligi" puanlama motoru.

5 gostergeden olusur, her saglikli durum +1 puan verir (toplam 0-5):
  - RSI (14)          : 50 <= RSI < 70 (yukari momentum, asiri alim degil)
  - MACD (12, 26, 9)  : MACD > sinyal cizgisi VE MACD > 0 (pozitif momentum aktif)
  - Bollinger (20, 2) : Fiyat orta band uzerinde VE ust banda < %95 (saglikli yukseliste, asiri uzanma yok)
  - EMA               : Fiyat > EMA50 VE fiyat > EMA20 (kisa ve orta vade trend pozitif)
  - Hacim             : Son 5 gunun ortalama hacmi, 20-gunluk ortalamadan >= %20 yuksek (gercek alici destegi)

Skor "anlik giris firsati" degil "pozisyon hala saglikli mi?" sorusunu yanitlar.
Trend devam ettigi surece skor yuksek kalir, bozulunca dusera.

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


def _safe_last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


# --- indikator degerlendirmeleri (trend sagligi tabanli) ---

def _evaluate_rsi(close: pd.Series) -> IndicatorResult:
    """RSI 50-70 araligi: yukari momentum aktif, asiri alim degil."""
    rsi = _rsi(close, 14)
    rsi_now = _safe_last(rsi)
    if rsi_now is None:
        return IndicatorResult("RSI", "rsi", False, None, "veri yok")

    healthy = 50.0 <= rsi_now < 70.0
    if rsi_now >= 70:
        detail = f"RSI {rsi_now:.0f} — asiri alim bolgesi"
    elif rsi_now >= 50:
        detail = f"RSI {rsi_now:.0f} — pozitif momentum"
    elif rsi_now >= 30:
        detail = f"RSI {rsi_now:.0f} — zayif momentum"
    else:
        detail = f"RSI {rsi_now:.0f} — asiri satim"

    return IndicatorResult(
        name="RSI", key="rsi", signal=healthy,
        value=round(rsi_now, 2),
        detail=detail,
    )


def _evaluate_macd(close: pd.Series) -> IndicatorResult:
    """MACD > sinyal cizgisi VE MACD > 0: pozitif momentum aktif."""
    macd_line, signal_line = _macd(close)
    macd_now = _safe_last(macd_line)
    sig_now = _safe_last(signal_line)
    if macd_now is None or sig_now is None:
        return IndicatorResult("MACD", "macd", False, None, "veri yok")

    above_signal = macd_now > sig_now
    above_zero = macd_now > 0
    healthy = above_signal and above_zero

    if healthy:
        detail = "sinyal uzerinde, pozitif bolge"
    elif above_signal and not above_zero:
        detail = "sinyal uzerinde ama negatif bolge"
    elif above_zero and not above_signal:
        detail = "pozitif bolge ama sinyal altinda"
    else:
        detail = "negatif momentum"

    return IndicatorResult(
        name="MACD", key="macd", signal=healthy,
        value=round(macd_now, 4),
        detail=detail,
    )


def _evaluate_bbands(close: pd.Series) -> IndicatorResult:
    """Fiyat orta band uzerinde VE ust banda < %95: saglikli yukselis, asiri uzanma yok."""
    upper, middle, lower = _bbands(close)
    price = _safe_last(close)
    upper_now = _safe_last(upper)
    middle_now = _safe_last(middle)

    if price is None or upper_now is None or middle_now is None:
        return IndicatorResult("BBands", "bbands", False, None, "veri yok")

    above_mid = price > middle_now
    not_extended = price < upper_now * 0.95
    healthy = above_mid and not_extended

    if not above_mid:
        detail = "orta band altinda"
    elif not not_extended:
        detail = "ust banda asiri yakin"
    else:
        detail = "orta-ust band arasinda saglikli"

    return IndicatorResult(
        name="BBands", key="bbands", signal=healthy,
        value=round(middle_now, 4),
        detail=detail,
    )


def _evaluate_ema(close: pd.Series, high_52w: float | None = None) -> IndicatorResult:
    """Fiyat > EMA50 VE fiyat > EMA20: kisa ve orta vade trend pozitif."""
    ema50 = _ema(close, 50)
    ema20 = _ema(close, 20)
    price = _safe_last(close)
    ema50_now = _safe_last(ema50)
    ema20_now = _safe_last(ema20)
    if price is None or ema50_now is None or ema20_now is None:
        return IndicatorResult("EMA", "ema50", False, None, "veri yok")

    above_50 = price > ema50_now
    above_20 = price > ema20_now
    healthy = above_50 and above_20

    if healthy:
        detail = "fiyat EMA20 ve EMA50 uzerinde"
    elif above_50:
        detail = "fiyat EMA50 uzerinde, EMA20 altinda"
    elif above_20:
        detail = "fiyat EMA20 uzerinde, EMA50 altinda"
    else:
        detail = "fiyat her iki EMA altinda"

    return IndicatorResult(
        name="EMA", key="ema50", signal=healthy,
        value=round(ema50_now, 4),
        detail=detail,
    )


def _evaluate_volume(volume: pd.Series) -> IndicatorResult:
    """Son 5 gunun ortalama hacmi, 20-gunluk ortalamadan >= %20 yuksek: gercek alici destegi."""
    if volume is None or volume.empty or len(volume) < 25:
        return IndicatorResult("Hacim", "volume", False, None, "veri yok")

    vol_clean = volume.dropna()
    if len(vol_clean) < 25:
        return IndicatorResult("Hacim", "volume", False, None, "veri yok")

    avg_5d = float(vol_clean.iloc[-5:].mean())
    avg_20d = float(vol_clean.iloc[-20:].mean())
    if avg_20d <= 0:
        return IndicatorResult("Hacim", "volume", False, None, "veri yok")

    ratio = avg_5d / avg_20d
    healthy = ratio >= 1.20

    if ratio >= 1.50:
        detail = f"hacim ortalamanin %{(ratio - 1) * 100:.0f} ustunde — guclu ilgi"
    elif ratio >= 1.20:
        detail = f"hacim ortalamanin %{(ratio - 1) * 100:.0f} ustunde — alici destegi"
    elif ratio >= 0.80:
        detail = "hacim normal seviyede"
    else:
        detail = f"hacim ortalamanin %{(1 - ratio) * 100:.0f} altinda — ilgi azaliyor"

    return IndicatorResult(
        name="Hacim", key="volume", signal=healthy,
        value=round(ratio, 2),
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
        _evaluate_volume(volume),
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
