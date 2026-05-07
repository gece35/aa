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
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager, current_user, login_required

from backend.alerts import (
    CONDITION_LABELS, check_alerts_for_user, count_active_alerts, create_alert,
    delete_alert, dismiss_alert, get_triggered, list_alerts,
)
from backend.auth import admin_required, auth_bp, email_verified_required
from backend.billing import billing_bp
from backend.newsletter import newsletter_bp
from backend.support import support_bp
from backend.cache import (
    exchange_cache, scan_cache, stock_cache, stock_news_cache, symbol_cache,
)
from backend.config import (
    APP_BASE_URL, DATABASE_URL, DEBUG, GA_MEASUREMENT_ID, LEGAL_ENTITY_ADDRESS,
    LEGAL_ENTITY_NAME, LOG_LEVEL, SECRET_KEY, SENTRY_DSN, SUPPORT_EMAIL,
)
from backend.data_fetcher import download_ohlcv, fetch_exchange_rate
from backend.db import db, migrate
from backend.limits import PLANS, enforce_collection_limit, get_plan, quota, requires_plan
from backend.models import Portfolio, User, Watchlist
from backend.news import fetch_news, fetch_stock_news
from backend.backtest import run_backtest
from backend.scanner import scan_market, scan_market_chunk
from backend.scoring import score_symbol_detailed
from backend.tickers import MARKETS

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


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
    resp = Response(html, mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def create_app() -> Flask:
    if SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration
            sentry_sdk.init(
                dsn=SENTRY_DSN,
                integrations=[FlaskIntegration()],
                traces_sample_rate=0.1,
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

    db.init_app(flask_app)
    migrate.init_app(flask_app, db)

    with flask_app.app_context():
        try:
            db.create_all()
        except Exception:
            logger.exception("db.create_all basarisiz — migration bekleniyor")

    CORS(
        flask_app,
        resources={r"/api/*": {"origins": [APP_BASE_URL] if APP_BASE_URL else ["http://localhost:5000"]}},
        supports_credentials=True,
    )

    login_manager = LoginManager()
    login_manager.init_app(flask_app)

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, user_id)

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
        if isinstance(e, HTTPException):
            return jsonify({"error": e.name.lower().replace(" ", "_"), "message": e.description}), e.code
        logger.exception("İşlenmeyen hata")
        return jsonify({"error": "server_error", "message": "Bir hata oluştu, lütfen tekrar deneyin."}), 500

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

    @flask_app.route("/blog/")
    @flask_app.route("/blog/<path:slug>")
    def blog_page(slug="index.html"):
        blog_dir = os.path.join(FRONTEND_DIR, "blog")
        fname = slug if slug.endswith(".html") else f"{slug}.html"
        fpath = os.path.join(blog_dir, fname)
        if not os.path.isfile(fpath):
            return "Sayfa bulunamadı", 404
        return _serve_html(blog_dir, fname)

    @flask_app.route("/legal/<path:slug>")
    def legal_page(slug):
        safe = slug.replace("..", "").strip("/")
        legal_dir = os.path.join(FRONTEND_DIR, "legal")
        fpath = os.path.join(legal_dir, f"{safe}.html")
        if not os.path.isfile(fpath):
            return "Sayfa bulunamadi", 404
        return _serve_html(legal_dir, f"{safe}.html")

    # ── API: Admin ─────────────────────────────────────────────────────────

    @flask_app.route("/api/admin/stats")
    @admin_required
    def api_admin_stats():
        from backend.models import User as UserModel
        from backend.newsletter import _load as load_newsletter
        total_users = db.session.query(UserModel).count()
        lifetime_users = db.session.query(UserModel).filter_by(subscription_status="lifetime").count()
        return jsonify({
            "total_users": total_users,
            "lifetime_users": lifetime_users,
            "lifetime_slots_left": max(0, 100 - total_users),
            "newsletter_subscribers": len(load_newsletter()),
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

        force = force_raw and plan.get("allow_force_refresh", False)
        if market == "bist":
            max_tickers = plan.get("max_bist_tickers")
        else:
            max_tickers = plan.get("max_us_tickers")

        sort = request.args.get("sort", "score")
        try:
            if limit_raw is not None:
                offset = int(offset_raw) if offset_raw else 0
                limit = int(limit_raw)
                payload = scan_market_chunk(
                        market=market, offset=offset, limit=limit,
                        force=force, sort=sort, max_tickers=max_tickers,
                    )
            else:
                payload = scan_market(market=market, force=force, max_tickers=max_tickers)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.exception("Tarama hatasi")
            return jsonify({"error": str(exc)}), 500

        return jsonify(payload)

    # ── API: Haberler ──────────────────────────────────────────────────────

    @flask_app.route("/api/news")
    def api_news():
        market = request.args.get("market", "us").lower()
        force = request.args.get("force", "0") in ("1", "true", "yes")
        if market not in MARKETS:
            return jsonify({"error": f"unknown market: {market}"}), 400
        return jsonify(fetch_news(market=market, force=force))

    @flask_app.route("/api/news/stock/<path:symbol>")
    def api_stock_news(symbol: str):
        symbol = symbol.upper().strip()
        return jsonify(fetch_stock_news(symbol))

    # ── API: Hisse detay ───────────────────────────────────────────────────

    @flask_app.route("/api/stock/<path:symbol>")
    @quota("stock_detail", per="day")
    def api_stock(symbol: str):
        symbol = symbol.upper().strip()
        force = request.args.get("force", "0") in ("1", "true", "yes")

        cache_key = f"stock:{symbol}"
        if not force:
            cached = stock_cache.get(cache_key)
            if cached is not None:
                c = dict(cached)
                c["cached"] = True
                return jsonify(c)

        data = download_ohlcv([symbol], period="2y", interval="1d")
        df = data.get(symbol)
        if df is None or df.empty:
            return jsonify({"error": f"data unavailable for {symbol}"}), 404

        detail = score_symbol_detailed(symbol, df)
        if detail is None:
            return jsonify({"error": f"insufficient data for {symbol}"}), 404

        detail["generated_at"] = int(time.time())
        detail["cached"] = False
        stock_cache.set(cache_key, detail)
        return jsonify(detail)

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
    def health():
        return jsonify({"ok": True, "ts": int(time.time())})

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
        to = request.get_json(silent=True, force=True).get("to", current_user.email) if request.data else current_user.email
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

        import re as _re
        if not symbol or not _re.fullmatch(r'[A-Z0-9.\-]{1,32}', symbol):
            return jsonify({"error": "Geçersiz sembol formatı"}), 400
        if not condition_type:
            return jsonify({"error": "symbol ve condition_type zorunludur"}), 400

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
        def _fetcher(symbol: str) -> dict:
            cache_key = f"stock:{symbol}"
            cached = stock_cache.get(cache_key)
            if cached:
                return cached
            data = download_ohlcv([symbol], period="2y", interval="1d")
            df = data.get(symbol)
            if df is None or df.empty:
                return {}
            return score_symbol_detailed(symbol, df) or {}

        try:
            check_alerts_for_user(current_user.id, _fetcher)
        except Exception:
            logger.exception("Alarm kontrol hatası user=%s", current_user.id)
        return jsonify({"triggered": get_triggered(current_user.id)})

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
        if not symbol:
            return jsonify({"error": "symbol_required"}), 400
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
        if not symbol or qty <= 0 or avg_price <= 0:
            return jsonify({"error": "invalid_input"}), 400
        err = enforce_collection_limit(current_user, "portfolio", len(current_user.portfolio))
        if err:
            return jsonify({"error": "plan_limit", "message": err, "upgrade_url": "/pricing"}), 402
        p = Portfolio(
            user_id=current_user.id, symbol=symbol,
            qty=qty, avg_price=avg_price, currency=currency,
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

    # ── API: Backtest ──────────────────────────────────────────────────────────
    _backtest_cache: dict = {}

    @flask_app.route("/api/backtest")
    @admin_required
    def api_backtest():
        market = request.args.get("market", "bist").lower()
        force  = request.args.get("force", "0") in ("1", "true", "yes")
        if market not in MARKETS:
            return jsonify({"hata": f"Bilinmeyen market: {market}"}), 400

        if not force and market in _backtest_cache:
            return jsonify(_backtest_cache[market])

        try:
            result = run_backtest(market)
        except Exception:
            logger.exception("Backtest hatası market=%s", market)
            return jsonify({"hata": "Backtest sırasında hata oluştu"}), 500

        _backtest_cache[market] = result
        return jsonify(result)

    return flask_app


# gunicorn için modül düzeyinde app nesnesi
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
