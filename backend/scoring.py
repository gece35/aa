"""Hibrit durum + kesişim puanlama motoru — 0-10.

Her bileşen mevcut piyasa durumunu (state) sürekli olarak ölçer;
kesişimler küçük tazelik bonusu verir ama zorunlu değildir.
Böylece hisseler aktif kesişim olmadan da yüksek skor alabilir.

Bileşenler ve maksimum katkıları:
  1. EMA Hizalama       (trend)     — 2.0  price>EMA30>EMA50>EMA200 hiyerarşisi
  2. MACD Pozisyon      (momentum)  — 1.5  MACD > sinyal + MACD > 0
  3. RSI Durumu         (rsi)       — 2.0  bölge skoru + oversold recovery
  4. BB Giriş           (bbands)    — 1.5  Bollinger alt banda yakınlık
  5. MACD Histogram     (macd_zero) — 1.0  histogram yönü + yön değişimi
  6. ADX Güç            (adx)       — 1.5  trend gücü + DI yönü
  7. Hacim Onayı        (volume)    — 1.0  bağımsız hacim spike
  Genişleme cezası      (extension) — 0 / −2.0

Ham maks ≈ 10.5 → clip(0, 10).

`compute_score_frame` tüm df boyunca vektörize seriler üretir; hem canlı
tarayıcı (`score_symbol`) hem backtest aynı motoru tüketir — tek kaynak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.patterns import detect_patterns, detect_auto_trendlines, summarize_patterns


# ── ayarlanabilir parametreler ───────────────────────────────────────────────

SMOOTH_SPAN = 2   # son puan yumuşatma (EWM span)

# Bileşen ağırlıkları (max puanlar)
W_TREND    = 2.0   # EMA hizalama
W_MOMENTUM = 1.5   # MACD pozisyon
W_RSI      = 2.0   # RSI durum + recovery
W_BBANDS   = 1.5   # Bollinger giriş
W_MACD_H   = 1.0   # MACD histogram
W_ADX      = 1.5   # ADX güç
W_VOLUME   = 1.0   # Hacim onayı
EXT_PENALTY_MAX = -2.0   # Genişleme cezası üst sınırı

# ── canlı giriş sinyali eşikleri ─────────────────────────────────────────────
# backend/backtest.py bu sabitleri buradan import eder — tek kaynak (TDOV giriş
# kuralları ile canlı taramadaki "Giriş Sinyali" rozeti birebir aynı eşikleri
# kullanır, iki yerde ayrı ayrı güncellenme riski olmasın diye).
ENTRY_TRIGGER_LOOKBACK = 2     # taze kesişim penceresi (bar)
MIN_SCORE_EVENT        = 6     # olay-tabanlı girişte istenen min skor
MIN_TREND_SUBSCORE     = 1.2   # ema_align max 2.0; %60 doluluk eşiği
HIGH52W_FLOOR          = 0.85  # 52 haftalık zirvenin altında kalınabilecek pay
REQUIRE_VOLUME_ENTRY   = True
REGIME_EMA_SHORT       = 50
REGIME_RECENT_DAYS     = 20
REGIME_RECENT_FLOOR    = -0.03


@dataclass
class IndicatorResult:
    name: str
    key: str
    score: float
    max_score: float
    signal: bool = False
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
    entry_signal: bool = False

    @staticmethod
    def _sf(v: float, ndigits: int = 2) -> float:
        """NaN/Inf değerlerini 0.0'a çevirir (JSON uyumluluğu için)."""
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return 0.0
        return round(v, ndigits)

    def to_dict(self) -> dict:
        sf = self._sf
        return {
            "symbol": self.symbol,
            "score": self.score,
            "price": sf(self.price, 4),
            "change_pct": sf(self.change_pct, 2),
            "change_week_pct": sf(self.change_week_pct, 2),
            "change_month_pct": sf(self.change_month_pct, 2),
            "volume": int(self.volume),
            "high_52w": sf(self.high_52w, 4) if self.high_52w else None,
            "low_52w": sf(self.low_52w, 4) if self.low_52w else None,
            "sparkline": [sf(float(v), 4) for v in self.sparkline],
            "indicators": [asdict(ind) for ind in self.indicators],
            "volume_spike": self.volume_spike,
            "near_peak": self.near_peak,
            "entry_signal": self.entry_signal,
        }


# ── temel indikatör hesapları ─────────────────────────────────────────────────

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


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    up   = high.diff()
    down = -low.diff()
    plus_dm  = ((up > down) & (up > 0)).astype(float) * up.clip(lower=0)
    minus_dm = ((down > up) & (down > 0)).astype(float) * down.clip(lower=0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    alpha = 1.0 / length
    atr      = tr.ewm(alpha=alpha, adjust=False, min_periods=length).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=alpha, adjust=False, min_periods=length).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False, min_periods=length).mean() / atr.replace(0, np.nan)
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=length).mean()
    return adx, plus_di, minus_di


