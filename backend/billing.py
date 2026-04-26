"""LemonSqueezy abonelik entegrasyonu — checkout, portal, webhook."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from .config import (
    APP_BASE_URL, LS_API_KEY, LS_STORE_ID, LS_VARIANT_MONTHLY, LS_VARIANT_YEARLY,
    LS_WEBHOOK_SECRET,
)
from .db import db
from .email import send_payment_failed
from .models import User, WebhookEvent

logger = logging.getLogger(__name__)
billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")

LS_API = "https://api.lemonsqueezy.com/v1"
LS_HEADERS = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
}


def _ls_headers() -> dict:
    return {**LS_HEADERS, "Authorization": f"Bearer {LS_API_KEY}"}


def cancel_subscription(subscription_id: str) -> bool:
    if not LS_API_KEY or not subscription_id:
        return False
    try:
        r = requests.delete(
            f"{LS_API}/subscriptions/{subscription_id}",
            headers=_ls_headers(),
            timeout=10,
        )
        return r.status_code < 400
    except requests.RequestException:
        logger.exception("LS cancel hatası")
        return False


# ── Endpoints ──────────────────────────────────────────────────────────────

@billing_bp.route("/plans", methods=["GET"])
def plans_endpoint():
    """Frontend pricing modal için."""
    from .limits import PLANS
    return jsonify({"plans": PLANS})


@billing_bp.route("/checkout", methods=["POST"])
@login_required
def create_checkout():
    body = request.get_json(silent=True) or {}
    period = body.get("period", "monthly")
    variant_id = LS_VARIANT_YEARLY if period == "yearly" else LS_VARIANT_MONTHLY

    if not LS_API_KEY or not LS_STORE_ID or not variant_id:
        # Dev modu: pricing sayfasına yönlendir
        logger.warning("LemonSqueezy ortam değişkenleri eksik — dev mock checkout")
        return jsonify({
            "url": f"{APP_BASE_URL}/?checkout=dev_mock_{period}",
            "dev": True,
        })

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": current_user.email,
                    "custom": {"user_id": current_user.id},
                },
                "product_options": {
                    "redirect_url": f"{APP_BASE_URL}/?checkout=success",
                },
                "checkout_options": {"embed": False, "media": False, "logo": True},
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": str(LS_STORE_ID)}},
                "variant": {"data": {"type": "variants", "id": str(variant_id)}},
            },
        }
    }
    try:
        r = requests.post(f"{LS_API}/checkouts", headers=_ls_headers(), json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        url = data.get("data", {}).get("attributes", {}).get("url")
        if not url:
            return jsonify({"error": "checkout_failed"}), 502
        return jsonify({"url": url})
    except requests.RequestException as exc:
        logger.exception("LS checkout hatası")
        return jsonify({"error": "checkout_failed", "detail": str(exc)}), 502


@billing_bp.route("/portal", methods=["POST"])
@login_required
def customer_portal():
    if not LS_API_KEY or not current_user.ls_customer_id:
        return jsonify({"error": "no_subscription"}), 400
    try:
        r = requests.get(
            f"{LS_API}/customers/{current_user.ls_customer_id}",
            headers=_ls_headers(),
            timeout=10,
        )
        r.raise_for_status()
        url = r.json().get("data", {}).get("attributes", {}).get("urls", {}).get("customer_portal")
        if not url:
            return jsonify({"error": "no_portal"}), 502
        return jsonify({"url": url})
    except requests.RequestException:
        logger.exception("LS portal hatası")
        return jsonify({"error": "portal_failed"}), 502


# ── Webhook ────────────────────────────────────────────────────────────────

@billing_bp.route("/webhook", methods=["POST"])
def webhook():
    raw = request.get_data()
    signature = request.headers.get("X-Signature", "")

    if not LS_WEBHOOK_SECRET:
        logger.error("LS webhook secret tanımsız — request reddedildi")
        return jsonify({"error": "not_configured"}), 503

    expected = hmac.new(LS_WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning("LS webhook imza geçersiz")
        return jsonify({"error": "invalid_signature"}), 401

    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({"error": "invalid_json"}), 400

    meta = payload.get("meta") or {}
    event_id = str(meta.get("event_id") or meta.get("webhook_id") or "")
    event_name = meta.get("event_name") or ""
    custom_data = (meta.get("custom_data") or {})
    user_id = custom_data.get("user_id")

    if not event_id or not event_name:
        return jsonify({"error": "invalid_event"}), 400

    # Idempotency
    existing = db.session.execute(
        select(WebhookEvent).where(WebhookEvent.ls_event_id == event_id)
    ).scalar_one_or_none()
    if existing and existing.processed_at:
        return jsonify({"ok": True, "duplicate": True})
    if not existing:
        existing = WebhookEvent(ls_event_id=event_id, event_name=event_name, body=payload)
        db.session.add(existing)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({"ok": True, "duplicate": True})

    data_attrs = (payload.get("data") or {}).get("attributes") or {}
    user = None
    if user_id:
        user = db.session.get(User, user_id)
    if user is None:
        # Email fallback
        email = data_attrs.get("user_email") or data_attrs.get("customer_email")
        if email:
            user = db.session.execute(
                select(User).where(User.email == email.lower())
            ).scalar_one_or_none()

    if user is None:
        logger.warning("LS webhook user bulunamadı: event=%s", event_name)
        existing.processed_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"ok": True})

    status = data_attrs.get("status")
    sub_id = (payload.get("data") or {}).get("id")
    customer_id = data_attrs.get("customer_id")
    variant_id = data_attrs.get("variant_id")
    renews_at = _parse_dt(data_attrs.get("renews_at"))
    ends_at = _parse_dt(data_attrs.get("ends_at"))

    if event_name in ("subscription_created", "subscription_updated", "subscription_resumed", "subscription_unpaused"):
        user.subscription_status = status or "active"
        if status in ("active", "on_trial"):
            user.plan = "premium"
        if sub_id:
            user.ls_subscription_id = str(sub_id)
        if customer_id:
            user.ls_customer_id = str(customer_id)
        if variant_id:
            user.ls_variant_id = str(variant_id)
        user.subscription_renews_at = renews_at
        user.subscription_ends_at = ends_at
    elif event_name == "subscription_cancelled":
        user.subscription_status = "cancelled"
        user.subscription_ends_at = ends_at
        # plan='premium' kalır ends_at'a kadar
    elif event_name == "subscription_expired":
        user.subscription_status = "expired"
        user.plan = "free"
    elif event_name == "subscription_payment_failed":
        user.subscription_status = "past_due"
        try:
            send_payment_failed(user.email)
        except Exception:
            logger.exception("Payment failed mail hatası")
    elif event_name == "subscription_payment_success":
        if status:
            user.subscription_status = status
        user.subscription_renews_at = renews_at
    else:
        logger.info("LS webhook ignored: %s", event_name)

    existing.processed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True})


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # LS formatı: "2024-12-04T05:00:00.000000Z"
        v = value.rstrip("Z")
        # Microseconds may have 6 digits
        if "." in v:
            return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    except Exception:
        return None
