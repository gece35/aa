"""Faz 2: yasal sayfalar, istemci IP'si ve limitler, sembol doğrulama, oturum
geçersiz kılma, yorum sahipliği, kaldırılan uçlar."""

from __future__ import annotations

import sys
import types

import pytest


# ── Statik sayfalar ──────────────────────────────────────────────────────────

def test_legal_stylesheet_and_pages(client):
    css = client.get("/legal/legal.css")
    assert css.status_code == 200 and "css" in css.content_type

    page = client.get("/legal/risk")
    assert page.status_code == 200 and "html" in page.content_type

    old = client.get("/legal/risk.html")
    assert old.status_code == 301 and old.headers["Location"].endswith("/legal/risk")


@pytest.mark.parametrize("path", [
    "/legal/yok-boyle-sayfa", "/legal/yok.html", "/legal/../../app", "/legal/..%2f..%2fapp",
    "/legal/a/b", "/blog/../index", "/blog/yok", "/olmayan-sayfa",
])
def test_unknown_or_traversal_paths_are_html_404(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert "html" in r.content_type and "noindex" in r.get_data(as_text=True)


def test_blog_routes(client):
    assert client.get("/blog/").status_code == 200
    assert client.get("/blog/rsi-gostergesi-nedir").status_code == 200
    r = client.get("/blog/rsi-gostergesi-nedir.html")
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/rsi-gostergesi-nedir")
    r = client.get("/blog/index.html")
    assert r.status_code == 301 and r.headers["Location"].endswith("/blog/")


def test_api_errors_stay_json(client):
    r = client.get("/api/yok-boyle-uc")
    assert r.status_code == 404 and r.is_json and r.get_json()["error"] == "not_found"


def test_repetition_endpoints_are_gone(client):
    assert client.get("/api/repetition/lessons").status_code == 404
    assert client.post("/api/repetition/lessons", json={"topic": "x"}).status_code in (404, 405)
    assert client.get("/api/repetition/upcoming").status_code == 404


def test_hsts_only_on_https(client):
    assert "Strict-Transport-Security" not in client.get("/api/markets").headers
    r = client.get("/api/markets", headers={"X-Forwarded-Proto": "https"})
    assert "max-age" in r.headers["Strict-Transport-Security"]


# ── İstemci IP'si ve hız sınırları ───────────────────────────────────────────

CF_EDGE = "172.64.10.20"          # Cloudflare aralığında bir adres


def via_cloudflare(ip):
    """Cloudflare → Railway yolundan gelen istek: Railway edge X-Real-IP'ye
    Cloudflare sunucusunu yazar, gerçek istemci CF-Connecting-IP'dedir."""
    return {"X-Real-IP": CF_EDGE, "CF-Connecting-IP": ip}


def direct(ip):
    """Railway alan adına doğrudan (Cloudflare'siz) gelen istek."""
    return {"X-Real-IP": ip}


def test_client_ip_trusts_cloudflare_header_only_from_cloudflare(app):
    from backend.security import client_ip, is_cloudflare_ip

    assert is_cloudflare_ip("172.64.10.20") and is_cloudflare_ip("2606:4700::1")
    assert not is_cloudflare_ip("203.0.113.7") and not is_cloudflare_ip("bozuk")

    with app.test_request_context(headers=via_cloudflare("203.0.113.7")):
        assert client_ip() == "203.0.113.7"
    # Cloudflare'i atlayıp başlığı uyduran istemci kendi adresiyle sayılır
    with app.test_request_context(headers={"X-Real-IP": "198.51.100.9", "CF-Connecting-IP": "1.2.3.4",
                                           "X-Forwarded-For": "5.6.7.8"}):
        assert client_ip() == "198.51.100.9"
    # X-Forwarded-For'un ilk değeri (istemci uydurabilir) kullanılmaz
    with app.test_request_context(headers={"X-Forwarded-For": "198.51.100.1, 10.0.0.1"},
                                  environ_base={"REMOTE_ADDR": "192.0.2.9"}):
        assert client_ip() == "192.0.2.9"
    with app.test_request_context(headers={"X-Real-IP": CF_EDGE, "CF-Connecting-IP": "<script>"}):
        assert client_ip() == CF_EDGE


def test_spoofed_cloudflare_header_cannot_bypass_limits(client):
    attacker = "198.51.100.66"
    for i in range(5):
        h = {"X-Real-IP": attacker, "CF-Connecting-IP": f"10.0.0.{i}"}
        assert client.post("/api/auth/signup", json={}, headers=h).status_code == 400
    h = {"X-Real-IP": attacker, "CF-Connecting-IP": "10.0.0.99"}
    assert client.post("/api/auth/signup", json={}, headers=h).status_code == 429


def test_rate_limit_is_per_client_not_site_wide(client):
    a = via_cloudflare("203.0.113.10")
    b = via_cloudflare("203.0.113.11")
    for _ in range(5):                       # signup: IP başına saatte 5
        assert client.post("/api/auth/signup", json={}, headers=a).status_code == 400
    assert client.post("/api/auth/signup", json={}, headers=a).status_code == 429
    # Başka bir ziyaretçi etkilenmez (eskiden herkes aynı kovayı paylaşıyordu)
    assert client.post("/api/auth/signup", json={}, headers=b).status_code == 400


def test_support_chat_is_rate_limited_and_tolerates_bad_history(client, monkeypatch):
    import backend.support as support

    class _Msg:
        content = "Merhaba"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class FakeGroq:
        def __init__(self, api_key=None):
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **kw: _Resp()))

    monkeypatch.setattr(support, "GROQ_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "groq", types.SimpleNamespace(Groq=FakeGroq))

    h = via_cloudflare("203.0.113.20")
    for bad in ("metin", [1, "x", None], {"a": 1}):
        r = client.post("/api/support/chat", json={"message": "selam", "history": bad}, headers=h)
        assert r.status_code == 200 and r.get_json()["reply"] == "Merhaba"
    for _ in range(5):
        client.post("/api/support/chat", json={"message": "selam"}, headers=h)
    assert client.post("/api/support/chat", json={"message": "selam"}, headers=h).status_code == 429


# ── Sembol doğrulama, misafir kotası, force ──────────────────────────────────

def test_resolve_symbol():
    from backend.tickers import resolve_symbol

    assert resolve_symbol("thyao") == "THYAO.IS"
    assert resolve_symbol(" THYAO.IS ") == "THYAO.IS"
    assert resolve_symbol("aapl") == "AAPL"
    assert resolve_symbol("YOKBOYLE") is None
    assert resolve_symbol("<img src=x>") is None
    assert resolve_symbol("") is None and resolve_symbol(None) is None


def test_guest_cannot_trigger_downloads_for_arbitrary_symbols(client, monkeypatch):
    import app as app_module

    def boom(*_a, **_k):
        raise AssertionError("bilinmeyen sembol için indirme yapılmamalı")

    monkeypatch.setattr(app_module, "download_ohlcv", boom)
    for sym in ("YOKBOYLE", "%3Cimg%20src%3Dx%3E", "A" * 40):
        r = client.get(f"/api/stock/{sym}")
        assert r.status_code == 404
        assert "<" not in r.get_data(as_text=True)          # girdi yankılanmıyor
    assert client.get("/api/stock/YOKBOYLE/fundamentals").status_code == 404
    assert client.get("/api/news/stock/YOKBOYLE").status_code == 404


def test_guest_stock_detail_quota_is_enforced_per_ip(client):
    from backend.cache import stock_cache

    stock_cache.set("stock:THYAO.IS", {"symbol": "THYAO.IS", "score": 7, "entry_signal": False})
    a = via_cloudflare("203.0.113.30")
    for _ in range(5):                                       # misafir: günde 5
        assert client.get("/api/stock/thyao", headers=a).status_code == 200
    blocked = client.get("/api/stock/THYAO.IS", headers=a)
    assert blocked.status_code == 401 and blocked.get_json()["error"] == "auth_required"
    # Başka IP'nin hakkı duruyor
    assert client.get("/api/stock/THYAO.IS", headers=direct("203.0.113.31")).status_code == 200


def test_member_force_refresh_is_throttled_and_limit_clamped(client, make_user, login, monkeypatch):
    import app as app_module

    seen = []

    def fake_chunk(market, offset, limit, force=False, sort="score", max_tickers=None):
        seen.append({"force": force, "limit": limit, "offset": offset})
        return {"market": market, "results": [], "total": 0}

    monkeypatch.setattr(app_module, "scan_market_chunk", fake_chunk)

    # Misafir: force yok sayılır
    client.get("/api/scan?market=bist&offset=0&limit=30&force=1")
    assert seen[-1]["force"] is False

    _, email, password = make_user()
    login(email, password)
    client.get("/api/scan?market=bist&offset=-5&limit=99999&force=1")
    assert seen[-1] == {"force": True, "limit": 60, "offset": 0}
    client.get("/api/scan?market=bist&offset=0&limit=30&force=1")
    assert seen[-1]["force"] is False                        # aralık dolmadan ikinci kez zorlanamaz
    assert client.get("/api/scan?market=bist&limit=abc").status_code == 400


def test_alert_symbol_is_normalised_to_known_ticker(client, make_user, login):
    _, email, password = make_user()
    login(email, password)
    r = client.post("/api/alerts", json={"symbol": "thyao", "condition_type": "price_above",
                                         "condition_value": 500})
    assert r.status_code == 201 and r.get_json()["alert"]["symbol"] == "THYAO.IS"


# ── Oturum geçersiz kılma ────────────────────────────────────────────────────

def _is_authed(c):
    return c.get("/api/auth/me").get_json()["authenticated"]


def test_password_change_logs_out_other_sessions_but_keeps_current(app, make_user):
    _, email, password = make_user()
    here, elsewhere = app.test_client(), app.test_client()
    for c in (here, elsewhere):
        assert c.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    assert _is_authed(here) and _is_authed(elsewhere)

    r = here.post("/api/auth/password",
                  json={"current_password": password, "new_password": "YeniSifre98765!"})
    assert r.status_code == 200
    assert _is_authed(here) is True          # şifreyi değiştiren cihaz açık kalır
    assert _is_authed(elsewhere) is False    # diğer cihazdaki oturum düşer


def test_legacy_session_id_without_fingerprint_is_rejected(app, client, make_user):
    uid, _, _ = make_user()
    with client.session_transaction() as sess:
        sess["_user_id"] = uid               # eski biçim: yalnızca kullanıcı kimliği
        sess["_fresh"] = True
    assert _is_authed(client) is False


def test_password_reset_invalidates_all_pending_reset_links_and_sessions(app, client, make_user, login):
    from backend.db import db
    from backend.models import EmailToken
    from backend.security import generate_token, token_expiry

    uid, email, password = make_user()
    login(email, password)
    with app.app_context():
        plain1, hashed1 = generate_token()
        plain2, hashed2 = generate_token()
        for h in (hashed1, hashed2):
            db.session.add(EmailToken(user_id=uid, kind="reset", token_hash=h, expires_at=token_expiry(1)))
        db.session.commit()

    anon = app.test_client()
    assert anon.post("/api/auth/reset", json={"token": plain1, "password": "BambaskaSifre321!"}).status_code == 200
    assert anon.post("/api/auth/reset", json={"token": plain2, "password": "UcuncuSifre654!"}).status_code == 400
    assert _is_authed(client) is False       # parola sıfırlanınca açık oturum düşer
    assert anon.post("/api/auth/login", json={"email": email, "password": "BambaskaSifre321!"}).status_code == 200


# ── Yorumlar ─────────────────────────────────────────────────────────────────

def test_comments_expose_ownership_not_user_id(app, make_user):
    _, e1, p1 = make_user("yazar@example.com")
    _, e2, p2 = make_user("okur@example.com")
    author, reader = app.test_client(), app.test_client()
    author.post("/api/auth/login", json={"email": e1, "password": p1})
    reader.post("/api/auth/login", json={"email": e2, "password": p2})

    created = author.post("/api/comments/thyao", json={"body": "<b>güzel</b> hisse"})
    assert created.status_code == 201
    comment = created.get_json()["comment"]
    assert comment["is_own"] is True and "user_id" not in comment

    mine = author.get("/api/comments/THYAO.IS").get_json()["comments"]
    theirs = reader.get("/api/comments/THYAO.IS").get_json()["comments"]
    assert mine[0]["is_own"] is True and theirs[0]["is_own"] is False
    assert "user_id" not in theirs[0] and theirs[0]["user_email"].startswith("yaz***")

    assert reader.delete(f"/api/comments/{comment['id']}").status_code == 403
    assert author.delete(f"/api/comments/{comment['id']}").status_code == 200


# ── Faz 5: tek adres, PWA dosyaları ──────────────────────────────────────────

@pytest.mark.parametrize("path,target", [
    ("/rehber.html", "/rehber"), ("/about.html", "/about"), ("/faq.html", "/faq"), ("/index.html", "/"),
])
def test_legacy_html_urls_redirect_to_clean_urls(client, path, target):
    r = client.get(path)
    assert r.status_code == 301 and r.headers["Location"].endswith(target)


def test_pwa_and_verification_files(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and "manifest+json" in manifest.content_type
    data = manifest.get_json(force=True)
    assert data["start_url"] == "/" and len(data["icons"]) >= 2
    for icon in data["icons"]:
        assert client.get(icon["src"]).status_code == 200
    assert client.get("/og-image.png").status_code == 200
    assert client.get("/icons/apple-touch-icon.png").status_code == 200

    # Google Search Console doğrulama dosyası genel yönlendirmeye takılmamalı
    g = client.get("/google43075d7795897bf5.html")
    assert g.status_code == 200
    assert g.get_data(as_text=True).strip() == "google-site-verification: google43075d7795897bf5.html"


def test_main_pages_declare_canonical_and_share_image(client):
    for path, canonical in (("/", "https://nebulascanner.com/"), ("/rehber", "https://nebulascanner.com/rehber"),
                            ("/legal/risk", "https://nebulascanner.com/legal/risk"),
                            ("/blog/", "https://nebulascanner.com/blog/")):
        html = client.get(path).get_data(as_text=True)
        assert f'rel="canonical" href="{canonical}"' in html, path
        assert 'rel="manifest"' in html and 'name="theme-color"' in html, path
    home = client.get("/").get_data(as_text=True)
    assert "og-image.png" in home and "lightweight-charts" not in home    # grafik kütüphanesi tembel yüklenir


# ── Tek alan adı ─────────────────────────────────────────────────────────────

def test_railway_domain_pages_redirect_to_canonical_site(client):
    host = {"Host": "aa-production-0db3.up.railway.app"}
    r = client.get("/legal/risk?x=1", headers=host)
    assert r.status_code == 301 and r.headers["Location"] == "http://localhost:5000/legal/risk?x=1"
    r = client.get("/", headers=host)
    assert r.status_code == 301 and r.headers["Location"] == "http://localhost:5000/"
    # API çağrıları (healthcheck, webhook) ve POST'lar yönlendirilmez
    assert client.get("/api/health", headers=host).status_code == 200
    assert client.post("/api/newsletter", json={}, headers=host).status_code == 400
    # Asıl alan adında yönlendirme yok
    assert client.get("/legal/risk").status_code == 200