def _safe_last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


# ── kesişim yardımcıları ──────────────────────────────────────────────────────

def _bars_since_cross(condition: pd.Series) -> pd.Series:
    """Her barda son True'dan bu yana geçen bar sayısını döndürür (0=o gün).
    İlk kesişimden önce NaN."""
    cum  = condition.cumsum()
    bars = condition.groupby(cum).cumcount()
    return bars.where(cum > 0, other=np.nan)


def _freshness(bars_since: pd.Series, lookback: float = 20) -> pd.Series:
    """Lineer sönme: kesişim gününde 1.0, lookback'te 0.0. Önce/sonra 0."""
    f = (1.0 - bars_since.fillna(lookback + 1) / lookback).clip(0.0, 1.0)
    return pd.Series(np.where(bars_since.notna(), f, 0.0), index=bars_since.index)


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    """a, b'yi yukarı kestiği barlar True."""
    return (a > b) & (a.shift(1) <= b.shift(1))


# ── yeni state-based sinyal fonksiyonları ────────────────────────────────────

def _bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0):
    """BB middle, upper, lower, bandwidth, %B.
    %B = 0 → alt bant, 1 → üst bant, <0 → alt bandın altı."""
    mid   = _sma(close, window)
    std   = close.rolling(window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    bw    = (upper - lower) / mid.replace(0, np.nan)
    pctb  = (close - lower) / (upper - lower).replace(0, np.nan)
    return mid, upper, lower, bw, pctb.fillna(0.5)


def _ema_align_score(close: pd.Series):
    """EMA hizalama skoru (0 – W_TREND). State-based, kesişimsiz.
    Döner: (score_series, ema30, ema50, ema200)"""
    ema30  = _ema(close, 30)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)
    # 3 kademeli hiyerarşi, her biri eşit ağırlık
    s = (
        (close > ema30 ).astype(float) * (W_TREND / 3)
      + (ema30  > ema50 ).astype(float) * (W_TREND / 3)
      + (ema50  > ema200).astype(float) * (W_TREND / 3)
    )
    return s, ema30, ema50, ema200


def _macd_position_score(close: pd.Series):
    """MACD pozisyon skoru (0 – W_MOMENTUM). State + taze kesişim bonusu.
    Döner: (score_series, macd_line, signal_line)"""
    macd_line, signal_line = _macd(close)
    above_sig  = (macd_line > signal_line).astype(float) * 0.5
    above_zero = (macd_line > 0).astype(float)            * 0.4
    cross      = _cross_up(macd_line, signal_line)
    fresh      = _freshness(_bars_since_cross(cross), lookback=5)
    score      = (above_sig + above_zero + fresh * 0.1).clip(0.0, 1.0)
    return score * W_MOMENTUM, macd_line, signal_line


def _rsi_state_score(close: pd.Series):
    """RSI bölge + recovery skoru (0 – W_RSI).
    Döner: (score_series, rsi_series)"""
    rsi = _rsi(close, 14)
    rv  = rsi.fillna(50).values.astype(float)

    # Bölge skoru: 50-65 tam puan, aşırı uçlar düşük
    zone = np.select(
        [rv < 30, rv < 40, rv < 50, rv < 65, rv < 75],
        [0.0,      0.2,    0.5,     1.0,      0.7],
        default=0.1,
    )
    zone_s = pd.Series(zone, index=rsi.index)

    # Recovery: son 14 barda RSI < 35 görmüş + şu an toparlandı mı?
    rsi_min = rsi.rolling(14, min_periods=5).min()
    was_os  = (rsi_min < 35).fillna(False)
    denom   = (55.0 - rsi_min).replace(0, np.nan)
    recov   = ((rsi - rsi_min) / denom).clip(0.0, 1.0).fillna(0.0)
    cross50 = _cross_up(rsi, pd.Series(50.0, index=rsi.index))
    fresh50 = _freshness(_bars_since_cross(cross50), lookback=10)
    recov_s = (recov + fresh50 * 0.3).clip(0.0, 1.0)
    # Oversold görülmediyse recovery katkısını küçük tut
    recov_s = pd.Series(
        np.where(was_os.values, recov_s.values, recov_s.values * 0.2),
        index=rsi.index,
    )

    combined = (zone_s * 0.6 + recov_s * 0.4).clip(0.0, 1.0)
    return combined * W_RSI, rsi


