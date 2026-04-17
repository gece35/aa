"""RSS feed tabanli piyasa haber toplama modulu.

feedparser yerine stdlib xml.etree.ElementTree + requests kullanilir.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import requests

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

NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NebulaScannerBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _parse_rss(source: str, url: str, limit: int = 12) -> List[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        logger.warning("Feed alinamadi %s: %s", url, exc)
        return []

    # Atom feed mi RSS feed mi?
    tag = root.tag
    items: List[dict] = []

    if "feed" in tag.lower():
        # Atom
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        for entry in entries[:limit]:
            title = _text(entry, ["{http://www.w3.org/2005/Atom}title"])
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = _text(entry, [
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
            ])
            published = _text(entry, [
                "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated",
            ])
            items.append(_make_item(source, title, link, summary, published))
    else:
        # RSS 2.0
        channel = root.find("channel")
        if channel is None:
            channel = root
        for item in channel.findall("item")[:limit]:
            title = _text(item, ["title"])
            link = _text(item, ["link"])
            summary = _text(item, ["description"])
            published = _text(item, ["pubDate", "dc:date"])
            items.append(_make_item(source, title, link, summary, published))

    return [it for it in items if it.get("title")]


def _text(el, tags: list) -> str:
    for tag in tags:
        found = el.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _make_item(source: str, title: str, link: str, summary: str, published: str) -> dict:
    # zaman damgasini cikarmaya calis
    ts = 0
    if published:
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                from datetime import datetime, timezone
                dt = datetime.strptime(published[:25].strip(), fmt[:len(published)]) if len(published) < 26 else datetime.strptime(published, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts = int(dt.timestamp())
                break
            except Exception:
                continue

    return {
        "source": source,
        "title": title[:240],
        "link": link,
        "summary": summary[:280] if summary else "",
        "published": published[:64] if published else "",
        "ts": ts,
    }


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
        futures = {pool.submit(_parse_rss, src, url): src for src, url in feeds}
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
