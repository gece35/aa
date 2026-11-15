"""Bülten aboneliği — aboneler veritabanında (NewsletterSubscriber) tutulur.

Eskiden aboneler çalışma dizinindeki bir JSON dosyasına yazılıyordu; Railway'in
diski kalıcı olmadığı için liste her deploy'da siliniyordu.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Optional, Tuple

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from .db import db
from .models import NewsletterSubscriber
from .security import limiter, now_utc

logger = logging.getLogger(__name__)

newsletter_bp = Blueprint("newsletter", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def normalize_email(raw) -> Optional[str]:
    email = str(raw or "").strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    return email


def subscribe_email(email: str, source: str = "website") -> Tuple[NewsletterSubscriber, bool]:
    """Aboneyi ekler (ya da ayrılmış aboneyi yeniden etkinleştirir).

    Dönüş: (abone, yeni_mi). Zaten etkin bir abone için `yeni_mi` False'tur.
    Çağıran commit etmelidir.
    """
    source = source if _SOURCE_RE.match(str(source or "")) else "website"
    sub = db.session.execute(
        select(NewsletterSubscriber).where(NewsletterSubscriber.email == email)
    ).scalar_one_or_none()
    if sub is None:
        sub = NewsletterSubscriber(
            email=email, source=source, unsubscribe_token=secrets.token_urlsafe(32),
        )
        db.session.add(sub)
        return sub, True
    if sub.unsubscribed_at is not None:
        sub.unsubscribed_at = None
        sub.subscribed_at = now_utc()
        return sub, True
    return sub, False


def unsubscribe_email(email: str) -> bool:
    """E-postayı abonelikten çıkarır. Çağıran commit etmelidir."""
    sub = db.session.execute(
        select(NewsletterSubscriber).where(NewsletterSubscriber.email == email)
    ).scalar_one_or_none()
    if sub is None or sub.unsubscribed_at is not None:
        return False
    sub.unsubscribed_at = now_utc()
    return True


def active_count() -> int:
    return db.session.scalar(
        select(func.count(NewsletterSubscriber.id))
        .where(NewsletterSubscriber.unsubscribed_at.is_(None))
    ) or 0


@newsletter_bp.route("/api/newsletter", methods=["POST"])
@limiter.limit("5 per hour")
def subscribe():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    kvkk = bool(data.get("kvkk_consent"))

    if not email:
        return jsonify({"ok": False, "error": "Geçerli bir e-posta adresi girin."}), 400
    if not kvkk:
        return jsonify({"ok": False, "error": "KVKK onayı zorunludur."}), 400

    try:
        _sub, created = subscribe_email(email, str(data.get("source") or "website"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Newsletter kayıt hatası")
        return jsonify({"ok": False, "error": "Kayıt sırasında hata oluştu."}), 500

    if not created:
        return jsonify({"ok": True, "already": True, "message": "Bu e-posta zaten kayıtlı."})
    logger.info("Newsletter: yeni abone")
    return jsonify({"ok": True, "message": "Abone oldunuz! Her Pazar piyasa özetini e-postanızda bulacaksınız."})


@newsletter_bp.route("/api/newsletter/count")
def subscriber_count():
    """Kamuya açık abone sayısı (pazarlama sayacı için)."""
    return jsonify({"count": active_count()})