def _bb_entry_score(
    close: pd.Series,
    bb_lower: pd.Series,
    bb_mid: pd.Series,
    bb_upper: pd.Series,
    pctb: pd.Series,
) -> pd.Series:
    """Bollinger giriş skoru (0 – W_BBANDS).
    Pozitif skor yalnızca pctb < 0.40 bölgesinde → bb_lower_touch alert uyumlu."""
    pv = pctb.fillna(0.5).values.astype(float)
    base = np.select(
        [pv < 0.10, pv < 0.20, pv < 0.40],
        [1.0,        0.7,       0.35],
        default=0.0,
    )
    base_s    = pd.Series(base, index=close.index)
    cross_mid = _cross_up(close, bb_mid)
    fresh_mid = _freshness(_bars_since_cross(cross_mid), lookback=8)
    score     = (base_s + fresh_mid * 0.3).clip(0.0, 1.0)
    return score * W_BBANDS


def _macd_histogram_score(macd_line: pd.Series, signal_line: pd.Series) -> pd.Series:
    """MACD histogram yön + momentum skoru (0 – W_MACD_H)."""
    hist     = macd_line - signal_line
    positive = (hist > 0).astype(float)            * 0.5
    growing  = (hist > hist.shift(1)).astype(float) * 0.3
    flip     = _cross_up(hist, pd.Series(0.0, index=hist.index))
    fresh_f  = _freshness(_bars_since_cross(flip), lookback=6)
    score    = (positive + growing + fresh_f * 0.2).clip(0.0, 1.0)
    return score * W_MACD_H


def _adx_strength_score(high: pd.Series, low: pd.Series, close: pd.Series):
    """ADX güç + DI yön skoru (0 – W_ADX).
    Döner: (score_series, adx_series, plus_di_series, minus_di_series)"""
    adx, plus_di, minus_di = _adx(high, low, close)
    av   = adx.fillna(0).values.astype(float)
    dpos = (plus_di > minus_di).astype(float).values

    base = np.select(
        [
            (av < 15) & (dpos == 0),
            (av < 15) & (dpos == 1),
            (av < 25) & (dpos == 1),
            (av < 40) & (dpos == 1),
        ],
        [0.0, 0.15, 0.5, 1.0],
        default=np.where(dpos == 1, 0.8, 0.0),
    )
    base_s   = pd.Series(base, index=close.index)
    di_cross = _cross_up(plus_di, minus_di)
    fresh_c  = _freshness(_bars_since_cross(di_cross), lookback=10)
    score    = (base_s + fresh_c * 0.2).clip(0.0, 1.0)
    return score * W_ADX, adx, plus_di, minus_di


