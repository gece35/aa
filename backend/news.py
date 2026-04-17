"""RSS feed tabanli piyasa haber toplama modulu."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import feedparser

from .cache import news_cache

logger = logging.getLogger(__name__)

FEEDS = {
    "bist": [
        ("Bloomberg HT", "https://www.bloomberght.com/rss"),
        ("Dunya Gazetesi", "https://www.dunya.com/rss?dunya"),
        ("Mynet Finans", "https://www.mynet.com/finans/rss.xml"),
    ],
    "us": [
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("CNBC Markets", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ],
}


def _parse_feed(source: str, url: str, limit: int = 10) -> List[dict]:
    try:
        feed = feedparser.parse(url)
    except Exception as exc:  # pragma: no cover
        logger.warning("Feed cekilemedi %s: %s", url, exc)
        return []

    items: List[dict] = []
    for entry in feed.entries[:limit]:
        published = entry.get("published") or entry.get("updated") or ""
        ts = None
        for key in ("published_parsed", "updated_parsed"):
            struct = entry.get(key)
            if struct:
                try:
                    ts = int(time.mktime(struct))
                    break
                except Exception:
                    pass
        items.append({
            "source": source,
            "title": entry.get("title", "").strip(),
            "link": entry.get("link", ""),
            "summary": (entry.get("summary", "") or "").strip()[:280],
            "published": published,
            "ts": ts or 0,
        })
    return items


def fetch_news(market: str, force: bool = False) -> dict:
    market = (market or "").lower()
    feeds = FEEDS.get(market, [])
    if not feeds:
        return {"market": market, "items": [], "generated_at": int(time.time())}

    cache_key = f"news:{market}"
    if not force:
        cached = news_cache.get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return cached

    results: List[dict] = []
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = {pool.submit(_parse_feed, src, url): src for src, url in feeds}
        for fut in as_completed(futures):
            try:
                results.extend(fut.result())
            except Exception:
                logger.exception("RSS parse hatasi")

    seen = set()
    unique: List[dict] = []
    for item in results:
        key = item.get("link") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    unique = unique[:40]

    payload = {
        "market": market,
        "count": len(unique),
        "items": unique,
        "generated_at": int(time.time()),
        "cached": False,
    }
    news_cache.set(cache_key, payload)
    return payload
