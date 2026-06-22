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
            neckline = round(valley, 4)
            # Sinyal tükendi mi? Fiyat neckline'dan >%7 aşağıdaysa formasyon geçersiz.
            if float(close_v[-1]) >= neckline * 0.93:
                patterns.append({
                    "type": "double_top",
                    "name": "İkili Tepe",
                    "emoji": "🔴",
                    "description": (
                        f"Fiyat iki kez ~{round(max(v1,v2),2)} direnç seviyesini test etti ve geri döndü. "
                        f"Tepeler arası benzerlik: %{round(sim*100,1)}. "
                        f"Boyun çizgisi: {neckline}."
                    ),
                    "signal": (
                        "Düşüş sinyali — boyun çizgisi kırılırsa satış hızlanabilir."
                        + (" Hacim T2'de azalmış, sinyal güvenilir." if vol_ok else "")
                    ),
                    "direction": "bearish",
                    "strength": strength,
                    "confidence": confidence,
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
            neckline  = round(peak_m, 4)
            # Sinyal tükendi mi? Fiyat neckline'dan >%7 yukarıdaysa formasyon geçersiz.
            if float(close_v[-1]) <= neckline * 1.07:
                patterns.append({
                    "type": "double_bottom",
                    "name": "İkili Dip",
                    "emoji": "🟢",
                    "description": (
                        f"Fiyat iki kez ~{round(min(v1,v2),2)} destek seviyesinde dip yaptı. "
                        f"Dipler arası benzerlik: %{round(sim*100,1)}. "
                        f"Boyun çizgisi (direnç): {neckline}."
                    ),
                    "signal": (
                        "Yükseliş sinyali — boyun çizgisi kırılırsa alım hızlanabilir."
                        + (" Hacim D2'de azalmış, dip oluşumu güvenilir." if vol_ok else "")
                    ),
                    "direction": "bullish",
                    "strength": strength,
                    "confidence": confidence,
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
            broken = float(close_v[-1]) < neckline * 0.99

            confidence = (
                "yüksek" if (shoulders_sim and broken) else
                "orta"   if shoulders_sim else
                "düşük"
            )
            strength = "çok güçlü" if confidence == "yüksek" else "güçlü"
            # Sinyal tükendi mi? Boyun kırılmış VE fiyat >%7 aşağıdaysa formasyon geçersiz.
            if not (broken and float(close_v[-1]) < neckline * 0.93):
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
            broken       = float(close_v[-1]) > neckline * 1.01

            confidence = (
                "yüksek" if (shoulders_sim and broken) else
                "orta"   if shoulders_sim else
                "düşük"
            )
            strength = "çok güçlü" if confidence == "yüksek" else "güçlü"
            # Sinyal tükendi mi? Boyun kırılmış VE fiyat >%7 yukarıdaysa formasyon geçersiz.
            if not (broken and float(close_v[-1]) > neckline * 1.07):
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

        candidate: dict | None = None

        if h_fall and l_rise:
            candidate = {
                "type": "symmetric_triangle", "name": "Simetrik Üçgen", "emoji": "🟡",
                "description": f"Son {w} barda hem tepe hem dip birbirine yaklaşıyor — fiyat sıkışıyor. Regresyon uyumu: {round(h_r2,2)}/{round(l_r2,2)}.",
                "signal": "Kırılım yakın. Hacim eşliğinde güçlü yön hareketi bekleniyor.",
                "direction": "neutral", "strength": "orta", "confidence": confidence,
                "markers": [], "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
            }
        elif h_fall and l_flat:
            candidate = {
                "type": "descending_triangle", "name": "Düşen Üçgen", "emoji": "🔴",
                "description": f"Son {w} barda direnç çizgisi düşerken destek yatay. Sıkışma mevcut.",
                "signal": "Genellikle aşağı kırılımla sonuçlanır. Destek kırılırsa satış artar.",
                "direction": "bearish", "strength": "orta", "confidence": confidence,
                "markers": [], "trendlines": [tl(h_slope, h_int), [{"t": t_start, "v": round(l_mean,4)}, {"t": t_end, "v": round(l_mean,4)}]],
            }
        elif l_rise and h_flat:
            candidate = {
                "type": "ascending_triangle", "name": "Yükselen Üçgen", "emoji": "🟢",
                "description": f"Son {w} barda destek çizgisi yükselirken direnç yatay. Yükseliş baskısı artıyor.",
                "signal": "Genellikle yukarı kırılımla sonuçlanır. Direnci geçerse güçlü alım gelir.",
                "direction": "bullish", "strength": "orta", "confidence": confidence,
                "markers": [], "trendlines": [[{"t": t_start, "v": round(h_mean,4)}, {"t": t_end, "v": round(h_mean,4)}], tl(l_slope, l_int)],
            }
        elif h_rise and l_rise and h_spct > l_spct + thr:
            candidate = {
                "type": "rising_wedge", "name": "Yükselen Kama", "emoji": "🔴",
                "description": f"Son {w} barda her iki çizgi yükseliyor ancak aralık daralıyor. Yükseliş ivmesi zayıflıyor.",
                "signal": "Düşüş öncesi klasik formasyon. Aşağı kırılım ihtimali yüksek.",
                "direction": "bearish", "strength": "orta", "confidence": confidence,
                "markers": [], "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
            }
        elif h_fall and l_fall and l_spct < h_spct - thr:
            candidate = {
                "type": "falling_wedge", "name": "Düşen Kama", "emoji": "🟢",
                "description": f"Son {w} barda her iki çizgi düşüyor ancak aralık daralıyor. Düşüş ivmesi zayıflıyor.",
                "signal": "Yükseliş öncesi klasik formasyon. Yukarı kırılım beklentisi güçlü.",
                "direction": "bullish", "strength": "orta", "confidence": confidence,
                "markers": [], "trendlines": [tl(h_slope, h_int), tl(l_slope, l_int)],
            }

        # Geçerlilik: fiyat hâlâ formasyon sınırları içinde mi?
        # Kırılım zaten gerçekleştiyse formasyon geçersizdir.
        if candidate is not None:
            upper_at_end = h_int + h_slope * (w - 1)
            lower_at_end = l_int + l_slope * (w - 1)
            cur = float(close_v[-1])
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
                    patterns.append({
                        "type": "bull_flag", "name": "Boğa Bayrağı", "emoji": "🟢",
                        "description": (
                            f"+%{pole_pct:.1f} güçlü yükseliş (sap) sonrası "
                            f"%{flag_rng:.1f} dar konsolidasyon (bayrak)."
                            + (" Bayrak hafif aşağı eğimli — klasik form." if is_counter else "")
                        ),
                        "signal": "Yukarı kırılım beklentisi yüksek. Hacim artışıyla kırılım teyitlenir.",
                        "direction": "bullish", "strength": "güçlü", "confidence": confidence,
                        "markers": [], "trendlines": [],
                    })

                elif pole_pct < -7 and tight_consol:
                    is_counter = flag_slope_pct > 0
                    confidence = "yüksek" if (pole_pct < -12 and is_counter and flag_rng < 4) else \
                                 "orta"   if (pole_pct < -9  and flag_rng < 5) else "düşük"
                    patterns.append({
                        "type": "bear_flag", "name": "Ayı Bayrağı", "emoji": "🔴",
                        "description": (
                            f"-%{abs(pole_pct):.1f} güçlü düşüş (sap) sonrası "
                            f"%{flag_rng:.1f} dar konsolidasyon (bayrak)."
                            + (" Bayrak hafif yukarı eğimli — klasik form." if is_counter else "")
                        ),
                        "signal": "Aşağı kırılım riski yüksek. Hacim artışıyla kırılım teyitlenir.",
                        "direction": "bearish", "strength": "güçlü", "confidence": confidence,
                        "markers": [], "trendlines": [],
                    })

    return patterns


# ── otomatik trend çizgileri ─────────────────────────────────────────────────

def detect_auto_trendlines(df: pd.DataFrame) -> dict:
    """Kısa ve uzun vadeli otomatik destek/direnç trend çizgilerini tespit eder."""
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
            {"t": date_at(i1),    "v": round(float(p1), 4)},
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

        peaks_rel,   _ = _find_pivots(high_v[-n_use:], window=window)
        _,  troughs_rel = _find_pivots(low_v[-n_use:],  window=window)

        peaks_abs   = _pivots_separated([i + offset for i in peaks_rel],   min_gap)
        troughs_abs = _pivots_separated([i + offset for i in troughs_rel], min_gap)

        if len(troughs_abs) >= 2:
            i1, i2 = troughs_abs[-2], troughs_abs[-1]
            result[label]["support"] = _fit_line(i1, low_v[i1], i2, low_v[i2])

        if len(peaks_abs) >= 2:
            i1, i2 = peaks_abs[-2], peaks_abs[-1]
            result[label]["resistance"] = _fit_line(i1, high_v[i1], i2, high_v[i2])

    return result
