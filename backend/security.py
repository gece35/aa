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


# Cloudflare'in yayımladığı kenar sunucu aralıkları (https://www.cloudflare.com/ips-v4
# ve /ips-v6, 2026-11 itibarıyla). Nadiren değişir; değişirse buraya eklenir.
_CLOUDFLARE_NETS = tuple(ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
))


def is_cloudflare_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _CLOUDFLARE_NETS)


def peer_ip() -> str:
    """Railway kenar sunucusunun bildirdiği istemci IP'si.

    Railway edge `X-Real-IP` başlığını her istekte kendisi yazar ve istemcinin
    gönderdiği değeri ezer. Canlıda doğrulandı (2026-11-15): Cloudflare üzerinden
    gelen istekte değer zaten gerçek ziyaretçi IP'sidir; Railway alan adına
    doğrudan gelen istekte uydurulmuş X-Real-IP / X-Forwarded-For /
    CF-Connecting-IP değerleri bu sonucu değiştirmez. Başlık yoksa (lokal
    geliştirme, testler) doğrudan bağlantının adresi kullanılır.
    """
    return (_valid_ip(request.headers.get("X-Real-IP", ""))
            or _valid_ip(request.remote_addr or "")
            or "0.0.0.0")


def client_ip() -> str:
    """İsteği yapan gerçek istemcinin IP'si (hız sınırı / kota anahtarı).

    Normal trafik Cloudflare → Railway edge → gunicorn yolunu izler: bağlanan
    taraf bir Cloudflare sunucusudur ve gerçek istemci `CF-Connecting-IP`
    başlığındadır. Ancak Railway'in kendi alan adı Cloudflare'i atlayarak
    doğrudan erişilebilir ve bu başlığı herkes uydurabilir; bu yüzden ona
    YALNIZCA bağlanan taraf gerçekten Cloudflare ise güvenilir. Aksi halde
    bağlanan tarafın adresi kullanılır. X-Forwarded-For'un ilk değeri de
    istemci tarafından uydurulabildiği için kullanılmaz.
    """
    peer = peer_ip()
    # Railway şu an Cloudflare trafiğinde de gerçek ziyaretçiyi bildiriyor; bu dal,
    # bir gün X-Real-IP olarak Cloudflare sunucusu gelirse diye bir yedektir.
    if is_cloudflare_ip(peer):
        cf = _valid_ip(request.headers.get("CF-Connecting-IP", ""))
        if cf:
            return cf
    return peer


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
