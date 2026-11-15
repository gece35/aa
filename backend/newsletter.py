"""Bülten aboneliği — aboneler veritabanında (NewsletterSubscriber) tutulur.

Eskiden aboneler çalışma dizinindeki bir JSON dosyasına yazılıyordu; Railway'in
diski kalıcı olmadığı için liste her deploy'da siliniyordu.
"""

from __future__ import annotations

import html as _html
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, or_, select, update

from .config import APP_BASE_URL
from .db import db
from .models import NewsletterSubscriber, User
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


# ── Abonelikten çıkış ────────────────────────────────────────────────────────

def _subscriber_by_token(token: str) -> Optional[NewsletterSubscriber]:
    token = str(token or "").strip()
    if not token or len(token) > 64:
        return None
    return db.session.execute(
        select(NewsletterSubscriber).where(NewsletterSubscriber.unsubscribe_token == token)
    ).scalar_one_or_none()


@newsletter_bp.route("/newsletter/unsubscribe", methods=["GET", "POST"])
@limiter.limit("30 per hour")
def unsubscribe_page():
    """E-postadaki "abonelikten çık" bağlantısı.

    GET yalnızca onay sayfasını gösterir; çıkış POST ile yapılır — e-posta
    istemcilerinin/güvenlik tarayıcılarının bağlantıyı önden açması kişiyi
    yanlışlıkla abonelikten çıkarmasın diye.
    """
    token = request.values.get("token", "")
    sub = _subscriber_by_token(token)
    if sub is None:
        return render_template("newsletter_unsubscribe.html", state="invalid", token=""), 404

    if request.method == "POST" and sub.unsubscribed_at is None:
        sub.unsubscribed_at = now_utc()
        # Üyeyse pazarlama iznini de kaldır; yoksa haftalık senkron yeniden eklerdi.
        user = db.session.execute(select(User).where(User.email == sub.email)).scalar_one_or_none()
        if user is not None:
            user.marketing_consent_at = None
        db.session.commit()
        logger.info("Newsletter: abonelikten çıkış")

    state = "done" if sub.unsubscribed_at is not None else "confirm"
    return render_template("newsletter_unsubscribe.html", state=state, token=token)


# ── Haftalık bülten ──────────────────────────────────────────────────────────

_SEND_WINDOW_DAYS = 3          # Pazar + 2 gün: günlük sınıra takılanlar ertesi gün gider
_SEND_HOUR_UTC = 7             # Pazar 10:00 (TSİ)
_PER_RUN_LIMIT = 40            # bir zamanlayıcı turunda en fazla bu kadar e-posta
_sent_today = {"day": None, "count": 0}


def newsletter_enabled() -> bool:
    return os.environ.get("NEWSLETTER_ENABLED", "0").lower() in ("1", "true", "yes", "on")


def _daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("NEWSLETTER_DAILY_CAP", "250")))
    except ValueError:
        return 250


def current_issue(now: Optional[datetime] = None) -> Optional[str]:
    """Şu an gönderilebilecek sayının anahtarı (o haftanın Pazar tarihi) ya da None.

    Pencere: Pazar 07:00 UTC'den başlayıp _SEND_WINDOW_DAYS gün sürer.
    """
    now = now or datetime.now(timezone.utc)
    days_since_sunday = (now.weekday() + 1) % 7      # Pazar=0, Pazartesi=1, ...
    sunday = (now - timedelta(days=days_since_sunday)).date()
    start = datetime(sunday.year, sunday.month, sunday.day, _SEND_HOUR_UTC, tzinfo=timezone.utc)
    if start <= now < start + timedelta(days=_SEND_WINDOW_DAYS):
        return sunday.isoformat()
    return None


def sync_member_subscriptions() -> int:
    """Pazarlama izni vermiş (e-postası doğrulanmış) üyeleri abone listesine ekler.
    Daha önce abonelikten çıkmış kişiler yeniden eklenmez."""
    existing = set(db.session.execute(select(NewsletterSubscriber.email)).scalars().all())
    emails = db.session.execute(
        select(User.email).where(
            User.marketing_consent_at.is_not(None),
            User.email_verified_at.is_not(None),
        )
    ).scalars().all()
    added = 0
    for email in emails:
        if email not in existing:
            db.session.add(NewsletterSubscriber(
                email=email, source="member", unsubscribe_token=secrets.token_urlsafe(32)))
            added += 1
    if added:
        db.session.commit()
    return added


