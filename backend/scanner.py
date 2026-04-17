"""Market tarama orkestrasyon katmani."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from .cache import scan_cache
from .data_fetcher import download_ohlcv
from .scoring import score_symbol
from .tickers import MARKETS, get_tickers

logger = logging.getLogger(__name__)

SCAN_CACHE_TTL = 600  # 10 dakika (cache icinde zaten tanimli)


def _compute_scores(data: Dict) -> List[dict]:
    results: List[dict] = []
    if not data:
        return results

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(score_symbol, symbol, df): symbol for symbol, df in data.items()
        }
        for fut in as_completed(futures):
            symbol = futures[fut]
            try:
                res = fut.result()
            except Exception:
                logger.exception("%s puanlama hatasi", symbol)
                continue
            if res is not None:
                results.append(res.to_dict())

    results.sort(key=lambda r: (r["score"], r["change_pct"]), reverse=True)
    return results


def scan_market(market: str, force: bool = False) -> dict:
    market = (market or "").lower()
    if market not in MARKETS:
        raise ValueError(f"Desteklenmeyen pazar: {market}")

    cache_key = f"scan:{market}"
    if not force:
        cached = scan_cache.get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            cached["cache_age_remaining"] = scan_cache.age(cache_key)
            return cached

    info = MARKETS[market]
    tickers = get_tickers(market)

    started = time.time()
    data = download_ohlcv(tickers, period="200d", interval="1d")
    download_secs = time.time() - started

    compute_started = time.time()
    results = _compute_scores(data)
    compute_secs = time.time() - compute_started

    payload = {
        "market": market,
        "label": info["label"],
        "currency": info["currency"],
        "total": len(tickers),
        "scored": len(results),
        "results": results,
        "generated_at": int(time.time()),
        "timings": {
            "download_secs": round(download_secs, 2),
            "compute_secs": round(compute_secs, 2),
        },
        "cached": False,
    }

    scan_cache.set(cache_key, payload)
    out = dict(payload)
    out["cache_age_remaining"] = scan_cache.age(cache_key)
    return out
