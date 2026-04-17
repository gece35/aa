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

from backend.cache import scan_cache, stock_cache
from backend.data_fetcher import download_ohlcv
from backend.news import fetch_news
from backend.scanner import scan_market
from backend.scoring import score_symbol_detailed
from backend.tickers import MARKETS, get_tickers

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

    if market not in MARKETS:
        return jsonify({"error": f"unknown market: {market}"}), 400

    try:
        payload = scan_market(market=market, force=force)
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


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "ts": int(time.time())})


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    scan_cache.clear()
    stock_cache.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
