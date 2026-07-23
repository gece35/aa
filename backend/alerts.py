"""Özelleştirilebilir fiyat alarmı sistemi (multi-tenant, SQLAlchemy).

Kasıtlı olarak tek bir şeye odaklanır: bir hisse belirlenen fiyat seviyesinin
üstüne çıktığında ya da altına düştüğünde kullanıcıya haber vermek. Daha
önce RSI/MACD/Bollinger/EMA/skor gibi teknik kriterler de desteklenirdi;
genel kullanıcı kitlesi için anlaşılması zor olduğundan kaldırıldı — bkz.
CONDITION_LABELS.

Desteklenen kriter tipleri:
  price_below, price_above  — Fiyat eşiği
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import select, func as sa_func

from .db import db
from .models import Alert

logger = logging.getLogger(__name__)

CONDITION_LABELS = {
    "price_above": "Fiyat şu değerin üstüne çıkınca",
    "price_below": "Fiyat şu değerin altına düşünce",
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
    """Fiyat eşiği kontrolü. Eski (artık kaldırılmış) teknik kriter tiplerinde
    kurulmuş bir alarm varsa condition_type burada tanınmaz ve sessizce
    False döner — bir daha tetiklenmez, hata vermez."""
    ct = alert.condition_type
    cv = alert.condition_value
    price = detail.get("price")

    if ct == "price_below":
        return price is not None and cv is not None and price < cv

    if ct == "price_above":
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
