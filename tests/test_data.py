"""Faz 3: bülten/geri bildirim kalıcılığı, portföy alış tarihi, e-posta linkleri,
şema sağlık kontrolü, KVKK dışa aktarım/silme."""

from __future__ import annotations

from datetime import date, timedelta


# ── Bülten ───────────────────────────────────────────────────────────────────

def test_newsletter_subscribers_are_stored_in_database(app, client):
    from backend.db import db
    from backend.models import NewsletterSubscriber
    from backend.newsletter import active_count, unsubscribe_email

    assert client.post("/api/newsletter", json={"email": "gecersiz", "kvkk_consent": True}).status_code == 400
    assert client.post("/api/newsletter", json={"email": "a@example.com"}).status_code == 400   # KVKK yok

    r = client.post("/api/newsletter", json={"email": " A@Example.com ", "kvkk_consent": True, "source": "footer"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    again = client.post("/api/newsletter", json={"email": "a@example.com", "kvkk_consent": True})
    assert again.get_json().get("already") is True
    assert client.get("/api/newsletter/count").get_json()["count"] == 1

    with app.app_context():
        sub = db.session.query(NewsletterSubscriber).one()
        assert sub.email == "a@example.com" and sub.source == "footer"
        assert len(sub.unsubscribe_token) >= 32 and sub.is_active
        token = sub.unsubscribe_token

        assert unsubscribe_email("a@example.com") is True
        db.session.commit()
        assert active_count() == 0

    # Yeniden abone olunca aynı kayıt etkinleşir (çıkış anahtarı değişmez)
    back = client.post("/api/newsletter", json={"email": "a@example.com", "kvkk_consent": True})
    assert back.get_json().get("already") is None
    with app.app_context():
        sub = db.session.query(NewsletterSubscriber).one()
        assert sub.is_active and sub.unsubscribe_token == token


# ── Geri bildirim ────────────────────────────────────────────────────────────

def test_feedback_is_stored_and_readable_by_admin_only(app, client, make_user, login):
    assert client.post("/api/feedback", json={"message": ""}).status_code == 400
    r = client.post("/api/feedback", json={"category": "hata", "message": "Grafik açılmıyor",
                                           "email": "misafir@example.com"})
    assert r.status_code == 200

    _, email, password = make_user("uye@example.com")
    member = app.test_client()
    member.post("/api/auth/login", json={"email": email, "password": password})
    # Üyenin e-postası istemciden değil oturumdan alınır
    member.post("/api/feedback", json={"category": "bilinmeyen", "message": "Öneri", "email": "sahte@example.com"})

    assert client.get("/api/admin/feedback").status_code == 401
    assert member.get("/api/admin/feedback").status_code == 403

    _, aemail, apassword = make_user("admin@example.com")
    admin = app.test_client()
    admin.post("/api/auth/login", json={"email": aemail, "password": apassword})
    rows = admin.get("/api/admin/feedback").get_json()["feedback"]
    assert [(f["category"], f["message"], f["email"]) for f in rows] == [
        ("genel", "Öneri", "uye@example.com"),
        ("hata", "Grafik açılmıyor", "misafir@example.com"),
    ]
    stats = admin.get("/api/admin/stats").get_json()
    assert stats["feedback_count"] == 2 and stats["newsletter_subscribers"] == 0


# ── Portföy alış tarihi ──────────────────────────────────────────────────────

def test_portfolio_buy_date_roundtrip(client, make_user, login):
    _, email, password = make_user()
    login(email, password)
    base = {"symbol": "THYAO.IS", "qty": 10, "avg_price": 250.5, "currency": "TRY"}

    ok = client.post("/api/portfolio", json={**base, "buy_date": "2026-03-15"})
    assert ok.status_code == 201 and ok.get_json()["position"]["buy_date"] == "2026-03-15"

    future = (date.today() + timedelta(days=5)).isoformat()
    for bad in ("15.03.2026", "", None, future):
        r = client.post("/api/portfolio", json={**base, "buy_date": bad})
        assert r.status_code == 201 and r.get_json()["position"]["buy_date"] is None

    listed = client.get("/api/portfolio").get_json()["portfolio"]
    assert [p["buy_date"] for p in listed].count("2026-03-15") == 1


# ── E-posta linkleri ─────────────────────────────────────────────────────────

def test_alert_email_links_to_working_deep_link(monkeypatch):
    import backend.email as email_mod

    sent = {}

    def fake_send(to, subject, html, text=None):
        sent.update(to=to, subject=subject, html=html, text=text)
        return True

    monkeypatch.setattr(email_mod, "_send", fake_send)
    assert email_mod.send_alert_triggered("u@example.com", "THYAO.IS", "Fiyat <100> üstü") is True
    assert "/?s=THYAO.IS" in sent["html"] and "/?s=THYAO.IS" in sent["text"]
    assert "focus=" not in sent["html"] and "focus=" not in sent["text"]
    assert "&lt;100&gt;" in sent["html"]                      # etiket HTML'de kaçışlı

    email_mod.send_payment_failed("u@example.com")
    assert "/account" not in sent["html"] and "/account" not in sent["text"]


# ── Sağlık ucu: şema geride ise 503 ──────────────────────────────────────────

def test_health_fails_when_schema_is_behind(client, monkeypatch):
    from backend import migrate_boot

    assert client.get("/api/health").status_code == 200
    monkeypatch.setattr(migrate_boot, "current_revision", lambda conn=None: "b3c4d5e6f7a8")
    r = client.get("/api/health")
    assert r.status_code == 503
    body = r.get_json()
    assert body["ok"] is False and body["schema_ok"] is False and body["db"] is True


# ── KVKK: dışa aktarım ve silme ──────────────────────────────────────────────

def test_export_includes_comments_and_delete_removes_them(app, client, make_user, login):
    from backend.db import db
    from backend.models import StockComment

    _, email, password = make_user()
    login(email, password)
    client.post("/api/comments/THYAO.IS", json={"body": "ilk yorum"})
    client.post("/api/portfolio", json={"symbol": "AAPL", "qty": 1, "avg_price": 100,
                                        "currency": "USD", "buy_date": "2026-01-02"})

    export = client.get("/api/auth/export").get_json()
    assert export["comments"][0]["symbol"] == "THYAO.IS" and export["comments"][0]["body"] == "ilk yorum"
    assert export["portfolio"][0]["buy_date"] == "2026-01-02"

    assert client.delete("/api/auth/me", json={"password": password}).status_code == 200
    with app.app_context():
        assert db.session.query(StockComment).count() == 0      # yorumlar hesapla birlikte silindi
