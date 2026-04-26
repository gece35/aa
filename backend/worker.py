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
from .models import Alert, User

logger = logging.getLogger(__name__)
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_TICK_SECONDS = int(os.environ.get("WORKER_TICK_SECONDS", "60"))
_LOCK_KEY = 42_000_001  # arbitrary, sabit


def _try_advisory_lock(session) -> bool:
    """Postgres pg_try_advisory_lock — sadece bir worker process tick'i çalıştırır.

    SQLite (lokal dev) için her zaman True döner.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return True
    row = session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).first()
    return bool(row and row[0])


def _release_advisory_lock(session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
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
    from .scoring import score_symbol_detailed
    data = download_ohlcv([symbol], period="200d", interval="1d")
    df = data.get(symbol)
    if df is None or df.empty:
        return {}
    return score_symbol_detailed(symbol, df) or {}


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


def tick():
    if not _try_advisory_lock(db.session):
        logger.debug("worker: advisory lock alınamadı, başka worker çalışıyor")
        return
    try:
        users = _due_users(time.time())
        if not users:
            return
        total = 0
        for u in users:
            try:
                total += _check_user(u)
            except Exception:
                logger.exception("worker: user %s check hatası", u.id)
        if total:
            logger.info("worker: %d alarm tetiklendi", total)
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
