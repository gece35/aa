"""Twitter/X otomatik sinyal paylaşım modülü.

Her TWEET_INTERVAL_SECONDS saniyede bir BIST taraması yapılır.
TWEET_MIN_SCORE puanına ulaşan hisseler için tweet atılır.
Aynı hisse son 24 saat içinde paylaşıldıysa atlanır.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_API_KEY = os.environ.get("TWITTER_API_KEY", "")
_API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")

MIN_SCORE = int(os.environ.get("TWEET_MIN_SCORE", "8"))


def _client():
    if not all([_API_KEY, _API_SECRET, _ACCESS_TOKEN, _ACCESS_TOKEN_SECRET]):
        return None
    try:
        import tweepy
        return tweepy.Client(
            consumer_key=_API_KEY,
            consumer_secret=_API_SECRET,
            access_token=_ACCESS_TOKEN,
            access_token_secret=_ACCESS_TOKEN_SECRET,
        )
    except ImportError:
        logger.warning("twitter_bot: tweepy kurulu değil")
        return None


_MARKET_TAGS = {
    "bist": "#bist #borsa #borsaanaliz #teknikanaliz",
    "us":   "#nasdaq #nyse #stocks #investing #technicalanalysis",
}

_MARKET_LABEL = {
    "bist": "BIST",
    "us":   "ABD",
}


def _build_tweet(symbol: str, score: int, result: dict, market: str = "bist") -> str:
    """Sinyal sonucundan tweet metni oluştur."""
    price = result.get("price", 0)
    change = result.get("change_pct", 0)
    arrow = "🟢" if change >= 0 else "🔴"
    change_str = f"{'+' if change >= 0 else ''}{change:.1f}%"
    market_label = _MARKET_LABEL.get(market, market.upper())

    lines = [
        f"📡 ${symbol} [{market_label}] — {score}/10 sinyal skoru",
        f"{arrow} Fiyat: {price:.2f}  ({change_str})",
        "",
    ]

    # Aktif indikatörleri listele
    indicators = result.get("indicators", [])
    for ind in indicators:
        if ind.get("score", 0) > 0:
            detail = ind.get("detail", "")
            if detail:
                lines.append(f"✅ {detail}")

    tags = _MARKET_TAGS.get(market, "")
    lines += [
        "",
        "🔗 nebulascanner.com",
        tags,
    ]
    return "\n".join(lines)


def post_signal_tweet(symbol: str, score: int, result: dict, market: str = "bist") -> Optional[str]:
    """Tweet at. Başarılıysa tweet ID, değilse None döner."""
    client = _client()
    if not client:
        logger.info("twitter_bot: credentials eksik, tweet atlanıyor")
        return None

    text = _build_tweet(symbol, score, result, market=market)
    # Twitter 280 karakter limiti
    if len(text) > 280:
        text = text[:277] + "..."

    try:
        import tweepy
        response = client.create_tweet(text=text)
        tweet_id = str(response.data["id"])
        logger.info("twitter_bot: tweet atıldı %s score=%d id=%s", symbol, score, tweet_id)
        return tweet_id
    except tweepy.TweepyException as exc:
        logger.error("twitter_bot: tweet atılamadı %s — %s", symbol, exc)
        return None
    except Exception as exc:
        logger.exception("twitter_bot: beklenmeyen hata %s — %s", symbol, exc)
        return None
