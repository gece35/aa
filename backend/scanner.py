"""Market tarama orkestrasyon katmani."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from .cache import scan_cache, symbol_cache
from .data_fetcher import download_ohlcv
from .market_hours import cache_ttl
from .scoring import compute_regime_ok, score_symbol
from .sectors import get_sector
from .tickers import MARKETS, get_index_symbol, get_tickers

logger = logging.getLogger(__name__)

SCAN_CACHE_TTL = 600  # seans acikken 10 dk; kapaliyken bir sonraki acilisa kadar (bkz. cache_ttl)

# Puanlama saf pandas/numpy (GIL altinda): 4'ten fazla thread hiz kazandirmaz,
# yalnizca ayni surecteki diger isteklerle CPU icin yarisir.
SCORE_WORKERS = max(1, int(os.environ.get("SCORE_WORKERS", "4")))

# Pazar basina tek "soguk" tarama: ayni anda gelen istekler ayni veriyi
# tekrar tekrar indirmesin (tek surec, cok thread).
_scan_locks: Dict[str, threading.Lock] = {m: threading.Lock() for m in MARKETS}


def _ttl(market: str) -> int:
    return cache_ttl(market, SCAN_CACHE_TTL)


def _result_dict(res) -> dict:
    """Tarama satırı: skor sonucu + sektör anahtarı (arayüzdeki sektör filtresi için)."""
    d = res.to_dict()
    d["sector"] = get_sector(d["symbol"])
    return d


def _fetch_index_df(market: str):
    """Market endeksini (goreceli guc icin) indirir; basarisizsa None."""
    index_symbol = get_index_symbol(market)
    if not index_symbol:
        return None
    try:
        idx_data = download_ohlcv([index_symbol], period="300d", interval="1d")
        return idx_data.get(index_symbol)
    except Exception:
        logger.warning("Endeks verisi alinamadi: %s", index_symbol)
        return None


def get_index_df(market: str):
    """Market endeksini cache'den (yoksa indirip) doner. Tekil hisse detayinda da kullanilir."""
    cached = symbol_cache.get(f"index:{market}")
    if cached is not None:
        return cached
    idx = _fetch_index_df(market)
    if idx is not None:
        symbol_cache.set(f"index:{market}", idx, ttl=_ttl(market))
    return idx


INDEX_LABELS = {"bist": "BIST 100", "us": "S&P 500"}


def build_index_summary(market: str) -> dict | None:
    """Tarama sekmesindeki endeks mini-grafiği için özet veri (BIST 100 / S&P 500).

    get_index_df ile aynı cache'i kullanır — tarama zaten indirdiği için ek
    maliyeti yoktur. regime_ok, compute_entry_signal rozetinin dayandığı aynı
    piyasa rejimi kriteridir; kullanıcı rozetin neden görünmediğini buradan
    (rejim olumsuzsa) anlayabilir.
    """
    market = (market or "").lower()
    if market not in MARKETS:
        return None
    index_df = get_index_df(market)
    if index_df is None or index_df.empty:
        return None

    close = index_df["Close"].astype(float).dropna()
    if close.empty:
        return None

    last = float(close.iloc[-1])

    def _chg(n: int) -> float:
        if len(close) <= n:
            return 0.0
        prev = float(close.iloc[-(n + 1)])
        return (last - prev) / prev * 100.0 if prev else 0.0

    return {
        "market": market,
        "symbol": get_index_symbol(market),
        "label": INDEX_LABELS.get(market, market.upper()),
        "price": round(last, 2),
        "change_pct": round(_chg(1), 2),
        "change_week_pct": round(_chg(5), 2),
        "change_month_pct": round(_chg(21), 2),
        "sparkline": [round(float(v), 2) for v in close.tail(90).tolist()],
        "regime_ok": compute_regime_ok(index_df),
        "generated_at": int(time.time()),
    }


def _compute_scores(data: Dict, index_df=None, market: str = "bist", regime_ok: bool = True) -> List[dict]:
    results: List[dict] = []
    if not data:
        return results

    with ThreadPoolExecutor(max_workers=min(SCORE_WORKERS, len(data))) as pool:
        futures = {
            pool.submit(score_symbol, symbol, df, index_df, market, regime_ok): symbol
            for symbol, df in data.items()
        }
        for fut in as_completed(futures):
            symbol = futures[fut]
            try:
                res = fut.result()
            except Exception:
                logger.exception("%s puanlama hatasi", symbol)
                continue
            if res is not None:
                results.append(_result_dict(res))

    results.sort(key=lambda r: (r["score"], r["change_pct"]), reverse=True)
    return results