def _volume_score(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Bağımsız hacim spike skoru (0 – W_VOLUME). Son 3 bar max alır."""
    if volume is None or volume.empty or len(volume) < 20:
        return pd.Series(0.0, index=close.index)
    sma20 = _sma(volume, 20)
    ratio = (volume / sma20.replace(0, np.nan)).fillna(0.0)
    rv    = ratio.values.astype(float)
    spike = np.select([rv >= 2.0, rv >= 1.5, rv >= 1.2], [1.0, 0.7, 0.4], default=0.0)
    return pd.Series(spike, index=close.index).rolling(3, min_periods=1).max() * W_VOLUME


def _extension_series(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Zirve konumu + EMA20 sapma cezası (0 ile −2.0 arası).
    Breakout muafiyeti: gerçek kırılımda ceza %70 azalır.
    Döner: (penalty_series, range_position_series)"""
    high52 = close.rolling(252, min_periods=60).max()
    low52  = close.rolling(252, min_periods=60).min()
    rng52  = (high52 - low52).replace(0, np.nan)
    rp     = ((close - low52) / rng52).clip(0, 1).fillna(0.5)

    rv = rp.values.astype(float)
    range_penalty = np.select(
        [rv <= 0.75, rv <= 0.85, rv <= 0.95],
        [
            0.0,
            -(rv - 0.75) / 0.10 * 0.8,
            -0.8 - (rv - 0.85) / 0.10 * 0.7,
        ],
        default=-1.5 - (rv - 0.95) / 0.05 * 1.0,
    )

    ema20 = _ema(close, 20)
    dev   = ((close - ema20) / ema20.replace(0, np.nan)).fillna(0)
    dv    = dev.values.astype(float)
    ema_penalty = -np.clip((dv - 0.07) / 0.08, 0.0, 0.5)

    total = (range_penalty + ema_penalty).clip(EXT_PENALTY_MAX, 0.0)

    if volume is not None and not volume.empty and len(volume) >= 20:
        vol_sma    = volume.rolling(20).mean()
        is_breakout = (
            (volume > vol_sma * 1.5) & (close >= high52 * 0.98)
        ).fillna(False)
        total = np.where(is_breakout.values, total * 0.30, total)

    score = pd.Series(np.clip(total, EXT_PENALTY_MAX, 0.0), index=close.index)
    return score, rp


# ── ana çerçeve ───────────────────────────────────────────────────────────────

def compute_score_frame(df: pd.DataFrame, index_close: Optional[pd.Series] = None) -> Dict[str, pd.Series]:
    """Tüm df boyunca vektörize alt-puanları, ham ve yumuşatılmış toplamı üretir.

    Döner: tüm sinyal serileri + total_raw + total + yardımcı değer serileri.
    Geriye uyumluluk için eski anahtarlar alias olarak eklenir.
    """
    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    # ── sinyal serileri ──
    trend_s, ema30, ema50, ema200       = _ema_align_score(close)
    mom_s, macd_line, signal_line       = _macd_position_score(close)
    rsi_s, rsi_val                      = _rsi_state_score(close)
    bb_mid, bb_upper, bb_lower, bb_bw, pctb = _bollinger(close)
    bb_s                                = _bb_entry_score(close, bb_lower, bb_mid, bb_upper, pctb)
    macdh_s                             = _macd_histogram_score(macd_line, signal_line)
    adx_s, adx_val, plus_di, minus_di   = _adx_strength_score(high, low, close)
    vol_s                               = _volume_score(close, volume)
    ext_penalty, rp                     = _extension_series(close, high, low, volume)

    # ── toplam ──
    total_raw = (
        trend_s.fillna(0)
        + mom_s.fillna(0)
        + rsi_s.fillna(0)
        + bb_s.fillna(0)
        + macdh_s.fillna(0)
        + adx_s.fillna(0)
        + vol_s.fillna(0)
        + ext_penalty.fillna(0)
    ).clip(0, 10)
    total = total_raw.ewm(span=SMOOTH_SPAN, adjust=False).mean().clip(0, 10)

    zero = pd.Series(0.0, index=close.index)

    return {
        # ── sinyal serileri (yeni key → yeni hesaplama) ──
        "trend":       trend_s,
        "momentum":    mom_s,
        "rsi":         rsi_s,
        "bbands":      bb_s,
        "macd_zero":   macdh_s,
        "adx":         adx_s,
        "volume":      vol_s,
        "ext_penalty": ext_penalty,
        # ── geriye uyumluluk alias'ları (backtest + alerts) ──
        "ema_cross":   trend_s,      # backtest MIN_TREND_SUBSCORE karşılaştırması
        "macd_signal": mom_s,
        "macd_cross":  mom_s,
        "rsi_signal":  rsi_s,
        "rsi_cross":   rsi_s,
        "di_cross":    adx_s,
        "rel_strength": zero,
        # ── toplamlar ──
        "total_raw": total_raw,
        "total":     total,
        # ── yardımcı değer serileri (detay ekranı + alert ind_val için) ──
        "ema30_val":      ema30,
        "ema50_val":      ema50,
        "ema200_val":     ema200,
        "macd_val":       macd_line,
        "signal_val":     signal_line,
        "rsi_val":        rsi_val,
        "rsi_signal_val": _ema(rsi_val, 9),
        "adx_val":        adx_val,
        "plus_di_val":    plus_di,
        "minus_di_val":   minus_di,
        "pctb_val":       pctb,
        "bb_mid_val":     bb_mid,
        "bb_upper_val":   bb_upper,
        "bb_lower_val":   bb_lower,
        "rp_val":         rp,
        # ── önceden hesaplanmış kesişim olay bayrakları (backtest + sinyal etüdü) ──
        # Boğa tetikleyicileri (yukarı kesişim):
        "x_macd_up":         _cross_up(macd_line, signal_line),
        "x_price_ema50_up":  _cross_up(close, ema50),
        "x_di_up":           _cross_up(plus_di, minus_di),
        "x_rsi50_up":        _cross_up(rsi_val, pd.Series(50.0, index=close.index)),
        # Ayı / trend kırılım tetikleyicileri (aşağı kesişim):
        "x_macd_dn":         _cross_up(signal_line, macd_line),
        "x_price_ema50_dn":  _cross_up(ema50, close),
        "x_di_dn":           _cross_up(minus_di, plus_di),
        "x_price_ema200_dn": _cross_up(ema200, close),
    }


# ── IndicatorResult üretimi ───────────────────────────────────────────────────

def _round1(v: float | None) -> float | None:
    return round(float(v), 1) if v is not None and not pd.isna(v) else None


def _build_indicators(frame: Dict[str, pd.Series]) -> List[IndicatorResult]:
    def last(key: str) -> float:
        v = _safe_last(frame.get(key))
        return 0.0 if v is None else v

    trend_sc = last("trend")
    mom_sc   = last("momentum")
    rsi_sc   = last("rsi")
    bb_sc    = last("bbands")
    macdh_sc = last("macd_zero")
    adx_sc   = last("adx")
    vol_sc   = last("volume")
    ext_sc   = last("ext_penalty")

    macd_v   = _safe_last(frame.get("macd_val"))
    rsi_v    = _safe_last(frame.get("rsi_val"))
    ema30_v  = _safe_last(frame.get("ema30_val"))
    ema50_v  = _safe_last(frame.get("ema50_val"))
    ema200_v = _safe_last(frame.get("ema200_val"))
    adx_v    = _safe_last(frame.get("adx_val"))
    pctb_v   = _safe_last(frame.get("pctb_val"))
    rp_v     = _safe_last(frame.get("rp_val"))

    def trend_detail() -> str:
        e30  = f"EMA30≈{ema30_v:.2f}"  if ema30_v  is not None else "EMA30"
        e50  = f"EMA50≈{ema50_v:.2f}"  if ema50_v  is not None else "EMA50"
        e200 = f"EMA200≈{ema200_v:.2f}" if ema200_v is not None else "EMA200"
        if trend_sc >= W_TREND * 0.9:
            return f"Fiyat > {e30} > {e50} > {e200} — tam hizalama, güçlü yükseliş trendi"
        if trend_sc >= W_TREND * 0.6:
            return f"Kısmi EMA hizalaması ({e50}) — trend gelişiyor"
        if trend_sc >= W_TREND * 0.3:
            return f"Fiyat en az bir EMA'nın üstünde ({e50})"
        return f"Fiyat EMA'ların altında ({e50}) — düşüş baskısı"

    def mom_detail() -> str:
        mv = f"MACD {macd_v:.3f}" if macd_v is not None else "MACD"
        if mom_sc >= W_MOMENTUM * 0.8:
            return f"{mv} — sinyal üstünde ve pozitif bölgede (güçlü momentum)"
        if mom_sc >= W_MOMENTUM * 0.4:
            return f"{mv} — sinyal veya sıfır üstünde (kısmi pozisyon)"
        return f"{mv} — sinyal altında veya negatif bölgede"

    def rsi_detail() -> str:
        rv = f"RSI {rsi_v:.0f}" if rsi_v is not None else "RSI"
        if rsi_sc >= W_RSI * 0.85:
            return f"{rv} — sağlıklı yükseliş bölgesinde (50-65) veya oversold'dan taze toparlama"
        if rsi_sc >= W_RSI * 0.55:
            return f"{rv} — momentum birikimi bölgesinde (40-65)"
        if rsi_sc >= W_RSI * 0.25:
            return f"{rv} — toparlanma başlangıcı veya düşük momentum bölgesi"
        if rsi_v is not None and rsi_v >= 75:
            return f"{rv} — aşırı alım bölgesinde, geri çekilme riski"
        return f"{rv} — zayıf momentum"

    def bb_detail() -> str:
        pv = f"%B {pctb_v:.2f}" if pctb_v is not None else ""
        if pctb_v is not None and pctb_v > 0.80:
            return f"{pv} — üst band yakını, aşırı alım riski"
        if bb_sc >= W_BBANDS * 0.8:
            return f"{pv} — Bollinger alt banda çok yakın: güçlü giriş bölgesi"
        if bb_sc >= W_BBANDS * 0.4:
            return f"{pv} — Bollinger alt bant bölgesinde veya orta bandı taze kesti"
        if bb_sc >= W_BBANDS * 0.1:
            return f"{pv} — Bollinger alt-orta band arası"
        return f"{pv} — Bollinger orta-üst band bölgesi, giriş için erken"

    def macdh_detail() -> str:
        if macdh_sc >= W_MACD_H * 0.8:
            return "MACD histogramı pozitif ve büyüyor — güçlenen momentum"
        if macdh_sc >= W_MACD_H * 0.4:
            return "MACD histogramı yön değiştirdi veya pozitife döndü"
        return "MACD histogramı negatif veya zayıflıyor"

    def adx_detail() -> str:
        av = f"ADX {adx_v:.0f}" if adx_v is not None else "ADX"
        if adx_sc >= W_ADX * 0.85:
            return f"{av} — güçlü trend, DI+ baskın (25+)"
        if adx_sc >= W_ADX * 0.45:
            return f"{av} — trend oluşuyor, DI+ > DI-"
        if adx_sc >= W_ADX * 0.1:
            return f"{av} — zayıf trend başlangıcı"
        return f"{av} — trend yok veya DI- baskın"

    def vol_detail() -> str:
        if vol_sc >= W_VOLUME * 0.9:
            return "Çok güçlü hacim spike (SMA20 × 2+) — güçlü katılım"
        if vol_sc >= W_VOLUME * 0.6:
            return "Güçlü hacim artışı — hareket teyitli"
        if vol_sc >= W_VOLUME * 0.3:
            return "Orta seviye hacim artışı"
        return "Belirgin hacim onayı yok"

    def ext_detail() -> str:
        if ext_sc >= -0.2:
            return "52-hft aralığında rahat konum, giriş riski düşük"
        rp_pct = round(rp_v * 100) if rp_v is not None else "?"
        if ext_sc >= -0.8:
            return f"52-hft aralığının %{rp_pct}'inde — hafif uzamış"
        if ext_sc >= -1.8:
            return f"52-hft aralığının %{rp_pct}'inde — uzamış, dikkat"
        return f"52-hft aralığının %{rp_pct}'inde — zirveye yapışık / geri çekilme riski yüksek"

    bb_ind = IndicatorResult("BB Giriş", "bbands", _round1(bb_sc), W_BBANDS,
                             value=_round1(pctb_v), detail=bb_detail())
    # alert bb_lower_touch uyumluluğu: signal sadece gerçekten alt band bölgesindeyken True
    bb_ind.signal = pctb_v is not None and pctb_v < 0.40

    return [
        IndicatorResult("EMA Hizalama",   "trend",    _round1(trend_sc), W_TREND,
                        value=_round1(ema50_v),   detail=trend_detail()),
        IndicatorResult("MACD Pozisyon",  "momentum", _round1(mom_sc),   W_MOMENTUM,
                        value=_round1(macd_v),    detail=mom_detail()),
        IndicatorResult("RSI Durumu",     "rsi",      _round1(rsi_sc),   W_RSI,
                        value=_round1(rsi_v),     detail=rsi_detail()),
        bb_ind,
        IndicatorResult("MACD Histogram", "macd_zero",_round1(macdh_sc), W_MACD_H,
                        value=_round1(macd_v),    detail=macdh_detail()),
        IndicatorResult("ADX Güç",        "adx",      _round1(adx_sc),   W_ADX,
                        value=_round1(adx_v),     detail=adx_detail()),
        IndicatorResult("Hacim Onayı",    "volume",   _round1(vol_sc),   W_VOLUME,
                        value=None,               detail=vol_detail()),
        IndicatorResult("Genişleme Riski","extension",_round1(ext_sc),   0.0,
                        value=_round1(rp_v),      detail=ext_detail()),
    ]


# ── destek / direnç ───────────────────────────────────────────────────────────

def _find_sr_levels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 120,
    window: int = 5,
    cluster_pct: float = 0.015,
) -> dict:
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

        neighbors_l = [float(l.iloc[i + j]) for j in range(-window, window + 1)
                       if j != 0 and not pd.isna(l.iloc[i + j])]
        if neighbors_l and lo <= min(neighbors_l):
            raw_sups.append(lo)

        neighbors_h = [float(h.iloc[i + j]) for j in range(-window, window + 1)
                       if j != 0 and not pd.isna(h.iloc[i + j])]
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

    return {"supports": cluster(raw_sups), "resistances": cluster(raw_ress)}


