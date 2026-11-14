"""Şifre hashleme + kısa süreli token üretimi/doğrulaması + rate limiting."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt as _bcrypt
from flask import request
from flask_limiter import Limiter

from .config import SECRET_KEY


def _valid_ip(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip() -> str:
    """İsteği yapan gerçek istemcinin IP'si.

    Site Cloudflare → Railway edge → gunicorn zincirinin arkasındadır;
    `request.remote_addr` her zaman bir vekil sunucunun adresidir. Onu anahtar
    alan rate-limit tüm ziyaretçileri tek kovaya koyuyordu (ör. "saatte 5
    kayıt" site geneline uygulanıyordu). Sıra: Cloudflare'in verdiği
    CF-Connecting-IP → X-Forwarded-For'un ilk (istemci) değeri → remote_addr.

    Not: başlıklar yalnızca Cloudflare üzerinden gelen trafikte güvenilirdir;
    origin'e doğrudan ulaşan biri bunları uydurabilir. Bu yüzden değer yalnızca
    hız sınırlama/kota anahtarı olarak kullanılır, yetkilendirme için değil.
    """
    ip = _valid_ip(request.headers.get("CF-Connecting-IP", ""))
    if ip:
        return ip
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        ip = _valid_ip(forwarded.split(",")[0])
        if ip:
            return ip
    return request.remote_addr or "0.0.0.0"


# Tek `limiter` nesnesi burada oluşturulur (app'e bağlanmadan) — böylece
# blueprint'ler (auth.py vb.) döngüsel import olmadan `@limiter.limit(...)`
# dekoratörünü kullanabilir. Gerçek app'e bağlama + storage config app.py'de
# create_app() içinde `limiter.init_app(flask_app)` ile yapılır.
limiter = Limiter(key_func=client_ip)


def hash_password(password: str) -> str:
    # bcrypt 72-byte hard limit: SHA-256 ile pre-hash
    ph = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")
    return _bcrypt.hashpw(ph, _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        ph = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")
        return _bcrypt.checkpw(ph, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def session_fingerprint(password_hash: str) -> str:
    """Oturum kimliğine eklenen parola parmak izi. Parola değişince değişir;
    böylece eski oturumlar ve "beni hatırla" çerezleri geçersiz kalır."""
    h = hashlib.sha256()
    h.update(SECRET_KEY.encode("utf-8"))
    h.update((password_hash or "").encode("utf-8"))
    return h.hexdigest()[:16]


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