def _cached_scan(cache_key: str, max_tickers: int = None):
    cached = scan_cache.get(cache_key)
    if cached is None:
        return None
    cached = dict(cached)
    cached["cached"] = True
    cached["cache_age_remaining"] = scan_cache.age(cache_key)
    if max_tickers is not None:
        cached["results"] = cached.get("results", [])[:max_tickers]
        cached["total"] = min(cached.get("total", 0), max_tickers)
    return cached


def scan_market(market: str, force: bool = False, max_tickers: int = None) -> dict:
    market = (market or "").lower()
    if market not in MARKETS:
        raise ValueError(f"Desteklenmeyen pazar: {market}")

    cache_key = f"scan:{market}"
    if not force:
        cached = _cached_scan(cache_key, max_tickers)
        if cached is not None:
            return cached

    if max_tickers is not None:
        # Plan limitiyle kirpilmis tarama: tum pazar cache'ini kirletmemek icin
        # sembol bazli cache'i kullanan chunk yolundan gecer (her cagrida
        # yeniden indirme yapmaz).
        return _limited_scan(market, max_tickers, force)

    with _scan_locks[market]:
        # Kilidi beklerken baska bir istek taramayi bitirmis olabilir.
        if not force:
            cached = _cached_scan(cache_key, max_tickers)
            if cached is not None:
                return cached

        info = MARKETS[market]
        tickers = get_tickers(market)

        started = time.time()
        data = download_ohlcv(tickers, period="300d", interval="1d")
        index_df = get_index_df(market)
        regime_ok = compute_regime_ok(index_df)
        download_secs = time.time() - started

        compute_started = time.time()
        results = _compute_scores(data, index_df, market, regime_ok)
        compute_secs = time.time() - compute_started

        payload = {
            "market": market,
            "label": info["label"],
            "currency": info["currency"],
            "total": len(tickers),
            "scored": len(results),
            "results": results,
            "regime_ok": regime_ok,
            "generated_at": int(time.time()),
            "timings": {
                "download_secs": round(download_secs, 2),
                "compute_secs": round(compute_secs, 2),
            },
            "cached": False,
        }

        ttl = _ttl(market)
        scan_cache.set(cache_key, payload, ttl=ttl)
        # full scan yapildi, tum sonuclari symbol_cache'e de yaz
        for item in results:
            symbol_cache.set(f"sym:{item['symbol']}", item, ttl=ttl)
        out = dict(payload)
        out["cache_age_remaining"] = scan_cache.age(cache_key)
        return out


def _limited_scan(market: str, max_tickers: int, force: bool) -> dict:
    """Ilk `max_tickers` hisseyi tarar (misafir plani). Sonuc `scan:{market}`
    anahtarina YAZILMAZ: aksi halde sonraki uye ayni anahtardan eksik liste alirdi."""
    chunk = scan_market_chunk(
        market=market, offset=0, limit=max_tickers, force=force, max_tickers=max_tickers,
    )
    results = sorted(
        chunk["results"], key=lambda r: (r["score"], r["change_pct"]), reverse=True,
    )
    regime_ok = chunk.get("regime_ok")
    if regime_ok is None:
        regime_ok = compute_regime_ok(get_index_df(market))
    return {
        "market": market,
        "label": chunk["label"],
        "currency": chunk["currency"],
        "total": chunk["total"],
        "scored": len(results),
        "results": results,
        "regime_ok": regime_ok,
        "generated_at": chunk["generated_at"],
        "timings": chunk["timings"],
        "cached": chunk["cached"],
        "cache_age_remaining": chunk["cache_ttl"],
    }


def _sort_tickers(tickers: List[str], sort: str) -> List[str]:
    """symbol_cache'deki verilerle tickers listesini siralar; cache'siz olanlar sona bırakılır."""
    scored, unscored = [], []
    for sym in tickers:
        c = symbol_cache.get(f"sym:{sym}")
        if c is not None:
            scored.append((sym, c))
        else:
            unscored.append(sym)

    if not scored:
        return tickers

    if sort == "change_desc":
        scored.sort(key=lambda x: x[1].get("change_pct", 0), reverse=True)
    elif sort == "change_asc":
        scored.sort(key=lambda x: x[1].get("change_pct", 0))
    elif sort == "week":
        scored.sort(key=lambda x: x[1].get("change_week_pct", 0), reverse=True)
    elif sort == "month":
        scored.sort(key=lambda x: x[1].get("change_month_pct", 0), reverse=True)
    elif sort == "symbol":
        scored.sort(key=lambda x: x[0])
    else:  # default: score
        scored.sort(key=lambda x: (x[1].get("score", 0), x[1].get("change_pct", 0)), reverse=True)

    return [sym for sym, _ in scored] + unscored


