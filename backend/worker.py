"""Alarm worker — ayrı process, advisory lock ile multi-instance safe.

Procfile'da `worker: python -m backend.worker` olarak çalışır.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timezone

from sqlalchemy import select, text

from .alerts import _check_single
from .config import LOG_LEVEL
from .db import db
from .email import send_alert_triggered
from .limits import get_plan
from .models import Alert, TweetLog, User
from .twitter_bot import MIN_SCORE, post_signal_tweet

logger = logging.getLogger(__name__)
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_TICK_SECONDS = int(os.environ.get("WORKER_TICK_SECONDS", "60"))
_TWEET_INTERVAL_SECONDS = int(os.environ.get("TWEET_INTERVAL_SECONDS", str(2 * 3600)))
_CLEANUP_INTERVAL_SECONDS = 24 * 3600
_LOCK_KEY = 42_000_001  # arbitrary, sabit
_last_tweet_scan: float = 0.0
_last_cleanup: float = 0.0


def _try_advisory_lock(session) -> bool:
    """Postgres pg_try_advisory_lock — sadece bir worker process tick'i çalıştırır.

    SQLite (lokal dev) için her zaman True döner.
    """
    if db.engine.dialect.name != "postgresql":
        return True
    row = session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).first()
    return bool(row and row[0])


def _release_advisory_lock(session) -> None:
    if db.engine.dialect.name != "postgresql":
        return
    try:
        session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
    except Exception:
        pass


def _due_users(now_ts: float) -> list[User]:
    """Plan periyoduna göre kontrol vakti gelen kullanıcılar."""
    users = db.session.execute(
        select(User).where(User.id.in_(select(Alert.user_id).where(
            Alert.is_active == True,  # noqa: E712
            Alert.triggered_at.is_(None),
            Alert.dismissed == False,  # noqa: E712
        )))
    ).scalars().all()
    return users


def _detail_fetcher(symbol: str) -> dict:
    from .data_fetcher import download_ohlcv
    from .scanner import get_index_df
    from .scoring import compute_regime_ok, score_symbol_detailed
    from .tickers import market_of_symbol
    data = download_ohlcv([symbol], period="200d", interval="1d")
    df = data.get(symbol)
    if df is None or df.empty:
        return {}
    symbol_market = market_of_symbol(symbol)
    index_df = get_index_df(symbol_market)
    return score_symbol_detailed(
        symbol, df, index_df=index_df,
        market=symbol_market, regime_ok=compute_regime_ok(index_df),
    ) or {}


def _check_user(user: User) -> int:
    plan = get_plan(user)
    interval = plan.get("alert_check_interval_seconds", 3600)
    now = datetime.now(timezone.utc)

    q = select(Alert).where(
        Alert.user_id == user.id,
        Alert.is_active == True,  # noqa: E712
        Alert.triggered_at.is_(None),
        Alert.dismissed == False,  # noqa: E712
    )
    active = db.session.execute(q).scalars().all()
    if not active:
        return 0

    symbols = list({a.symbol for a in active})
    details = {}
    for sym in symbols:
        try:
            details[sym] = _detail_fetcher(sym) or {}
        except Exception as exc:
            logger.warning("worker: %s veri hatası: %s", sym, exc)

    fired = 0
    for a in active:
        d = details.get(a.symbol)
        if not d:
            continue
        try:
            if _check_single(a, d):
                a.triggered_at = now
                a.is_active = False
                fired += 1
                try:
                    send_alert_triggered(user.email, a.symbol, a.label)
                except Exception:
                    logger.exception("Alarm mail gönderilemedi")
        except Exception:
            continue

    if fired:
        db.session.commit()
    return fired


def cleanup_unverified_users() -> None:
    """Kaydolup 7 gün içinde e-postasını doğrulamayan hesapları siler."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    users = db.session.execute(
        select(User).where(
            User.email_verified_at.is_(None),
            User.created_at < cutoff,
        )
    ).scalars().all()
    for user in users:
        db.session.delete(user)
    if users:
        db.session.commit()
        logger.info("cleanup: %d doğrulanmamış hesap silindi", len(users))


def tweet_tick() -> None:
    """BIST ve ABD taraması yap, skor >= MIN_SCORE hisseler için tweet at.
    Son 24 saat içinde paylaşılan hisseler atlanır."""
    global _last_tweet_scan
    now_ts = time.time()
    if now_ts - _last_tweet_scan < _TWEET_INTERVAL_SECONDS:
        return
    _last_tweet_scan = now_ts

    from datetime import timedelta
    from .scanner import scan_market

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for market in ("bist", "us"):
        logger.info("tweet_tick: %s taraması başlıyor (min_score=%d)", market.upper(), MIN_SCORE)
        try:
            result = scan_market(market)
            candidates = [r for r in result.get("results", []) if r.get("score", 0) >= MIN_SCORE]
        except Exception:
            logger.exception("tweet_tick: %s tarama hatası", market)
            continue

        if not candidates:
            logger.info("tweet_tick: %s — %d puanın üstünde hisse yok", market.upper(), MIN_SCORE)
            continue

        for stock in candidates:
            symbol = stock.get("symbol", "")
            score = stock.get("score", 0)
            if not symbol:
                continue
            # Son 24 saat içinde bu hisseyi paylaştık mı?
            recent = db.session.execute(
                select(TweetLog)
                .where(TweetLog.symbol == symbol, TweetLog.tweeted_at >= cutoff)
            ).scalar_one_or_none()
            if recent:
                logger.debug("tweet_tick: %s son 24s içinde paylaşıldı, atlanıyor", symbol)
                continue

            tweet_id = post_signal_tweet(symbol, score, stock, market=market)
            log = TweetLog(symbol=symbol, score=score, tweet_id=tweet_id)
            db.session.add(log)
            db.session.commit()
            logger.info("tweet_tick: %s paylaşıldı (score=%d market=%s)", symbol, score, market)


def tick():
    global _last_cleanup
    if not _try_advisory_lock(db.session):
        logger.debug("worker: advisory lock alınamadı, başka worker çalışıyor")
        return
    try:
        # Kullanıcı alarmları
        users = _due_users(time.time())
        total = 0
        for u in users:
            try:
                total += _check_user(u)
            except Exception:
                logger.exception("worker: user %s check hatası", u.id)
        if total:
            logger.info("worker: %d alarm tetiklendi", total)

        # Twitter otomatik paylaşım
        try:
            tweet_tick()
        except Exception:
            logger.exception("worker: tweet_tick hatası")

        # Doğrulanmamış hesap temizliği (günlük)
        now_ts = time.time()
        if now_ts - _last_cleanup >= _CLEANUP_INTERVAL_SECONDS:
            _last_cleanup = now_ts
            try:
                cleanup_unverified_users()
            except Exception:
                logger.exception("worker: cleanup hatası")
    finally:
        _release_advisory_lock(db.session)


def main():
    # App context
    from app import create_app
    app = create_app()
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True
        logger.info("worker: SIGTERM alındı, kapanıyor")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("worker: başlatıldı (tick=%ss)", _TICK_SECONDS)
    while not stop:
        try:
            with app.app_context():
                tick()
        except Exception:
            logger.exception("worker: tick hatası")
        for _ in range(_TICK_SECONDS):
            if stop:
                break
            time.sleep(1)
    logger.info("worker: kapandı")


if __name__ == "__main__":
    main()
