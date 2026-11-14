"""Web süreci içinde çalışan hafif zamanlayıcı.

Eskiden ayrı, 7/24 açık bir worker servisi her 60 saniyede alarm sembollerini
tek tek indirip tam skor hesabı yapıyordu. Bu modül aynı işi web sürecindeki
tek bir daemon thread ile, seans saatlerinde ve toplu fiyat indirmesiyle yapar.

Başlatma yalnızca gunicorn altında olur (bkz. gunicorn.conf.py ve app.py'deki
before_request yedeği); flask CLI, pytest ve `python -m backend.worker`
altında kendiliğinden başlamaz.

Çok süreç güvenliği (Railway deploy'unda eski/yeni sürüm kısa süre birlikte
çalışır): tick başına Postgres advisory lock + alarm satırını atomik
"sahiplenme" (UPDATE ... WHERE triggered_at IS NULL).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import select, text, update

from .db import db
from .market_hours import MARKET_CODES, is_market_open

logger = logging.getLogger(__name__)

TICK_SECONDS = max(30, int(os.environ.get("SCHEDULER_TICK_SECONDS", "300")))
_FIRST_TICK_DELAY = 20          # süreç açılışını yormamak için ilk tick gecikmesi
_CLEANUP_INTERVAL = 24 * 3600
_CLEANUP_BATCH = 200
_UNVERIFIED_MAX_AGE_DAYS = 7
# Eski worker'ın (42_000_001) pooled bağlantıda takılı kalabilen kilidinden
# bağımsız olsun diye yeni anahtar.
_LOCK_KEY = 42_000_101

_start_lock = threading.Lock()
_stop = threading.Event()
_state: Dict[str, object] = {
    "pid": None,
    "thread": None,
    "started_at": None,
    "last_tick": None,
    "last_ok": None,
    "last_error": None,
    "ticks": 0,
}
_last_cleanup = 0.0


def _disabled() -> bool:
    return os.environ.get("SCHEDULER_DISABLED", "0").lower() in ("1", "true", "yes", "on")


def is_running() -> bool:
    t = _state.get("thread")
    return bool(_state.get("pid") == os.getpid() and t is not None and t.is_alive())


def status() -> dict:
    """/api/health için özet."""
    return {
        "running": is_running(),
        "disabled": _disabled(),
        "tick_seconds": TICK_SECONDS,
        "started_at": _state.get("started_at"),
        "last_tick": _state.get("last_tick"),
        "last_ok": _state.get("last_ok"),
        "last_error": _state.get("last_error"),
        "ticks": _state.get("ticks"),
    }


def start(app) -> bool:
    """Zamanlayıcı thread'ini bu süreçte (yoksa) başlatır. Başlattıysa True."""
    if _disabled():
        return False
    if is_running():
        return False
    with _start_lock:
        if is_running():
            return False
        _stop.clear()
        t = threading.Thread(target=_loop, args=(app,), name="nebula-scheduler", daemon=True)
        _state.update(pid=os.getpid(), thread=t, started_at=int(time.time()))
        t.start()
        logger.info("scheduler: başlatıldı (pid=%s, tick=%ss)", os.getpid(), TICK_SECONDS)
        return True


def stop() -> None:
    _stop.set()


def _loop(app) -> None:
    if _stop.wait(_FIRST_TICK_DELAY):
        return
    while not _stop.is_set():
        _state["last_tick"] = int(time.time())
        _state["ticks"] = int(_state.get("ticks") or 0) + 1
        try:
            with app.app_context():
                try:
                    run_due_jobs()
                    _state["last_ok"] = int(time.time())
                    _state["last_error"] = None
                except Exception as exc:
                    db.session.rollback()
                    _state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                    logger.exception("scheduler: tick hatası")
                finally:
                    db.session.remove()
        except Exception:  # app_context kurulamadıysa bile döngü ölmesin
            logger.exception("scheduler: beklenmeyen hata")
        if _stop.wait(TICK_SECONDS):
            break
    logger.info("scheduler: durdu")


# ── Kilit ────────────────────────────────────────────────────────────────────

@contextmanager
def _job_lock():
    """Tick boyunca AYRI bir bağlantıda tutulan Postgres advisory lock.

    Session-level advisory lock bağlantıya aittir; ORM oturumunun pooled
    bağlantısında alınırsa commit'ler arasında bağlantı değişebilir ve kilit
    başka bağlantıda takılı kalır. Bu yüzden kilit için ayrı bağlantı açılır
    ve iş bitene kadar bırakılmaz. SQLite'ta (lokal) kilit yoktur.
    """
    if db.engine.dialect.name != "postgresql":
        yield True
        return
    conn = db.engine.connect()
    got = False
    try:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar())
        conn.commit()
        yield got
    finally:
        try:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                conn.commit()
        except Exception:
            # Kilit bırakılamadıysa bağlantıyı tamamen düşür: Postgres oturum
            # kapanınca kilidi kendisi serbest bırakır.
            logger.exception("scheduler: kilit bırakılamadı, bağlantı düşürülüyor")
            try:
                conn.invalidate()
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ── İşler ────────────────────────────────────────────────────────────────────

