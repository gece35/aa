"""Flask giris noktasi.

Calistirmak icin:
    pip install -r requirements.txt
    python app.py
Varsayilan olarak http://127.0.0.1:5000 uzerinde calisir.
"""

from __future__ import annotations

import logging
import os
import time

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.alerts import (
    check_alerts, create_alert, delete_alert, dismiss_alert,
    get_triggered, list_alerts, start_worker, CONDITION_LABELS,
)
from backend.cache import exchange_cache, scan_cache, stock_cache, stock_news_cache, symbol_cache
from backend.data_fetcher import download_ohlcv, fetch_exchange_rate
from backend.news import fetch_news, fetch_stock_news
from backend.scanner import scan_market, scan_market_chunk
from backend.scoring import score_symbol_detailed
from backend.tickers import MARKETS

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

app = Flask(
    __name__,
    static_folder=FRONTEND_DIR,
    static_url_path="",
)
CORS(app)


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/markets")
def api_markets():
    payload = [
        {
            "code": info["code"],
            "label": info["label"],
            "flag": info["flag"],
            "currency": info["currency"],
            "ticker_count": len(info["tickers"]),
        }
        for info in MARKETS.values()
    ]
    return jsonify({"markets": payload})


@app.route("/api/scan")
def api_scan():
    market = request.args.get("market", "us").lower()
    force = request.args.get("force", "0") in ("1", "true", "yes")
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if market not in MARKETS:
        return jsonify({"error": f"unknown market: {market}"}), 400

    sort = request.args.get("sort", "score")
    try:
        if limit_raw is not None:
            offset = int(offset_raw) if offset_raw else 0
            limit = int(limit_raw)
            payload = scan_market_chunk(market=market, offset=offset, limit=limit, force=force, sort=sort)
        else:
            payload = scan_market(market=market, force=force)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Tarama hatasi")
        return jsonify({"error": str(exc)}), 500

    return jsonify(payload)


@app.route("/api/news")
def api_news():
    market = request.args.get("market", "us").lower()
    force = request.args.get("force", "0") in ("1", "true", "yes")
    if market not in MARKETS:
        return jsonify({"error": f"unknown market: {market}"}), 400
    payload = fetch_news(market=market, force=force)
    return jsonify(payload)


@app.route("/api/stock/<path:symbol>")
def api_stock(symbol: str):
    symbol = symbol.upper().strip()
    force = request.args.get("force", "0") in ("1", "true", "yes")

    cache_key = f"stock:{symbol}"
    if not force:
        cached = stock_cache.get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return jsonify(cached)

    data = download_ohlcv([symbol], period="200d", interval="1d")
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


@app.route("/api/news/stock/<path:symbol>")
def api_stock_news(symbol: str):
    symbol = symbol.upper().strip()
    payload = fetch_stock_news(symbol)
    return jsonify(payload)


@app.route("/api/exchange-rate")
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


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "ts": int(time.time())})


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    scan_cache.clear()
    stock_cache.clear()
    symbol_cache.clear()
    stock_news_cache.clear()
    exchange_cache.clear()
    return jsonify({"ok": True})


# ── Alarm API ─────────────────────────────────────────────────────────────────

@app.route("/api/alerts", methods=["GET"])
def api_alerts_list():
    include_dismissed = request.args.get("all", "0") in ("1", "true")
    return jsonify({"alerts": list_alerts(include_dismissed)})


@app.route("/api/alerts", methods=["POST"])
def api_alerts_create():
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip()
    condition_type = (body.get("condition_type") or "").strip()
    condition_value = body.get("condition_value")

    if not symbol or not condition_type:
        return jsonify({"error": "symbol ve condition_type zorunludur"}), 400
    try:
        cv = float(condition_value) if condition_value is not None else None
        alert = create_alert(symbol, condition_type, cv)
        return jsonify({"ok": True, "alert": alert}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/alerts/<alert_id>", methods=["DELETE"])
def api_alerts_delete(alert_id: str):
    if delete_alert(alert_id):
        return jsonify({"ok": True})
    return jsonify({"error": "bulunamadı"}), 404


@app.route("/api/alerts/<alert_id>/dismiss", methods=["POST"])
def api_alerts_dismiss(alert_id: str):
    if dismiss_alert(alert_id):
        return jsonify({"ok": True})
    return jsonify({"error": "bulunamadı"}), 404


@app.route("/api/alerts/triggered", methods=["GET"])
def api_alerts_triggered():
    return jsonify({"triggered": get_triggered()})


@app.route("/api/alerts/conditions", methods=["GET"])
def api_alerts_conditions():
    return jsonify({"conditions": [
        {"type": k, "label": v} for k, v in CONDITION_LABELS.items()
    ]})


@app.route("/api/alerts/check", methods=["POST"])
def api_alerts_check():
    def fetcher(sym):
        data = download_ohlcv([sym], period="200d", interval="1d")
        df = data.get(sym)
        if df is None or df.empty:
            return {}
        return score_symbol_detailed(sym, df) or {}
    fired = check_alerts(fetcher)
    return jsonify({"triggered": fired, "count": len(fired)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))

    def _detail_fetcher(sym: str) -> dict:
        data = download_ohlcv([sym], period="200d", interval="1d")
        df = data.get(sym)
        if df is None or df.empty:
            return {}
        return score_symbol_detailed(sym, df) or {}

    start_worker(_detail_fetcher, interval_seconds=300)
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