def _top_rows(market: str, limit: int = 10) -> list:
    from .scanner import scan_market

    try:
        results = scan_market(market).get("results", [])
    except Exception:
        logger.exception("Bülten: %s taraması alınamadı", market)
        return []
    return results[:limit]


def build_weekly_digest() -> Optional[dict]:
    """Haftalık özetin içeriği. Veri alınamazsa None (boş bülten gönderilmez)."""
    from .scanner import build_index_summary
    from .tickers import strip_suffix

    sections = []
    for market, title, sign in (("bist", "BIST", "₺"), ("us", "ABD", "$")):
        rows = _top_rows(market)
        if not rows:
            continue
        index = build_index_summary(market) or {}
        sections.append({
            "title": title,
            "index_label": index.get("label"),
            "index_week": index.get("change_week_pct"),
            "regime_ok": index.get("regime_ok"),
            "rows": [{
                "name": strip_suffix(r["symbol"]),
                "score": r.get("score", 0),
                "price": f"{sign}{r.get('price', 0):,.2f}".replace(",", "§").replace(".", ",").replace("§", "."),
                "week": r.get("change_week_pct") or 0.0,
            } for r in rows],
        })
    if not sections:
        return None
    return {"subject": "Nebula Scanner — Haftalık piyasa özeti", "sections": sections}


def render_digest(digest: dict, unsubscribe_url: str) -> Tuple[str, str]:
    """(html, text) üretir."""
    base = APP_BASE_URL.rstrip("/")

    def pct(v) -> str:
        return f"%{'+' if v > 0 else ''}{v:.2f}".replace(".", ",")

    html_parts = [
        '<div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111;">',
        '<h2 style="margin-top:0;">Haftalık piyasa özeti</h2>',
        '<p style="color:#444;">Bu hafta teknik analiz puanı en yüksek hisseler. Puan 0-10 arasındadır; '
        'trend, momentum, Bollinger, ADX ve hacim göstergelerinden hesaplanır.</p>',
    ]
    text_parts = ["Nebula Scanner — Haftalık piyasa özeti", ""]
    for sec in digest["sections"]:
        head = sec["title"]
        if sec.get("index_label") and sec.get("index_week") is not None:
            head += f" — {sec['index_label']} haftalık {pct(sec['index_week'])}"
        html_parts.append(f'<h3 style="margin:24px 0 8px;">{_html.escape(head)}</h3>')
        if sec.get("regime_ok") is False:
            html_parts.append('<p style="color:#b45309;font-size:13px;margin:0 0 8px;">'
                              'Endeks uzun vadeli ortalamasının altında: genel görünüm zayıf.</p>')
        html_parts.append('<table style="width:100%;border-collapse:collapse;font-size:14px;">'
                          '<tr style="color:#666;text-align:left;"><th style="padding:6px 4px;">Hisse</th>'
                          '<th style="padding:6px 4px;">Puan</th><th style="padding:6px 4px;">Fiyat</th>'
                          '<th style="padding:6px 4px;">Haftalık</th></tr>')
        text_parts.append(head)
        for row in sec["rows"]:
            color = "#15803d" if row["week"] >= 0 else "#b91c1c"
            name = _html.escape(row["name"])
            html_parts.append(
                f'<tr style="border-top:1px solid #eee;">'
                f'<td style="padding:6px 4px;"><a href="{base}/hisse/{name}" style="color:#2563eb;text-decoration:none;font-weight:600;">{name}</a></td>'
                f'<td style="padding:6px 4px;">{int(row["score"])}/10</td>'
                f'<td style="padding:6px 4px;">{_html.escape(row["price"])}</td>'
                f'<td style="padding:6px 4px;color:{color};">{pct(row["week"])}</td></tr>')
            text_parts.append(f"  {row['name']}: {int(row['score'])}/10, {row['price']}, haftalık {pct(row['week'])}")
        html_parts.append("</table>")
        text_parts.append("")
    html_parts.append(
        f'<p style="text-align:center;margin:32px 0;"><a href="{base}/" style="background:#2563eb;color:#fff;'
        f'text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;">Tüm taramayı aç</a></p>'
        '<p style="color:#999;font-size:12px;">Bu e-posta yatırım tavsiyesi değildir; yalnızca geçmiş fiyat '
        'verisine dayalı teknik göstergelerin otomatik özetidir. Eğitim ve bilgilendirme amaçlıdır.</p>'
        f'<p style="color:#999;font-size:12px;">Bu bülteni almak istemiyorsanız '
        f'<a href="{_html.escape(unsubscribe_url)}" style="color:#999;">abonelikten çıkabilirsiniz</a>.</p></div>')
    text_parts += [f"Tüm tarama: {base}/", "",
                   "Bu e-posta yatırım tavsiyesi değildir; eğitim ve bilgilendirme amaçlıdır.",
                   f"Abonelikten çıkmak için: {unsubscribe_url}"]
    return "".join(html_parts), "\n".join(text_parts)