def _calc_sl_tp(price: float, supports: list, resistances: list) -> tuple:
    sups_below = [s for s in supports if s < price * 0.995]
    ress_above = [r for r in resistances if r > price * 1.005]
    stop_loss   = round(max(sups_below) * 0.985, 4) if sups_below else None
    take_profit = round(min(ress_above), 4)          if ress_above else None
    return stop_loss, take_profit


# ── yardımcılar ───────────────────────────────────────────────────────────────

def _pct_change_back(close: pd.Series, n: int) -> float:
    clean = close.dropna()
    if len(clean) <= n:
        return 0.0
    last = float(clean.iloc[-1])
    prev = float(clean.iloc[-(n + 1)])
    if prev == 0:
        return 0.0
    return (last - prev) / prev * 100.0


def _index_close_of(index_df) -> Optional[pd.Series]:
    if index_df is None:
        return None
    if isinstance(index_df, pd.Series):
        return index_df.astype(float)
    if isinstance(index_df, pd.DataFrame) and "Close" in index_df.columns:
        return index_df["Close"].astype(float)
    return None


# ── canlı giriş sinyali (backtest.py'nin olay-tabanlı giriş kurallarıyla aynı eşikler) ──

def compute_regime_ok(index_df) -> bool:
    """Piyasa rejimi yukarı mı? (BIST: XU100, ABD: S&P 500)

    backtest.py'deki dual rejim kapısıyla birebir aynı kriter: endeks EMA200
    üstünde VE (EMA50 üstünde OR son 20 günde -%3'ten fazla düşmemiş). Rejim
    kapalıyken hiçbir hissede Giriş Sinyali rozeti gösterilmez — backtest'te de
    rejim kapalıyken portföy hiç yeni pozisyon açmaz, aynı kural canlıda uygulanır.
    """
    index_close = _index_close_of(index_df)
    if index_close is None:
        return True  # endeks verisi yoksa filtre uygulanamaz, engellemeyelim
    close = index_close.dropna()
    if len(close) < 60:
        return True

    long_ok = True
    if len(close) >= 200:
        ema200 = close.ewm(span=200, adjust=False).mean()
        long_ok = bool(close.iloc[-1] > ema200.iloc[-1])
    if not long_ok:
        return False

    ema_short = close.ewm(span=REGIME_EMA_SHORT, adjust=False).mean()
    above_short = bool(close.iloc[-1] > ema_short.iloc[-1])
    not_falling = True
    if len(close) > REGIME_RECENT_DAYS:
        ret_recent = close.pct_change(REGIME_RECENT_DAYS).iloc[-1]
        not_falling = bool(not pd.isna(ret_recent) and ret_recent > REGIME_RECENT_FLOOR)
    return above_short or not_falling


