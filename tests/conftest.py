"""Test ortamı: geçici SQLite, zamanlayıcı kapalı, dış servisler devre dışı.

Ortam değişkenleri `app` import edilmeden ÖNCE ayarlanmalıdır (backend/config.py
modül düzeyinde okur; load_dotenv mevcut değişkenleri ezmez — bu sayede yerel
.env'deki gerçek e-posta/AI anahtarları testlerde kullanılmaz).
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="nebula-test-"))

os.environ.update({
    "DEBUG": "1",
    "SECRET_KEY": "test-secret-key",
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "APP_BASE_URL": "http://localhost:5000",
    "SCHEDULER_DISABLED": "1",
    "ADMIN_EMAILS": "admin@example.com",
    # Dış servisler: boş değer = yapılandırılmamış
    "REDIS_URL": "",
    "SENTRY_DSN": "",
    "GROQ_API_KEY": "",
    "BREVO_API_KEY": "",
    "BREVO_FROM_EMAIL": "",
    "SMTP_HOST": "",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "RESEND_API_KEY": "",
    "LEMONSQUEEZY_API_KEY": "",
    "LEMONSQUEEZY_WEBHOOK_SECRET": "",
    "NEWSLETTER_FILE": str(_TMP / "newsletter.json"),
    "DATA_DIR": str(_TMP),
})
os.environ.pop("SERVER_SOFTWARE", None)
os.environ.pop("RUN_SCHEDULER", None)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolate(app):
    """Her testten sonra tabloları, önbellekleri ve sayaçları temizle."""
    yield
    from backend import cache as cache_mod
    from backend import quota_store
    from backend.db import db
    from backend.security import limiter

    with app.app_context():
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        db.session.remove()
        try:
            limiter.reset()
        except Exception:
            pass
    from backend import seo as seo_mod

    for obj in list(vars(cache_mod).values()) + [seo_mod.seo_cache]:
        if isinstance(obj, cache_mod.TTLCache):
            obj.clear()
    quota_store.reset()


@pytest.fixture()
def make_user(app):
    """Doğrulanmış kullanıcı oluşturur; (id, email, password) döner."""
    from backend.db import db
    from backend.models import User
    from backend.security import hash_password, now_utc

    def _make(email="user@example.com", password="Sifre12345!", verified=True, **extra):
        with app.app_context():
            u = User(
                email=email,
                password_hash=hash_password(password),
                email_verified_at=now_utc() if verified else None,
                kvkk_consent_at=now_utc(),
                **extra,
            )
            db.session.add(u)
            db.session.commit()
            return u.id, email, password

    return _make


@pytest.fixture()
def login(client):
    def _login(email, password):
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.get_json()
        return r

    return _login
