"""Surekli, durum bazli 10 puanlik puanlama motoru.

Eski sistem "olay" puanliyordu (taze kesisim, histogram bugun>dun gibi)
ve esiklerde uucurumlar vardi; bu yuzden puan gun-gun 7'den 0'a ziplayabiliyordu.
Yeni motor 6 gostergeyi *surekli* ve *durum bazli* puanlar, sonra puan serisini
hafifce yumusatir. Bir kosul kaybolunca puan kademeli duser, ucurum olmaz.

Toplam 0-10, agirliklar (max):

  1. TREND (EMA dizilim + egim)        0-3.0
  2. MOMENTUM (MACD, durum bazli)      0-2.0
  3. TREND GUCU (ADX 14)               0-1.5
  4. GORECELI GUC (endekse karsi)      0-1.5
  5. RSI (14, plateau egrisi)          0-1.0  (asiri alimda hafif negatif)
  6. BOLLINGER + HACIM                  0-1.0

Bilesik puan EMA(span=2) ile hafifce yumusatilir (tepki oncelikli) ve 0-10'a clamp edilir.

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
    "trend": 3.0,
    "momentum": 2.0,
    "adx": 1.5,
    "rel_strength": 1.5,
    "rsi": 1.0,
    "bbands": 1.0,
}
SMOOTH_SPAN = 2  # bilesik puan yumusatma (tepki oncelikli: kucuk = cevik)
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


# --- surekli alt-puan serileri ---

def _trend_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """TREND (0-3): EMA dizilimi + egim, kismi kredi. (skor, ema50) doner."""
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)

    score = (
        0.50 * (close > ema20).astype(float)
        + 0.75 * (close > ema50).astype(float)
        + 0.75 * (ema50 > ema200).astype(float)
        + 0.50 * _clip01(ema50.pct_change(10) / 0.05)
        + 0.50 * _clip01(ema200.pct_change(20) / 0.05)
    )
    return score.clip(0, WEIGHTS["trend"]), ema50


def _momentum_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """MOMENTUM (0-2): MACD durum bazli. (skor, macd_line) doner."""
    macd_line, signal_line = _macd(close)
    hist = macd_line - signal_line

    above = (macd_line > signal_line).astype(float)
    # fiyata gore normalize histogram buyuklugu (gurultu yerine olcek)
    hist_norm = _clip01((hist / close.replace(0, np.nan)) / 0.015)
    comp_a = above * (0.5 + 0.5 * hist_norm)                       # 0-1.0
    # 3-barlik ortalama histogram egimi (tek gunluk flip yerine)
    hist_slope3 = (hist - hist.shift(3)) / 3.0
    comp_b = 0.5 * _clip01(hist_slope3 / (close.replace(0, np.nan) * 0.003))  # 0-0.5
    comp_c = 0.5 * (macd_line > 0).astype(float)                   # 0-0.5

    score = (comp_a + comp_b + comp_c).clip(0, WEIGHTS["momentum"])
    return score, macd_line


def _adx_series(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """TREND GUCU (0-1.5): ADX, bullish yonde tam kredi. (skor, adx) doner."""
    adx, plus_di, minus_di = _adx(high, low, close)
    strength = _clip01((adx - 15) / 15.0)            # 0 @15, 1 @30+
    bullish = (plus_di > minus_di)
    dir_factor = bullish.astype(float) * 1.0 + (~bullish).astype(float) * 0.3
    score = (strength * WEIGHTS["adx"] * dir_factor).clip(0, WEIGHTS["adx"])
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


def _rsi_score_series(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """RSI (0-1, plateau): 50-65 zirve, asiri alimda hafif negatif. (skor, rsi) doner."""
    rsi = _rsi(close, 14)
    r = rsi.to_numpy(dtype=float)
    val = np.select(
        [r <= 50, r <= 65, r <= 80],
        [
            np.clip((r - 35) / 15.0, 0.0, 1.0),       # 35->50 : 0->1
            1.0,                                       # 50-65 plateau
            1.0 - 0.8 * ((r - 65) / 15.0),             # 65->80 : 1.0->0.2
        ],
        default=np.maximum(-0.3, 0.2 - 0.5 * ((r - 80) / 10.0)),  # >80 : 0.2->-0.3
    )
    val = np.where(np.isnan(r), np.nan, val)
    return pd.Series(val, index=close.index), rsi


def _bbands_score_series(close: pd.Series, volume: pd.Series) -> tuple[pd.Series, pd.Series]:
    """BOLLINGER + HACIM (0-1): %B konumu x hacim teyidi. (skor, %B) doner."""
    upper, mid, lower = _bbands(close)
    width = (upper - lower).replace(0, np.nan)
    pctb = (close - lower) / width
    # 0.8 civarinda zirve yapan ucgen: orta-ust yari saglikli, asiri uzanma cezali
    loc = (1.0 - (pctb - 0.8).abs() / 0.8).clip(0, 1)

    if volume is not None and not volume.empty:
        vol_sma = volume.rolling(20).mean()
        vol_ratio = (volume / vol_sma.replace(0, np.nan)).clip(0.6, 1.2)
        vol_factor = vol_ratio.fillna(1.0)
    else:
        vol_factor = pd.Series(1.0, index=close.index)

    score = (loc * vol_factor).clip(0, WEIGHTS["bbands"])
    return score, pctb


def compute_score_frame(df: pd.DataFrame, index_close: Optional[pd.Series] = None) -> Dict[str, pd.Series]:
    """Tum df boyunca vektorize alt-puanlari, ham ve yumusatilmis toplami uretir.

    Doner: trend/momentum/adx/rel_strength/rsi/bbands alt-puan serileri,
    total_raw, total (yumusatilmis+clamp), ve detay icin yardimci deger serileri.
    Canli tarayici ve backtest ayni fonksiyonu kullanir.
    """
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(dtype=float)

    trend, ema50 = _trend_series(close)
    momentum, macd_line = _momentum_series(close)
    adx_score, adx_val = _adx_series(high, low, close)
    rel = _rel_strength_series(close, index_close)
    rsi_score, rsi_val = _rsi_score_series(close)
    bb_score, pctb = _bbands_score_series(close, volume)

    total_raw = (
        trend.fillna(0) + momentum.fillna(0) + adx_score.fillna(0)
        + rel.fillna(REL_NEUTRAL) + rsi_score.fillna(0) + bb_score.fillna(0)
    )
    total = total_raw.ewm(span=SMOOTH_SPAN, adjust=False).mean().clip(0, 10)

    return {
        "trend": trend,
        "momentum": momentum,
        "adx": adx_score,
        "rel_strength": rel,
        "rsi": rsi_score,
        "bbands": bb_score,
        "total_raw": total_raw,
        "total": total,
        # detay/yardimci degerler
        "ema50_val": ema50,
        "macd_val": macd_line,
        "adx_val": adx_val,
        "rsi_val": rsi_val,
        "pctb_val": pctb,
    }


# --- son bardan IndicatorResult uretimi (gosterim) ---

def _round1(v: float | None) -> float | None:
    return round(float(v), 1) if v is not None and not pd.isna(v) else None


def _build_indicators(frame: Dict[str, pd.Series], has_index: bool) -> List[IndicatorResult]:
    def last(key: str) -> float:
        v = _safe_last(frame[key])
        return 0.0 if v is None else v

    trend_s = last("trend")
    mom_s = last("momentum")
    adx_s = last("adx")
    rel_s = last("rel_strength")
    rsi_s = last("rsi")
    bb_s = last("bbands")

    adx_v = _safe_last(frame["adx_val"])
    rsi_v = _safe_last(frame["rsi_val"])
    macd_v = _safe_last(frame["macd_val"])
    pctb_v = _safe_last(frame["pctb_val"])
    ema50_v = _safe_last(frame["ema50_val"])

    def trend_detail() -> str:
        if trend_s >= 2.5:
            return "guclu yukselis trendi: EMA dizilimi ve egim pozitif"
        if trend_s >= 1.5:
            return "yukari egilimli: fiyat ana ortalamalarin uzerinde"
        if trend_s >= 0.75:
            return "karma trend: dizilim kismi"
        return "trend zayif / bozuk"

    def mom_detail() -> str:
        if mom_s >= 1.5:
            return "guclu momentum: MACD sinyal ve sifir uzerinde, histogram artiyor"
        if mom_s >= 0.8:
            return "momentum pozitif"
        if mom_s >= 0.3:
            return "momentum zayif/toparlaniyor"
        return "momentum negatif"

    def adx_detail() -> str:
        av = f"ADX {adx_v:.0f}" if adx_v is not None else "ADX"
        strong = adx_v is not None and adx_v >= 25
        if strong and adx_s >= 1.0:
            return f"{av} — guclu yukari yonlu trend"
        if strong:
            return f"{av} — guclu trend ama yon asagi/karma"
        if adx_v is not None and adx_v >= 20:
            return f"{av} — trend gucleniyor"
        return f"{av} — yatay/zayif trend"

    def rel_detail() -> str:
        if not has_index:
            return "endeks verisi yok — notr"
        if rel_s >= 1.0:
            return "endeksten belirgin guclu (lider)"
        if rel_s >= 0.5:
            return "endekse paralel/hafif guclu"
        return "endeksten zayif"

    def rsi_detail() -> str:
        rv = f"RSI {rsi_v:.0f}" if rsi_v is not None else "RSI"
        if rsi_v is None:
            return rv
        if rsi_v > 80:
            return f"{rv} — sert asiri alim, geri cekilme riski"
        if rsi_v > 70:
            return f"{rv} — asiri alim bolgesi"
        if rsi_v >= 55:
            return f"{rv} — saglikli momentum bolgesi"
        if rsi_v < 45:
            return f"{rv} — zayif/asiri satim"
        return f"{rv} — notr"

    def bb_detail() -> str:
        if pctb_v is not None and pctb_v > 1.0:
            return "fiyat ust band disinda — asiri uzanma"
        if bb_s >= 0.7:
            return "bant icinde saglikli ust-yari konum"
        return "bant ici notr seyir"

    return [
        IndicatorResult("Trend (EMA)", "trend", _round1(trend_s), WEIGHTS["trend"],
                        value=_round1(ema50_v), detail=trend_detail()),
        IndicatorResult("Momentum (MACD)", "momentum", _round1(mom_s), WEIGHTS["momentum"],
                        value=_round1(macd_v), detail=mom_detail()),
        IndicatorResult("Trend Gucu (ADX)", "adx", _round1(adx_s), WEIGHTS["adx"],
                        value=_round1(adx_v), detail=adx_detail()),
        IndicatorResult("Goreceli Guc", "rel_strength", _round1(rel_s), WEIGHTS["rel_strength"],
                        value=None, detail=rel_detail()),
        IndicatorResult("RSI", "rsi", _round1(rsi_s), WEIGHTS["rsi"],
                        value=_round1(rsi_v), detail=rsi_detail()),
        IndicatorResult("Bollinger", "bbands", _round1(bb_s), WEIGHTS["bbands"],
                        value=_round1(pctb_v), detail=bb_detail()),
    ]


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
