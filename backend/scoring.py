"""Kesisim (crossover) bazli saf sinyal puanlama motoru — 0-10.

Her bileşen: son CROSS_LOOKBACK bar içinde kesişim olduysa aktif,
lineer sönme ile ağırlığının tamamına iner → sıfıra döner.
"Henüz kesti" = tam puan; "3 hafta önce kesti" = çok az puan.

Sinyaller ve maksimum katkıları:
  1. MACD / sinyal hattı kesişimi   (macd_signal)   — 2.0 puan
  2. MACD / 0 hattı kesişimi        (macd_zero)     — 1.0 puan
  3. RSI / RSI-EMA9 sinyal hattı    (rsi_signal)    — 1.5 puan
  4. Fiyat / EMA30 kesişimi         (ema30)         — 0.5 puan
  5. Fiyat / EMA50 kesişimi         (ema50)         — 0.75 puan
  6. Fiyat / EMA200 kesişimi        (ema200)        — 0.75 puan
  7. DI+ / DI- kesişimi             (di_cross)      — 1.5 puan
  8. Hacim onayı (kesişimle eş)     (volume)        — 1.0 puan  [bonus]
  Genişleme cezası                  (ext_penalty)   — 0 / −2.0

Ham maks ≈ 9.0; ceza ile gerçekçi üst sınır ≈ 9.0 → clip(0, 10).

`compute_score_frame` tüm df boyunca vektörize seriler üretir; hem canlı
tarayıcı (`score_symbol`) hem backtest aynı motoru tüketir — tek kaynak.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.patterns import detect_patterns


# ── ayarlanabilir parametreler ───────────────────────────────────────────────

CROSS_LOOKBACK = 20   # bar — kesişimden bu bar sonra sinyal tamamen söner (lineer)
SMOOTH_SPAN    = 2    # son puan yumuşatma (EWM span)

WEIGHTS = {
    "macd_signal": 2.0,   # MACD çizgisi sinyal hattını yukarı kesti
    "macd_zero":   1.0,   # MACD çizgisi 0 hattını yukarı kesti
    "rsi_signal":  1.5,   # RSI çizgisi kendi EMA-9 sinyal hattını yukarı kesti
    "ema30":       0.5,   # Fiyat EMA30'u yukarı kesti
    "ema50":       0.75,  # Fiyat EMA50'yi yukarı kesti
    "ema200":      0.75,  # Fiyat EMA200'ü yukarı kesti
    "di_cross":    1.5,   # +DI çizgisi −DI'yı yukarı kesti
    "volume":      1.0,   # Kesişim sırasında hacim spike'ı (bonus)
}
EXT_PENALTY_MAX = -2.0   # Zirve konumu cezası üst sınırı


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


def _freshness(bars_since: pd.Series, lookback: float = CROSS_LOOKBACK) -> pd.Series:
    """Lineer sönme: kesişim gününde 1.0, CROSS_LOOKBACK'te 0.0. Önce/sonra 0."""
    f = (1.0 - bars_since.fillna(lookback + 1) / lookback).clip(0.0, 1.0)
    return pd.Series(np.where(bars_since.notna(), f, 0.0), index=bars_since.index)


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    """a, b'yi yukarı kestiği barlar True."""
    return (a > b) & (a.shift(1) <= b.shift(1))


# ── sinyal serileri ───────────────────────────────────────────────────────────

def _macd_series(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD sinyal + sıfır kesişimleri.
    Döner: (macd_signal_score, macd_zero_score, macd_line)"""
    macd_line, signal_line = _macd(close)

    fresh_signal = _freshness(_bars_since_cross(_cross_up(macd_line, signal_line)))
    fresh_zero   = _freshness(_bars_since_cross(_cross_up(macd_line, pd.Series(0.0, index=close.index))))

    return (
        fresh_signal * WEIGHTS["macd_signal"],
        fresh_zero   * WEIGHTS["macd_zero"],
        macd_line,
    )


def _rsi_signal_series(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """RSI çizgisinin kendi EMA-9 sinyal hattını yukarı kesmesi.
    Döner: (rsi_signal_score, rsi, rsi_signal_line)"""
    rsi        = _rsi(close, 14)
    rsi_signal = _ema(rsi, 9)          # RSI sinyal hattı

    fresh = _freshness(_bars_since_cross(_cross_up(rsi, rsi_signal)))
    return fresh * WEIGHTS["rsi_signal"], rsi, rsi_signal


def _ema_cross_series(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Fiyatın EMA30 / EMA50 / EMA200'ü yukarı kesmesi.
    Döner: (ema30_score, ema50_score, ema200_score, ema50, ema200)"""
    ema30  = _ema(close, 30)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)

    s30  = _freshness(_bars_since_cross(_cross_up(close, ema30)))  * WEIGHTS["ema30"]
    s50  = _freshness(_bars_since_cross(_cross_up(close, ema50)))  * WEIGHTS["ema50"]
    s200 = _freshness(_bars_since_cross(_cross_up(close, ema200))) * WEIGHTS["ema200"]

    return s30, s50, s200, ema50, ema200


