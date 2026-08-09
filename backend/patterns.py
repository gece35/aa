"""Grafik formasyon (pattern) tespiti — v2.

Temel iyileştirmeler:
  - Pivot tespiti: tepe için High, dip için Low değerleri (Close yerine)
  - Anlamlı pivot filtresi: gürültülü küçük salınımlar eleniyor
  - Genişletilmiş lookback: 90 → 120 bar
  - Gevşetilmiş eşikler: double top/bottom %5, omuzlar %8
  - H&S neckline: omuzlar arasındaki gerçek dip değerinden hesaplanıyor
  - Üçgen/kama: 20-30-45-60 bar pencerelerinin en iyi uyumu aranıyor
  - Güven skoru: her formasyon için yüksek/orta/düşük hesaplanıyor
  - Hacim onayı: mevcut olduğunda formasyon gücü güncelleniyor
"""

from __future__ import annotations

import math
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


def _find_pivot_highs(values: np.ndarray, window: int = 3) -> list[int]:
    """Yerel tepe indekslerini döndürür (High dizisi üzerinde)."""
    peaks, n = [], len(values)
    for i in range(window, n - window):
        v = float(values[i])
        if all(v >= float(values[i + j]) for j in range(-window, window + 1) if j != 0):
            peaks.append(i)
    return peaks


def _find_pivot_lows(values: np.ndarray, window: int = 3) -> list[int]:
    """Yerel dip indekslerini döndürür (Low dizisi üzerinde)."""
    troughs, n = [], len(values)
    for i in range(window, n - window):
        v = float(values[i])
        if all(v <= float(values[i + j]) for j in range(-window, window + 1) if j != 0):
            troughs.append(i)
    return troughs


def _filter_significant(
    indices: list[int],
    values: np.ndarray,
    min_pct: float = 0.025,
) -> list[int]:
    """Önceki anlamlı pivota göre minimum yüzde hareketi olmayan pivotları eler.
    Bu sayede gürültülü küçük salınımlar temizlenir."""
    if not indices:
        return []
    sig = [indices[0]]
    for idx in indices[1:]:
        prev_v = float(values[sig[-1]])
        curr_v = float(values[idx])
        ref    = max(prev_v, curr_v)
        if ref > 0 and abs(curr_v - prev_v) / ref >= min_pct:
            sig.append(idx)
    return sig


def _r2(y: np.ndarray, y_pred: np.ndarray) -> float:
    """R² — regresyon uyum kalitesi (0=kötü, 1=mükemmel)."""
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


# ── eski API uyumu ─────────────────────────────────────────────────────────────

def _find_pivots(values: np.ndarray, window: int = 5) -> tuple[list[int], list[int]]:
    """Geriye dönük uyumluluk için: hem tepe hem dip, aynı dizi üzerinde."""
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

