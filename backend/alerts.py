"""Özelleştirilebilir alarm sistemi (multi-tenant, SQLAlchemy).

Desteklenen kriter tipleri:
  rsi_below, rsi_above      — RSI eşik değeri
  macd_cross_up             — MACD sinyali yukarı kesti
  macd_cross_down           — MACD sinyali aşağı kesti
  bb_lower_touch            — Bollinger alt banda değdi
  bb_upper_touch            — Bollinger üst banda değdi
  ema_cross_up              — Fiyat EMA50 üzerine çıktı
  score_above               — Skor eşiği aştı
  price_below, price_above  — Fiyat eşiği
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select, func as sa_func

from .db import db
from .models import Alert

logger = logging.getLogger(__name__)

CONDITION_LABELS = {
    "rsi_below":       "RSI <",
    "rsi_above":       "RSI >",
    "macd_cross_up":   "MACD Yukarı Kesti",
    "macd_cross_down": "MACD Aşağı Kesti",
    "bb_lower_touch":  "Bollinger Alt Band",
    "bb_upper_touch":  "Bollinger Üst Band",
    "ema_cross_up":    "EMA50 Üzerine Çıktı",
    "score_above":     "Skor ≥",
    "price_below":     "Fiyat <",
    "price_above":     "Fiyat >",
}


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_alert(
    user_id: str,
    symbol: str,
    condition_type: str,
    condition_value: Optional[float] = None,
) -> Dict:
    symbol = symbol.upper().strip()
    if condition_type not in CONDITION_LABELS:
        raise ValueError(f"Geçersiz kriter: {condition_type}")

    label_base = CONDITION_LABELS[condition_type]
    label = f"{label_base} {condition_value}" if condition_value is not None else label_base

    a = Alert(
        user_id=user_id,
        symbol=symbol,
        condition_type=condition_type,
        condition_value=condition_value,
        label=label,
        is_active=True,
        dismissed=False,
    )
    db.session.add(a)
    db.session.commit()
    return a.to_dict()


def list_alerts(user_id: str, include_dismissed: bool = False) -> List[Dict]:
    q = select(Alert).where(Alert.user_id == user_id)
    if not include_dismissed:
        q = q.where(Alert.dismissed == False)  # noqa: E712
    q = q.order_by(Alert.created_at.desc())
    rows = db.session.execute(q).scalars().all()
    return [a.to_dict() for a in rows]


def get_triggered(user_id: str, limit: int = 20) -> List[Dict]:
    q = (
        select(Alert)
        .where(
            Alert.user_id == user_id,
            Alert.triggered_at.is_not(None),
            Alert.dismissed == False,  # noqa: E712
        )
        .order_by(Alert.triggered_at.desc())
        .limit(limit)
    )
    rows = db.session.execute(q).scalars().all()
    return [a.to_dict() for a in rows]


def delete_alert(user_id: str, alert_id: str) -> bool:
    a = db.session.get(Alert, alert_id)
    if a is None or a.user_id != user_id:
        return False
    db.session.delete(a)
    db.session.commit()
    return True


def dismiss_alert(user_id: str, alert_id: str) -> bool:
    a = db.session.get(Alert, alert_id)
    if a is None or a.user_id != user_id:
        return False
    a.dismissed = True
    db.session.commit()
    return True


def count_active_alerts(user_id: str) -> int:
    return db.session.scalar(
        select(sa_func.count(Alert.id)).where(
            Alert.user_id == user_id,
            Alert.dismissed == False,  # noqa: E712
            Alert.triggered_at.is_(None),
        )
    ) or 0


# ── Alarm kontrol mantığı ──────────────────────────────────────────────────

def _check_single(alert: Alert, detail: Dict) -> bool:
    ct = alert.condition_type
    cv = alert.condition_value

    indicators: Dict[str, Any] = {
        ind["key"]: ind for ind in detail.get("indicators", [])
    }

    def ind_val(key: str) -> Optional[float]:
        return indicators.get(key, {}).get("value")

    def ind_sig(key: str) -> bool:
        return bool(indicators.get(key, {}).get("signal", False))

    if ct == "rsi_below":
        v = ind_val("rsi")
        return v is not None and cv is not None and v < cv

    if ct == "rsi_above":
        v = ind_val("rsi")
        return v is not None and cv is not None and v > cv

    if ct == "macd_cross_up":
        return ind_sig("macd")

    if ct == "macd_cross_down":
        v = ind_val("macd")
        return v is not None and v < 0

    if ct == "bb_lower_touch":
        return ind_sig("bbands")

    if ct == "bb_upper_touch":
        v = ind_val("bbands")
        return v is not None and v > 0.95

    if ct == "ema_cross_up":
        return ind_sig("ema50")

    if ct == "score_above":
        score = detail.get("score")
        return score is not None and cv is not None and score >= cv

    if ct == "price_below":
        price = detail.get("price")
        return price is not None and cv is not None and price < cv

    if ct == "price_above":
        price = detail.get("price")
        return price is not None and cv is not None and price > cv

    return False


def check_alerts_for_user(
    user_id: str,
    detail_fetcher: Callable[[str], Dict],
    notifier: Optional[Callable[[Alert], None]] = None,
) -> List[Dict]:
    """Bir kullanıcının aktif alarmlarını kontrol eder."""
    q = select(Alert).where(
        Alert.user_id == user_id,
        Alert.is_active == True,  # noqa: E712
        Alert.triggered_at.is_(None),
        Alert.dismissed == False,  # noqa: E712
    )
    active = db.session.execute(q).scalars().all()

    if not active:
        return []

    symbols = list({a.symbol for a in active})
    details: Dict[str, Dict] = {}
    for sym in symbols:
        try:
            details[sym] = detail_fetcher(sym) or {}
        except Exception as exc:
            logger.warning("Alarm kontrol verisi alinamadi %s: %s", sym, exc)

    triggered: List[Dict] = []
    now = datetime.now(timezone.utc)
    for alert in active:
        d = details.get(alert.symbol)
        if not d:
            continue
        try:
            fired = _check_single(alert, d)
        except Exception:
            continue
        if fired:
            alert.triggered_at = now
            alert.is_active = False
            triggered.append(alert.to_dict())
            if notifier:
                try:
                    notifier(alert)
                except Exception:
                    logger.exception("Alarm notifier hatası")
            logger.info("Alarm tetiklendi: user=%s %s %s", user_id, alert.symbol, alert.label)

    if triggered:
        db.session.commit()
    return triggered