def compute_entry_signal(
    df: pd.DataFrame,
    frame: Dict[str, pd.Series],
    index_close: Optional[pd.Series],
    market: str,
) -> bool:
    """Son bar için backtest.py'nin olay-tabanlı giriş kurallarının aynısını kontrol eder.

    Tarama ekranındaki "🎯 Giriş Sinyali" rozeti bu fonksiyona dayanır: taze
    boğa kesişimi + trend yönü onayı + (ABD'de) göreli güç + hacim onayı +
    52 hafta filtresi — backend/backtest.py `_build_signals`/ana döngü ile aynı
    eşikleri kullanır (bkz. rehber.html "Basit Anlatım"). Backtest'in aksine
    250 barlık ısınma zorunluluğu yoktur (score_symbol ile aynı min. 60 bar);
    bu yüzden kısa geçmişli hisselerde EMA200 daha az anlamlı olabilir.
    """
    close = df["Close"].astype(float)
    if len(close.dropna()) < 60:
        return False

    ema50_val, ema200_val = frame["ema50_val"], frame["ema200_val"]
    c_last, e50_last, e200_last = close.iloc[-1], ema50_val.iloc[-1], ema200_val.iloc[-1]
    if pd.isna(c_last) or pd.isna(e50_last) or pd.isna(e200_last):
        return False
    if not (c_last > e200_last and e50_last > e200_last):
        return False

    market = (market or "bist").lower()
    if market == "us":
        # ABD: en az 2 eş zamanlı yukarı kesişim — tek kesişim gürültülü
        bull_count = (
            frame["x_macd_up"].fillna(False).astype(int)
            + frame["x_price_ema50_up"].fillna(False).astype(int)
            + frame["x_di_up"].fillna(False).astype(int)
            + frame["x_rsi50_up"].fillna(False).astype(int)
        )
        bull_trigger = bool((bull_count.tail(ENTRY_TRIGGER_LOOKBACK) >= 2).any())

        rel_ok = True
        if index_close is not None and len(close) > 20:
            idx_ret20 = index_close.reindex(df.index, method="ffill").pct_change(20)
            if len(idx_ret20.dropna()):
                stock_ret20 = close.pct_change(20).iloc[-1]
                idx_last = idx_ret20.iloc[-1]
                if not pd.isna(stock_ret20) and not pd.isna(idx_last):
                    rel_ok = stock_ret20 > idx_last
    else:
        # BIST: tek kesişim yeterli, göreli güç filtresi yok
        bull_any = (
            frame["x_macd_up"].fillna(False)
            | frame["x_price_ema50_up"].fillna(False)
            | frame["x_di_up"].fillna(False)
            | frame["x_rsi50_up"].fillna(False)
        )
        bull_trigger = bool(bull_any.tail(ENTRY_TRIGGER_LOOKBACK).any())
        rel_ok = True

    if not bull_trigger or not rel_ok:
        return False

    total_last = _safe_last(frame["total"])
    score = int(round(max(0.0, min(10.0, total_last)))) if total_last is not None else 0
    if score < MIN_SCORE_EVENT:
        return False

    trend_sub = _safe_last(frame["trend"])
    if trend_sub is None or trend_sub < MIN_TREND_SUBSCORE:
        return False

    if REQUIRE_VOLUME_ENTRY and "Volume" in df.columns:
        volume = df["Volume"].astype(float)
        if len(volume) >= 20:
            vol_sma20 = volume.rolling(20).mean().iloc[-1]
            if pd.isna(vol_sma20) or volume.iloc[-1] < vol_sma20:
                return False

    high52w = close.rolling(252, min_periods=60).max().iloc[-1]
    if pd.isna(high52w) or c_last < high52w * HIGH52W_FLOOR:
        return False

    return True


