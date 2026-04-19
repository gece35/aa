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
from backend.repetition import build_repetition_schedule, next_sunday_summary_times
from backend.scanner import scan_market
from backend.scoring import score_symbol_detailed
from backend.storage import (
    add_lesson,
    delete_lesson,
    get_all_lessons,
    get_lesson,
    get_upcoming_repetitions,
    update_synced_events,
)
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


# ── Spaced Repetition endpoints ────────────────────────────────────────────────

@app.route("/api/repetition/lessons", methods=["GET"])
def rep_list_lessons():
    return jsonify({"lessons": get_all_lessons()})


@app.route("/api/repetition/lessons", methods=["POST"])
def rep_add_lesson():
    body = request.get_json(silent=True) or {}
    topic = (body.get("topic") or "").strip()
    subject = (body.get("subject") or "").strip()
    study_date_str = (body.get("study_date") or "").strip()

    if not topic:
        return jsonify({"error": "topic gerekli"}), 400

    from datetime import date
    try:
        study_date = date.fromisoformat(study_date_str) if study_date_str else date.today()
    except ValueError:
        return jsonify({"error": "study_date gecersiz (YYYY-MM-DD)"}), 400

    schedule = build_repetition_schedule(topic, subject, study_date)
    lesson = add_lesson(topic, subject, study_date.isoformat(), schedule)

    sync_calendar = body.get("sync_calendar", False)
    sync_result = {"synced": False, "event_ids": [], "error": None}
    if sync_calendar:
        try:
            from backend.calendar_api import create_repetition_events, is_configured
            if is_configured():
                event_ids = create_repetition_events(schedule)
                update_synced_events(lesson["id"], event_ids)
                lesson["synced_event_ids"] = event_ids
                sync_result = {"synced": True, "event_ids": event_ids, "error": None}
            else:
                sync_result["error"] = "GOOGLE_CALENDAR_CREDENTIALS ayarlanmamis"
        except Exception as exc:
            sync_result["error"] = str(exc)

    return jsonify({"lesson": lesson, "calendar_sync": sync_result}), 201


@app.route("/api/repetition/lessons/<lesson_id>", methods=["GET"])
def rep_get_lesson(lesson_id: str):
    lesson = get_lesson(lesson_id)
    if not lesson:
        return jsonify({"error": "bulunamadi"}), 404
    return jsonify({"lesson": lesson})


@app.route("/api/repetition/lessons/<lesson_id>", methods=["DELETE"])
def rep_delete_lesson(lesson_id: str):
    lesson = get_lesson(lesson_id)
    if not lesson:
        return jsonify({"error": "bulunamadi"}), 404

    event_ids = lesson.get("synced_event_ids", [])
    if event_ids:
        try:
            from backend.calendar_api import delete_calendar_event
            for eid in event_ids:
                delete_calendar_event(eid)
        except Exception:
            pass

    delete_lesson(lesson_id)
    return jsonify({"ok": True})


@app.route("/api/repetition/upcoming")
def rep_upcoming():
    days = int(request.args.get("days", 7))
    return jsonify({"upcoming": get_upcoming_repetitions(days_ahead=days)})


@app.route("/api/repetition/calendar-status")
def rep_calendar_status():
    try:
        from backend.calendar_api import is_configured
        configured = is_configured()
    except Exception:
        configured = False
    return jsonify({"configured": configured})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
