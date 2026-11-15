"""Uygulama açılışında şema bootstrap'ı (db.create_all() yerine).

Neden: Railway, Procfile'daki `release: flask db upgrade` adımını çalıştırmaz;
üretim tabloları büyük olasılıkla db.create_all() ile kurulmuştur ve
`alembic_version` tablosu yoktur. Bu modül açılışta:

  1. Mevcut tabloların hangi migration revizyonuna denk geldiğini bulur,
  2. `alembic_version` yok/geride ise o revizyona damga vurur (stamp — DDL yok),
  3. head'e kadar bekleyen migration'ları uygular.

Hiçbir durumda uygulamanın açılmasını engellemez: hata olursa loglar ve
durumu `state()` üzerinden /api/health'e bildirir.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Optional, Set, Tuple

import sqlalchemy as sa
from sqlalchemy import text

from .db import db

logger = logging.getLogger(__name__)

_BOOT_LOCK_KEY = 42_000_102
_BOOT_LOCK_WAIT_SECONDS = 45

# (revizyon, o revizyonun OLUŞTURDUĞU tablolar) — migrations/versions ile aynı sırada.
# Yeni bir migration tablo ekliyorsa buraya da eklenmelidir.
_LADDER = [
    ("2c546aa52be9", {"users", "webhook_events", "alerts", "email_tokens", "portfolio", "watchlist"}),
    ("a1b2c3d4e5f6", {"stock_comments"}),
    ("b3c4d5e6f7a8", {"tweet_logs"}),
    ("c4d5e6f7a8b9", {"newsletter_subscribers", "feedback"}),  # + portfolio.buy_date kolonu
]

_state = {"ran": False, "action": None, "error": None, "head": None}


def state() -> dict:
    return dict(_state)


def _auto_migrate_disabled() -> bool:
    return os.environ.get("AUTO_MIGRATE", "1").lower() in ("0", "false", "no", "off")


def _running_flask_db_cli() -> bool:
    """`flask db ...` komutu kendi upgrade/stamp işini yapar; çift çalıştırma."""
    argv = sys.argv
    if len(argv) < 2 or argv[1] != "db":
        return False
    exe = os.path.basename(argv[0]).lower()
    return "flask" in exe or argv[0].endswith("__main__.py")


def _alembic_config(app):
    ext = app.extensions["migrate"]
    return ext.migrate.get_config(ext.directory)


def expected_head(app) -> Optional[str]:
    """Koddaki en yeni migration revizyonu."""
    if _state["head"]:
        return _state["head"]
    from alembic.script import ScriptDirectory

    with app.app_context():
        head = ScriptDirectory.from_config(_alembic_config(app)).get_current_head()
    _state["head"] = head
    return head


def current_revision(conn=None) -> Optional[str]:
    """Veritabanındaki alembic revizyonu (yoksa None). App context gerekir."""
    from alembic.runtime.migration import MigrationContext

    def _read(c) -> Optional[str]:
        heads = MigrationContext.configure(c).get_current_heads()
        return heads[0] if heads else None

    if conn is not None:
        return _read(conn)
    with db.engine.connect() as c:
        return _read(c)


def detect_revision(tables: Set[str]) -> Tuple[Optional[str], bool]:
    """Var olan tablolardan (revizyon, yarım_durum) çıkarır.

    - Hiç uygulama tablosu yok → (None, False): boş DB, baştan upgrade edilir.
    - Bir revizyonun tablolarının yalnızca bir kısmı var → yarım durum: dokunma.
    """
    detected: Optional[str] = None
    partial = False
    gap = False  # tam kurulmamış bir revizyon görüldü
    for rev, rev_tables in _LADDER:
        present = rev_tables & tables
        if present == rev_tables:
            if gap:
                partial = True  # arada eksik revizyon varken sonraki revizyonun tabloları var
            else:
                detected = rev
        else:
            if present:
                partial = True  # revizyonun tablolarının yalnızca bir kısmı var
            gap = True
    return detected, partial


@contextmanager
def _boot_lock():
    """Aynı anda açılan süreçler (deploy çakışması) migration'ı tek tek çalıştırsın."""
    if db.engine.dialect.name != "postgresql":
        yield True
        return
    conn = db.engine.connect()
    got = False
    try:
        deadline = time.time() + _BOOT_LOCK_WAIT_SECONDS
        while True:
            got = bool(conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _BOOT_LOCK_KEY}
            ).scalar())
            conn.commit()
            if got or time.time() >= deadline:
                break
            time.sleep(0.5)
        yield got
    finally:
        try:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _BOOT_LOCK_KEY})
                conn.commit()
        except Exception:
            # Bırakılamadıysa bağlantıyı düşür: oturum kapanınca kilit de kalkar.
            try:
                conn.invalidate()
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


def _revision_order(cfg) -> list:
    """Revizyonlar eskiden yeniye."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    return [r.revision for r in reversed(list(script.walk_revisions()))]


def _bootstrap(app) -> str:
    from alembic import command

    cfg = _alembic_config(app)
    order = _revision_order(cfg)
    head = order[-1] if order else None
    _state["head"] = head

    with db.engine.connect() as conn:
        current = current_revision(conn)
        tables = set(sa.inspect(conn).get_table_names())

    if current is not None and current not in order:
        # Kod geri alınmış olabilir (DB koddan yeni). Dokunma.
        logger.error("migrate_boot: DB revizyonu (%s) kodda yok — şemaya dokunulmadı", current)
        return "unknown_revision"

    if current == head:
        return "at_head"

    detected, partial = detect_revision(tables)
    if partial:
        logger.error(
            "migrate_boot: tablolar yarım durumda (algılanan=%s, mevcut=%s) — "
            "şemaya dokunulmadı, elle inceleme gerekir", detected, current,
        )
        return "partial"

    action = []
    if detected is not None and (current is None or order.index(current) < order.index(detected)):
        logger.warning("migrate_boot: mevcut tablolar %s revizyonuna denk — damgalanıyor (önceki=%s)",
                       detected, current)
        command.stamp(cfg, detected)
        current = detected
        action.append(f"stamped:{detected}")

    if current != head:
        logger.warning("migrate_boot: %s → %s upgrade ediliyor", current, head)
        command.upgrade(cfg, "head")
        action.append(f"upgraded:{head}")

    return ",".join(action) or "at_head"


def ensure_schema(app) -> dict:
    """Şemayı güncel hale getirir. Asla exception fırlatmaz."""
    if _auto_migrate_disabled():
        _state.update(ran=False, action="disabled")
        return state()
    if _running_flask_db_cli():
        _state.update(ran=False, action="flask_db_cli")
        return state()
    try:
        with app.app_context():
            with _boot_lock() as got:
                if not got:
                    logger.warning("migrate_boot: kilit alınamadı (başka süreç migration yapıyor) — atlandı")
                    _state.update(ran=False, action="lock_timeout")
                else:
                    _state.update(ran=True, action=_bootstrap(app), error=None)
            db.session.remove()
    except BaseException as exc:  # alembic/flask-migrate SystemExit de atabilir
        if isinstance(exc, KeyboardInterrupt):
            raise
        logger.exception("migrate_boot: şema bootstrap'ı başarısız — uygulama yine de açılıyor")
        _state.update(ran=True, action="error", error=f"{type(exc).__name__}: {exc}"[:300])
    return state()