# ── ana puanlama ──────────────────────────────────────────────────────────────

def score_symbol(
    symbol: str,
    df: pd.DataFrame,
    index_df=None,
    market: str = "bist",
    regime_ok: bool = True,
) -> ScoreResult | None:
    if df is None or df.empty or len(df) < 60:
        return None

    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    close_clean = close.dropna()
    if close_clean.empty:
        return None

    index_close = _index_close_of(index_df)
    frame = compute_score_frame(df, index_close)

    last_close = float(close_clean.iloc[-1])
    change_pct = 0.0
    if len(close_clean) >= 2 and close_clean.iloc[-2] != 0:
        change_pct = (last_close - float(close_clean.iloc[-2])) / float(close_clean.iloc[-2]) * 100.0

    high_52 = float(high.tail(252).dropna().max()) if not high.tail(252).dropna().empty else None
    low_52  = float(low.tail(252).dropna().min())  if not low.tail(252).dropna().empty else None

    indicators   = _build_indicators(frame)
    total_last   = _safe_last(frame["total"])
    score        = int(round(max(0.0, min(10.0, total_last)))) if total_last is not None else 0
    sparkline    = close.tail(30).dropna().tolist()
    week_change  = _pct_change_back(close, 5)
    month_change = _pct_change_back(close, 21)

    last_volume = float(volume.iloc[-1]) if not volume.empty and not pd.isna(volume.iloc[-1]) else 0.0
    volume_spike = False
    if last_volume > 0 and len(volume) >= 12:
        avg_vol = float(volume.iloc[-11:-1].dropna().mean())
        if avg_vol > 0:
            volume_spike = last_volume > 1.5 * avg_vol

    near_peak = bool(high_52 and high_52 > 0 and last_close >= high_52 * 0.97)

    entry_signal = regime_ok and compute_entry_signal(df, frame, index_close, market)

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
        sparkline=sparkline,
        indicators=indicators,
        volume_spike=volume_spike,
        near_peak=near_peak,
        entry_signal=entry_signal,
    )


