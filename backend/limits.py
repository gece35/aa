"""Free vs Premium plan limitleri ve gating decorator'ları."""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Optional

from flask import jsonify
from flask_login import current_user

logger = logging.getLogger(__name__)

# Plan tanımları — UI ve backend tek noktadan okur.
PLANS = {
    "free": {
        "label": "Bedava",
        "price_try": 0,
        "markets": ["bist"],
        "max_bist_tickers": 50,
        "allow_force_refresh": False,
        "stock_detail_per_day": 10,
        "stock_news_per_stock": False,
        "watchlist_max": 5,
        "portfolio_max": 3,
        "alerts_max": 3,
        "alert_check_interval_seconds": 3600,
        "patterns_full": False,
        "csv_export": False,
    },
    "premium": {
        "label": "Premium",
        "price_try_monthly": 149,
        "price_try_yearly": 1290,
        "markets": ["bist", "us"],
        "max_bist_tickers": None,  # unlimited
        "allow_force_refresh": True,
        "stock_detail_per_day": None,
        "stock_news_per_stock": True,
        "watchlist_max": 100,
        "portfolio_max": 50,
        "alerts_max": 50,
        "alert_check_interval_seconds": 300,
        "patterns_full": True,
        "csv_export": True,
    },
}


class PlanLimitError(Exception):
    def __init__(self, message: str, code: str = "plan_limit"):
        super().__init__(message)
        self.message = message
        self.code = code


def get_plan(user) -> dict:
    if user is None or not getattr(user, "is_authenticated", False):
        return PLANS["free"]
    return PLANS["premium"] if getattr(user, "is_premium", False) else PLANS["free"]


def requires_plan(plan_name: str):
    """Decorator: yalnızca verilen plan veya üstü erişebilir."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({"error": "auth_required",
                                "message": "Bu özellik için giriş yapmanız gerekir."}), 401
            if plan_name == "premium" and not current_user.is_premium:
                return jsonify({
                    "error": "premium_required",
                    "message": "Bu özellik Premium aboneliğine özeldir.",
                    "upgrade_url": "/pricing",
                }), 402
            return fn(*args, **kwargs)
        return wrapper
    return deco


def quota(scope: str, per: str = "day"):
    """Günlük kullanım limiti — Redis varsa Redis, yoksa in-memory counter."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({"error": "auth_required"}), 401
            plan = get_plan(current_user)
            limit_key = f"{scope}_per_{per}"
            limit = plan.get(limit_key)
            if limit is None:  # premium / unlimited
                return fn(*args, **kwargs)
            from .quota_store import incr_and_get
            count = incr_and_get(current_user.id, scope, per)
            if count > limit:
                return jsonify({
                    "error": "quota_exceeded",
                    "message": f"Günlük {scope} limiti aşıldı (Premium ile sınırsız).",
                    "upgrade_url": "/pricing",
                }), 429
            return fn(*args, **kwargs)
        return wrapper
    return deco


def enforce_collection_limit(user, collection: str, current_count: int) -> Optional[str]:
    """Watchlist / portfolio / alerts ekleme öncesi çağrılır. Hata mesajı ya da None döner."""
    plan = get_plan(user)
    key_map = {
        "watchlist": "watchlist_max",
        "portfolio": "portfolio_max",
        "alerts": "alerts_max",
    }
    key = key_map.get(collection)
    if not key:
        return None
    limit = plan.get(key)
    if limit is not None and current_count >= limit:
        return f"Plan limiti: en fazla {limit} {collection} ekleyebilirsiniz."
    return None