def _di_cross_series(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """+DI çizgisinin −DI'yı yukarı kesmesi.
    Döner: (di_score, adx)"""
    adx, plus_di, minus_di = _adx(high, low, close)
    fresh = _freshness(_bars_since_cross(_cross_up(plus_di, minus_di)))
    return fresh * WEIGHTS["di_cross"], adx


def _volume_confirm_series(
    close: pd.Series,
    volume: pd.Series,
    any_cross_today: pd.Series,
) -> pd.Series:
    """Herhangi bir kesişimle aynı barda hacim spike'ı varsa bonus puan.
    Spike tanımı: hacim > SMA20 × 1.5"""
    if volume is None or volume.empty or len(volume) < 20:
        return pd.Series(0.0, index=close.index)

    vol_sma = _sma(volume, 20)
    spike   = (volume > vol_sma * 1.5).fillna(False)
    # Kesişimden bu yana CROSS_LOOKBACK bar içinde spike olan barlar puan alır
    cross_with_spike = any_cross_today & spike
    fresh = _freshness(_bars_since_cross(cross_with_spike))
    return fresh * WEIGHTS["volume"]


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
    macd_sig_score, macd_zero_score, macd_line = _macd_series(close)
    rsi_sig_score, rsi_val, rsi_signal_val     = _rsi_signal_series(close)
    ema30_score, ema50_score, ema200_score, ema50, ema200 = _ema_cross_series(close)
    di_score, adx_val                          = _di_cross_series(high, low, close)

    # Herhangi bir kesişimin bugün gerçekleştiği barlar (hacim onayı için)
    _, signal_line = _macd(close)
    rsi_tmp        = _rsi(close, 14)
    ema30_tmp      = _ema(close, 30)
    _, plus_di, minus_di = _adx(high, low, close)

    any_cross_today = (
        _cross_up(macd_line, signal_line)
        | _cross_up(macd_line, pd.Series(0.0, index=close.index))
        | _cross_up(rsi_tmp, _ema(rsi_tmp, 9))
        | _cross_up(close, ema30_tmp)
        | _cross_up(close, ema50)
        | _cross_up(close, ema200)
        | _cross_up(plus_di, minus_di)
    ).fillna(False)

    vol_score   = _volume_confirm_series(close, volume, any_cross_today)
    ext_penalty, rp = _extension_series(close, high, low, volume)

    # ── toplam ──
    total_raw = (
        macd_sig_score.fillna(0)
        + macd_zero_score.fillna(0)
        + rsi_sig_score.fillna(0)
        + ema30_score.fillna(0)
        + ema50_score.fillna(0)
        + ema200_score.fillna(0)
        + di_score.fillna(0)
        + vol_score.fillna(0)
        + ext_penalty.fillna(0)
    )
    total = total_raw.ewm(span=SMOOTH_SPAN, adjust=False).mean().clip(0, 10)

    zero = pd.Series(0.0, index=close.index)

    return {
        # yeni sinyal bileşenleri
        "macd_signal":  macd_sig_score,
        "macd_zero":    macd_zero_score,
        "rsi_signal":   rsi_sig_score,
        "ema30":        ema30_score,
        "ema50":        ema50_score,
        "ema200":       ema200_score,
        "di_cross":     di_score,
        "volume":       vol_score,
        "ext_penalty":  ext_penalty,
        # geriye uyumluluk alias'ları (backtest + alerts)
        "macd_cross":   macd_sig_score + macd_zero_score,
        "ema_cross":    ema30_score + ema50_score + ema200_score,
        "rsi_cross":    rsi_sig_score,
        "rel_strength": zero,
        "trend":        ema30_score + ema50_score + ema200_score,
        "momentum":     macd_sig_score + macd_zero_score,
        "adx":          di_score,
        "rsi":          rsi_sig_score,
        "bbands":       zero,
        # toplam
        "total_raw": total_raw,
        "total":     total,
        # yardımcı değerler (detay görüntü için)
        "ema50_val":      ema50,
        "ema200_val":     ema200,
        "macd_val":       macd_line,
        "rsi_val":        rsi_val,
        "rsi_signal_val": rsi_signal_val,
        "adx_val":        adx_val,
        "pctb_val":       zero,
        "rp_val":         rp,
    }


# ── IndicatorResult üretimi ───────────────────────────────────────────────────

def _round1(v: float | None) -> float | None:
    return round(float(v), 1) if v is not None and not pd.isna(v) else None


def _build_indicators(frame: Dict[str, pd.Series]) -> List[IndicatorResult]:
    def last(key: str) -> float:
        v = _safe_last(frame[key])
        return 0.0 if v is None else v

    ms  = last("macd_signal")
    mz  = last("macd_zero")
    rs  = last("rsi_signal")
    e30 = last("ema30")
    e50 = last("ema50")
    e200= last("ema200")
    di  = last("di_cross")
    vol = last("volume")
    ext = last("ext_penalty")

    macd_v   = _safe_last(frame["macd_val"])
    rsi_v    = _safe_last(frame["rsi_val"])
    rsig_v   = _safe_last(frame["rsi_signal_val"])
    ema50_v  = _safe_last(frame["ema50_val"])
    ema200_v = _safe_last(frame["ema200_val"])
    adx_v    = _safe_last(frame["adx_val"])
    rp_v     = _safe_last(frame["rp_val"])

    def macd_sig_detail() -> str:
        if ms >= 1.5:  return "MACD sinyal hattını taze kesti — güçlü alım sinyali"
        if ms >= 0.8:  return "MACD sinyal üstünde, kesişim görece yeni"
        if ms >= 0.2:  return "MACD sinyal üstünde, kesişim eskimeye başladı"
        return "MACD sinyal hattının altında — momentum negatif"

    def macd_zero_detail() -> str:
        if mz >= 0.8:  return "MACD 0 hattını taze kesti — trend pozitif teyit"
        if mz >= 0.4:  return "MACD 0 üstünde, sıfır kesişimi görece yeni"
        if mz >= 0.1:  return "MACD 0 üstünde, kesişim eskiyor"
        mv = f"MACD {macd_v:.3f}" if macd_v is not None else "MACD"
        return f"{mv} — 0 hattının altında, trend henüz doğrulanmadı"

    def rsi_sig_detail() -> str:
        rv = f"RSI {rsi_v:.0f}" if rsi_v is not None else "RSI"
        sv = f"/ sinyal {rsig_v:.0f}" if rsig_v is not None else ""
        if rs >= 1.2:  return f"{rv}{sv} — RSI sinyal hattını taze kesti"
        if rs >= 0.6:  return f"{rv}{sv} — RSI sinyal üstünde, kesişim yeni"
        if rs >= 0.1:  return f"{rv}{sv} — RSI sinyal üstünde, eskiyor"
        return f"{rv}{sv} — RSI sinyal hattının altında"

    def ema_detail(score: float, period: int, val: float | None) -> str:
        vstr = f"≈{val:.2f}" if val is not None else ""
        if score >= 0.7 * (WEIGHTS[f"ema{period}"]):
            return f"Fiyat EMA{period}'ü ({vstr}) taze kesti — yukarı geçiş"
        if score >= 0.2 * (WEIGHTS[f"ema{period}"]):
            return f"Fiyat EMA{period} ({vstr}) üstünde, kesişim eskiyor"
        return f"Fiyat EMA{period} ({vstr}) altında"

    def di_detail() -> str:
        av = f"ADX {adx_v:.0f}" if adx_v is not None else "ADX"
        if di >= 1.2:  return f"+DI/−DI kesişimi taze — {av} ile yeni trend başlıyor"
        if di >= 0.6:  return f"+DI, −DI üstünde — {av} trend güçleniyor"
        if di >= 0.1:  return f"+DI, −DI üstünde — {av} kesişim eskiyor"
        return f"+DI zayıf veya −DI üstünde — {av} yatay/düşüş trendi"

    def vol_detail() -> str:
        if vol >= 0.8:  return "Kesişimle birlikte güçlü hacim spike'ı — sinyal güvenilir"
        if vol >= 0.3:  return "Kesişim döneminde hacim artışı"
        return "Kesişim sırasında belirgin hacim onayı yok"

    def ext_detail() -> str:
        if ext >= -0.2:
            return "52-hft aralığında rahat konum, giriş riski düşük"
        rp_pct = round(rp_v * 100) if rp_v is not None else "?"
        if ext >= -0.8:
            return f"52-hft aralığının %{rp_pct}'inde — hafif uzamış"
        if ext >= -1.8:
            return f"52-hft aralığının %{rp_pct}'inde — uzamış, dikkat"
        return f"52-hft aralığının %{rp_pct}'inde — zirveye yapışık / geri çekilme riski yüksek"

    return [
        IndicatorResult("MACD × Sinyal",  "momentum", _round1(ms),  WEIGHTS["macd_signal"],
                        value=_round1(macd_v),   detail=macd_sig_detail()),
        IndicatorResult("MACD × Sıfır",   "macd_zero", _round1(mz), WEIGHTS["macd_zero"],
                        value=_round1(macd_v),   detail=macd_zero_detail()),
        IndicatorResult("RSI × Sinyal",   "rsi",      _round1(rs),  WEIGHTS["rsi_signal"],
                        value=_round1(rsi_v),    detail=rsi_sig_detail()),
        IndicatorResult("Fiyat × EMA30",  "ema30",    _round1(e30), WEIGHTS["ema30"],
                        value=_round1(ema50_v),  detail=ema_detail(e30, 30, _safe_last(frame["ema50_val"]))),
        IndicatorResult("Fiyat × EMA50",  "trend",    _round1(e50), WEIGHTS["ema50"],
                        value=_round1(ema50_v),  detail=ema_detail(e50, 50, ema50_v)),
        IndicatorResult("Fiyat × EMA200", "ema200",   _round1(e200),WEIGHTS["ema200"],
                        value=_round1(ema200_v), detail=ema_detail(e200, 200, ema200_v)),
        IndicatorResult("DI+ × DI−",      "adx",      _round1(di),  WEIGHTS["di_cross"],
                        value=_round1(adx_v),    detail=di_detail()),
        IndicatorResult("Hacim Onayı",    "volume",   _round1(vol), WEIGHTS["volume"],
                        value=None,              detail=vol_detail()),
        IndicatorResult("Genişleme Riski","extension",_round1(ext), 0.0,
                        value=_round1(rp_v),     detail=ext_detail()),
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
    if len(close) <= n:
        return 0.0
    prev = float(close.iloc[-(n + 1)])
    if prev == 0 or pd.isna(prev):
        return 0.0
    return (float(close.iloc[-1]) - prev) / prev * 100.0


def _index_close_of(index_df) -> Optional[pd.Series]:
    if index_df is None:
        return None
    if isinstance(index_df, pd.Series):
        return index_df.astype(float)
    if isinstance(index_df, pd.DataFrame) and "Close" in index_df.columns:
        return index_df["Close"].astype(float)
    return None


# ── ana puanlama ──────────────────────────────────────────────────────────────

def score_symbol(symbol: str, df: pd.DataFrame, index_df=None) -> ScoreResult | None:
    if df is None or df.empty or len(df) < 60:
        return None

    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    index_close = _index_close_of(index_df)
    frame = compute_score_frame(df, index_close)

    last_close = float(close.iloc[-1])
    change_pct = 0.0
    if len(close) >= 2 and not pd.isna(close.iloc[-2]) and close.iloc[-2] != 0:
        change_pct = (last_close - float(close.iloc[-2])) / float(close.iloc[-2]) * 100.0

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
    )


def score_symbol_detailed(symbol: str, df: pd.DataFrame, index_df=None) -> dict | None:
    base = score_symbol(symbol, df, index_df=index_df)
    if base is None:
        return None

    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

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
            date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
            vol_val  = row.get("Volume", 0)
            ohlcv.append({
                "t": date_str,
                "o": round(float(row["Open"]),  4),
                "h": round(float(row["High"]),  4),
                "l": round(float(row["Low"]),   4),
                "c": round(float(row["Close"]), 4),
                "v": int(float(vol_val)) if not pd.isna(vol_val) else 0,
            })
        except (KeyError, ValueError, TypeError):
            continue

    avg_vol = float(volume.tail(20).mean()) if not volume.empty else 0.0
    sr      = _find_sr_levels(high, low, close)
    stop_loss, take_profit = _calc_sl_tp(float(close.iloc[-1]), sr["supports"], sr["resistances"])

    risk_reward = None
    price = float(close.iloc[-1])
    if stop_loss and take_profit and price > stop_loss:
        risk = price - stop_loss
        if risk > 0:
            risk_reward = round((take_profit - price) / risk, 2)

    patterns = detect_patterns(df)

    out = base.to_dict()
    out.update({
        "history":       hist,
        "ohlcv":         ohlcv,
        "patterns":      patterns,
        "avg_volume_20d": round(avg_vol, 2),
        "data_points":   int(len(close)),
        "supports":      sr["supports"],
        "resistances":   sr["resistances"],
        "stop_loss":     stop_loss,
        "take_profit":   take_profit,
        "risk_reward":   risk_reward,
    })
    return out
