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


def test_create_all_database_is_stamped_not_recreated(mini_app):
    """Üretim senaryosu: tablolar create_all ile var, alembic_version yok."""
    from backend import migrate_boot
    from backend.db import db
    from backend.models import User

    with mini_app.app_context():
        db.create_all()
        db.session.add(User(email="keep@example.com", password_hash="x"))
        db.session.commit()
    assert "alembic_version" not in _tables(mini_app)

    result = migrate_boot.ensure_schema(mini_app)
    assert result["error"] is None
    assert result["action"].startswith(f"stamped:{HEAD_BEFORE_NEW_TABLES}")
    assert _revision(mini_app) == migrate_boot.expected_head(mini_app)
    with mini_app.app_context():
        assert db.session.scalar(sa.select(sa.func.count()).select_from(User)) == 1  # veri duruyor

    # İkinci açılış: yapılacak iş yok
    assert migrate_boot.ensure_schema(mini_app)["action"] == "at_head"


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
    assert detect_revision(first | {"stock_comments", "tweet_logs"}) == (HEAD_BEFORE_NEW_TABLES, False)
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
