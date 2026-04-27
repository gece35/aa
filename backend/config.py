"""Tek noktada toplanan environment yapılandırması."""

from __future__ import annotations

import os
from typing import Set

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def _csv(name: str) -> Set[str]:
    raw = os.environ.get(name, "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-do-not-use-in-prod")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
DEBUG = _bool("DEBUG", False)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Database — Postgres in prod, SQLite fallback for local dev
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///nebula_dev.db")
# Railway sometimes provides "postgres://" which SQLAlchemy 2.x rejects
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

REDIS_URL = os.environ.get("REDIS_URL", "")

# LemonSqueezy
LS_API_KEY = os.environ.get("LEMONSQUEEZY_API_KEY", "")
LS_STORE_ID = os.environ.get("LEMONSQUEEZY_STORE_ID", "")
LS_WEBHOOK_SECRET = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")
LS_VARIANT_MONTHLY = os.environ.get("LEMONSQUEEZY_VARIANT_PREMIUM_MONTHLY", "")
LS_VARIANT_YEARLY = os.environ.get("LEMONSQUEEZY_VARIANT_PREMIUM_YEARLY", "")

# Email
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Nebula Scanner <noreply@nebulascanner.com>")

# Monitoring
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

# Legal entity (rendered in footer)
LEGAL_ENTITY_NAME = os.environ.get("LEGAL_ENTITY_NAME", "Nebula Scanner")
LEGAL_ENTITY_ADDRESS = os.environ.get("LEGAL_ENTITY_ADDRESS", "")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "destek@nebulascanner.com")

ADMIN_EMAILS: Set[str] = _csv("ADMIN_EMAILS")

# SMTP (Gmail veya başka bir SMTP sunucusu ile ücretsiz e-posta)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# Google Analytics 4
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")
