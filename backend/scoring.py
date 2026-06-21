"""Kesisim (crossover) bazli erken kirılım puanlama motoru — 0-10.

Her bileşen iki katman kullanır:
  - TAZELIK: Kesisim aninda 1.0, her barda uste-ustel azalir (decay_half=7 barda 0.5).
  - KALICI:  Hala uygun durumda (MACD sinyal ustunde vs.) kucuk sabit bonus.

Boylece "az once MACD kesti → yuksek puan", "3 hafta once kesti → dusuk puan"
davranisi saglanir; uzun suredir yukselen, tepede olan hisseler one cikmaz.

Toplam 0-10, agirliklar (max):

  1. MACD KESISIMI  (macd_cross)   0-3.0
  2. EMA KIRILIMI   (ema_cross)    0-2.0
  3. DI/ADX KESISIMI (di_cross)   0-1.5
  4. RSI TOPARLANMA  (rsi_cross)   0-1.5
  5. GORECELI GUC   (rel_strength) 0-1.5
  6. GENISLEME CEZASI (ext_penalty) 0 / -3.0

Bilesik puan EWM(span=2) ile yumusatilir ve 0-10'a clamp edilir.

`compute_score_frame` tum df boyunca vektorize seriler uretir; hem canli tarayici
(`score_symbol`) hem backtest ayni motoru tuketir — tek kaynak, sapma yok.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.patterns import detect_patterns


# --- ayarlanabilir agirliklar / esikler (backtest ile ince ayara acik) ---

WEIGHTS = {
    "macd_cross":   3.0,
    "ema_cross":    2.0,
    "di_cross":     1.5,
    "rsi_cross":    1.5,
    "rel_strength": 1.5,
}
DECAY_HALF  = 7    # barlarda yarim omur: 7. barda tazelik 0.5'e iner
SMOOTH_SPAN = 2    # bilesik puan yumusatma (tepki oncelikli: kucuk = cevik)
REL_NEUTRAL = WEIGHTS["rel_strength"] * 0.5  # endeks yoksa notr goreceli guc


@dataclass
class IndicatorResult:
    name: str
    key: str
    score: float
    max_score: float
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


# --- saf pandas indikator hesaplamalari ---

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


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Wilder ADX + yonlu gostergeler (+DI / -DI)."""
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)).astype(float) * up.clip(lower=0)
    minus_dm = ((down > up) & (down > 0)).astype(float) * down.clip(lower=0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    alpha = 1.0 / length
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=length).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False, min_periods=length).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False, min_periods=length).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=length).mean()
    return adx, plus_di, minus_di


def _safe_last(series: pd.Series):
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _clip01(s: pd.Series) -> pd.Series:
    return s.clip(lower=0.0, upper=1.0)


def _bars_since_cross(condition: pd.Series) -> pd.Series:
    """Her barda son True'dan bu yana gecen bar sayisini dondurur (0=o gun).
    Ilk kesisimden once NaN. Pandas groupby.cumcount ile tam vektorize."""
    cum = condition.cumsum()
    bars = condition.groupby(cum).cumcount()
    return bars.where(cum > 0, other=np.nan)


def _freshness(bars_since: pd.Series, decay_half: float = DECAY_HALF) -> pd.Series:
    """Ustel azalma: kesisim gununde 1.0, decay_half barda 0.5. Kesisim oncesi 0."""
    rate = np.log(2) / decay_half
    f = np.exp(-rate * bars_since.fillna(9999))
    return pd.Series(np.where(bars_since.notna(), f, 0.0), index=bars_since.index)


# --- kesisim bazli alt-puan serileri ---

def _ema_cross_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """EMA KIRILIMI (0-2): Fiyatin EMA20/50/200 ustunu yeni kesmesi. (skor, ema50) doner."""
    ema20  = _ema(close, 20)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)

    cross20  = (close > ema20)  & (close.shift(1) <= ema20.shift(1))
    cross50  = (close > ema50)  & (close.shift(1) <= ema50.shift(1))
    cross200 = (close > ema200) & (close.shift(1) <= ema200.shift(1))

    taze = (
        _freshness(_bars_since_cross(cross20))  * 0.4
        + _freshness(_bars_since_cross(cross50))  * 0.5
        + _freshness(_bars_since_cross(cross200)) * 0.7
    )
    kalan = (
        (close > ema50).astype(float) * 0.3
        + _clip01(ema50.pct_change(10) / 0.05) * 0.2
    )
    score = (taze + kalan).clip(0, WEIGHTS["ema_cross"])
    return score, ema50


