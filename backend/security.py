"""Şifre hashleme + kısa süreli token üretimi/doğrulaması + rate limiting."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt as _bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .config import SECRET_KEY

# Tek `limiter` nesnesi burada oluşturulur (app'e bağlanmadan) — böylece
# blueprint'ler (auth.py vb.) döngüsel import olmadan `@limiter.limit(...)`
# dekoratörünü kullanabilir. Gerçek app'e bağlama + storage config app.py'de
# create_app() içinde `limiter.init_app(flask_app)` ile yapılır.
limiter = Limiter(key_func=get_remote_address)


def hash_password(password: str) -> str:
    # bcrypt 72-byte hard limit: SHA-256 ile pre-hash
    import hashlib as _hl
    ph = _hl.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")
    return _bcrypt.hashpw(ph, _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        import hashlib as _hl
        ph = _hl.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")
        return _bcrypt.checkpw(ph, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def is_strong_password(password: str) -> bool:
    if password is None:
        return False
    if len(password) < 10:
        return False
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    return classes >= 2


def generate_token() -> Tuple[str, str]:
    """(plain, hashed) çifti döner. Plain mail gönder, hashed DB'de sakla."""
    plain = secrets.token_urlsafe(32)
    hashed = _hash_token(plain)
    return plain, hashed


def _hash_token(plain: str) -> str:
    h = hashlib.sha256()
    h.update(SECRET_KEY.encode("utf-8"))
    h.update(plain.encode("utf-8"))
    return h.hexdigest()


def hash_token(plain: str) -> str:
    return _hash_token(plain)


def token_expiry(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
