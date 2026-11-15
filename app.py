"""Flask giris noktasi (factory pattern).

Calistirmak icin:
    pip install -r requirements.txt
    cp .env.example .env  # ve doldur
    flask db upgrade
    python app.py
Varsayilan olarak http://127.0.0.1:5000 uzerinde calisir.
"""

from __future__ import annotations

import logging
import os
import re
import time

import hmac
import threading
from datetime import date

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager, current_user, login_required
from sqlalchemy import text

from backend import migrate_boot, scheduler
from backend.alerts import (
    CONDITION_LABELS, count_active_alerts, create_alert,
    delete_alert, dismiss_alert, get_triggered, list_alerts,
)
from backend.auth import admin_required, auth_bp, email_verified_required
from backend.billing import billing_bp
from backend.newsletter import newsletter_bp
from backend.support import support_bp
from backend.cache import (
    analysis_cache, exchange_cache, fundamentals_cache, scan_cache, stock_cache,
    stock_news_cache, symbol_cache,
)
from backend.config import (
    APP_BASE_URL, DATABASE_URL, DEBUG, GA_MEASUREMENT_ID, LEGAL_ENTITY_ADDRESS,
    LEGAL_ENTITY_NAME, LOG_LEVEL, SECRET_KEY, SENTRY_DSN, SUPPORT_EMAIL,
)
from backend.data_fetcher import download_ohlcv, fetch_exchange_rate
from backend.db import db, migrate
from backend.limits import PLANS, enforce_collection_limit, get_plan, quota, requires_plan
from backend.market_hours import cache_ttl
from backend.models import Portfolio, StockComment, TweetLog, User, Watchlist
from backend.news import fetch_news, fetch_stock_news
from backend.fundamentals import GROQ_API_KEY, analyze_fundamentals
from backend.backtest import run_backtest, run_signal_study
from backend.scanner import build_index_summary, get_index_df, scan_market, scan_market_chunk
from backend.scoring import compute_regime_ok, score_symbol_detailed
from backend.security import limiter, session_fingerprint
from backend.tickers import MARKETS, market_of_symbol, resolve_symbol

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")

# gunicorn, arbiter açılırken SERVER_SOFTWARE ortam değişkenini ayarlar; flask
# CLI, pytest ve `python app.py` altında bu değer yoktur. Zamanlayıcının yalnızca
# gerçek web sürecinde başlaması için kullanılır (RUN_SCHEDULER=1 lokal deneme).
_SCHEDULER_HOST = (
    os.environ.get("SERVER_SOFTWARE", "").lower().startswith("gunicorn")
    or os.environ.get("RUN_SCHEDULER", "0").lower() in ("1", "true", "yes", "on")
)

# /api/health şema kontrolü: True iken DB revizyonu koddaki head'den farklıysa
# 503 döner: Railway healthcheck, migration'ı uygulanamamış (şeması eksik) bir
# sürümü yayına almaz, eski sürüm açık kalır.
STRICT_SCHEMA_HEALTH = True

# Hisse sembolü formatı — alerts/watchlist/portfolio uçlarının hepsinde aynı
# doğrulama: rastgele/aşırı uzun string'lerin DB'ye yazılmasını (ve Postgres'te
# String(32) sınırını aşınca 500 hatası almasını) önler.
_SYMBOL_RE = re.compile(r'^[A-Z0-9.\-]{1,32}$')
# Statik sayfa adı (legal/blog): yalnızca küçük harf, rakam, tire — yol
# ayracı ve nokta içeremez, dolayısıyla dizin dışına çıkılamaz.
_SLUG_RE = re.compile(r'^[a-z0-9-]{1,80}$')

# Üyenin "zorla yenile" (force=1) isteği: tüm pazarı yeniden indirir. Kullanıcı +
# pazar başına bu aralıkta en fazla bir kez; daha sık gelirse önbellekten yanıtlanır.
_FORCE_MIN_INTERVAL = 300
_SCAN_CHUNK_MAX = 60   # /api/scan tek istekte en fazla bu kadar hisse
_force_last: dict = {}
_force_lock = threading.Lock()


def _is_admin_user() -> bool:
    return bool(current_user.is_authenticated and getattr(current_user, "is_admin", False))


def _force_allowed(market: str) -> bool:
    """force=1 şimdi uygulanabilir mi? Admin: her zaman. Üye: aralık dolduysa."""
    if not current_user.is_authenticated:
        return False
    if _is_admin_user():
        return True
    key = f"{current_user.id}:{market}"
    now = time.time()
    with _force_lock:
        if now - _force_last.get(key, 0.0) < _FORCE_MIN_INTERVAL:
            return False
        _force_last[key] = now
        if len(_force_last) > 5000:
            for k in [k for k, t in _force_last.items() if now - t > _FORCE_MIN_INTERVAL]:
                _force_last.pop(k, None)
        return True


