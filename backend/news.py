"""RSS feed tabanli piyasa haber toplama modulu.

feedparser yerine stdlib xml.etree.ElementTree + requests kullanilir.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import requests
import yfinance as yf

from .cache import news_cache, stock_news_cache
from .sentiment import classify as classify_sentiment

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


_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def _parse_published(published: str) -> int:
    if not published:
        return 0
    text = published.strip()

    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
    except (TypeError, ValueError, IndexError):
        pass

    normalized = re.sub(r"Z$", "+0000", text)
    normalized = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", normalized)
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(normalized, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return 0


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return _TAG_RE.sub(" ", text).strip()


def _make_item(source: str, title: str, link: str, summary: str, published: str) -> dict:
    ts = _parse_published(published)
    clean_title = _strip_html(title)
    clean_summary = _strip_html(summary)
    sentiment, sent_score = classify_sentiment(clean_title, clean_summary)

    return {
        "source": source,
        "title": clean_title[:240],
        "link": link,
        "summary": clean_summary[:280] if clean_summary else "",
        "published": published[:64] if published else "",
        "ts": ts,
        "sentiment": sentiment,
        "sentiment_score": sent_score,
    }


def fetch_stock_news(symbol: str, limit: int = 5) -> dict:
    """yfinance Ticker.news ile sembol bazli son haberleri döner."""
    symbol = (symbol or "").upper().strip()
    cache_key = f"stock_news:{symbol}"
    cached = stock_news_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    items = []
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
        for n in raw_news[:limit]:
            if not isinstance(n, dict):
                continue
            # yfinance 1.x: nested under 'content'; older: flat dict
            content = n.get("content") if isinstance(n.get("content"), dict) else n
            title = content.get("title", "")
            if not title:
                continue
            # link
            link = (
                content.get("canonicalUrl", {}).get("url", "")
                or content.get("clickThroughUrl", {}).get("url", "")
                or n.get("link", "")
            )
            # publisher
            provider = content.get("provider", {})
            publisher = (
                provider.get("displayName", "")
                if isinstance(provider, dict) else ""
            ) or n.get("publisher", "")
            # timestamp
            pub_date = content.get("pubDate", "") or n.get("providerPublishTime", 0)
            ts = 0
            if isinstance(pub_date, (int, float)):
                ts = int(pub_date)
            elif isinstance(pub_date, str) and pub_date:
                ts = _parse_published(pub_date)

            sentiment, _ = classify_sentiment(str(title), "")
            items.append({
                "title": str(title)[:200],
                "link": str(link),
                "publisher": str(publisher)[:80],
                "published": ts,
                "sentiment": sentiment,
            })
    except Exception as exc:
        logger.warning("Haber alinamadi %s: %s", symbol, exc)

    payload = {"symbol": symbol, "items": items, "count": len(items)}
    stock_news_cache.set(cache_key, payload)
    return payload


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

    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for it in unique:
        s = it.get("sentiment") or "neutral"
        counts[s] = counts.get(s, 0) + 1

    payload = {
        "market": market,
        "count": len(unique),
        "items": unique,
        "sentiment_counts": counts,
        "generated_at": int(time.time()),
        "cached": False,
    }
    news_cache.set(cache_key, payload)
    return payload
