"""Newsletter abonelik sistemi."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

newsletter_bp = Blueprint("newsletter", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_STORE_PATH = os.environ.get("NEWSLETTER_FILE", "newsletter_subscribers.json")


def _load() -> list[dict]:
    if not os.path.isfile(_STORE_PATH):
        return []
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(subscribers: list[dict]) -> None:
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(subscribers, f, ensure_ascii=False, indent=2)


@newsletter_bp.route("/api/newsletter", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    kvkk = bool(data.get("kvkk_consent"))

    if not email or not _EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Geçerli bir e-posta adresi girin."}), 400
    if not kvkk:
        return jsonify({"ok": False, "error": "KVKK onayı zorunludur."}), 400

    subscribers = _load()
    if any(s["email"] == email for s in subscribers):
        return jsonify({"ok": True, "already": True, "message": "Bu e-posta zaten kayıtlı."})

    subscribers.append({
        "email": email,
        "subscribed_at": datetime.now(timezone.utc).isoformat(),
        "source": data.get("source", "website"),
        "kvkk_consent": True,
    })
    try:
        _save(subscribers)
    except Exception:
        logger.exception("Newsletter kayıt hatası")
        return jsonify({"ok": False, "error": "Kayıt sırasında hata oluştu."}), 500

    logger.info("Newsletter: yeni abone %s", email)
    return jsonify({"ok": True, "message": "Abone oldunuz! Her Pazar piyasa özetini e-postanızda bulacaksınız."})


@newsletter_bp.route("/api/newsletter/count")
def subscriber_count():
    """Kamuya açık abone sayısı (pazarlama sayacı için)."""
    return jsonify({"count": len(_load())})