def unsubscribe_url_for(token: str) -> str:
    return f"{APP_BASE_URL.rstrip('/')}/newsletter/unsubscribe?token={token}"


def _claim_issue(subscriber_id: int, issue: str) -> bool:
    """Bu sayıyı bu aboneye göndermeyi atomik olarak sahiplenir: yalnızca ilk
    çağıran True alır — yeniden başlatma ya da çakışan deploy çift gönderemez."""
    res = db.session.execute(
        update(NewsletterSubscriber)
        .where(
            NewsletterSubscriber.id == subscriber_id,
            NewsletterSubscriber.unsubscribed_at.is_(None),
            or_(NewsletterSubscriber.last_issue_key.is_(None),
                NewsletterSubscriber.last_issue_key != issue),
        )
        .values(last_issue_key=issue)
    )
    db.session.commit()
    return res.rowcount == 1


def send_weekly_issue(now: Optional[datetime] = None, force: bool = False) -> dict:
    """Vakti geldiyse haftalık bülteni bekleyen abonelere gönderir.

    NEWSLETTER_ENABLED=1 değilse hiçbir şey yapmaz. Bir çağrıda en fazla
    _PER_RUN_LIMIT, bir günde en fazla NEWSLETTER_DAILY_CAP e-posta gönderir;
    kalanlar sonraki turlarda/ertesi gün gider.
    """
    from .email import _send

    out = {"enabled": newsletter_enabled(), "issue": None, "sent": 0, "pending": 0}
    if not out["enabled"]:
        return out
    now = now or datetime.now(timezone.utc)
    issue = current_issue(now) or (now.date().isoformat() if force else None)
    out["issue"] = issue
    if issue is None:
        return out

    today = now.date().isoformat()
    if _sent_today["day"] != today:
        _sent_today.update(day=today, count=0)
    budget = min(_PER_RUN_LIMIT, _daily_cap() - _sent_today["count"])
    if budget <= 0:
        return out

    sync_member_subscriptions()
    pending = db.session.execute(
        select(NewsletterSubscriber.id, NewsletterSubscriber.email, NewsletterSubscriber.unsubscribe_token)
        .where(
            NewsletterSubscriber.unsubscribed_at.is_(None),
            or_(NewsletterSubscriber.last_issue_key.is_(None),
                NewsletterSubscriber.last_issue_key != issue),
        )
        .order_by(NewsletterSubscriber.id)
        .limit(budget)
    ).all()
    db.session.rollback()  # gönderim sırasında açık transaction tutma
    out["pending"] = len(pending)
    if not pending:
        return out

    digest = build_weekly_digest()   # tarama yalnızca gönderilecek biri varken yapılır
    if digest is None:
        logger.warning("Bülten: veri alınamadı, bu tur gönderim yok")
        return out

    for row in pending:
        try:
            if not _claim_issue(row.id, issue):
                continue
        except Exception:
            db.session.rollback()
            logger.exception("Bülten: abone %s sahiplenilemedi", row.id)
            continue
        html, text = render_digest(digest, unsubscribe_url_for(row.unsubscribe_token))
        try:
            if _send(row.email, digest["subject"], html, text):
                out["sent"] += 1
        except Exception:
            logger.exception("Bülten e-postası gönderilemedi")
        _sent_today["count"] += 1
        time.sleep(0.25)
    if out["sent"]:
        logger.info("Bülten %s: %d e-posta gönderildi", issue, out["sent"])
    return out
