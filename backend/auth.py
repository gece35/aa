"""Auth blueprint — signup, login, logout, verify, password reset, KVKK haklarına ilişkin endpoint'ler."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import wraps

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, jsonify, redirect, request, send_from_directory, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from .config import ADMIN_EMAILS, APP_BASE_URL
from .db import db
from .email import send_password_reset, send_verify_email
from .models import EmailToken, User
from .security import (
    generate_token, hash_password, hash_token, is_strong_password, now_utc,
    token_expiry, verify_password,
)

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "auth_required"}), 401
        if not getattr(current_user, "is_admin", False):
            return jsonify({"error": "admin_required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def email_verified_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "auth_required"}), 401
        if not current_user.email_verified_at:
            return jsonify({"error": "email_not_verified", "message": "Bu özelliği kullanmak için e-posta adresinizi doğrulamanız gerekiyor."}), 403
        return fn(*args, **kwargs)
    return wrapper


def _normalize_email(raw: str) -> str:
    try:
        info = validate_email(raw, check_deliverability=False)
        return info.normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(str(exc))


# ── Endpoints ──────────────────────────────────────────────────────────────

@auth_bp.route("/signup", methods=["POST"])
def signup():
    body = request.get_json(silent=True) or {}
    raw_email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    kvkk_consent = bool(body.get("kvkk_consent"))
    marketing_consent = bool(body.get("marketing_consent"))

    if not kvkk_consent:
        return jsonify({"error": "kvkk_consent_required",
                        "message": "KVKK aydınlatma metnini kabul etmelisiniz."}), 400
    try:
        email = _normalize_email(raw_email)
    except ValueError as exc:
        return jsonify({"error": "invalid_email", "message": str(exc)}), 400
    if not is_strong_password(password):
        return jsonify({"error": "weak_password",
                        "message": "Şifre en az 10 karakter ve birden fazla karakter sınıfı içermelidir."}), 400

    existing = db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        return jsonify({"error": "email_in_use",
                        "message": "Bu e-posta ile bir hesap zaten var."}), 409

    now = now_utc()
    # İlk 100 kayıtlı kullanıcıya ömür boyu premium
    existing_count = db.session.query(User).count()
    grant_lifetime = existing_count < 100
    user = User(
        email=email,
        password_hash=hash_password(password),
        kvkk_consent_at=now,
        marketing_consent_at=now if marketing_consent else None,
        plan="premium" if grant_lifetime else "free",
        subscription_status="lifetime" if grant_lifetime else "none",
    )
    db.session.add(user)
    db.session.flush()

    plain, hashed = generate_token()
    db.session.add(EmailToken(
        user_id=user.id,
        kind="verify",
        token_hash=hashed,
        expires_at=token_expiry(hours=24),
    ))
    db.session.commit()

    send_verify_email(user.email, plain)
    login_user(user)
    user.last_login_at = now
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_public_dict()}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    try:
        email = _normalize_email((body.get("email") or "").strip())
    except ValueError:
        return jsonify({"error": "invalid_credentials"}), 401
    password = body.get("password") or ""

    user = db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return jsonify({"error": "invalid_credentials",
                        "message": "E-posta veya şifre hatalı."}), 401

    login_user(user, remember=True)
    user.last_login_at = now_utc()
    if ADMIN_EMAILS:
        should_be_admin = user.email in ADMIN_EMAILS
        if user.is_admin != should_be_admin:
            user.is_admin = should_be_admin
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_public_dict()})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    return jsonify({
        "authenticated": True,
        "user": current_user.to_public_dict(),
    })


@auth_bp.route("/forgot", methods=["POST"])
def forgot():
    body = request.get_json(silent=True) or {}
    try:
        email = _normalize_email((body.get("email") or "").strip())
    except ValueError:
        return jsonify({"ok": True})  # Don't leak existence
    user = db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        plain, hashed = generate_token()
        token_row = EmailToken(
            user_id=user.id,
            kind="reset",
            token_hash=hashed,
            expires_at=token_expiry(hours=1),
        )
        db.session.add(token_row)
        db.session.commit()
        sent = send_password_reset(user.email, plain)
        if not sent:
            db.session.delete(token_row)
            db.session.commit()
            return jsonify({"ok": False, "error": "email_send_failed"}), 500
    return jsonify({"ok": True})


@auth_bp.route("/reset", methods=["POST"])
def reset():
    body = request.get_json(silent=True) or {}
    token = body.get("token") or ""
    new_password = body.get("password") or ""
    if not token or not is_strong_password(new_password):
        return jsonify({"error": "invalid_request"}), 400

    et = db.session.execute(
        select(EmailToken).where(EmailToken.token_hash == hash_token(token), EmailToken.kind == "reset")
    ).scalar_one_or_none()
    if not et or et.used_at is not None:
        return jsonify({"error": "invalid_token"}), 400
    expires = et.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now_utc():
        return jsonify({"error": "expired"}), 400

    user = db.session.get(User, et.user_id)
    if not user:
        return jsonify({"error": "invalid_token"}), 400
    user.password_hash = hash_password(new_password)
    et.used_at = now_utc()
    db.session.commit()
    return jsonify({"ok": True})


@auth_bp.route("/verify", methods=["POST"])
def verify_post():
    body = request.get_json(silent=True) or {}
    token = body.get("token") or ""
    if not token:
        return jsonify({"error": "invalid_request"}), 400
    et = db.session.execute(
        select(EmailToken).where(EmailToken.token_hash == hash_token(token), EmailToken.kind == "verify")
    ).scalar_one_or_none()
    if not et or et.used_at is not None:
        return jsonify({"error": "invalid_token"}), 400
    expires = et.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now_utc():
        return jsonify({"error": "expired"}), 400
    user = db.session.get(User, et.user_id)
    if not user:
        return jsonify({"error": "invalid_token"}), 400
    user.email_verified_at = now_utc()
    et.used_at = now_utc()
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_public_dict()})


# Browser-friendly link target
@auth_bp.route("/verify", methods=["GET"], strict_slashes=False)
def verify_get():
    token = request.args.get("token", "")
    if not token:
        return redirect(f"{APP_BASE_URL}/?verify=missing")
    et = db.session.execute(
        select(EmailToken).where(EmailToken.token_hash == hash_token(token), EmailToken.kind == "verify")
    ).scalar_one_or_none()
    if not et or et.used_at is not None:
        return redirect(f"{APP_BASE_URL}/?verify=invalid")
    expires = et.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now_utc():
        return redirect(f"{APP_BASE_URL}/?verify=expired")
    user = db.session.get(User, et.user_id)
    if not user:
        return redirect(f"{APP_BASE_URL}/?verify=invalid")
    user.email_verified_at = now_utc()
    et.used_at = now_utc()
    db.session.commit()
    return redirect(f"{APP_BASE_URL}/?verify=ok")


@auth_bp.route("/resend-verify", methods=["POST"])
@login_required
def resend_verify():
    if current_user.email_verified_at:
        return jsonify({"ok": True})
    plain, hashed = generate_token()
    db.session.add(EmailToken(
        user_id=current_user.id,
        kind="verify",
        token_hash=hashed,
        expires_at=token_expiry(hours=24),
    ))
    db.session.commit()
    sent = send_verify_email(current_user.email, plain)
    if not sent:
        return jsonify({"ok": False, "error": "email_send_failed"}), 500
    return jsonify({"ok": True})


# KVKK rights ──────────────────────────────────────────────────────────────

@auth_bp.route("/me", methods=["DELETE"])
@login_required
def delete_account():
    """KVKK Madde 11 — silme hakkı. LS aboneliği iptal etmeyi billing.py yapar."""
    user = current_user._get_current_object()
    user_id = user.id
    # LS subscription cancellation
    try:
        from .billing import cancel_subscription
        if user.ls_subscription_id:
            cancel_subscription(user.ls_subscription_id)
    except Exception:
        logger.exception("LS abonelik iptali hatası — devam ediliyor")
    logout_user()
    db.session.delete(user)
    db.session.commit()
    logger.info("KVKK silme: user_id=%s", user_id)
    return jsonify({"ok": True})


@auth_bp.route("/export", methods=["GET"])
@login_required
def export_data():
    """KVKK veri taşınabilirliği — kullanıcının tüm verisi JSON."""
    u = current_user._get_current_object()
    return jsonify({
        "user": u.to_public_dict(),
        "kvkk_consent_at": u.kvkk_consent_at.isoformat() if u.kvkk_consent_at else None,
        "marketing_consent_at": u.marketing_consent_at.isoformat() if u.marketing_consent_at else None,
        "alerts": [a.to_dict() for a in u.alerts],
        "watchlist": [{"symbol": w.symbol} for w in u.watchlist],
        "portfolio": [p.to_dict() for p in u.portfolio],
    })


@auth_bp.route("/consent", methods=["POST"])
@login_required
def update_consent():
    """Pazarlama izni güncelleme — KVKK uyumlu (ayrı consent)."""
    body = request.get_json(silent=True) or {}
    marketing = bool(body.get("marketing_consent"))
    u = current_user._get_current_object()
    u.marketing_consent_at = now_utc() if marketing else None
    db.session.commit()
    return jsonify({"ok": True, "marketing_consent": marketing})