def detect_patterns(df: pd.DataFrame, lookback: int = 120) -> List[Dict[str, Any]]:
    """Son `lookback` barda grafik formasyonlarini tespit eder.

    Returns:
        Her formasyon bir dict:
          type, name, emoji, description, signal, direction, strength, confidence,
          markers: [{t, v, pos, shape, color, label}],
          trendlines: [[{t, v}, {t, v}], ...]
    """
    patterns: List[Dict[str, Any]] = []

    if df is None or len(df) < 30:
        return patterns

    n_use  = min(lookback, len(df))
    df_use = df.tail(n_use).copy()

    close_v  = df_use["Close"].astype(float).values
    high_v   = df_use["High"].astype(float).values
    low_v    = df_use["Low"].astype(float).values
    volume_v = df_use["Volume"].astype(float).values if "Volume" in df_use.columns else None
    n = len(close_v)
    # Son geçerli kapanış — NaN trailing değerleri görmezden gel (ABD tatil günleri vs.)
    _valid = close_v[~np.isnan(close_v)]
    last_close = float(_valid[-1]) if len(_valid) > 0 else float("nan")

    def date_at(i: int) -> str:
        return _date_at(df_use, i)

    # ── Pivot tespiti: tepe için High, dip için Low ───────────────────────────
    raw_peaks   = _find_pivot_highs(high_v,  window=3)
    raw_troughs = _find_pivot_lows(low_v,    window=3)

    # Gürültüyü temizle: pivot değerleri arasında en az %2.5 fark olsun
    peaks   = _filter_significant(raw_peaks,   high_v, min_pct=0.025)
    troughs = _filter_significant(raw_troughs, low_v,  min_pct=0.025)

    # ── İkili Tepe ────────────────────────────────────────────────────────────
    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        v1, v2 = float(high_v[p1]), float(high_v[p2])
        gap    = p2 - p1
        sim    = abs(v1 - v2) / max(v1, v2)
        valley = float(np.min(low_v[p1:p2 + 1]))
        depth  = (min(v1, v2) - valley) / min(v1, v2)
        age    = n - 1 - p2

        if gap >= 7 and sim < 0.05 and depth > 0.025 and age <= 25:
            # Hacim onayı: T2'de hacim T1'den düşükse güvenilirlik artar
            vol_ok = False
            if volume_v is not None:
                v1_avg = float(np.mean(volume_v[max(0, p1-2):p1+3]))
                v2_avg = float(np.mean(volume_v[max(0, p2-2):p2+3]))
                vol_ok = v2_avg < v1_avg * 0.9

            confidence = (
                "yüksek" if (sim < 0.025 and depth > 0.05 and age <= 10 and vol_ok) else
                "orta"   if (sim < 0.04  and depth > 0.03 and age <= 18) else
                "düşük"
            )
            strength = "çok güçlü" if confidence == "yüksek" else "güçlü" if confidence == "orta" else "zayıf"
            neckline   = round(valley, 4)
            resistance = max(v1, v2)  # tepelerin direnç seviyesi
            # Formasyon başarısız mı? Fiyat direncin üstüne kırıldıysa ikili tepe iptal
            # (düşüş beklenirken yukarı kırılım = ters yön, formasyon çökmüş).
            failed = last_close > resistance * 1.01
            broken = last_close < neckline
            # Sinyal tükendi mi? Fiyat neckline'dan >%7 aşağıdaysa (kırılım fazlasıyla gerçekleşti).
            if not failed and last_close >= neckline * 0.93:
                patterns.append({
                    "type": "double_top",
                    "name": "İkili Tepe",
                    "emoji": "🔴",
                    "description": (
                        f"Fiyat iki kez ~{round(max(v1,v2),2)} direnç seviyesini test etti ve geri döndü. "
                        f"Tepeler arası benzerlik: %{round(sim*100,1)}. "
                        f"Boyun çizgisi: {neckline}."
                        + (" ⚠️ Boyun çizgisi kırıldı." if broken else "")
                    ),
                    "signal": (
                        ("Düşüş sinyali gerçekleşti — boyun çizgisi kırıldı, satış baskısı sürebilir."
                         if broken else
                         "Düşüş sinyali — boyun çizgisi kırılırsa satış hızlanabilir.")
                        + (" Hacim T2'de azalmış, sinyal güvenilir." if vol_ok else "")
                    ),
                    "direction": "bearish",
                    "strength": strength,
                    "confidence": confidence,
                    "confirmed": broken,
                    "trigger_distance_pct": abs(last_close - neckline) / neckline if neckline else 1.0,
                    "volume_confirmed": vol_ok,
                    "pattern_age": age,
                    "markers": [
                        {"t": date_at(p1), "v": float(high_v[p1]), "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "T1"},
                        {"t": date_at(p2), "v": float(high_v[p2]), "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "T2"},
                    ],
                    "trendlines": [
                        [{"t": date_at(p1), "v": neckline}, {"t": date_at(n-1), "v": neckline}],
                    ],
                })

    # ── İkili Dip ─────────────────────────────────────────────────────────────
    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        v1, v2 = float(low_v[t1]), float(low_v[t2])
        gap    = t2 - t1
        sim    = abs(v1 - v2) / max(v1, v2)
        peak_m = float(np.max(high_v[t1:t2 + 1]))
        depth  = (peak_m - max(v1, v2)) / max(v1, v2)
        age    = n - 1 - t2

        if gap >= 7 and sim < 0.05 and depth > 0.025 and age <= 25:
            vol_ok = False
            if volume_v is not None:
                v1_avg = float(np.mean(volume_v[max(0, t1-2):t1+3]))
                v2_avg = float(np.mean(volume_v[max(0, t2-2):t2+3]))
                vol_ok = v2_avg < v1_avg * 0.9

            confidence = (
                "yüksek" if (sim < 0.025 and depth > 0.05 and age <= 10 and vol_ok) else
                "orta"   if (sim < 0.04  and depth > 0.03 and age <= 18) else
                "düşük"
            )
            strength  = "çok güçlü" if confidence == "yüksek" else "güçlü" if confidence == "orta" else "zayıf"
            neckline = round(peak_m, 4)
            support  = min(v1, v2)  # diplerin destek seviyesi
            # Formasyon başarısız mı? Fiyat desteğin altına kırıldıysa ikili dip iptal
            # (yükseliş beklenirken aşağı kırılım = ters yön, formasyon çökmüş).
            failed = last_close < support * 0.99
            broken = last_close > neckline
            # Sinyal tükendi mi? Fiyat neckline'dan >%7 yukarıdaysa (kırılım fazlasıyla gerçekleşti).
            if not failed and last_close <= neckline * 1.07:
                patterns.append({
                    "type": "double_bottom",
                    "name": "İkili Dip",
                    "emoji": "🟢",
                    "description": (
                        f"Fiyat iki kez ~{round(min(v1,v2),2)} destek seviyesinde dip yaptı. "
                        f"Dipler arası benzerlik: %{round(sim*100,1)}. "
                        f"Boyun çizgisi (direnç): {neckline}."
                        + (" ✅ Boyun çizgisi kırıldı." if broken else "")
                    ),
                    "signal": (
                        ("Yükseliş sinyali gerçekleşti — boyun çizgisi kırıldı, momentum sürebilir."
                         if broken else
                         "Yükseliş sinyali — boyun çizgisi kırılırsa alım hızlanabilir.")
                        + (" Hacim D2'de azalmış, dip oluşumu güvenilir." if vol_ok else "")
                    ),
                    "direction": "bullish",
                    "strength": strength,
                    "confidence": confidence,
                    "confirmed": broken,
                    "trigger_distance_pct": abs(last_close - neckline) / neckline if neckline else 1.0,
                    "volume_confirmed": vol_ok,
                    "pattern_age": age,
                    "markers": [
                        {"t": date_at(t1), "v": float(low_v[t1]), "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "D1"},
                        {"t": date_at(t2), "v": float(low_v[t2]), "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "D2"},
                    ],
                    "trendlines": [
                        [{"t": date_at(t1), "v": neckline}, {"t": date_at(n-1), "v": neckline}],
                    ],
                })

    # ── Omuz-Baş-Omuz ────────────────────────────────────────────────────────
    if len(peaks) >= 3:
        sl, sh, sr = peaks[-3], peaks[-2], peaks[-1]
        vl = float(high_v[sl])
        vh = float(high_v[sh])
        vr = float(high_v[sr])

        head_higher    = vh > vl * 1.015 and vh > vr * 1.015
        shoulders_sim  = abs(vl - vr) / max(vl, vr) < 0.08   # gevşetildi: %5 → %8
        min_gap        = (sh - sl) >= 6 and (sr - sh) >= 6
        age            = n - 1 - sr

        if head_higher and shoulders_sim and min_gap and age <= 25:
            # Gerçek neckline: iki omuz arasındaki dip değerlerinden
            left_valley  = float(np.min(low_v[sl:sh + 1]))
            right_valley = float(np.min(low_v[sh:sr + 1]))
            neckline     = round((left_valley + right_valley) / 2, 4)

            # Boyun çizgisi kırıldı mı?
            broken = last_close < neckline * 0.99

            confidence = (
                "yüksek" if (shoulders_sim and broken) else
                "orta"   if shoulders_sim else
                "düşük"
            )
            strength = "çok güçlü" if confidence == "yüksek" else "güçlü"
            # Formasyon başarısız mı? Fiyat başın üstüne çıktıysa O-B-O iptal
            # (düşüş beklenirken yeni zirve = ters yön, formasyon çökmüş).
            failed = last_close > vh
            # Sinyal tükendi mi? Boyun kırılmış VE fiyat >%7 aşağıdaysa formasyon geçersiz.
            if not failed and not (broken and last_close < neckline * 0.93):
                patterns.append({
                    "type": "head_shoulders",
                    "name": "Omuz-Baş-Omuz",
                    "emoji": "🔴",
                    "description": (
                        f"Sol omuz: {round(vl,2)}, Baş: {round(vh,2)}, Sağ omuz: {round(vr,2)}. "
                        f"Boyun çizgisi: ~{neckline}."
                        + (" ⚠️ Boyun kırıldı." if broken else "")
                    ),
                    "signal": (
                        "Çok güçlü düşüş sinyali — boyun kırılmışsa satış baskısı güçlü."
                        if broken else
                        "Güçlü düşüş sinyali — boyun kırılması bekleniyor."
                    ),
                    "direction": "bearish",
                    "strength": strength,
                    "confidence": confidence,
                    "confirmed": broken,
                    "trigger_distance_pct": abs(last_close - neckline) / neckline if neckline else 1.0,
                    "volume_confirmed": False,
                    "pattern_age": age,
                    "markers": [
                        {"t": date_at(sl), "v": vl, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "Sol"},
                        {"t": date_at(sh), "v": vh, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff0000", "label": "Baş"},
                        {"t": date_at(sr), "v": vr, "pos": "aboveBar", "shape": "arrowDown", "color": "#ff5370", "label": "Sağ"},
                    ],
                    "trendlines": [
                        [{"t": date_at(sl), "v": neckline}, {"t": date_at(n-1), "v": neckline}],
                    ],
                })

    # ── Ters Omuz-Baş-Omuz ───────────────────────────────────────────────────
    if len(troughs) >= 3:
        sl, sh, sr = troughs[-3], troughs[-2], troughs[-1]
        vl = float(low_v[sl])
        vh = float(low_v[sh])
        vr = float(low_v[sr])

        head_lower    = vh < vl * 0.985 and vh < vr * 0.985
        shoulders_sim = abs(vl - vr) / max(vl, vr) < 0.08
        min_gap       = (sh - sl) >= 6 and (sr - sh) >= 6
        age           = n - 1 - sr

        if head_lower and shoulders_sim and min_gap and age <= 25:
            left_peak    = float(np.max(high_v[sl:sh + 1]))
            right_peak   = float(np.max(high_v[sh:sr + 1]))
            neckline     = round((left_peak + right_peak) / 2, 4)
            broken       = last_close > neckline * 1.01

            confidence = (
                "yüksek" if (shoulders_sim and broken) else
                "orta"   if shoulders_sim else
                "düşük"
            )
            strength = "çok güçlü" if confidence == "yüksek" else "güçlü"
            # Formasyon başarısız mı? Fiyat başın altına indiyse ters O-B-O iptal
            # (yükseliş beklenirken yeni dip = ters yön, formasyon çökmüş).
            failed = last_close < vh
            # Sinyal tükendi mi? Boyun kırılmış VE fiyat >%7 yukarıdaysa formasyon geçersiz.
            if not failed and not (broken and last_close > neckline * 1.07):
                patterns.append({
                    "type": "inv_head_shoulders",
                    "name": "Ters Omuz-Baş-Omuz",
                    "emoji": "🟢",
                    "description": (
                        f"Sol omuz: {round(vl,2)}, Baş: {round(vh,2)}, Sağ omuz: {round(vr,2)}. "
                        f"Boyun çizgisi: ~{neckline}."
                        + (" ✅ Boyun kırıldı." if broken else "")
                    ),
                    "signal": (
                        "Çok güçlü yükseliş sinyali — boyun kırılmışsa momentum güçlü."
                        if broken else
                        "Güçlü yükseliş sinyali — boyun kırılması bekleniyor."
                    ),
                    "direction": "bullish",
                    "strength": strength,
                    "confidence": confidence,
                    "confirmed": broken,
                    "trigger_distance_pct": abs(last_close - neckline) / neckline if neckline else 1.0,
                    "volume_confirmed": False,
                    "pattern_age": age,
                    "markers": [
                        {"t": date_at(sl), "v": vl, "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "Sol"},
                        {"t": date_at(sh), "v": vh, "pos": "belowBar", "shape": "arrowUp", "color": "#00ff88", "label": "Baş"},
                        {"t": date_at(sr), "v": vr, "pos": "belowBar", "shape": "arrowUp", "color": "#34f5a8", "label": "Sağ"},
                    ],
                    "trendlines": [
                        [{"t": date_at(sl), "v": neckline}, {"t": date_at(n-1), "v": neckline}],
                    ],
                })

    # ── Üçgen & Kama — çoklu pencere boyutu ─────────────────────────────────
    # 4 farklı pencere dener, en iyi R² uyumunu seçer
    best_wedge: dict | None = None
    best_r2_sum = -1.0

    for w in [20, 30, 45, 60]:
        if n < w + 5:
            continue

        rh = high_v[-w:]
        rl = low_v[-w:]
        x  = np.arange(w, dtype=float)

        h_coeffs       = np.polyfit(x, rh, 1)
        l_coeffs       = np.polyfit(x, rl, 1)
        h_slope, h_int = float(h_coeffs[0]), float(h_coeffs[1])
        l_slope, l_int = float(l_coeffs[0]), float(l_coeffs[1])

        h_pred = h_coeffs[0] * x + h_coeffs[1]
        l_pred = l_coeffs[0] * x + l_coeffs[1]
        h_r2   = _r2(rh, h_pred)
        l_r2   = _r2(rl, l_pred)

        # Regresyon uyumu çok kötüyse bu pencereyi atla
        if h_r2 < 0.35 or l_r2 < 0.35:
            continue

        h_mean = float(np.mean(rh))
        l_mean = float(np.mean(rl))
        h_spct = h_slope / h_mean * 100 if h_mean else 0
        l_spct = l_slope / l_mean * 100 if l_mean else 0

        # Yakınsama kontrolü: ilk yarı aralığı son yarıdan geniş mi?
        half = w // 2
        early_rng = float(np.max(rh[:half]) - np.min(rl[:half]))
        late_rng  = float(np.max(rh[half:]) - np.min(rl[half:]))
        converging = early_rng > 0 and late_rng < early_rng * 0.80

        if not converging:
            continue

        thr     = 0.04   # %/bar minimum eğim eşiği
        h_fall  = h_spct < -thr
        h_flat  = abs(h_spct) <= thr
        l_rise  = l_spct > thr
        l_flat  = abs(l_spct) <= thr
        h_rise  = h_spct > thr
        l_fall  = l_spct < -thr

        t_start = date_at(n - w)
        t_end   = date_at(n - 1)

        def tl(slope: float, intercept: float) -> list:
            return [
                {"t": t_start, "v": round(float(intercept), 4)},
                {"t": t_end,   "v": round(float(intercept + slope * (w - 1)), 4)},
            ]

        r2_sum    = h_r2 + l_r2
        confidence = "yüksek" if (h_r2 > 0.72 and l_r2 > 0.72) else "orta" if (h_r2 > 0.5 and l_r2 > 0.5) else "düşük"

        # Formasyon sınırlarının bugünkü (son bar) uzantısı — hem geçerlilik
        # kontrolünde hem tetikleyiciye yakınlık hesabında kullanılır.
        upper_at_end = h_int + h_slope * (w - 1)
        lower_at_end = l_int + l_slope * (w - 1)

        candidate: dict | None = None

        if h_fall and l_rise:
            # Yön belirsiz: hangi sınır daha yakınsa kırılım o yönde beklenir.
            dist_up   = abs(last_close - upper_at_end) / upper_at_end if upper_at_end else 1.0
            dist_down = abs(last_close - lower_at_end) / lower_at_end if lower_at_end else 1.0
            candidate = {
                "type": "symmetric_triangle", "name": "Simetrik Üçgen", "emoji": "🟡",
                "description": f"Son {w} barda hem tepe hem dip birbirine yaklaşıyor — fiyat sıkışıyor. Regresyon uyumu: {round(h_r2,2)}/{round(l_r2,2)}.",
                "signal": "Kırılım yakın. Hacim eşliğinde güçlü yön hareketi bekleniyor.",
                "direction": "neutral", "strength": "orta", "confidence": confidence,
                "confirmed": False, "trigger_distance_pct": min(dist_up, dist_down),
                "volume_confirmed": False, "pattern_age": 0,
                "markers": [], "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
            }
        elif h_fall and l_flat:
            candidate = {
                "type": "descending_triangle", "name": "Düşen Üçgen", "emoji": "🔴",
                "description": f"Son {w} barda direnç çizgisi düşerken destek yatay. Sıkışma mevcut.",
                "signal": "Genellikle aşağı kırılımla sonuçlanır. Destek kırılırsa satış artar.",
                "direction": "bearish", "strength": "orta", "confidence": confidence,
                "confirmed": False,
                "trigger_distance_pct": abs(last_close - l_mean) / l_mean if l_mean else 1.0,
                "volume_confirmed": False, "pattern_age": 0,
                "markers": [], "trendlines": [tl(h_slope, h_int), [{"t": t_start, "v": round(l_mean,4)}, {"t": t_end, "v": round(l_mean,4)}]],
            }
        elif l_rise and h_flat:
            candidate = {
                "type": "ascending_triangle", "name": "Yükselen Üçgen", "emoji": "🟢",
                "description": f"Son {w} barda destek çizgisi yükselirken direnç yatay. Yükseliş baskısı artıyor.",
                "signal": "Genellikle yukarı kırılımla sonuçlanır. Direnci geçerse güçlü alım gelir.",
                "direction": "bullish", "strength": "orta", "confidence": confidence,
                "confirmed": False,
                "trigger_distance_pct": abs(last_close - h_mean) / h_mean if h_mean else 1.0,
                "volume_confirmed": False, "pattern_age": 0,
                "markers": [], "trendlines": [[{"t": t_start, "v": round(h_mean,4)}, {"t": t_end, "v": round(h_mean,4)}], tl(l_slope, l_int)],
            }
        elif h_rise and l_rise and h_spct > l_spct + thr:
            candidate = {
                "type": "rising_wedge", "name": "Yükselen Kama", "emoji": "🔴",
                "description": f"Son {w} barda her iki çizgi yükseliyor ancak aralık daralıyor. Yükseliş ivmesi zayıflıyor.",
                "signal": "Düşüş öncesi klasik formasyon. Aşağı kırılım ihtimali yüksek.",
                "direction": "bearish", "strength": "orta", "confidence": confidence,
                "confirmed": False,
                "trigger_distance_pct": abs(last_close - lower_at_end) / lower_at_end if lower_at_end else 1.0,
                "volume_confirmed": False, "pattern_age": 0,
                "markers": [], "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
            }
        elif h_fall and l_fall and l_spct < h_spct - thr:
            candidate = {
                "type": "falling_wedge", "name": "Düşen Kama", "emoji": "🟢",
                "description": f"Son {w} barda her iki çizgi düşüyor ancak aralık daralıyor. Düşüş ivmesi zayıflıyor.",
                "signal": "Yükseliş öncesi klasik formasyon. Yukarı kırılım beklentisi güçlü.",
                "direction": "bullish", "strength": "orta", "confidence": confidence,
                "confirmed": False,
                "trigger_distance_pct": abs(last_close - upper_at_end) / upper_at_end if upper_at_end else 1.0,
                "volume_confirmed": False, "pattern_age": 0,
                "markers": [], "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
            }

        # Geçerlilik: fiyat hâlâ formasyon sınırları içinde mi?
        # Kırılım zaten gerçekleştiyse formasyon geçersizdir.
        if candidate is not None:
            cur = last_close
            BREAK_MARGIN = 0.025  # %2.5 dışarıya çıkmış = kırılım olmuş
            if cur > upper_at_end * (1 + BREAK_MARGIN) or cur < lower_at_end * (1 - BREAK_MARGIN):
                candidate = None

        if candidate is not None and r2_sum > best_r2_sum:
            best_wedge  = candidate
            best_r2_sum = r2_sum

    if best_wedge:
        patterns.append(best_wedge)

    # ── Bayrak formasyonları ──────────────────────────────────────────────────
    if n >= 30:
        # Sap: son 25-15. barlar, Bayrak: son 15 bar
        pole_bars  = close_v[-(25):-(15)]
        flag_close = close_v[-15:]
        flag_high  = high_v[-15:]
        flag_low   = low_v[-15:]

        if len(pole_bars) >= 5:
            p0, p1_v = float(pole_bars[0]), float(pole_bars[-1])
            if p0 > 0:
                pole_pct = (p1_v - p0) / p0 * 100
                flag_mean = float(np.mean(flag_close)) if len(flag_close) else 0
                flag_rng  = (
                    (float(np.max(flag_high)) - float(np.min(flag_low))) / flag_mean * 100
                    if flag_mean else 0
                )
                # Konsolidasyon: dar aralık (<%6) ve düz/hafif karşı hareket
                flag_slope_pct = (
                    (float(flag_close[-1]) - float(flag_close[0])) / float(flag_close[0]) * 100
                    if flag_close[0] > 0 else 0
                )
                tight_consol = flag_rng < 6

                if pole_pct > 7 and tight_consol:
                    # Hafif aşağı bayrak (counter-trend) daha güvenilir
                    is_counter = flag_slope_pct < 0
                    confidence = "yüksek" if (pole_pct > 12 and is_counter and flag_rng < 4) else \
                                 "orta"   if (pole_pct > 9  and flag_rng < 5) else "düşük"
                    flag_top = float(np.max(flag_high))
                    patterns.append({
                        "type": "bull_flag", "name": "Boğa Bayrağı", "emoji": "🟢",
                        "description": (
                            f"+%{pole_pct:.1f} güçlü yükseliş (sap) sonrası "
                            f"%{flag_rng:.1f} dar konsolidasyon (bayrak)."
                            + (" Bayrak hafif aşağı eğimli — klasik form." if is_counter else "")
                        ),
                        "signal": "Yukarı kırılım beklentisi yüksek. Hacim artışıyla kırılım teyitlenir.",
                        "direction": "bullish", "strength": "güçlü", "confidence": confidence,
                        "confirmed": last_close > flag_top,
                        "trigger_distance_pct": abs(last_close - flag_top) / flag_top if flag_top else 1.0,
                        "volume_confirmed": False, "pattern_age": 0,
                        "markers": [], "trendlines": [],
                    })

                elif pole_pct < -7 and tight_consol:
                    is_counter = flag_slope_pct > 0
                    confidence = "yüksek" if (pole_pct < -12 and is_counter and flag_rng < 4) else \
                                 "orta"   if (pole_pct < -9  and flag_rng < 5) else "düşük"
                    flag_bottom = float(np.min(flag_low))
                    patterns.append({
                        "type": "bear_flag", "name": "Ayı Bayrağı", "emoji": "🔴",
                        "description": (
                            f"-%{abs(pole_pct):.1f} güçlü düşüş (sap) sonrası "
                            f"%{flag_rng:.1f} dar konsolidasyon (bayrak)."
                            + (" Bayrak hafif yukarı eğimli — klasik form." if is_counter else "")
                        ),
                        "signal": "Aşağı kırılım riski yüksek. Hacim artışıyla kırılım teyitlenir.",
                        "direction": "bearish", "strength": "güçlü", "confidence": confidence,
                        "confirmed": last_close < flag_bottom,
                        "trigger_distance_pct": abs(last_close - flag_bottom) / flag_bottom if flag_bottom else 1.0,
                        "volume_confirmed": False, "pattern_age": 0,
                        "markers": [], "trendlines": [],
                    })

    # Baskınlık skoruna göre sırala + en olası formasyonu işaretle
    _rank_patterns(patterns)
    return patterns


# ── otomatik trend çizgileri ─────────────────────────────────────────────────

def _line_violates_candles(
    prices: np.ndarray,
    a: int,
    pa: float,
    slope: float,
    end: int,
    kind: str,
    tol_pct: float,
) -> bool:
    """Çizgi [a, end] aralığında herhangi bir mumun içinden geçiyor mu?

    Referans tutarlıdır — çizgi her zaman mum *fitillerini* baz alır:
    support    → çizgi tüm Low'ların altında/değmeli kalmalı (Low ≥ çizgi)
    resistance → çizgi tüm High'ların üstünde/değmeli kalmalı (High ≤ çizgi)

    `tol_pct` kadar küçük fitil gürültüsüne izin verilir; bunun ötesinde mum
    gövdesini delerse çizgi geçersizdir.
    """
    for i in range(a, end + 1):
        lv = pa + slope * (i - a)
        if lv <= 0:
            return True
        tol = lv * tol_pct
        if kind == "support":
            if prices[i] < lv - tol:
                return True
        else:
            if prices[i] > lv + tol:
                return True
    return False


_MIN_TOUCHES = 3


def _angle_score(slope: float, x_scale: float, y_scale: float) -> float:
    """Aşırı dik çizgileri cezalandırır; yatay ile ~50° arası tam puan.

    x ekseni `x_scale` bar, y ekseni `y_scale` fiyat aralığına göre [0,1]
    karesine ölçeklenir; böylece açı grafik en-boy oranından bağımsız,
    anlamlı bir "diklik" ölçüsü olur. Yatay S/R çizgileri en az diyagonal
    kadar değerlidir, o yüzden yalnızca sürdürülemez dik eğim (>50°)
    puan kaybettirir; 75° ve üstü 0 alır.
    """
    if y_scale <= 0 or x_scale <= 0:
        return 0.5
    norm_slope = abs(slope) * x_scale / y_scale
    angle = math.degrees(math.atan(norm_slope))
    if angle <= 50.0:
        return 1.0
    if angle >= 75.0:
        return 0.0
    return (75.0 - angle) / 25.0


def _window_trend_sign(closes: np.ndarray) -> int:
    """Pencerenin genel trend yönü: +1 yukarı, -1 aşağı, 0 yatay.

    Kapanışlara doğrusal regresyon uygulanır; pencere boyunca toplam eğim
    ortalama fiyatın ±%5'inden küçükse yatay kabul edilir.
    """
    n = len(closes)
    if n < 10:
        return 0
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, closes.astype(float), 1)[0])
    mean = float(np.mean(closes))
    if mean <= 0:
        return 0
    total_change = slope * (n - 1) / mean
    if total_change > 0.05:
        return 1
    if total_change < -0.05:
        return -1
    return 0


def _spacing_balance(touch_idx: list[int]) -> float:
    """Temas noktaları arası zaman aralığının dengesi [0,1].

    Ardışık temaslar arasındaki boşlukların değişim katsayısı (CoV) düşükse
    (eşit aralıklı temas) puan 1'e, düzensizse 0'a yaklaşır.
    """
    if len(touch_idx) < 3:
        return 0.0
    gaps = np.diff(sorted(touch_idx)).astype(float)
    mean = gaps.mean()
    if mean <= 0:
        return 0.0
    cov = gaps.std() / mean
    return max(0.0, 1.0 - cov)


def _best_trendline(
    pivots: list[int],
    prices: np.ndarray,
    n_total: int,
    kind: str,
    min_span: int,
    x_scale: float,
    y_scale: float,
    tol_pct: float = 0.003,
    touch_tol: float = 0.006,
    min_touches: int = _MIN_TOUCHES,
    end_price: float = 0.0,
    max_end_dist: float = 1.0,
    trend_sign: int = 0,
    min_age: int = 0,
) -> tuple[int, float, float] | None:
    """Mumların içinden geçmeyen en iyi trend çizgisini seçer.

    Kabul kriterleri:
      • Hiçbir mum gövdesini delmez ([a, son bar] boyunca gövdeleri baz alır).
      • En az `min_touches` pivota değer.
      • Güncel fiyata yakınlık: çizginin bugünkü uzantısı `end_price`'tan
        `max_end_dist` (oran) uzaktaysa çizgi alakasızdır, elenir. Fiyattan
        kopuk "tarihi" çizgilerin (ör. yükseliş öncesi eski diplere oturan
        alçalan sözde-destek) çizilmesini engelleyen ana kuraldır.
    Skorlama (hepsi [0,1] aralığına normalize, ağırlıklı toplam):
      • temas sayısı (güç)        → çok temas = sağlam trend
      • fiyata yakınlık           → bugün işlem gören seviye tercih edilir
      • trend yönü uyumu          → yükselen pencerede yükselen destek,
                                    düşen pencerede alçalan direnç (klasik kural)
      • son temas güncelliği      → yakın geçmişte test edilmiş çizgi
      • açı sağduyusu             → yalnızca aşırı dik (>50°) cezalandırılır
      • temas aralığı dengesi     → eşit zaman aralıklı temas tercih edilir
      • span                      → uzun çizgi hafif bonus
    Döner: (anchor_index, anchor_price, slope) | None.

    Not: İhlal toleransı temas toleransıyla aynı tutulur — çizgiye `touch_tol`
    kadar yakın bir pivot "temas" sayılır, dolayısıyla aynı miktar "delme"
    olarak elenmez (üç dip nadiren tam doğrusaldır; ortadaki temas noktasının
    çizgiyi milimetrik aşması çizgiyi geçersiz kılmamalı).
    """
    best: tuple[int, float, float] | None = None
    best_score = -1.0
    end = n_total - 1
    pierce_tol = max(tol_pct, touch_tol)

    for ai in range(len(pivots)):
        a  = pivots[ai]
        # Uzun vadeli çizgi eski yapıya demirlemeli — kısa vadelinin
        # kopyası olmasın diye anchor en az `min_age` bar geride olmalı.
        if end - a < min_age:
            continue
        pa = float(prices[a])
        for bi in range(ai + 1, len(pivots)):
            b = pivots[bi]
            if b - a < min_span:
                continue
            pb    = float(prices[b])
            slope = (pb - pa) / (b - a)

            # Güncel fiyata yakınlık — uzantısı fiyattan kopuk çizgiler elenir
            lv_end = pa + slope * (end - a)
            if lv_end <= 0 or end_price <= 0:
                continue
            end_dist = abs(end_price - lv_end) / end_price
            if end_dist > max_end_dist:
                continue

            if _line_violates_candles(prices, a, pa, slope, end, kind, pierce_tol):
                continue

            # Çizgiye değen pivotlar (çok değen çizgi = daha güçlü trend)
            touch_idx = []
            for p in pivots:
                lv = pa + slope * (p - a)
                if lv > 0 and abs(float(prices[p]) - lv) <= lv * touch_tol:
                    touch_idx.append(p)
            touches = len(touch_idx)

            if touches < min_touches:
                continue

            span = b - a
            touch_norm   = min(touches, 6) / 6.0
            prox_norm    = 1.0 - end_dist / max_end_dist
            angle_norm   = _angle_score(slope, x_scale, y_scale)
            balance_norm = _spacing_balance(touch_idx)
            last_touch_norm = max(touch_idx) / max(1, n_total - 1)
            span_norm    = min(1.0, span / max(1.0, x_scale))
            # Trend yönü uyumu: yatay pencere veya yatay çizgi her zaman uyumlu
            if trend_sign == 0 or slope == 0:
                dir_match = 1.0
            else:
                dir_match = 1.0 if (slope > 0) == (trend_sign > 0) else 0.0

            score = (3.0 * touch_norm
                     + 2.2 * prox_norm
                     + 1.2 * angle_norm
                     + 1.0 * balance_norm
                     + 1.2 * last_touch_norm
                     + 0.5 * span_norm
                     + 0.8 * dir_match)
            if score > best_score:
                best_score = score
                best = (a, pa, slope)

    return best


def _horizontal_level(
    pivots: list[int],
    prices: np.ndarray,
    n_total: int,
    kind: str,
    end_price: float,
    max_end_dist: float,
    touch_tol: float,
    pierce_tol: float,
    min_touches: int = 2,
    min_age: int = 0,
) -> tuple[int, float, float] | None:
    """Geçerli diyagonal çizgi yoksa yatay destek/direnç seviyesi arar.

    Pivotları fiyat yakınlığına göre kümeler (seviye bir "bölge" olduğu için
    kümeleme toleransı temas toleransının 1.5 katıdır); en çok test edilmiş ve
    güncel fiyata en yakın kümenin ortalamasını yatay seviye olarak döndürür.
    Kabul: seviye desteğe göre fiyatın altında / dirence göre üstünde olmalı,
    fiyata `max_end_dist`'ten yakın olmalı ve ilk temasından bugüne hiçbir mum
    gövdesince delinmemiş olmalı (kırılmış seviye artık destek/direnç değildir).
    Döner: (first_touch_index, level, 0.0) | None — slope=0.
    """
    if end_price <= 0 or not pivots:
        return None
    end = n_total - 1
    cluster_tol = touch_tol * 1.5
    best: tuple[int, float, float] | None = None
    best_score = -1.0

    for p in pivots:
        seed = float(prices[p])
        if seed <= 0:
            continue
        # Rol tarafı: destek fiyatın altında, direnç üstünde kalmalı
        if kind == "support" and seed > end_price * (1 + touch_tol):
            continue
        if kind == "resistance" and seed < end_price * (1 - touch_tol):
            continue
        touch_idx = [q for q in pivots
                     if abs(float(prices[q]) - seed) <= seed * cluster_tol]
        if len(touch_idx) < min_touches:
            continue
        if end - min(touch_idx) < min_age:
            continue
        level = float(np.mean([float(prices[q]) for q in touch_idx]))
        dist = abs(end_price - level) / end_price
        if dist > max_end_dist:
            continue
        first = min(touch_idx)
        if _line_violates_candles(prices, first, level, 0.0, end, kind, pierce_tol):
            continue

        touch_norm = min(len(touch_idx), 6) / 6.0
        prox_norm  = 1.0 - dist / max_end_dist
        last_touch_norm = max(touch_idx) / max(1, n_total - 1)
        score = 3.0 * touch_norm + 2.2 * prox_norm + 1.2 * last_touch_norm
        if score > best_score:
            best_score = score
            best = (first, level, 0.0)

    return best


def _recent_pivot_level(
    pivots: list[int],
    prices: np.ndarray,
    n_total: int,
    kind: str,
    end_price: float,
    max_end_dist: float,
    touch_tol: float,
    pierce_tol: float,
) -> tuple[int, float, float] | None:
    """Kısa vade son çare: henüz kırılmamış en güncel swing dip/tepe seviyesi.

    Klasik "son dip = destek, son tepe = direnç" kuralı. Tek temaslı olduğu
    için zayıftır; yalnızca kısa vadede, diyagonal ve yatay küme bulunamadığında
    kullanılır. Seviye güncel fiyata `max_end_dist`'ten yakın olmalı ve pivot
    gününden bugüne gövdelerce delinmemiş (hâlâ geçerli) olmalıdır.
    """
    if end_price <= 0:
        return None
    end = n_total - 1
    for p in sorted(pivots, reverse=True):
        level = float(prices[p])
        if level <= 0:
            continue
        if kind == "support" and level > end_price * (1 + touch_tol):
            continue
        if kind == "resistance" and level < end_price * (1 - touch_tol):
            continue
        if abs(end_price - level) / end_price > max_end_dist:
            continue
        if _line_violates_candles(prices, p, level, 0.0, end, kind, pierce_tol):
            continue
        return (p, level, 0.0)
    return None


def detect_auto_trendlines(df: pd.DataFrame) -> dict:
    """Kısa ve uzun vadeli otomatik destek/direnç trend çizgilerini tespit eder.

    Tutarlı referans: çizgiler mum *gövdelerini* baz alır (fitil gürültüsü göz
    ardı edilir) — destek her barın gövde dibinin (min(Açılış,Kapanış)) altında,
    direnç gövde tepesinin (max(Açılış,Kapanış)) üstünde kalır. Pivot tespiti,
    ihlal kontrolü ve temas sayımı aynı gövde dizisini kullanır.

    Bir çizginin geçerli olması için yeterli pivota değmesi, hiçbir gövdeyi
    delmemesi ve bugünkü uzantısının güncel fiyata yakın olması gerekir
    (kısa vade ≤%7, uzun vade ≤%15) — fiyattan kopuk "tarihi" çizgiler böylece
    elenir. Seçimde pencerenin trend yönüne uyumlu eğim (yükselen pencerede
    yükselen destek), yakın geçmişte test edilmişlik ve dengeli temas aralığı
    tercih edilir. Geçerli diyagonal çizgi yoksa en çok test edilmiş, o günden
    beri kırılmamış yatay destek/direnç seviyesine düşülür; o da yoksa None.
    """
    if df is None or len(df) < 30:
        return {"short": {"support": None, "resistance": None},
                "long":  {"support": None, "resistance": None}}

    open_v  = df["Open"].astype(float).values
    close_v = df["Close"].astype(float).values
    body_hi = np.maximum(open_v, close_v)   # gövde tepesi → direnç referansı
    body_lo = np.minimum(open_v, close_v)   # gövde dibi   → destek referansı
    n_total = len(df)

    def date_at(abs_i: int) -> str:
        try:
            ts = df.index[abs_i]
            return str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
        except Exception:
            return ""

    def _project(anchor: int, p_anchor: float, slope: float) -> list[dict] | None:
        i_end = n_total - 1
        p_end = p_anchor + slope * (i_end - anchor)
        if p_end <= 0:
            return None
        return [
            {"t": date_at(anchor), "v": round(float(p_anchor), 4)},
            {"t": date_at(i_end),  "v": round(float(p_end),    4)},
        ]

    result = {"short": {"support": None, "resistance": None},
              "long":  {"support": None, "resistance": None}}

    # (etiket, lookback, pivot penceresi, min anchor mesafesi, gövde tol,
    #  temas tol, min temas, max fiyat uzaklığı)
    # İhlal toleransı = max(gövde, temas); küçük tutulur ki çizgi gövdeleri
    # görünür biçimde delmesin (≤%0.5-0.6).
    # Kısa vade: 2 temas yeterli (yeni oluşan trend; 2 nokta çizgiyi tanımlar).
    # Uzun vade: 3 temas zorunlu (teyit edilmiş, gürültüden arınmış trend).
    # Max fiyat uzaklığı: çizginin bugünkü uzantısı güncel fiyattan bu orandan
    # fazla uzaksa çizgi işlem kararına hizmet etmez, çizilmez.
    # Min yaş: uzun vadeli çizgi en az 60 bar geriden başlamalı ki kısa
    # vadelinin kopyası değil, büyük yapının çizgisi olsun.
    for label, lookback, window, min_span, tol_pct, touch_tol, min_touches, max_end_dist, min_age in [
        ("short", 60,  3, 5,  0.0030, 0.005, 2, 0.07, 0),
        ("long",  200, 6, 15, 0.0040, 0.006, 3, 0.15, 60),
    ]:
        n_use  = min(lookback, n_total)
        offset = n_total - n_use

        # Açı normalizasyonu için pencere ölçekleri: x = bar sayısı,
        # y = pencerenin gövde aralığı (her iki rol için ortak).
        x_scale = float(max(1, n_use - 1))
        win_hi  = float(np.max(body_hi[offset:]))
        win_lo  = float(np.min(body_lo[offset:]))
        y_scale = max(win_hi - win_lo, 1e-9)

        trough_rel = _find_pivot_lows(body_lo[-n_use:],  window=window)
        peak_rel   = _find_pivot_highs(body_hi[-n_use:], window=window)

        troughs = [i + offset for i in trough_rel]
        peaks   = [i + offset for i in peak_rel]

        end_price  = float(close_v[-1])
        trend_sign = _window_trend_sign(close_v[offset:])
        pierce_tol = max(tol_pct, touch_tol)

        sup = _best_trendline(troughs, body_lo, n_total, "support", min_span,
                              x_scale, y_scale, tol_pct, touch_tol, min_touches,
                              end_price=end_price, max_end_dist=max_end_dist,
                              trend_sign=trend_sign, min_age=min_age)
        if sup is None:
            sup = _horizontal_level(troughs, body_lo, n_total, "support",
                                    end_price, max_end_dist, touch_tol,
                                    pierce_tol, min_age=min_age)
        if sup is None and label == "short":
            sup = _recent_pivot_level(troughs, body_lo, n_total, "support",
                                      end_price, max_end_dist, touch_tol, pierce_tol)
        if sup is not None:
            result[label]["support"] = _project(*sup)

        res = _best_trendline(peaks, body_hi, n_total, "resistance", min_span,
                              x_scale, y_scale, tol_pct, touch_tol, min_touches,
                              end_price=end_price, max_end_dist=max_end_dist,
                              trend_sign=trend_sign, min_age=min_age)
        if res is None:
            res = _horizontal_level(peaks, body_hi, n_total, "resistance",
                                    end_price, max_end_dist, touch_tol,
                                    pierce_tol, min_age=min_age)
        if res is None and label == "short":
            res = _recent_pivot_level(peaks, body_hi, n_total, "resistance",
                                      end_price, max_end_dist, touch_tol, pierce_tol)
        if res is not None:
            result[label]["resistance"] = _project(*res)

    return result


# ── formasyon baskınlık analizi ──────────────────────────────────────────────

_CONF_NORM   = {"yüksek": 1.0, "orta": 0.6, "düşük": 0.3}
_DIR_TR      = {"bullish": "yükseliş", "bearish": "düşüş", "neutral": "nötr"}

# Baskınlık ağırlıkları — her biri [0,1] normalize, toplam = 9.0
_W_CONFIRMED = 3.0   # boyun/sınır zaten kırılmış mı (en belirleyici faktör)
_W_PROXIMITY = 2.5   # fiyat tetikleyici seviyeye ne kadar yakın (kırılmadıysa)
_W_QUALITY   = 2.0   # formasyon kalitesi (simetri / R² uyumu → confidence)
_W_VOLUME    = 0.8   # hacim onayı (mevcutsa)
_W_RECENCY   = 0.7   # formasyonun tazeliği
_PROXIMITY_MAX_DIST = 0.10  # bu orandan uzaksa yakınlık puanı 0'a iner
_RECENCY_MAX_AGE    = 25    # detect_patterns'daki age<=25 filtresiyle tutarlı


def _pattern_dominance_score(p: Dict[str, Any]) -> float:
    """Bir formasyonun ne kadar baskın/olası olduğunu sayısallaştırır.

    Beş faktörün ağırlıklı toplamı:
      1. Teyit  — boyun/sınır çizgisi zaten kırılmış mı (en ağırlıklı; kırılmış
         bir formasyon her zaman kırılmamış olandan öncelikli sayılır).
      2. Yakınlık — kırılmadıysa, fiyat tetikleyici seviyeye (boyun çizgisi,
         üçgen/kama sınırı, bayrak aralığı) ne kadar yakın. Bu, önceden hiç
         hesaba katılmayan ama en çok gözden kaçan faktördü: iki formasyon
         aynı güven/güç etiketine sahip olsa bile kırılıma %1 kalan biri,
         %8 uzaktaki formasyondan çok daha imminent'tir.
      3. Kalite — omuz/tepe/dip simetrisi veya üçgen-kama regresyon uyumu
         (confidence alanına yansımış durumda).
      4. Hacim onayı — mevcutsa küçük bir bonus.
      5. Tazelik — formasyonun son referans noktası ne kadar yeni.
    """
    confirmed = bool(p.get("confirmed", False))
    confirmed_norm = 1.0 if confirmed else 0.0

    dist = p.get("trigger_distance_pct")
    if confirmed or dist is None:
        proximity_norm = 1.0
    else:
        proximity_norm = max(0.0, 1.0 - min(float(dist), _PROXIMITY_MAX_DIST) / _PROXIMITY_MAX_DIST)

    quality_norm = _CONF_NORM.get(p.get("confidence", "orta"), 0.6)
    volume_norm  = 1.0 if p.get("volume_confirmed") else 0.0

    age = p.get("pattern_age", 0) or 0
    recency_norm = max(0.0, 1.0 - min(age, _RECENCY_MAX_AGE) / _RECENCY_MAX_AGE)

    score = (
        _W_CONFIRMED * confirmed_norm
        + _W_PROXIMITY * proximity_norm
        + _W_QUALITY * quality_norm
        + _W_VOLUME * volume_norm
        + _W_RECENCY * recency_norm
    )
    return round(score, 3)


def _rank_patterns(patterns: List[Dict[str, Any]]) -> None:
    """Formasyonları baskınlık skoruna göre yerinde sıralar ve işaretler."""
    if not patterns:
        return
    for p in patterns:
        p["dominance_score"] = _pattern_dominance_score(p)
    patterns.sort(key=lambda x: x.get("dominance_score", 0.0), reverse=True)
    for i, p in enumerate(patterns):
        p["dominant"] = (i == 0)


def summarize_patterns(patterns: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Birden fazla formasyon varsa hangisinin baskın/olası olduğunu analiz eder.

    Aynı yöndeki formasyonların birbirini güçlendirdiğini, ters yöndekilerin
    çeliştiğini açıklayan bir özet üretir."""
    if not patterns:
        return None

    lead = patterns[0]
    lead_dir = _DIR_TR.get(lead.get("direction", "neutral"), "nötr")
    lead_conf = lead.get("confidence", "orta")

    if len(patterns) == 1:
        return {
            "leader":   lead.get("type"),
            "conflict": False,
            "summary": (
                f"Tek aktif formasyon: {lead.get('name')} "
                f"({lead_conf} güven, {lead_dir} yönlü). {lead.get('signal', '')}"
            ),
        }

    second = patterns[1]
    second_dir = _DIR_TR.get(second.get("direction", "neutral"), "nötr")
    diff   = lead.get("dominance_score", 0.0) - second.get("dominance_score", 0.0)
    margin = "belirgin biçimde" if diff >= 1.5 else "az farkla"
    same_dir = lead.get("direction") == second.get("direction")

    if same_dir:
        summary = (
            f"{lead.get('name')} baskın formasyon ({lead_conf} güven) ve "
            f"{second.get('name')} ile aynı {lead_dir} yönünde — iki sinyal "
            f"birbirini güçlendiriyor, senaryo {margin} daha olası. "
            f"{lead.get('signal', '')}"
        )
        conflict = False
    else:
        summary = (
            f"Çelişen sinyaller: {lead.get('name')} ({lead_dir}) {margin} daha "
            f"baskın ({lead_conf} güven), ancak {second.get('name')} "
            f"({second_dir}) ters yönde. Net kırılım teyidi gelene kadar "
            f"temkinli olun — baskın senaryo: {lead.get('signal', '')}"
        )
        conflict = True

    return {"leader": lead.get("type"), "conflict": conflict, "summary": summary}