def run_due_jobs(force: bool = False) -> dict:
    """Vakti gelen işleri çalıştırır. App context içinde çağrılmalıdır.

    force=True: seans saatine ve günlük aralığa bakmadan hepsini çalıştır
    (`python -m backend.worker --once` ve testler için).
    """
    global _last_cleanup
    out = {"skipped": False, "alerts_fired": 0, "cleaned": 0}
    with _job_lock() as got:
        if not got:
            out["skipped"] = True
            logger.debug("scheduler: kilit başka süreçte, tick atlandı")
            return out

        try:
            out["alerts_fired"] = check_price_alerts(force=force)
        except Exception:
            db.session.rollback()
            logger.exception("scheduler: alarm kontrolü hatası")

        now_ts = time.time()
        if force or now_ts - _last_cleanup >= _CLEANUP_INTERVAL:
            _last_cleanup = now_ts
            try:
                out["cleaned"] = cleanup_unverified_users()
            except Exception:
                db.session.rollback()
                logger.exception("scheduler: temizlik hatası")
    return out


def _last_prices(symbols: List[str]) -> Dict[str, float]:
    """Semboller için son kapanış fiyatı (tek toplu indirme)."""
    from .data_fetcher import download_ohlcv

    prices: Dict[str, float] = {}
    data = download_ohlcv(symbols, period="5d", interval="1d")
    for sym, df in data.items():
        try:
            close = df["Close"].dropna()
            if not close.empty:
                price = float(close.iloc[-1])
                if price > 0:
                    prices[sym] = price
        except Exception:
            logger.debug("scheduler: %s fiyatı okunamadı", sym)
    return prices


def _claim_alert(alert_id: str, now: datetime) -> bool:
    """Alarmı atomik olarak 'tetiklendi' yapar. Yalnızca ilk çağıran True alır;
    böylece çakışan iki süreç aynı alarm için iki e-posta gönderemez."""
    from .models import Alert

    res = db.session.execute(
        update(Alert)
        .where(Alert.id == alert_id, Alert.triggered_at.is_(None))
        .values(triggered_at=now, is_active=False)
    )
    db.session.commit()
    return res.rowcount == 1


def check_price_alerts(force: bool = False, price_fetcher=None) -> int:
    """Aktif fiyat alarmlarını kontrol eder; tetiklenenleri işaretleyip e-posta atar.

    Yalnızca seansı açık pazarların sembolleri indirilir. `price_fetcher`
    testlerde sahte fiyat kaynağı vermek içindir.
    """
    from .alerts import _check_single
    from .email import send_alert_triggered
    from .models import Alert, User
    from .tickers import market_of_symbol

    open_markets = {m for m in MARKET_CODES if force or is_market_open(m)}

    rows = db.session.execute(
        select(Alert.id, Alert.symbol, Alert.condition_type, Alert.condition_value,
               Alert.label, Alert.created_at, User.email)
        .join(User, User.id == Alert.user_id)
        .where(
            Alert.is_active == True,  # noqa: E712
            Alert.triggered_at.is_(None),
            Alert.dismissed == False,  # noqa: E712
        )
    ).all()
    # İndirme/e-posta sırasında açık transaction (ve pooled bağlantı) tutma.
    db.session.rollback()

    # Pazar kapalıyken fiyat değişmez; ama YENİ kurulan bir alarmın koşulu son
    # kapanışla zaten sağlanıyor olabilir — onu açılışı beklemeden bir kez kontrol et.
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(seconds=2 * TICK_SECONDS + 60)

    def _is_fresh(created_at) -> bool:
        if created_at is None:
            return False
        if created_at.tzinfo is None:  # SQLite saf (UTC) datetime döndürür
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at >= fresh_cutoff

    pending = [
        r for r in rows
        if market_of_symbol(r.symbol) in open_markets or _is_fresh(r.created_at)
    ]
    if not pending:
        return 0

    symbols = sorted({r.symbol for r in pending})
    prices = (price_fetcher or _last_prices)(symbols)

    fired = 0
    now = datetime.now(timezone.utc)
    for r in pending:
        price = prices.get(r.symbol)
        if price is None:
            continue
        try:
            if not _check_single(r, {"price": price}):
                continue
            if not _claim_alert(r.id, now):
                continue  # başka süreç/istek önce davrandı
        except Exception:
            db.session.rollback()
            logger.exception("scheduler: alarm %s işlenemedi", r.id)
            continue
        fired += 1
        logger.info("Alarm tetiklendi: %s %s (fiyat=%s)", r.symbol, r.label, price)
        try:
            send_alert_triggered(r.email, r.symbol, r.label)
        except Exception:
            logger.exception("Alarm e-postası gönderilemedi: %s", r.symbol)
    return fired


def cleanup_unverified_users() -> int:
    """Kaydolup 7 gün içinde e-postasını doğrulamayan hesapları siler.

    Admin hesapları (doğrulamadan giriş yapabilir) ve ödeme kaydı olan
    hesaplar dokunulmaz. Tur başına en fazla _CLEANUP_BATCH hesap.
    """
    from .models import User

    cutoff = datetime.now(timezone.utc) - timedelta(days=_UNVERIFIED_MAX_AGE_DAYS)
    users = db.session.execute(
        select(User).where(
            User.email_verified_at.is_(None),
            User.created_at < cutoff,
            User.is_admin == False,  # noqa: E712
            User.ls_subscription_id.is_(None),
            User.ls_customer_id.is_(None),
        ).limit(_CLEANUP_BATCH)
    ).scalars().all()
    for user in users:
        db.session.delete(user)
    if users:
        db.session.commit()
        logger.info("cleanup: %d doğrulanmamış hesap silindi", len(users))
    return len(users)
