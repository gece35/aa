"""Açılıştaki şema bootstrap'ı: boş DB, create_all ile kurulmuş DB, head, yarım durum."""

from __future__ import annotations

import logging
import pathlib

import pytest
import sqlalchemy as sa
from flask import Flask

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEAD_BEFORE_NEW_TABLES = "b3c4d5e6f7a8"


@pytest.fixture()
def mini_app(tmp_path):
    """Ayrı bir SQLite dosyasına bağlı, yalnızca db+migrate kurulu küçük uygulama."""
    from backend.db import db, migrate
    import backend.models  # noqa: F401 — metadata dolsun

    app = Flask("mini")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp_path / 'boot.db').as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    migrate.init_app(app, db, directory=str(ROOT / "migrations"))
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _tables(app):
    from backend.db import db

    with app.app_context():
        with db.engine.connect() as conn:
            return set(sa.inspect(conn).get_table_names())


def _revision(app):
    from backend import migrate_boot

    with app.app_context():
        return migrate_boot.current_revision()


def test_fresh_database_is_upgraded_from_scratch(mini_app):
    from backend import migrate_boot

    assert _tables(mini_app) == set()
    result = migrate_boot.ensure_schema(mini_app)
    assert result["error"] is None and "upgraded" in result["action"]
    assert _revision(mini_app) == migrate_boot.expected_head(mini_app)
    assert {"users", "alerts", "stock_comments", "tweet_logs"} <= _tables(mini_app)


def _legacy_schema_without_version_table(app):
    """Üretimin bootstrap öncesi hali: eski (b3c4...) tablolar var, alembic_version yok."""
    from alembic import command

    from backend import migrate_boot
    from backend.db import db

    with app.app_context():
        command.upgrade(migrate_boot._alembic_config(app), HEAD_BEFORE_NEW_TABLES)
        with db.engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE alembic_version"))
            conn.execute(sa.text(
                "INSERT INTO users (id, email, password_hash, plan, is_admin) "
                "VALUES ('u1', 'keep@example.com', 'x', 'free', 0)"))
            conn.execute(sa.text(
                "INSERT INTO portfolio (user_id, symbol, qty, avg_price, currency) "
                "VALUES ('u1', 'THYAO.IS', 10, 100, 'TRY')"))


def test_legacy_database_is_stamped_then_upgraded_keeping_data(mini_app):
    """Üretim senaryosu: tablolar create_all ile kurulmuş, alembic_version yok."""
    from backend import migrate_boot
    from backend.db import db
    from backend.models import Portfolio, User

    _legacy_schema_without_version_table(mini_app)
    assert "alembic_version" not in _tables(mini_app)
    assert "newsletter_subscribers" not in _tables(mini_app)

    result = migrate_boot.ensure_schema(mini_app)
    assert result["error"] is None
    assert result["action"].startswith(f"stamped:{HEAD_BEFORE_NEW_TABLES},upgraded:")
    assert _revision(mini_app) == migrate_boot.expected_head(mini_app)
    assert {"newsletter_subscribers", "feedback"} <= _tables(mini_app)
    with mini_app.app_context():
        assert db.session.scalar(sa.select(sa.func.count()).select_from(User)) == 1  # veri duruyor
        position = db.session.execute(sa.select(Portfolio)).scalar_one()
        assert position.symbol == "THYAO.IS" and position.buy_date is None      # yeni kolon eklendi

    # İkinci açılış: yapılacak iş yok
    assert migrate_boot.ensure_schema(mini_app)["action"] == "at_head"


def test_new_migration_is_idempotent_when_objects_already_exist(mini_app):
    """Tablo/kolon zaten varsa (çakışan deploy) migration hata vermeden geçer."""
    from backend import migrate_boot
    from backend.db import db

    _legacy_schema_without_version_table(mini_app)
    with mini_app.app_context():
        with db.engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE feedback (id INTEGER PRIMARY KEY, created_at DATETIME, "
                                 "category VARCHAR(16), message TEXT, email VARCHAR(255))"))
            conn.execute(sa.text("ALTER TABLE portfolio ADD COLUMN buy_date DATE"))

    # feedback var ama newsletter_subscribers yok → merdiven "yarım" der; bu durumda
    # bootstrap dokunmaz. Migration'ın kendisini doğrudan çalıştırıp idempotent olduğunu sına.
    from alembic import command
    with mini_app.app_context():
        cfg = migrate_boot._alembic_config(mini_app)
        command.stamp(cfg, HEAD_BEFORE_NEW_TABLES)
        command.upgrade(cfg, "head")
    assert _revision(mini_app) == migrate_boot.expected_head(mini_app)
    assert {"newsletter_subscribers", "feedback"} <= _tables(mini_app)


def test_partial_schema_is_left_untouched(mini_app):
    from backend import migrate_boot
    from backend.db import db

    with mini_app.app_context():
        with db.engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE tweet_logs (id INTEGER PRIMARY KEY)"))

    result = migrate_boot.ensure_schema(mini_app)
    assert result["action"] == "partial"
    assert _revision(mini_app) is None
    assert "users" not in _tables(mini_app)


def test_detect_revision_ladder():
    from backend.migrate_boot import _LADDER, detect_revision

    first = set(_LADDER[0][1])
    assert detect_revision(set()) == (None, False)
    assert detect_revision(first) == ("2c546aa52be9", False)
    assert detect_revision(first | {"stock_comments"}) == ("a1b2c3d4e5f6", False)
    legacy = first | {"stock_comments", "tweet_logs"}
    assert detect_revision(legacy) == (HEAD_BEFORE_NEW_TABLES, False)
    assert detect_revision(legacy | {"newsletter_subscribers", "feedback"}) == ("c4d5e6f7a8b9", False)
    assert detect_revision(legacy | {"feedback"}) == (HEAD_BEFORE_NEW_TABLES, True)
    # İlk revizyonun yarısı var → yarım
    assert detect_revision({"users"})[1] is True
    # Aradaki revizyon eksikken sonraki var → yarım
    assert detect_revision(first | {"tweet_logs"}) == ("2c546aa52be9", True)


def test_bootstrap_does_not_silence_application_logging(mini_app):
    """migrations/env.py fileConfig'i mevcut logger'ları kapatmamalı."""
    from backend import migrate_boot

    root = logging.getLogger()
    app_logger = logging.getLogger("backend.scanner")
    handler = logging.NullHandler()
    root.addHandler(handler)
    level_before = root.level
    try:
        migrate_boot.ensure_schema(mini_app)
        assert app_logger.disabled is False
        assert handler in root.handlers
        assert root.level == level_before
    finally:
        root.removeHandler(handler)


def test_auto_migrate_can_be_disabled(mini_app, monkeypatch):
    from backend import migrate_boot

    monkeypatch.setenv("AUTO_MIGRATE", "0")
    assert migrate_boot.ensure_schema(mini_app)["action"] == "disabled"
    assert _tables(mini_app) == set()
