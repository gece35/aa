"""Market tarama orkestrasyon katmani."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from .cache import scan_cache, symbol_cache
from .data_fetcher import download_ohlcv
from .scoring import compute_regime_ok, score_symbol
from .tickers import MARKETS, get_index_symbol, get_tickers

logger = logging.getLogger(__name__)

SCAN_CACHE_TTL = 600  # 10 dakika (cache icinde zaten tanimli)


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
        symbol_cache.set(f"index:{market}", idx)
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

    with ThreadPoolExecutor(max_workers=16) as pool:
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
                results.append(res.to_dict())

    results.sort(key=lambda r: (r["score"], r["change_pct"]), reverse=True)
    return results


def scan_market(market: str, force: bool = False, max_tickers: int = None) -> dict:
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
            if max_tickers is not None:
                cached["results"] = cached.get("results", [])[:max_tickers]
                cached["total"] = min(cached.get("total", 0), max_tickers)
            return cached

    info = MARKETS[market]
    tickers = get_tickers(market)
    if max_tickers is not None:
        tickers = tickers[:max_tickers]

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

    scan_cache.set(cache_key, payload)
    # full scan yapildi, tum sonuclari symbol_cache'e de yaz
    for item in results:
        symbol_cache.set(f"sym:{item['symbol']}", item)
    out = dict(payload)
    out["cache_age_remaining"] = scan_cache.age(cache_key)
    return out


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
    missing: List[str] = []
    if not force:
        for sym in chunk_symbols:
            c = symbol_cache.get(f"sym:{sym}")
            if c is not None:
                cached_map[sym] = c
            else:
                missing.append(sym)
    else:
        missing = list(chunk_symbols)

    download_secs = 0.0
    compute_secs = 0.0
    regime_ok = None

    if missing:
        started = time.time()
        data = download_ohlcv(missing, period="300d", interval="1d")
        # Endeksi (goreceli guc icin) market basina cache'le, her chunk'ta yeniden indirme
        index_df = get_index_df(market)
        regime_ok = compute_regime_ok(index_df)
        download_secs = time.time() - started

        compute_started = time.time()
        if data:
            with ThreadPoolExecutor(max_workers=min(16, len(data))) as pool:
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
                    d = res.to_dict()
                    cached_map[symbol] = d
                    symbol_cache.set(f"sym:{symbol}", d)
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
        "timings": {
            "download_secs": round(download_secs, 2),
            "compute_secs": round(compute_secs, 2),
            "cached_hits": len(chunk_symbols) - len(missing),
            "fetched": len(missing),
        },
        "cached": len(missing) == 0,
    }