def score_symbol_detailed(
    symbol: str,
    df: pd.DataFrame,
    index_df=None,
    market: str = "bist",
    regime_ok: bool = True,
) -> dict | None:
    base = score_symbol(symbol, df, index_df=index_df, market=market, regime_ok=regime_ok)
    if base is None:
        return None

    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)
    last_close = float(close.dropna().iloc[-1]) if not close.dropna().empty else 0.0

    hist = [
        {
            "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
            "close": float(val),
        }
        for idx, val in close.tail(500).items()
        if not pd.isna(val)
    ]

    ohlcv = []
    for idx, row in df.tail(500).iterrows():
        try:
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            if any(math.isnan(v) or math.isinf(v) for v in (o, h, l, c)):
                continue
            date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
            vol_val  = row.get("Volume", 0)
            ohlcv.append({
                "t": date_str,
                "o": round(o, 4),
                "h": round(h, 4),
                "l": round(l, 4),
                "c": round(c, 4),
                "v": int(float(vol_val)) if not pd.isna(vol_val) else 0,
            })
        except (KeyError, ValueError, TypeError):
            continue

    avg_vol = float(volume.tail(20).mean()) if not volume.empty else 0.0
    sr      = _find_sr_levels(high, low, close)
    stop_loss, take_profit = _calc_sl_tp(last_close, sr["supports"], sr["resistances"])

    risk_reward = None
    price = last_close
    if stop_loss and take_profit and price > stop_loss:
        risk = price - stop_loss
        if risk > 0:
            risk_reward = round((take_profit - price) / risk, 2)

    patterns         = detect_patterns(df)
    auto_trendlines  = detect_auto_trendlines(df)
    pattern_analysis = summarize_patterns(patterns)

    out = base.to_dict()
    out.update({
        "history":          hist,
        "ohlcv":            ohlcv,
        "patterns":         patterns,
        "pattern_analysis": pattern_analysis,
        "auto_trendlines":  auto_trendlines,
        "avg_volume_20d": round(avg_vol, 2),
        "data_points":   int(len(close)),
        "supports":      sr["supports"],
        "resistances":   sr["resistances"],
        "stop_loss":     stop_loss,
        "take_profit":   take_profit,
        "risk_reward":   risk_reward,
    })
    return out