def scan_market_chunk(market: str, offset: int, limit: int, force: bool = False, sort: str = "score", max_tickers: int = None) -> dict:
    """Sadece `tickers[offset:offset+limit]` dilimini tarar, kalanini lazy birakir.

    - Per-sembol cache'den faydalanir, tekrar istenen hisseyi yeniden indirmez.
    - sort parametresi ile cache'deki skorlara gore ticker sirasi yeniden duzenlenir.
    - max_tickers: plan limiti; None ise sinir yok.
    """
    market = (market or "").lower()
    if market not in MARKETS:
        raise ValueError(f"Desteklenmeyen pazar: {market}")

    info = MARKETS[market]
    tickers = get_tickers(market)
    full_total = len(tickers)
    if max_tickers is not None:
        tickers = tickers[:max_tickers]
    total = len(tickers)

    if sort == "symbol":
        tickers = sorted(tickers)
    elif not force:
        tickers = _sort_tickers(tickers, sort)

    offset = max(0, int(offset))
    limit = max(1, int(limit))
    chunk_symbols = tickers[offset : offset + limit]

    cached_map: Dict[str, dict] = {}

    def _split_cached(symbols: List[str]) -> List[str]:
        """Cache'te olanlari cached_map'e yazar, eksik kalanlari doner."""
        absent: List[str] = []
        for sym in symbols:
            c = symbol_cache.get(f"sym:{sym}")
            if c is not None:
                cached_map[sym] = c
            else:
                absent.append(sym)
        return absent

    missing: List[str] = list(chunk_symbols) if force else _split_cached(chunk_symbols)
    fetched = len(missing)

    download_secs = 0.0
    compute_secs = 0.0
    regime_ok = None

    if missing:
        with _scan_locks[market]:
            # Kilidi beklerken baska bir istek ayni sembolleri doldurmus olabilir.
            if not force:
                missing = _split_cached(missing)
                fetched = len(missing)
            if missing:
                started = time.time()
                data = download_ohlcv(missing, period="300d", interval="1d")
                # Endeksi (goreceli guc icin) market basina cache'le, her chunk'ta yeniden indirme
                index_df = get_index_df(market)
                regime_ok = compute_regime_ok(index_df)
                download_secs = time.time() - started

                compute_started = time.time()
                if data:
                    ttl = _ttl(market)
                    with ThreadPoolExecutor(max_workers=min(SCORE_WORKERS, len(data))) as pool:
                        futures = {
                            pool.submit(score_symbol, symbol, df, index_df, market, regime_ok): symbol
                            for symbol, df in data.items()
                        }
                        for fut in as_completed(futures):
                            symbol = futures[fut]
                            try:
                                res = fut.result()
                            except Exception:
                                logger.exception("%s puanlama hatasi", symbol)
                                continue
                            if res is None:
                                continue
                            d = _result_dict(res)
                            cached_map[symbol] = d
                            symbol_cache.set(f"sym:{symbol}", d, ttl=ttl)
                compute_secs = time.time() - compute_started

    # input sirasina gore sirala
    results = [cached_map[s] for s in chunk_symbols if s in cached_map]

    return {
        "market": market,
        "label": info["label"],
        "currency": info["currency"],
        "total": total,
        "full_total": full_total,
        "offset": offset,
        "limit": limit,
        "scored": len(results),
        "results": results,
        "has_more": (offset + len(chunk_symbols)) < total,
        "next_offset": offset + len(chunk_symbols),
        "regime_ok": regime_ok,
        "generated_at": int(time.time()),
        "cache_ttl": _ttl(market),
        "timings": {
            "download_secs": round(download_secs, 2),
            "compute_secs": round(compute_secs, 2),
            "cached_hits": len(chunk_symbols) - fetched,
            "fetched": fetched,
        },
        "cached": fetched == 0,
    }
