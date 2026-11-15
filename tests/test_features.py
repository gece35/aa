"""Faz 4: sektör alanı, SEO hisse sayfaları + sitemap, haftalık bülten."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

SNAPSHOT = {
    "symbol": "THYAO.IS", "score": 7, "price": 320.25, "change_pct": 1.2,
    "change_week_pct": -2.5, "change_month_pct": 8.0, "volume": 1000,
    "high_52w": 350.0, "low_52w": 210.5, "sparkline": [1, 2, 3],
    "indicators": [
        {"name": "RSI Durumu", "key": "rsi", "score": 1.5, "max_score": 2.0, "value": 58.0,
         "detail": "RSI 58 — <script>alert(1)</script> sağlıklı bölge"},
        {"name": "Genişleme Riski", "key": "extension", "score": -0.5, "max_score": 0.0, "value": 0.9,
         "detail": "hafif uzamış"},
    ],
    "volume_spike": True, "near_peak": False, "entry_signal": True, "sector": "aviation",
}


# ── Sektör ───────────────────────────────────────────────────────────────────

def test_scan_rows_carry_sector_and_config_exposes_labels(client, monkeypatch):
    from backend import scanner
    from tests.test_infra import _fake_ohlcv

    monkeypatch.setattr(scanner, "download_ohlcv",
                        lambda tickers, period="300d", interval="1d": {t: _fake_ohlcv(seed=3) for t in tickers})
    monkeypatch.setattr(scanner, "get_index_df", lambda market: None)
    rows = scanner.scan_market_chunk("bist", 0, 3)["results"]
    labels = client.get("/api/config").get_json()["sector_labels"]
    assert rows and all(r["sector"] in labels for r in rows)
    assert labels["bank"] == "Bankacılık"


# ── SEO hisse sayfaları ──────────────────────────────────────────────────────

def test_stock_page_renders_public_summary_only(client):
    from backend.cache import symbol_cache

    symbol_cache.set("sym:THYAO.IS", SNAPSHOT)
    r = client.get("/hisse/THYAO")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "text/html" in r.content_type
    assert "<title>THYAO Hisse Teknik Analiz: 7/10 Puan (BIST) | Nebula Scanner</title>" in html
    assert 'rel="canonical" href="http://localhost:5000/hisse/THYAO"' in html
    assert "₺320,25" in html and "%+1,20" in html and "%-2,50" in html
    assert "Havacılık ve Ulaştırma" in html and "application/ld+json" in html
    assert 'href="/hisse/PGSUS"' in html                       # aynı sektörden iç link
    assert "<script>alert(1)</script>" not in html             # gösterge metni kaçışlı
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    for secret in ("TDOV", "entry_signal", "Giriş sinyali"):   # üyeye/admin'e özel bilgi sızmaz
        assert secret not in html
    assert "noindex" not in html


@pytest.mark.parametrize("path,target", [
    ("/hisse/thyao", "/hisse/THYAO"), ("/hisse/THYAO.IS", "/hisse/THYAO"), ("/hisse/aapl", "/hisse/AAPL"),
])
def test_stock_page_has_single_canonical_url(client, path, target):
    r = client.get(path)
    assert r.status_code == 301 and r.headers["Location"].endswith(target)


def test_unknown_stock_is_html_404_without_download(client, monkeypatch):
    from backend import data_fetcher

    monkeypatch.setattr(data_fetcher, "download_ohlcv",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("indirme yapılmamalı")))
    r = client.get("/hisse/YOKBOYLE")
    assert r.status_code == 404 and "noindex" in r.get_data(as_text=True)


def test_stock_page_without_data_is_503_and_negative_cached(client, monkeypatch):
    from backend import data_fetcher

    calls = []
    monkeypatch.setattr(data_fetcher, "download_ohlcv", lambda tickers, **k: calls.append(tickers) or {})
    for _ in range(3):
        r = client.get("/hisse/GARAN")
        assert r.status_code == 503 and r.headers["Retry-After"] == "3600"
        assert r.headers["X-Robots-Tag"] == "noindex" and 'content="noindex"' in r.get_data(as_text=True)
    assert len(calls) == 1                                     # başarısız sonuç kısa süre önbellekte


def test_stock_index_and_sitemap_cover_all_tickers(client):
    from backend.tickers import BIST_TICKERS, US_TICKERS

    total = len(BIST_TICKERS) + len(US_TICKERS)
    index = client.get("/hisseler")
    assert index.status_code == 200
    assert index.get_data(as_text=True).count('href="/hisse/') == total

    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200 and "xml" in sm.content_type
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = ET.fromstring(sm.data).findall("s:url", ns)
    locs = [u.find("s:loc", ns).text for u in urls]
    assert len(locs) == len(set(locs))
    assert sum("/hisse/" in loc for loc in locs) == total
    for expected in ("/", "/hisseler", "/rehber", "/blog/rsi-gostergesi-nedir", "/legal/risk", "/hisse/THYAO", "/hisse/AAPL"):
        assert f"http://localhost:5000{expected}" in locs
    assert all(u.find("s:lastmod", ns) is not None for u in urls)
    assert not any(loc.endswith(".html") for loc in locs)


# ── Haftalık bülten ──────────────────────────────────────────────────────────

DIGEST = {"subject": "Nebula Scanner — Haftalık piyasa özeti", "sections": [{
    "title": "BIST", "index_label": "BIST 100", "index_week": 1.5, "regime_ok": True,
    "rows": [{"name": "THYAO", "score": 9, "price": "₺320,25", "week": 4.2}],
}]}


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_issue_window_is_sunday_morning_plus_two_days():
    from backend.newsletter import current_issue

    assert current_issue(_utc(2026, 11, 15, 6, 59)) is None          # Pazar, saat gelmedi
    assert current_issue(_utc(2026, 11, 15, 7, 0)) == "2026-11-15"   # Pazar 10:00 TSİ
    assert current_issue(_utc(2026, 11, 17, 23, 0)) == "2026-11-15"  # Salı: aynı sayı (kalanlar)
    assert current_issue(_utc(2026, 11, 18, 7, 0)) is None           # Çarşamba: pencere kapandı
    assert current_issue(_utc(2026, 11, 14, 12, 0)) is None          # Cumartesi


@pytest.fixture()
def mailbox(monkeypatch):
    import backend.email as email_mod
    import backend.newsletter as nl

    sent = []
    monkeypatch.setattr(email_mod, "_send",
                        lambda to, subject, html, text=None: sent.append((to, subject, html, text)) or True)
    monkeypatch.setattr(nl, "build_weekly_digest", lambda: DIGEST)
    monkeypatch.setattr(nl.time, "sleep", lambda s: None)
    monkeypatch.setitem(nl._sent_today, "day", None)
    monkeypatch.setitem(nl._sent_today, "count", 0)
    return sent


def _subscribe(app, *emails):
    from backend.db import db
    from backend.newsletter import subscribe_email

    with app.app_context():
        for e in emails:
            subscribe_email(e)
        db.session.commit()


def test_newsletter_is_off_by_default(app, mailbox, monkeypatch):
    from backend import newsletter, scheduler

    monkeypatch.delenv("NEWSLETTER_ENABLED", raising=False)
    _subscribe(app, "a@example.com")
    with app.app_context():
        assert newsletter.send_weekly_issue(now=_utc(2026, 11, 15, 8))["sent"] == 0
        monkeypatch.setattr(scheduler, "_last_prices", lambda symbols: {})
        assert scheduler.run_due_jobs(force=True)["newsletter_sent"] == 0
    assert mailbox == []


def test_newsletter_sends_each_issue_once_and_skips_unsubscribed(app, mailbox, monkeypatch, make_user):
    from backend import newsletter
    from backend.db import db
    from backend.models import NewsletterSubscriber, User
    from backend.security import now_utc

    monkeypatch.setenv("NEWSLETTER_ENABLED", "1")
    _subscribe(app, "a@example.com", "gone@example.com")
    member_id, _, _ = make_user("uye@example.com")
    make_user("izinsiz@example.com")
    with app.app_context():
        db.session.get(User, member_id).marketing_consent_at = now_utc()
        newsletter.unsubscribe_email("gone@example.com")
        db.session.commit()

        sunday = _utc(2026, 11, 15, 8)
        assert newsletter.send_weekly_issue(now=_utc(2026, 11, 14, 8))["sent"] == 0    # Cumartesi
        first = newsletter.send_weekly_issue(now=sunday)
        assert first["sent"] == 2 and first["issue"] == "2026-11-15"
        assert newsletter.send_weekly_issue(now=sunday)["sent"] == 0                    # aynı sayı tekrar gitmez
        assert newsletter.send_weekly_issue(now=_utc(2026, 11, 22, 8))["sent"] == 2     # sonraki hafta
        keys = {s.email: s.last_issue_key for s in db.session.query(NewsletterSubscriber)}
        assert keys["a@example.com"] == "2026-11-22" and keys["gone@example.com"] is None

    recipients = sorted(m[0] for m in mailbox[:2])
    assert recipients == ["a@example.com", "uye@example.com"]      # izin veren üye eklendi, diğerleri yok
    html, text = mailbox[0][2], mailbox[0][3]
    assert "/newsletter/unsubscribe?token=" in html and "/newsletter/unsubscribe?token=" in text
    assert "yatırım tavsiyesi değildir" in html and "/hisse/THYAO" in html


def test_newsletter_respects_daily_cap(app, mailbox, monkeypatch):
    from backend import newsletter

    monkeypatch.setenv("NEWSLETTER_ENABLED", "1")
    monkeypatch.setenv("NEWSLETTER_DAILY_CAP", "2")
    _subscribe(app, "a@example.com", "b@example.com", "c@example.com")
    with app.app_context():
        assert newsletter.send_weekly_issue(now=_utc(2026, 11, 15, 8))["sent"] == 2
        assert newsletter.send_weekly_issue(now=_utc(2026, 11, 15, 9))["sent"] == 0     # günlük sınır doldu
        assert newsletter.send_weekly_issue(now=_utc(2026, 11, 16, 8))["sent"] == 1     # kalan ertesi gün
    assert sorted(m[0] for m in mailbox) == ["a@example.com", "b@example.com", "c@example.com"]


def test_unsubscribe_requires_confirmation_and_clears_member_consent(app, client, make_user):
    from backend.db import db
    from backend.models import NewsletterSubscriber, User
    from backend.newsletter import subscribe_email, sync_member_subscriptions
    from backend.security import now_utc

    uid, email, _ = make_user("uye@example.com")
    with app.app_context():
        db.session.get(User, uid).marketing_consent_at = now_utc()
        sub, _ = subscribe_email(email, "member")
        db.session.commit()
        token = sub.unsubscribe_token

    assert client.get("/newsletter/unsubscribe?token=yanlis").status_code == 404
    page = client.get(f"/newsletter/unsubscribe?token={token}")
    assert page.status_code == 200 and "Abonelikten çık" in page.get_data(as_text=True)
    with app.app_context():                                     # GET tek başına çıkarmaz
        assert db.session.query(NewsletterSubscriber).one().unsubscribed_at is None

    done = client.post("/newsletter/unsubscribe", data={"token": token})
    assert done.status_code == 200 and "Abonelikten çıktınız" in done.get_data(as_text=True)
    with app.app_context():
        assert db.session.query(NewsletterSubscriber).one().unsubscribed_at is not None
        assert db.session.get(User, uid).marketing_consent_at is None
        assert sync_member_subscriptions() == 0                  # yeniden eklenmez


def test_marketing_consent_toggles_subscription(app, client, make_user, login):
    from backend.newsletter import active_count

    _, email, password = make_user()
    login(email, password)
    assert client.post("/api/auth/consent", json={"marketing_consent": True}).status_code == 200
    with app.app_context():
        assert active_count() == 1
    client.post("/api/auth/consent", json={"marketing_consent": False})
    with app.app_context():
        assert active_count() == 0


def test_admin_newsletter_test_goes_only_to_admin(app, mailbox, make_user):
    _subscribe(app, "a@example.com")
    _, email, password = make_user("uye@example.com")
    member = app.test_client()
    member.post("/api/auth/login", json={"email": email, "password": password})
    assert member.post("/api/admin/newsletter/test").status_code == 403
    assert member.get("/api/admin/newsletter/preview").status_code == 403

    _, aemail, apassword = make_user("admin@example.com")
    admin = app.test_client()
    admin.post("/api/auth/login", json={"email": aemail, "password": apassword})
    preview = admin.get("/api/admin/newsletter/preview")
    assert preview.status_code == 200 and "Haftalık piyasa özeti" in preview.get_data(as_text=True)

    r = admin.post("/api/admin/newsletter/test")
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True and body["sent_to"] == "admin@example.com"
    assert body["active_subscribers"] == 1 and body["enabled"] is False
    assert [m[0] for m in mailbox] == ["admin@example.com"]      # aboneye gitmedi
    assert mailbox[0][1].startswith("[TEST]")


def test_stock_page_does_not_block_threads_when_another_fetch_is_running(client, monkeypatch):
    """Önbelleksiz hisse sayfası, başka bir indirme sürerken sınırsız beklemez."""
    from backend import seo

    monkeypatch.setattr(seo, "_FETCH_WAIT_SECONDS", 0.05)
    assert seo._fetch_lock.acquire(timeout=1)
    try:
        r = client.get("/hisse/GARAN")
    finally:
        seo._fetch_lock.release()
    assert r.status_code == 503 and r.headers["Retry-After"] == "120"
    assert seo.seo_cache.get("miss:GARAN.IS") is None      # meşgul ≠ veri yok: negatif önbelleğe yazılmaz
