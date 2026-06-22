"""Grafik formasyon (pattern) tespiti.

Son 90 barlik OHLCV verisinde bilinen teknik formasyonlari tespit eder:
  - Ikili Tepe / Ikili Dip
  - Omuz-Bas-Omuz / Ters Omuz-Bas-Omuz
  - Yukseliyor / Dusuyor Kama
  - Yukseliyor / Dusuyor / Simetrik Ucgen
  - Boga Bayragi / Ayi Bayragi
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


# ── yardımcılar ──────────────────────────────────────────────────────────────

def _date_at(df_use: pd.DataFrame, idx: int) -> str:
    try:
        ts = df_use.index[idx]
        return str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
    except Exception:
        return ""


def _find_pivots(values: np.ndarray, window: int = 5) -> tuple[list[int], list[int]]:
    """Basit yerel tepe/dip noktalarini bulur."""
    peaks, troughs = [], []
    n = len(values)
    for i in range(window, n - window):
        v = float(values[i])
        nbrs = [float(values[i + j]) for j in range(-window, window + 1) if j != 0]
        if not nbrs:
            continue
        if v >= max(nbrs):
            peaks.append(i)
        elif v <= min(nbrs):
            troughs.append(i)
    return peaks, troughs


# ── ana fonksiyon ─────────────────────────────────────────────────────────────

def detect_patterns(df: pd.DataFrame, lookback: int = 90) -> List[Dict[str, Any]]:
    """Son `lookback` barda grafik formasyonlarini tespit eder.

    Returns:
        Her formasyon bir dict:
          type, name, emoji, description, signal, direction, strength,
          markers: [{t, v, pos, shape, color, label}],
          trendlines: [[{t, v}, {t, v}], ...]
    """
    patterns: List[Dict[str, Any]] = []

    if df is None or len(df) < 30:
        return patterns

    n_use = min(lookback, len(df))
    df_use = df.tail(n_use).copy()

    close_v = df_use["Close"].astype(float).values
    high_v = df_use["High"].astype(float).values
    low_v = df_use["Low"].astype(float).values
    n = len(close_v)

    def date_at(i: int) -> str:
        return _date_at(df_use, i)

    # ── Pivot noktaları ───────────────────────────────────────────────────────
    peaks, troughs = _find_pivots(close_v, window=5)

    # ── İkili Tepe ────────────────────────────────────────────────────────────
    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        v1, v2 = float(close_v[p1]), float(close_v[p2])
        gap = p2 - p1
        sim = abs(v1 - v2) / max(v1, v2)
        if gap >= 8 and sim < 0.03:
            valley = float(np.min(close_v[p1 : p2 + 1]))
            depth = (min(v1, v2) - valley) / min(v1, v2)
            age = n - 1 - p2
            if depth > 0.03 and age <= 15:
                patterns.append({
                    "type": "double_top",
                    "name": "İkili Tepe",
                    "emoji": "🔴",
                    "description": (
                        f"Fiyat iki kez ~{round(max(v1, v2), 2)} direnç bölgesini test etti "
                        f"ve geri döndü. Aralarındaki dip %{round(depth*100,1)} daha aşağıda."
                    ),
                    "signal": "Düşüş sinyali — direnç geçilmeden satış baskısı devam edebilir.",
                    "direction": "bearish",
                    "strength": "güçlü",
                    "markers": [
                        {"t": date_at(p1), "v": v1, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "T1"},
                        {"t": date_at(p2), "v": v2, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "T2"},
                    ],
                    "trendlines": [],
                })

    # ── İkili Dip ─────────────────────────────────────────────────────────────
    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        v1, v2 = float(close_v[t1]), float(close_v[t2])
        gap = t2 - t1
        sim = abs(v1 - v2) / max(v1, v2)
        if gap >= 8 and sim < 0.03:
            peak_max = float(np.max(close_v[t1 : t2 + 1]))
            depth = (peak_max - max(v1, v2)) / max(v1, v2)
            age = n - 1 - t2
            if depth > 0.03 and age <= 15:
                patterns.append({
                    "type": "double_bottom",
                    "name": "İkili Dip",
                    "emoji": "🟢",
                    "description": (
                        f"Fiyat iki kez ~{round(min(v1, v2), 2)} destek bölgesinde "
                        f"dip yaptı ve döndü. Aralarındaki zirve %{round(depth*100,1)} daha yukarıda."
                    ),
                    "signal": "Yükseliş sinyali — destek güçlü, toparlanma beklentisi yüksek.",
                    "direction": "bullish",
                    "strength": "güçlü",
                    "markers": [
                        {"t": date_at(t1), "v": v1, "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "D1"},
                        {"t": date_at(t2), "v": v2, "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "D2"},
                    ],
                    "trendlines": [],
                })

    # ── Omuz-Baş-Omuz ────────────────────────────────────────────────────────
    if len(peaks) >= 3:
        sl, sh, sr = peaks[-3], peaks[-2], peaks[-1]
        vl, vh, vr = float(close_v[sl]), float(close_v[sh]), float(close_v[sr])
        head_higher = vh > vl * 1.02 and vh > vr * 1.02
        shoulders_similar = abs(vl - vr) / max(vl, vr) < 0.05
        min_gap = sh - sl >= 7 and sr - sh >= 7
        age = n - 1 - sr
        if head_higher and shoulders_similar and min_gap and age <= 20:
            neckline = round((vl + vr) / 2, 4)
            patterns.append({
                "type": "head_shoulders",
                "name": "Omuz-Baş-Omuz",
                "emoji": "🔴",
                "description": (
                    f"Sol omuz ({round(vl,2)}), baş ({round(vh,2)}), sağ omuz ({round(vr,2)}). "
                    f"Boyun çizgisi ~{neckline}."
                ),
                "signal": "Çok güçlü düşüş sinyali — boyun çizgisi kırılırsa satış hızlanabilir.",
                "direction": "bearish",
                "strength": "çok güçlü",
                "markers": [
                    {"t": date_at(sl), "v": vl, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "Sol"},
                    {"t": date_at(sh), "v": vh, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff0000", "label": "Baş"},
                    {"t": date_at(sr), "v": vr, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "Sağ"},
                ],
                "trendlines": [],
            })

    # ── Ters Omuz-Baş-Omuz ───────────────────────────────────────────────────
    if len(troughs) >= 3:
        sl, sh, sr = troughs[-3], troughs[-2], troughs[-1]
        vl, vh, vr = float(close_v[sl]), float(close_v[sh]), float(close_v[sr])
        head_lower = vh < vl * 0.98 and vh < vr * 0.98
        shoulders_similar = abs(vl - vr) / max(vl, vr) < 0.05
        min_gap = sh - sl >= 7 and sr - sh >= 7
        age = n - 1 - sr
        if head_lower and shoulders_similar and min_gap and age <= 20:
            neckline = round((vl + vr) / 2, 4)
            patterns.append({
                "type": "inv_head_shoulders",
                "name": "Ters Omuz-Baş-Omuz",
                "emoji": "🟢",
                "description": (
                    f"Sol omuz ({round(vl,2)}), baş ({round(vh,2)}), sağ omuz ({round(vr,2)}). "
                    f"Boyun çizgisi ~{neckline}."
                ),
                "signal": "Çok güçlü yükseliş sinyali — boyun çizgisi kırılırsa alım hızlanabilir.",
                "direction": "bullish",
                "strength": "çok güçlü",
                "markers": [
                    {"t": date_at(sl), "v": vl, "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "Sol"},
                    {"t": date_at(sh), "v": vh, "pos": "belowBar", "shape": "arrowUp", "color": "#00ff88", "label": "Baş"},
                    {"t": date_at(sr), "v": vr, "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "Sağ"},
                ],
                "trendlines": [],
            })

    # ── Üçgen & Kama (son 30 bar lineer regresyon) ────────────────────────────
    if n >= 30:
        w = 30
        rh = high_v[-w:]
        rl = low_v[-w:]
        x = np.arange(w, dtype=float)

        h_coeffs = np.polyfit(x, rh, 1)
        l_coeffs = np.polyfit(x, rl, 1)
        h_slope, h_int = float(h_coeffs[0]), float(h_coeffs[1])
        l_slope, l_int = float(l_coeffs[0]), float(l_coeffs[1])

        h_mean = float(np.mean(rh))
        l_mean = float(np.mean(rl))

        h_spct = h_slope / h_mean * 100 if h_mean else 0
        l_spct = l_slope / l_mean * 100 if l_mean else 0

        early_rng = float(np.max(rh[:15]) - np.min(rl[:15]))
        late_rng = float(np.max(rh[15:]) - np.min(rl[15:]))
        converging = early_rng > 0 and late_rng < early_rng * 0.80

        t_start = date_at(n - w)
        t_end = date_at(n - 1)

        def tl(slope: float, intercept: float) -> list:
            return [
                {"t": t_start, "v": float(intercept)},
                {"t": t_end, "v": float(intercept + slope * (w - 1))},
            ]

        thr = 0.05  # %/bar minimum eşik

        if converging:
            h_fall = h_spct < -thr
            h_flat = abs(h_spct) <= thr
            l_rise = l_spct > thr
            l_flat = abs(l_spct) <= thr
            h_rise = h_spct > thr
            l_fall = l_spct < -thr

            if h_fall and l_rise:
                patterns.append({
                    "type": "symmetric_triangle",
                    "name": "Simetrik Üçgen",
                    "emoji": "🟡",
                    "description": "Hem tepe hem dip çizgileri birbirine yaklaşıyor. Fiyat sıkışıyor.",
                    "signal": "Kırılım yakın. Hacim eşliğinde güçlü yön hareketi bekleniyor.",
                    "direction": "neutral",
                    "strength": "orta",
                    "markers": [],
                    "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
                })
            elif h_fall and l_flat:
                patterns.append({
                    "type": "descending_triangle",
                    "name": "Düşen Üçgen",
                    "emoji": "🔴",
                    "description": "Direnç çizgisi düşerken destek yatay seyrediyor.",
                    "signal": "Genellikle aşağı kırılımla sonuçlanır. Destek kırılırsa satış artar.",
                    "direction": "bearish",
                    "strength": "orta",
                    "markers": [],
                    "trendlines": [tl(h_slope, h_int), [{"t": t_start, "v": l_mean}, {"t": t_end, "v": l_mean}]],
                })
            elif l_rise and h_flat:
                patterns.append({
                    "type": "ascending_triangle",
                    "name": "Yükselen Üçgen",
                    "emoji": "🟢",
                    "description": "Destek çizgisi yükselirken direnç yatay seyrediyor.",
                    "signal": "Genellikle yukarı kırılımla sonuçlanır. Direnci geçerse güçlü alım gelir.",
                    "direction": "bullish",
                    "strength": "orta",
                    "markers": [],
                    "trendlines": [[{"t": t_start, "v": h_mean}, {"t": t_end, "v": h_mean}], tl(l_slope, l_int)],
                })
            elif h_rise and l_rise and h_spct > l_spct + thr:
                patterns.append({
                    "type": "rising_wedge",
                    "name": "Yükselen Kama",
                    "emoji": "🔴",
                    "description": "Her iki çizgi yükseliyor ancak aralık daralıyor. Yükseliş ivmesi zayıflıyor.",
                    "signal": "Genellikle düşüşten önce oluşur. Aşağı kırılım ihtimali yüksek.",
                    "direction": "bearish",
                    "strength": "orta",
                    "markers": [],
                    "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
                })
            elif h_fall and l_fall and l_spct < h_spct - thr:
                patterns.append({
                    "type": "falling_wedge",
                    "name": "Düşen Kama",
                    "emoji": "🟢",
                    "description": "Her iki çizgi düşüyor ancak aralık daralıyor. Düşüş ivmesi zayıflıyor.",
                    "signal": "Genellikle yükselişten önce oluşur. Yukarı kırılım beklentisi güçlü.",
                    "direction": "bullish",
                    "strength": "orta",
                    "markers": [],
                    "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
                })

    # ── Bayrak formasyonları ──────────────────────────────────────────────────
    if n >= 25:
        pole = close_v[-(25) : -(15)]
        flag_c = close_v[-15:]
        if len(pole) >= 5:
            p0, p1_v = float(pole[0]), float(pole[-1])
            if p0 != 0:
                pole_pct = (p1_v - p0) / abs(p0) * 100
                flag_mean = float(np.mean(flag_c)) if len(flag_c) else 0
                flag_rng = (
                    (float(np.max(flag_c)) - float(np.min(flag_c))) / flag_mean * 100
                    if flag_mean else 0
                )
                if pole_pct > 8 and flag_rng < 5:
                    patterns.append({
                        "type": "bull_flag",
                        "name": "Boğa Bayrağı",
                        "emoji": "🟢",
                        "description": (
                            f"+%{pole_pct:.1f} güçlü yükseliş (sap) sonrası "
                            f"%{flag_rng:.1f} dar konsolidasyon (bayrak)."
                        ),
                        "signal": "Yukarı kırılım beklentisi yüksek. Bayraktan çıkışla yükseliş sürebilir.",
                        "direction": "bullish",
                        "strength": "güçlü",
                        "markers": [],
                        "trendlines": [],
                    })
                elif pole_pct < -8 and flag_rng < 5:
                    patterns.append({
                        "type": "bear_flag",
                        "name": "Ayı Bayrağı",
                        "emoji": "🔴",
                        "description": (
                            f"-%{abs(pole_pct):.1f} güçlü düşüş (sap) sonrası "
                            f"%{flag_rng:.1f} dar konsolidasyon (bayrak)."
                        ),
                        "signal": "Aşağı kırılım riski yüksek. Bayraktan çıkışla düşüş sürebilir.",
                        "direction": "bearish",
                        "strength": "güçlü",
                        "markers": [],
                        "trendlines": [],
                    })

    return patterns


# ── otomatik trend çizgileri ─────────────────────────────────────────────────

def detect_auto_trendlines(df: pd.DataFrame) -> dict:
    """Kısa ve uzun vadeli otomatik destek/direnç trend çizgilerini tespit eder.

    Her timeframe için pivot dip/tepelerden doğru üretir ve günümüze uzatır.

    Döner:
      {
        "short": {"support": [{t,v},{t,v}] | None, "resistance": [...] | None},
        "long":  {"support": [...] | None,          "resistance": [...] | None},
      }
    """
    if df is None or len(df) < 30:
        return {"short": {"support": None, "resistance": None},
                "long":  {"support": None, "resistance": None}}

    high_v  = df["High"].astype(float).values
    low_v   = df["Low"].astype(float).values
    n_total = len(df)

    def date_at(abs_i: int) -> str:
        try:
            ts = df.index[abs_i]
            return str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
        except Exception:
            return ""

    def _pivots_separated(indices: list[int], min_gap: int) -> list[int]:
        if not indices:
            return []
        out = [indices[0]]
        for idx in indices[1:]:
            if idx - out[-1] >= min_gap:
                out.append(idx)
        return out

    def _fit_line(i1: int, p1: float, i2: int, p2: float) -> list[dict] | None:
        if i2 <= i1:
            return None
        slope = (p2 - p1) / (i2 - i1)
        i_end = n_total - 1
        p_end = p2 + slope * (i_end - i2)
        if p_end <= 0:
            return None
        return [
            {"t": date_at(i1), "v": round(float(p1), 4)},
            {"t": date_at(i_end), "v": round(float(p_end), 4)},
        ]

    result = {"short": {"support": None, "resistance": None},
              "long":  {"support": None, "resistance": None}}

    for label, lookback, window, min_gap in [
        ("short", 60,  3, 8),
        ("long",  200, 7, 20),
    ]:
        n_use  = min(lookback, n_total)
        offset = n_total - n_use

        peaks_rel,   _            = _find_pivots(high_v[-n_use:], window=window)
        _,           troughs_rel  = _find_pivots(low_v[-n_use:],  window=window)

        peaks_abs   = _pivots_separated([i + offset for i in peaks_rel],   min_gap)
        troughs_abs = _pivots_separated([i + offset for i in troughs_rel], min_gap)

        if len(troughs_abs) >= 2:
            i1, i2 = troughs_abs[-2], troughs_abs[-1]
            result[label]["support"] = _fit_line(i1, low_v[i1], i2, low_v[i2])

        if len(peaks_abs) >= 2:
            i1, i2 = peaks_abs[-2], peaks_abs[-1]
            result[label]["resistance"] = _fit_line(i1, high_v[i1], i2, high_v[i2])

    return result