def _macd_cross_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """MACD KESISIMI (0-3): Taze MACD/sinyal kesisimi + ivme + sifir cizgisi. (skor, macd_line) doner."""
    macd_line, signal_line = _macd(close)
    hist = macd_line - signal_line

    cross_up = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    taze = _freshness(_bars_since_cross(cross_up)) * 2.5

    kalan  = (macd_line > signal_line).astype(float) * 0.25
    hist_slope3 = (hist - hist.shift(3)) / 3.0
    ivme   = _clip01(hist_slope3 / (close.replace(0, np.nan) * 0.003)) * 0.2
    sifir  = (macd_line > 0).astype(float) * 0.15

    score = (taze + kalan + ivme + sifir).clip(0, WEIGHTS["macd_cross"])
    return score, macd_line


def _di_cross_series(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """DI/ADX KESISIMI (0-1.5): +DI/-DI taze kesisimi + ADX guc teyidi. (skor, adx) doner."""
    adx, plus_di, minus_di = _adx(high, low, close)

    cross_up = (plus_di > minus_di) & (plus_di.shift(1) <= minus_di.shift(1))
    taze  = _freshness(_bars_since_cross(cross_up)) * 1.0
    kalan = (plus_di > minus_di).astype(float) * _clip01((adx - 15) / 15.0) * 0.5

    score = (taze + kalan).clip(0, WEIGHTS["di_cross"])
    return score, adx


def _rel_strength_series(close: pd.Series, index_close: Optional[pd.Series]) -> pd.Series:
    """GORECELI GUC (0-1.5): hissenin endekse gore 20/60 gun performansi."""
    if index_close is None or index_close.dropna().empty:
        return pd.Series(REL_NEUTRAL, index=close.index)
    idx = index_close.reindex(close.index).ffill()
    out20 = close.pct_change(20) - idx.pct_change(20)
    out60 = close.pct_change(60) - idx.pct_change(60)
    s20 = _clip01(out20 / 0.10)   # +%10 fark = tam
    s60 = _clip01(out60 / 0.15)   # +%15 fark = tam
    score = (0.6 * s20 + 0.9 * s60).clip(0, WEIGHTS["rel_strength"])
    # ilk barlarda NaN -> notr
    return score.fillna(REL_NEUTRAL)


def _rsi_cross_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """RSI TOPARLANMA (0-1.5): RSI'in 40 ve 50'yi asagi-yukari kesmesi. (skor, rsi) doner.
    RSI > 70 iken kalici bonus sifir — asiri alimda odul yok."""
    rsi = _rsi(close, 14)

    cross40 = (rsi > 40) & (rsi.shift(1) <= 40)
    cross50 = (rsi > 50) & (rsi.shift(1) <= 50)
    taze = (
        _freshness(_bars_since_cross(cross40)) * 0.4
        + _freshness(_bars_since_cross(cross50)) * 0.6
    )
    in_zone = ((rsi >= 40) & (rsi <= 65)).astype(float) * 0.5
    score = (taze + in_zone).clip(0, WEIGHTS["rsi_cross"])
    return score, rsi


def _extension_series(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """GENISLEME CEZASI (0 ile -3.0 arasi, sadece negatif): 52-hft konum + EMA20 sapma.

    Breakout muafiyeti: hacim > SMA20*1.5 VE fiyat >= 52-hft yuksek*0.98 ise
    ceza %70 indirimli uygulanir — gercek kirilim firsatini engelleme.
    (skor_serisi, rp_serisi [0=dip,1=tepe]) doner.
    """
    # 52-haftalik aralik icindeki konum (0=dip, 1=tepe)
    high52 = close.rolling(252, min_periods=60).max()
    low52  = close.rolling(252, min_periods=60).min()
    rng52  = (high52 - low52).replace(0, np.nan)
    rp     = ((close - low52) / rng52).clip(0, 1).fillna(0.5)

    rv = rp.values.astype(float)
    range_penalty = np.select(
        [rv <= 0.75, rv <= 0.85, rv <= 0.95],
        [
            0.0,
            -(rv - 0.75) / 0.10 * 0.8,                           # 0.75-0.85: 0 -> -0.8
            -0.8 - (rv - 0.85) / 0.10 * 0.7,                     # 0.85-0.95: -0.8 -> -1.5
        ],
        default=-1.5 - (rv - 0.95) / 0.05 * 1.0,                 # 0.95-1.00: -1.5 -> -2.5
    )

    # EMA20 sapma cezasi (fiyat EMA20'nin cok uzagina cikmissa)
    ema20 = _ema(close, 20)
    dev = ((close - ema20) / ema20.replace(0, np.nan)).fillna(0)
    dv = dev.values.astype(float)
    ema_penalty = -np.clip((dv - 0.07) / 0.08, 0.0, 0.5)

    total_penalty = (range_penalty + ema_penalty).clip(-3.0, 0.0)

    # Breakout muafiyeti: gercek kirilimda cezayi %70 azalt
    if volume is not None and not volume.empty and len(volume) >= 20:
        vol_sma = volume.rolling(20).mean()
        is_breakout = (
            (volume > vol_sma * 1.5) & (close >= high52 * 0.98)
        ).fillna(False)
        total_penalty = np.where(is_breakout.values, total_penalty * 0.30, total_penalty)

    score = pd.Series(np.clip(total_penalty, -3.0, 0.0), index=close.index)
    return score, rp


def compute_score_frame(df: pd.DataFrame, index_close: Optional[pd.Series] = None) -> Dict[str, pd.Series]:
    """Tum df boyunca vektorize alt-puanlari, ham ve yumusatilmis toplami uretir.

    Doner: macd_cross/ema_cross/di_cross/rsi_cross/rel_strength/ext_penalty alt-puan serileri,
    total_raw, total (yumusatilmis+clamp), ve detay icin yardimci deger serileri.
    Geri uyumluluk icin eski anahtarlar (trend/momentum/adx/rsi/bbands) alias olarak eklenir.
    Canli tarayici ve backtest ayni fonksiyonu kullanir.
    """
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    macd_score, macd_line = _macd_cross_series(close)
    ema_score,  ema50     = _ema_cross_series(close)
    di_score,   adx_val   = _di_cross_series(high, low, close)
    rsi_score,  rsi_val   = _rsi_cross_series(close)
    rel                   = _rel_strength_series(close, index_close)
    ext_penalty, rp       = _extension_series(close, high, low, volume)

    total_raw = (
        macd_score.fillna(0) + ema_score.fillna(0) + di_score.fillna(0)
        + rsi_score.fillna(0) + rel.fillna(REL_NEUTRAL) + ext_penalty.fillna(0)
    )
    total = total_raw.ewm(span=SMOOTH_SPAN, adjust=False).mean().clip(0, 10)

    zero_series = pd.Series(0.0, index=close.index)

    return {
        # birincil bilesenler
        "macd_cross":   macd_score,
        "ema_cross":    ema_score,
        "di_cross":     di_score,
        "rsi_cross":    rsi_score,
        "rel_strength": rel,
        "ext_penalty":  ext_penalty,
        # geri uyumluluk alias'lari (backtest + alerts icin)
        "trend":    ema_score,
        "momentum": macd_score,
        "adx":      di_score,
        "rsi":      rsi_score,
        "bbands":   zero_series,
        # toplam
        "total_raw": total_raw,
        "total":     total,
        # detay/yardimci degerler
        "ema50_val": ema50,
        "macd_val":  macd_line,
        "adx_val":   adx_val,
        "rsi_val":   rsi_val,
        "pctb_val":  zero_series,
        "rp_val":    rp,
    }


# --- son bardan IndicatorResult uretimi (gosterim) ---

def _round1(v: float | None) -> float | None:
    return round(float(v), 1) if v is not None and not pd.isna(v) else None


def _build_indicators(frame: Dict[str, pd.Series], has_index: bool) -> List[IndicatorResult]:
    def last(key: str) -> float:
        v = _safe_last(frame[key])
        return 0.0 if v is None else v

    macd_s = last("macd_cross")
    ema_s  = last("ema_cross")
    di_s   = last("di_cross")
    rsi_s  = last("rsi_cross")
    rel_s  = last("rel_strength")
    ext_s  = last("ext_penalty")

    adx_v   = _safe_last(frame["adx_val"])
    rsi_v   = _safe_last(frame["rsi_val"])
    macd_v  = _safe_last(frame["macd_val"])
    ema50_v = _safe_last(frame["ema50_val"])
    rp_v    = _safe_last(frame["rp_val"])

    def macd_detail() -> str:
        if macd_s >= 2.0:
            return "taze MACD kesisimi — erken yukselis sinyali"
        if macd_s >= 1.0:
            return "MACD sinyal ustunde, kesisim yaklasik 1-2 hafta once"
        if macd_s >= 0.3:
            return "MACD sinyal ustunde, kesisim eski"
        return "MACD sinyalin altinda — momentum negatif"

    def ema_detail() -> str:
        if ema_s >= 1.4:
            return "fiyat taze EMA kirilimiyla yukari gecti"
        if ema_s >= 0.7:
            return "fiyat EMA50 uzerinde, kiriltim gorece yeni"
        if ema_s >= 0.3:
            return "fiyat EMA50 uzerinde, eski gecis"
        return "fiyat ana ortalamalarin altinda"

    def di_detail() -> str:
        av = f"ADX {adx_v:.0f}" if adx_v is not None else "ADX"
        if di_s >= 1.0:
            return f"taze +DI/-DI kesisimi — {av} ile yeni yonlu trend basliyor"
        if di_s >= 0.4:
            return f"+DI, -DI uzerinde — {av} trend gucleniyor"
        return f"+DI zayif veya -DI uzerinde — {av} yatay/dusus trendi"

    def rsi_detail() -> str:
        rv = f"RSI {rsi_v:.0f}" if rsi_v is not None else "RSI"
        if rsi_v is None:
            return rv
        if rsi_s >= 1.0:
            return f"{rv} — taze toparlanma: 40/50 ustu yeni gecis"
        if rsi_v > 70:
            return f"{rv} — asiri alim, yeni kesisim odul almaz"
        if rsi_v >= 40:
            return f"{rv} — toparlanma bolgesinde"
        return f"{rv} — zayif/asiri satim bolgesi"

    def rel_detail() -> str:
        if not has_index:
            return "endeks verisi yok — notr"
        if rel_s >= 1.0:
            return "endeksten belirgin guclu (lider)"
        if rel_s >= 0.5:
            return "endekse paralel/hafif guclu"
        return "endeksten zayif"

    def ext_detail() -> str:
        if ext_s >= -0.2:
            return "52-hft araliginda rahat konum, giris riski dusuk"
        if ext_s >= -0.8:
            rp_pct = round(rp_v * 100) if rp_v is not None else "?"
            return f"52-hft araliginin %{rp_pct}'inde — hafif uzamis"
        if ext_s >= -1.8:
            rp_pct = round(rp_v * 100) if rp_v is not None else "?"
            return f"52-hft araliginin %{rp_pct}'inde — uzamis, dikkat"
        rp_pct = round(rp_v * 100) if rp_v is not None else "?"
        return f"52-hft araliginin %{rp_pct}'inde — zirveye yapisik / geri cekilme riski yuksek"

    inds = [
        IndicatorResult("MACD Kesisimi", "momentum", _round1(macd_s), WEIGHTS["macd_cross"],
                        value=_round1(macd_v), detail=macd_detail()),
        IndicatorResult("EMA Kirilimi", "trend", _round1(ema_s), WEIGHTS["ema_cross"],
                        value=_round1(ema50_v), detail=ema_detail()),
        IndicatorResult("DI/ADX Yonu", "adx", _round1(di_s), WEIGHTS["di_cross"],
                        value=_round1(adx_v), detail=di_detail()),
        IndicatorResult("RSI Toparlanma", "rsi", _round1(rsi_s), WEIGHTS["rsi_cross"],
                        value=_round1(rsi_v), detail=rsi_detail()),
        IndicatorResult("Goreceli Guc", "rel_strength", _round1(rel_s), WEIGHTS["rel_strength"],
                        value=None, detail=rel_detail()),
        IndicatorResult("Genisleme Riski", "extension", _round1(ext_s), 0.0,
                        value=_round1(rp_v), detail=ext_detail()),
    ]
    return inds


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
        stop_loss = round(nearest_sup * 0.985, 4)
    else:
        stop_loss = None

    take_profit = round(min(ress_above), 4) if ress_above else None
    return stop_loss, take_profit


# --- yardimci ---

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


# --- ana puanlama ---

def score_symbol(symbol: str, df: pd.DataFrame, index_df=None) -> ScoreResult | None:
    if df is None or df.empty or len(df) < 60:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    index_close = _index_close_of(index_df)
    frame = compute_score_frame(df, index_close)

    last_close = float(close.iloc[-1])
    if len(close) >= 2 and not pd.isna(close.iloc[-2]) and close.iloc[-2] != 0:
        change_pct = (last_close - float(close.iloc[-2])) / float(close.iloc[-2]) * 100.0
    else:
        change_pct = 0.0

    high_series = high.tail(252).dropna()
    low_series = low.tail(252).dropna()
    high_52 = float(high_series.max()) if not high_series.empty else None
    low_52 = float(low_series.min()) if not low_series.empty else None

    indicators = _build_indicators(frame, has_index=index_close is not None)

    total_last = _safe_last(frame["total"])
    score = int(round(max(0.0, min(10.0, total_last)))) if total_last is not None else 0

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


def score_symbol_detailed(symbol: str, df: pd.DataFrame, index_df=None) -> dict | None:
    base = score_symbol(symbol, df, index_df=index_df)
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
        for idx, val in close.tail(500).items()
        if not pd.isna(val)
    ]

    # Tam OHLCV — grafik icin son 500 bar (~2 yil)
    ohlcv = []
    for idx, row in df.tail(500).iterrows():
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