def _clean_symbol(raw: str):
    """Yoldan gelen sembolü doğrular. Taranan evrendeki hisseler herkese açıktır
    (kısa yazım kabul: THYAO → THYAO.IS); evren dışı ama biçimi geçerli
    semboller yalnızca giriş yapmış kullanıcıya (portföy/alarm için). Geçersizse None."""
    sym = (raw or "").upper().strip()
    known = resolve_symbol(sym)
    if known:
        return known
    if current_user.is_authenticated and _SYMBOL_RE.fullmatch(sym):
        return sym
    return None


_ERROR_PAGE = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex" />
<title>{code} — Nebula Scanner</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f172a;color:#e2e8f0;font-family:Inter,Arial,sans-serif;text-align:center;padding:24px}}
h1{{font-size:56px;margin:0 0 8px}}p{{color:#94a3b8;margin:0 0 24px}}
a{{color:#fff;background:#2563eb;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600}}</style>
</head><body><div><h1>{code}</h1><p>{message}</p><a href="/">Ana sayfaya dön</a></div></body></html>"""


def _html_error(code: int, message: str) -> Response:
    resp = Response(_ERROR_PAGE.format(code=code, message=message), status=code,
                    mimetype="text/html")
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


def _mask_entry_signal_one(d: dict) -> dict:
    """'TDOV Eşleşti' rozetini yalnızca admin hesabına göstermek için diğer
    kullanıcılara giden yanıtta entry_signal'i False'a çeker. Cache'deki asıl
    sözlüğü bozmamak için (in-memory TTLCache referans tutar) maskeleme
    gerektiğinde yeni bir kopya döner — doğrudan mutasyon symbol_cache/
    scan_cache/stock_cache'i kalıcı olarak bozar."""
    return {**d, "entry_signal": False} if d.get("entry_signal") else d


def _mask_entry_signal(results: list) -> list:
    return [_mask_entry_signal_one(r) for r in results]


def _asset_version() -> str:
    """app.js ve style.css mtime'ını birleştirip cache-buster string üretir."""
    try:
        a = int(os.path.getmtime(os.path.join(FRONTEND_DIR, "app.js")))
        c = int(os.path.getmtime(os.path.join(FRONTEND_DIR, "style.css")))
        return f"{a}-{c}"
    except OSError:
        return str(int(time.time()))


def _serve_html(directory: str, filename: str) -> Response:
    """HTML dosyasını okur, app.js ve style.css'e versiyon query'si ekler, no-cache header ile döndürür."""
    fpath = os.path.join(directory, filename)
    with open(fpath, "r", encoding="utf-8") as f:
        html = f.read()
    v = _asset_version()
    html = html.replace('src="app.js"', f'src="app.js?v={v}"')
    html = html.replace('href="style.css"', f'href="style.css?v={v}"')
    resp = Response(html, mimetype="text/html")  # charset=utf-8 Flask tarafından eklenir
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def create_app() -> Flask:
    if SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration
            sentry_sdk.init(
                dsn=SENTRY_DSN,
                integrations=[
                    FlaskIntegration(),
                    LoggingIntegration(
                        level=logging.INFO,
                        event_level=logging.ERROR,
                    ),
                ],
                traces_sample_rate=0.0,  # yalnızca hata raporu; performans izleme kapalı
                send_default_pii=False,
            )
        except Exception:
            logger.exception("Sentry init basarisiz")

    flask_app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
    flask_app.config.update(
        SECRET_KEY=SECRET_KEY,
        SQLALCHEMY_DATABASE_URI=DATABASE_URL,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not DEBUG and APP_BASE_URL.startswith("https"),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=not DEBUG and APP_BASE_URL.startswith("https"),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    )
    if DATABASE_URL.startswith("postgresql"):
        # Tek süreç uzun yaşar: boşta kalan bağlantılar bayatlamasın (pre_ping),
        # 8 istek thread'i + zamanlayıcı + kilit bağlantısı havuza sığsın.
        flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_size": 10,
            "max_overflow": 5,
        }

    db.init_app(flask_app)
    migrate.init_app(flask_app, db, directory=MIGRATIONS_DIR)

    # Şema: db.create_all() yerine migration bootstrap'ı (bkz. backend/migrate_boot.py).
    migrate_boot.ensure_schema(flask_app)

    CORS(
        flask_app,
        resources={r"/api/*": {"origins": [APP_BASE_URL] if APP_BASE_URL else ["http://localhost:5000"]}},
        supports_credentials=True,
    )

    # ── Rate limiting — brute-force / spam koruması (login, signup, e-posta
    # gönderimi gibi hassas uçlar auth.py'de @limiter.limit(...) ile ayrıca
    # sınırlanır). Buradaki varsayılan, tek bir IP'den gelen anormal trafiğe
    # karşı genel bir güvenlik ağıdır — normal kullanım (tarama, alarm polling
    # vb.) bu limitin çok altında kalır.
    # Depo süreç belleği: uygulama tek süreç çalıştığı için sayaçlar tutarlıdır,
    # Redis'e gerek yoktur (REDIS_URL tanımlı olsa da kullanılmaz).
    flask_app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    flask_app.config.setdefault("RATELIMIT_DEFAULT", "2000 per hour")
    flask_app.config.setdefault("RATELIMIT_HEADERS_ENABLED", True)
    limiter.init_app(flask_app)

    if _SCHEDULER_HOST:
        # Yedek başlatma: gunicorn.conf.py kancası çalışmadıysa (özel -c ayarı,
        # --preload vb.) zamanlayıcı ilk istekte bu süreçte başlar. Çalışıyorsa
        # yalnızca bir bayrak kontrolüdür.
        @flask_app.before_request
        def _ensure_scheduler():
            if not scheduler.is_running():
                scheduler.start(flask_app)

    # ── Güvenlik başlıkları ─────────────────────────────────────────────────
    # CSP şimdilik Report-Only: siteyi kırmadan tarayıcı konsolunda ihlalleri
    # görüp allowlist'i tamamladıktan sonra enforce moduna geçilebilir.
    _CSP_REPORT_ONLY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.clarity.ms https://www.googletagmanager.com "
        "https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://www.clarity.ms https://www.google-analytics.com; "
        "frame-ancestors 'none'"
    )

    @flask_app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault("Content-Security-Policy-Report-Only", _CSP_REPORT_ONLY)
        if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    login_manager = LoginManager()
    login_manager.init_app(flask_app)

    @login_manager.user_loader
    def load_user(user_id: str):
        # Oturum kimliği "<id>:<parola parmak izi>" (User.get_id). Parmak izi
        # tutmuyorsa (parola değişmiş ya da eski biçimli oturum) oturum geçersizdir.
        uid, _, fingerprint = str(user_id).partition(":")
        user = db.session.get(User, uid)
        if user is None or not fingerprint:
            return None
        if not hmac.compare_digest(fingerprint, session_fingerprint(user.password_hash)):
            return None
        return user

    @login_manager.unauthorized_handler
    def _unauth():
        return jsonify({"error": "auth_required"}), 401

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(billing_bp)
    flask_app.register_blueprint(newsletter_bp)
    flask_app.register_blueprint(support_bp)

    @flask_app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import HTTPException
        is_api = request.path.startswith("/api/")
        if isinstance(e, HTTPException):
            if is_api:
                return jsonify({"error": e.name.lower().replace(" ", "_"), "message": e.description}), e.code
            message = "Aradığınız sayfa bulunamadı." if e.code == 404 else "İstek işlenemedi."
            return _html_error(e.code or 500, message)
        logger.exception("İşlenmeyen hata")
        if is_api:
            return jsonify({"error": "server_error", "message": "Bir hata oluştu, lütfen tekrar deneyin."}), 500
        return _html_error(500, "Bir hata oluştu, lütfen tekrar deneyin.")

    # ── Statik sayfalar ────────────────────────────────────────────────────

    @flask_app.route("/")
    def index():
        return _serve_html(FRONTEND_DIR, "index.html")

    @flask_app.route("/robots.txt")
    @flask_app.route("/sitemap.xml")
    def seo_files():
        fname = request.path.lstrip("/")
        return send_from_directory(FRONTEND_DIR, fname)

    @flask_app.route("/rehber")
    def rehber_page():
        return _serve_html(FRONTEND_DIR, "rehber.html")

    @flask_app.route("/about")
    def about_page():
        return _serve_html(FRONTEND_DIR, "about.html")

    @flask_app.route("/faq")
    def faq_page():
        return _serve_html(FRONTEND_DIR, "faq.html")

    def _static_page(directory: str, url_prefix: str, slug: str):
        """`<dizin>/<slug>.html` dosyasını sunar. `slug.html` biçimi tek (uzantısız)
        adrese 301 ile yönlenir; ad _SLUG_RE ile sınırlı olduğu için dizin dışına çıkılamaz."""
        if slug.endswith(".html"):
            stem = slug[:-5]
            if _SLUG_RE.fullmatch(stem) and os.path.isfile(os.path.join(directory, f"{stem}.html")):
                return redirect(f"{url_prefix}/{stem}", code=301)
            abort(404)
        if not _SLUG_RE.fullmatch(slug) or not os.path.isfile(os.path.join(directory, f"{slug}.html")):
            abort(404)
        return _serve_html(directory, f"{slug}.html")

    @flask_app.route("/blog/")
    @flask_app.route("/blog/<path:slug>")
    def blog_page(slug=""):
        blog_dir = os.path.join(FRONTEND_DIR, "blog")
        if slug == "":
            return _serve_html(blog_dir, "index.html")
        if slug in ("index", "index.html"):
            return redirect("/blog/", code=301)
        return _static_page(blog_dir, "/blog", slug)

    @flask_app.route("/legal/<path:slug>")
    def legal_page(slug):
        legal_dir = os.path.join(FRONTEND_DIR, "legal")
        # Bu rota /legal/ altındaki her şeyi yakaladığı için stil dosyasını da
        # kendisi sunmalı (eskiden legal.css.html arayıp 404 dönüyordu —
        # yasal sayfaların tamamı stilsiz görünüyordu).
        if slug == "legal.css":
            return send_from_directory(legal_dir, "legal.css")
        return _static_page(legal_dir, "/legal", slug)

    # ── API: Admin ─────────────────────────────────────────────────────────

    @flask_app.route("/api/admin/stats")
    @admin_required
    def api_admin_stats():
        from backend.models import Feedback, User as UserModel
        from backend.newsletter import active_count as newsletter_active_count
        total_users = db.session.query(UserModel).count()
        lifetime_users = db.session.query(UserModel).filter_by(subscription_status="lifetime").count()
        return jsonify({
            "total_users": total_users,
            "lifetime_users": lifetime_users,
            "lifetime_slots_left": max(0, 100 - lifetime_users),
            "newsletter_subscribers": newsletter_active_count(),
            "feedback_count": db.session.query(Feedback).count(),
        })

    @flask_app.route("/api/admin/feedback")
    @admin_required
    def api_admin_feedback():
        """Geri bildirim formundan gelen son kayıtlar (en yeni önce)."""
        from backend.models import Feedback
        rows = (
            db.session.query(Feedback)
            .order_by(Feedback.created_at.desc(), Feedback.id.desc())
            .limit(200)
            .all()
        )
        return jsonify({"feedback": [f.to_dict() for f in rows]})

    @flask_app.route("/api/admin/users")
    @admin_required
    def api_admin_users():
        from backend.models import User as UserModel
        page = request.args.get("page", 1, type=int)
        per_page = 50
        q = request.args.get("q", "").strip()
        query = db.session.query(UserModel)
        if q:
            query = query.filter(UserModel.email.ilike(f"%{q}%"))
        total = query.count()
        users = query.order_by(UserModel.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return jsonify({
            "users": [
                {
                    "email": u.email,
                    "plan": u.plan,
                    "subscription_status": u.subscription_status or "-",
                    "is_admin": u.is_admin,
                    "email_verified": bool(u.email_verified_at),
                    "created_at": u.created_at.strftime("%d.%m.%Y %H:%M") if u.created_at else "-",
                    "last_login_at": u.last_login_at.strftime("%d.%m.%Y %H:%M") if u.last_login_at else "-",
                }
                for u in users
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        })

    # ── API: Config ────────────────────────────────────────────────────────

    @flask_app.route("/api/config")
    def api_config():
        return jsonify({
            "legal_entity_name": LEGAL_ENTITY_NAME,
            "legal_entity_address": LEGAL_ENTITY_ADDRESS,
            "support_email": SUPPORT_EMAIL,
            "plans": PLANS,
            "ga_measurement_id": GA_MEASUREMENT_ID,
        })

    @flask_app.route("/api/markets")
    def api_markets():
        plan = get_plan(current_user)
        allowed = set(plan.get("markets") or ["bist"])
        payload = [
            {
                "code": info["code"],
                "label": info["label"],
                "flag": info["flag"],
                "currency": info["currency"],
                "ticker_count": len(info["tickers"]),
                "allowed": info["code"] in allowed,
            }
            for info in MARKETS.values()
        ]
        return jsonify({
            "markets": payload,
            "plan": "premium" if (current_user.is_authenticated and current_user.is_premium) else "free",
        })

    # ── API: Endeks özeti (Tarama sekmesi mini grafiği) ────────────────────

    @flask_app.route("/api/index/<market>")
    def api_index(market: str):
        market = (market or "").lower()
        if market not in MARKETS:
            return jsonify({"error": f"unknown market: {market}"}), 400
        summary = build_index_summary(market)
        if summary is None:
            return jsonify({"error": "index data unavailable"}), 404
        return jsonify(summary)

    # ── API: Tarama ────────────────────────────────────────────────────────

    @flask_app.route("/api/scan")
    def api_scan():
        market = request.args.get("market", "us").lower()
        force_raw = request.args.get("force", "0") in ("1", "true", "yes")
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")

        if market not in MARKETS:
            return jsonify({"error": f"unknown market: {market}"}), 400

        plan = get_plan(current_user)
        if market not in (plan.get("markets") or ["bist"]):
            return jsonify({
                "error": "premium_required",
                "message": "Bu pazar Premium aboneliğine özeldir.",
                "upgrade_url": "/pricing",
            }), 402

        # force=1 tüm pazarı yeniden indirir (pahalı): yalnızca planı izin veren
        # üyeye ve belirli aralıkla; aksi halde sessizce önbellekten yanıtlanır.
        force = bool(force_raw and plan.get("allow_force_refresh", False) and _force_allowed(market))
        if market == "bist":
            max_tickers = plan.get("max_bist_tickers")
        else:
            max_tickers = plan.get("max_us_tickers")

        sort = request.args.get("sort", "score")
        try:
            if limit_raw is not None:
                offset = max(0, int(offset_raw)) if offset_raw else 0
                limit = max(1, min(int(limit_raw), _SCAN_CHUNK_MAX))
                payload = scan_market_chunk(
                        market=market, offset=offset, limit=limit,
                        force=force, sort=sort, max_tickers=max_tickers,
                    )
            else:
                payload = scan_market(market=market, force=force, max_tickers=max_tickers)
        except ValueError:
            return jsonify({"error": "invalid_parameter", "message": "Geçersiz parametre."}), 400
        except Exception:
            logger.exception("Tarama hatasi")
            return jsonify({"error": "scan_failed",
                            "message": "Tarama şu an yapılamadı, lütfen biraz sonra tekrar deneyin."}), 500

        if not _is_admin_user():
            payload = dict(payload)
            payload["results"] = _mask_entry_signal(payload.get("results", []))

        return jsonify(payload)

    # ── API: Haberler ──────────────────────────────────────────────────────

    @flask_app.route("/api/news")
    def api_news():
        market = request.args.get("market", "us").lower()
        # force (6 RSS + çeviri çağrısı) yalnızca admin'e açık
        force = request.args.get("force", "0") in ("1", "true", "yes") and _is_admin_user()
        if market not in MARKETS:
            return jsonify({"error": "unknown_market"}), 400
        return jsonify(fetch_news(market=market, force=force))

    @flask_app.route("/api/news/stock/<path:symbol>")
    def api_stock_news(symbol: str):
        symbol = _clean_symbol(symbol)
        if symbol is None:
            return jsonify({"error": "unknown_symbol", "items": []}), 404
        return jsonify(fetch_stock_news(symbol))

    # ── API: Hisse detay ───────────────────────────────────────────────────

    @flask_app.route("/api/stock/<path:symbol>")
    @quota("stock_detail", per="day")
    def api_stock(symbol: str):
        symbol = _clean_symbol(symbol)
        if symbol is None:
            return jsonify({"error": "unknown_symbol", "message": "Hisse bulunamadı."}), 404
        force = request.args.get("force", "0") in ("1", "true", "yes") and _is_admin_user()

        cache_key = f"stock:{symbol}"
        if not force:
            cached = stock_cache.get(cache_key)
            if cached is not None:
                c = dict(cached)
                c["cached"] = True
                if not _is_admin_user():
                    c = _mask_entry_signal_one(c)
                return jsonify(c)

        data = download_ohlcv([symbol], period="2y", interval="1d")
        df = data.get(symbol)
        if df is None or df.empty:
            return jsonify({"error": "data_unavailable",
                            "message": "Bu hisse için veri şu an alınamıyor."}), 404

        symbol_market = market_of_symbol(symbol)
        index_df = get_index_df(symbol_market)
        detail = score_symbol_detailed(
            symbol, df, index_df=index_df,
            market=symbol_market, regime_ok=compute_regime_ok(index_df),
        )
        if detail is None:
            return jsonify({"error": "insufficient_data",
                            "message": "Bu hisse için yeterli geçmiş veri yok."}), 404

        detail["generated_at"] = int(time.time())
        detail["cached"] = False
        stock_cache.set(cache_key, detail, ttl=cache_ttl(symbol_market, stock_cache.ttl))
        if not _is_admin_user():
            detail = _mask_entry_signal_one(detail)
        return jsonify(detail)

    # ── API: AI destekli bilanço analizi ───────────────────────────────────
    # Herkese açık ama her önbelleksiz çağrı ücretli bir LLM isteğidir: IP başına
    # sınırlı ve yalnızca geçerli semboller için çalışır.

    @flask_app.route("/api/stock/<path:symbol>/fundamentals")
    @limiter.limit("30 per hour")
    def api_stock_fundamentals(symbol: str):
        symbol = _clean_symbol(symbol)
        if symbol is None:
            return jsonify({"error": "unknown_symbol", "available": False}), 404
        if not GROQ_API_KEY:
            return jsonify({
                "error": "config_error",
                "message": "Bilanço analizi servisi şu an kullanılamıyor.",
            }), 503

        cache_key = f"fund:{symbol}"
        cached = fundamentals_cache.get(cache_key)
        if cached is not None:
            c = dict(cached)
            c["cached"] = True
            return jsonify(c)

        result = analyze_fundamentals(symbol)
        # available=False ise (veri yok / AI hatası) cache'leme — sonraki denemede
        # tekrar denensin. Yalnızca başarılı analizleri cache'le.
        if result.get("available"):
            result["generated_at"] = int(time.time())
            result["cached"] = False
            fundamentals_cache.set(cache_key, result)
        return jsonify(result)

    @flask_app.route("/api/exchange-rate")
    def api_exchange_rate():
        cache_key = "exchange:USDTRY"
        cached = exchange_cache.get(cache_key)
        if cached is not None:
            return jsonify(cached)
        rate = fetch_exchange_rate("TRY=X")
        if rate is None:
            return jsonify({"error": "kur alinamadi"}), 503
        payload = {"rate": round(rate, 4), "pair": "USD/TRY", "ts": int(time.time())}
        exchange_cache.set(cache_key, payload)
        return jsonify(payload)

    @flask_app.route("/api/health")
    @limiter.exempt
    def health():
        payload = {
            "ok": True,
            "ts": int(time.time()),
            "db": False,
            "schema": None,
            "schema_head": None,
            "schema_ok": None,
            "migration": migrate_boot.state(),
            "scheduler": scheduler.status(),
        }
        try:
            db.session.execute(text("SELECT 1"))
            payload["db"] = True
        except Exception:
            logger.exception("health: DB erişilemiyor")
        if payload["db"]:
            try:
                payload["schema"] = migrate_boot.current_revision()
                payload["schema_head"] = migrate_boot.expected_head(flask_app)
                payload["schema_ok"] = payload["schema"] == payload["schema_head"]
            except Exception:
                logger.exception("health: şema revizyonu okunamadı")
        healthy = payload["db"] and not (STRICT_SCHEMA_HEALTH and payload["schema_ok"] is False)
        payload["ok"] = bool(healthy)
        return jsonify(payload), (200 if healthy else 503)

    # Bu route yalnızca yerel geliştirmede (DEBUG=1) kaydedilir — prod'da
    # (Railway'de DEBUG hep 0) endpoint hiç var olmaz, DEV_SECRET yanlışlıkla
    # set edilse bile erişilemez. Daha önce prod'da da canlıydı ve tek
    # koruması bir shared-secret string karşılaştırmasıydı.
    if DEBUG:
        _DEV_SECRET = os.environ.get("DEV_SECRET", "")

        @flask_app.route("/api/dev/make-premium", methods=["POST"])
        def dev_make_premium():
            body = request.get_json(silent=True) or {}
            secret = body.get("secret", "")
            if not _DEV_SECRET or secret != _DEV_SECRET:
                return jsonify({"error": "forbidden"}), 403
            email = (body.get("email") or "").strip().lower()
            if not email:
                return jsonify({"error": "email_required"}), 400
            from backend.models import User
            user = db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()
            if not user:
                return jsonify({"error": "not_found"}), 404
            user.plan = "premium"
            user.subscription_status = "active"
            db.session.commit()
            return jsonify({"ok": True, "email": user.email, "plan": user.plan, "is_premium": user.is_premium})

    @flask_app.route("/api/admin/email-test", methods=["POST"])
    @login_required
    @admin_required
    def email_test():
        from backend.email import _cfg, _send
        cfg = _cfg()
        config_info = {
            "brevo_configured": bool(cfg["brevo_key"] and cfg["brevo_from"]),
            "smtp_configured": bool(cfg["smtp_host"] and cfg["smtp_user"] and cfg["smtp_pass"]),
            "resend_configured": bool(cfg["resend_key"]),
            "brevo_from": cfg["brevo_from"] or "(boş)",
            "smtp_host": cfg["smtp_host"] or "(boş)",
            "smtp_user": cfg["smtp_user"] or "(boş)",
        }
        to = (request.get_json(silent=True) or {}).get("to") or current_user.email
        ok = _send(to, "Nebula Scanner — E-posta test", "<p>Test maili başarıyla gönderildi.</p>", "Test maili başarıyla gönderildi.")
        return jsonify({"ok": ok, "config": config_info, "sent_to": to})

    @flask_app.route("/api/cache/clear", methods=["POST"])
    @login_required
    @admin_required
    def cache_clear():
        scan_cache.clear()
        stock_cache.clear()
        symbol_cache.clear()
        stock_news_cache.clear()
        exchange_cache.clear()
        return jsonify({"ok": True})

    # ── API: Alarm ─────────────────────────────────────────────────────────

    @flask_app.route("/api/alerts", methods=["GET"])
    @login_required
    def api_alerts_list():
        include_dismissed = request.args.get("all", "0") in ("1", "true")
        return jsonify({"alerts": list_alerts(current_user.id, include_dismissed)})

    @flask_app.route("/api/alerts", methods=["POST"])
    @login_required
    @email_verified_required
    def api_alerts_create():
        body = request.get_json(silent=True) or {}
        symbol = (body.get("symbol") or "").strip().upper()
        condition_type = (body.get("condition_type") or "").strip()
        condition_value = body.get("condition_value")

        if not symbol or not _SYMBOL_RE.fullmatch(symbol):
            return jsonify({"error": "Geçersiz sembol formatı"}), 400
        # Bilinen hisseyi resmi sembolüne çevir (MGROS → MGROS.IS); aksi halde
        # veri kaynağı sembolü bulamaz ve alarm hiç tetiklenmez.
        symbol = resolve_symbol(symbol) or symbol
        if condition_type not in CONDITION_LABELS:
            return jsonify({"error": "Geçersiz kriter"}), 400
        if condition_value is None:
            return jsonify({"error": "Hedef fiyat zorunludur"}), 400

        err = enforce_collection_limit(current_user, "alerts", count_active_alerts(current_user.id))
        if err:
            return jsonify({"error": "plan_limit", "message": err, "upgrade_url": "/pricing"}), 402

        try:
            cv = float(condition_value) if condition_value is not None else None
            alert = create_alert(current_user.id, symbol, condition_type, cv)
            return jsonify({"ok": True, "alert": alert}), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @flask_app.route("/api/alerts/<alert_id>", methods=["DELETE"])
    @login_required
    @email_verified_required
    def api_alerts_delete(alert_id: str):
        if delete_alert(current_user.id, alert_id):
            return jsonify({"ok": True})
        return jsonify({"error": "bulunamadi"}), 404

    @flask_app.route("/api/alerts/<alert_id>/dismiss", methods=["POST"])
    @login_required
    @email_verified_required
    def api_alerts_dismiss(alert_id: str):
        if dismiss_alert(current_user.id, alert_id):
            return jsonify({"ok": True})
        return jsonify({"error": "bulunamadi"}), 404

    @flask_app.route("/api/alerts/triggered", methods=["GET"])
    @login_required
    def api_alerts_triggered():
        """Tetiklenmiş (kapatılmamış) alarmlar — yalnızca DB okur.

        Alarm kontrolünü ve e-postayı zamanlayıcı yapar (backend/scheduler.py).
        Bu uç eskiden her çağrıda yfinance indirip alarmı kendisi tetikliyordu;
        o yolla tetiklenen alarmın e-postası hiç gitmiyordu.
        `?since=<unix ts>` verilirse yalnızca o andan sonra tetiklenenler döner.
        """
        triggered = get_triggered(current_user.id)
        since = request.args.get("since", type=int)
        if since:
            triggered = [a for a in triggered if (a.get("triggered_at") or 0) > since]
        return jsonify({"triggered": triggered, "ts": int(time.time())})

    @flask_app.route("/api/alerts/conditions", methods=["GET"])
    def api_alerts_conditions():
        return jsonify({"conditions": [
            {"type": k, "label": v} for k, v in CONDITION_LABELS.items()
        ]})

    # ── API: Watchlist ─────────────────────────────────────────────────────

    @flask_app.route("/api/watchlist", methods=["GET"])
    @login_required
    def watchlist_list():
        return jsonify({"watchlist": [w.symbol for w in current_user.watchlist]})

    @flask_app.route("/api/watchlist", methods=["POST"])
    @login_required
    @email_verified_required
    def watchlist_add():
        body = request.get_json(silent=True) or {}
        symbol = (body.get("symbol") or "").upper().strip()
        if not symbol or not _SYMBOL_RE.fullmatch(symbol):
            return jsonify({"error": "invalid_symbol", "message": "Geçersiz sembol formatı"}), 400
        existing = [w.symbol for w in current_user.watchlist]
        if symbol in existing:
            return jsonify({"ok": True})
        err = enforce_collection_limit(current_user, "watchlist", len(existing))
        if err:
            return jsonify({"error": "plan_limit", "message": err, "upgrade_url": "/pricing"}), 402
        db.session.add(Watchlist(user_id=current_user.id, symbol=symbol))
        db.session.commit()
        return jsonify({"ok": True})

    @flask_app.route("/api/watchlist/<symbol>", methods=["DELETE"])
    @login_required
    @email_verified_required
    def watchlist_remove(symbol):
        symbol = symbol.upper().strip()
        for w in list(current_user.watchlist):
            if w.symbol == symbol:
                db.session.delete(w)
        db.session.commit()
        return jsonify({"ok": True})

    # ── API: Portföy ───────────────────────────────────────────────────────

    @flask_app.route("/api/portfolio", methods=["GET"])
    @login_required
    def portfolio_list():
        return jsonify({"portfolio": [p.to_dict() for p in current_user.portfolio]})

    @flask_app.route("/api/portfolio", methods=["POST"])
    @login_required
    @email_verified_required
    def portfolio_add():
        body = request.get_json(silent=True) or {}
        symbol = (body.get("symbol") or "").upper().strip()
        try:
            qty = float(body.get("qty") or 0)
            avg_price = float(body.get("avg_price") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_input"}), 400
        currency = (body.get("currency") or "TRY").upper().strip()
        if not symbol or not _SYMBOL_RE.fullmatch(symbol) or qty <= 0 or avg_price <= 0 or len(currency) > 8:
            return jsonify({"error": "invalid_input"}), 400
        # Alış tarihi isteğe bağlı (YYYY-AA-GG); geçersiz/gelecek tarih yok sayılır.
        buy_date = None
        raw_date = str(body.get("buy_date") or "").strip()[:10]
        if raw_date:
            try:
                parsed = date.fromisoformat(raw_date)
                if parsed <= date.today():
                    buy_date = parsed
            except ValueError:
                buy_date = None
        err = enforce_collection_limit(current_user, "portfolio", len(current_user.portfolio))
        if err:
            return jsonify({"error": "plan_limit", "message": err, "upgrade_url": "/pricing"}), 402
        p = Portfolio(
            user_id=current_user.id, symbol=symbol,
            qty=qty, avg_price=avg_price, currency=currency, buy_date=buy_date,
        )
        db.session.add(p)
        db.session.commit()
        return jsonify({"ok": True, "position": p.to_dict()}), 201

    @flask_app.route("/api/portfolio/<int:position_id>", methods=["DELETE"])
    @login_required
    @email_verified_required
    def portfolio_remove(position_id: int):
        p = db.session.get(Portfolio, position_id)
        if p is None or p.user_id != current_user.id:
            return jsonify({"error": "not_found"}), 404
        db.session.delete(p)
        db.session.commit()
        return jsonify({"ok": True})

    # ── API: Yorumlar ──────────────────────────────────────────────────────────
    _COMMENT_MAX_LEN = 500

    @flask_app.route("/api/comments/<symbol>", methods=["GET"])
    @login_required
    def comments_list(symbol: str):
        symbol = _clean_symbol(symbol)
        if symbol is None:
            return jsonify({"error": "unknown_symbol", "comments": []}), 404
        rows = (
            db.session.query(StockComment)
            .filter_by(symbol=symbol)
            .order_by(StockComment.created_at.desc())
            .limit(50)
            .all()
        )
        return jsonify({"comments": [c.to_dict(current_user.id) for c in rows]})

    @flask_app.route("/api/comments/<symbol>", methods=["POST"])
    @login_required
    @email_verified_required
    @limiter.limit("10 per minute")
    def comments_add(symbol: str):
        symbol = _clean_symbol(symbol)
        if symbol is None:
            return jsonify({"error": "unknown_symbol"}), 404
        body = str((request.get_json(silent=True) or {}).get("body") or "").strip()
        if not body:
            return jsonify({"error": "empty"}), 400
        if len(body) > _COMMENT_MAX_LEN:
            return jsonify({"error": "too_long", "max": _COMMENT_MAX_LEN}), 400
        comment = StockComment(user_id=current_user.id, symbol=symbol, body=body)
        db.session.add(comment)
        db.session.commit()
        return jsonify({"ok": True, "comment": comment.to_dict(current_user.id)}), 201

    @flask_app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
    @login_required
    def comments_delete(comment_id: int):
        comment = db.session.get(StockComment, comment_id)
        if comment is None:
            return jsonify({"error": "not_found"}), 404
        if comment.user_id != current_user.id and not current_user.is_admin:
            return jsonify({"error": "forbidden"}), 403
        db.session.delete(comment)
        db.session.commit()
        return jsonify({"ok": True})

    # ── API: Backtest ──────────────────────────────────────────────────────────
    # Sonuçlar analysis_cache'te (6 saat) tutulur: süreç ömrü boyunca
    # sınırsız kalan sözlükler yerine.

    @flask_app.route("/api/backtest")
    @admin_required
    def api_backtest():
        market = request.args.get("market", "bist").lower()
        force  = request.args.get("force", "0") in ("1", "true", "yes")
        if market not in MARKETS:
            return jsonify({"hata": f"Bilinmeyen market: {market}"}), 400

        cache_key = f"backtest:{market}"
        if not force:
            cached = analysis_cache.get(cache_key)
            if cached is not None:
                return jsonify(cached)

        try:
            result = run_backtest(market)
        except Exception:
            logger.exception("Backtest hatası market=%s", market)
            return jsonify({"hata": "Backtest sırasında hata oluştu"}), 500

        analysis_cache.set(cache_key, result)
        return jsonify(result)

    # ── API: Sinyal İsabet Etüdü ────────────────────────────────────────────────

    @flask_app.route("/api/signal-study")
    @admin_required
    def api_signal_study():
        market = request.args.get("market", "bist").lower()
        force  = request.args.get("force", "0") in ("1", "true", "yes")
        if market not in MARKETS:
            return jsonify({"hata": f"Bilinmeyen market: {market}"}), 400

        cache_key = f"signal-study:{market}"
        if not force:
            cached = analysis_cache.get(cache_key)
            if cached is not None:
                return jsonify(cached)

        try:
            result = run_signal_study(market)
        except Exception:
            logger.exception("Sinyal etüdü hatası market=%s", market)
            return jsonify({"hata": "Sinyal etüdü sırasında hata oluştu"}), 500

        analysis_cache.set(cache_key, result)
        return jsonify(result)

    return flask_app


# gunicorn için modül düzeyinde app nesnesi
app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
