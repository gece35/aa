"""SQLAlchemy modelleri — User, Alert, Watchlist, Portfolio, WebhookEvent, EmailToken."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import db


def _uuid() -> str:
    return str(uuid.uuid4())


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    email_verified_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    kvkk_consent_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    marketing_consent_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free")  # 'free' | 'premium'
    subscription_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    subscription_renews_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_ends_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    ls_customer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ls_subscription_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ls_variant_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    watchlist: Mapped[list["Watchlist"]] = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    portfolio: Mapped[list["Portfolio"]] = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
    email_tokens: Mapped[list["EmailToken"]] = relationship("EmailToken", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_premium(self) -> bool:
        if self.plan != "premium":
            return False
        if self.subscription_status == "lifetime":
            return True
        if self.subscription_status in ("active", "on_trial"):
            return True
        # Cancelled but still in paid period
        if self.subscription_status == "cancelled" and self.subscription_ends_at:
            return self.subscription_ends_at.timestamp() > time.time()
        return False

    @property
    def is_lifetime(self) -> bool:
        return self.plan == "premium" and self.subscription_status == "lifetime"

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "plan": "premium" if self.is_premium else "free",
            "subscription_status": self.subscription_status,
            "subscription_renews_at": self.subscription_renews_at.isoformat() if self.subscription_renews_at else None,
            "subscription_ends_at": self.subscription_ends_at.isoformat() if self.subscription_ends_at else None,
            "is_admin": self.is_admin,
            "is_lifetime": self.is_lifetime,
            "email_verified": bool(self.email_verified_at),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "can_manage_billing": bool(self.ls_customer_id),
            "marketing_consent": bool(self.marketing_consent_at),
        }


class Alert(db.Model):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    triggered_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_user_active", "user_id", "is_active", "dismissed"),
        Index("ix_alerts_triggered", "user_id", "triggered_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "condition_type": self.condition_type,
            "condition_value": self.condition_value,
            "label": self.label,
            "created_at": int(self.created_at.timestamp()) if self.created_at else None,
            "triggered_at": int(self.triggered_at.timestamp()) if self.triggered_at else None,
            "is_active": self.is_active,
            "dismissed": self.dismissed,
        }


class Watchlist(db.Model):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="watchlist")


class Portfolio(db.Model):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="TRY")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="portfolio")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "currency": self.currency,
        }


class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ls_event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[dict] = mapped_column(JSON, nullable=False)
    received_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)


class StockComment(db.Model):
    __tablename__ = "stock_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_email": self.user.email[:3] + "***" + self.user.email[self.user.email.index("@"):] if "@" in self.user.email else "***",
            "user_id": self.user_id,
            "body": self.body,
            "created_at": int(self.created_at.timestamp()) if self.created_at else None,
        }


class TweetLog(db.Model):
    """Otomatik atılan tweetleri takip eder — aynı hisseyi 24 saat içinde tekrar paylaşmamak için."""
    __tablename__ = "tweet_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    tweet_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tweeted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_tweet_logs_symbol_date", "symbol", "tweeted_at"),
    )


class EmailToken(db.Model):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # 'verify' | 'reset' | 'magic'
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="email_tokens")
