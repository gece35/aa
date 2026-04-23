"""Özelleştirilebilir alarm sistemi.

Desteklenen kriter tipleri:
  rsi_below, rsi_above      — RSI eşik değeri
  macd_cross_up             — MACD sinyali yukarı kesti
  macd_cross_down           — MACD sinyali aşağı kesti
  bb_lower_touch            — Bollinger alt banda değdi
  bb_upper_touch            — Bollinger üst banda değdi
  ema_cross_up              — Fiyat EMA50 üzerine çıktı
  score_above               — Skor eşiği aştı
  price_below, price_above  — Fiyat eşiği
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = "alerts.db"
_lock = threading.Lock()

CONDITION_LABELS = {
    "rsi_below":       "RSI <",
    "rsi_above":       "RSI >",
    "macd_cross_up":   "MACD Yukarı Kesti",
    "macd_cross_down": "MACD Aşağı Kesti",
    "bb_lower_touch":  "Bollinger Alt Band",
    "bb_upper_touch":  "Bollinger Üst Band",
    "ema_cross_up":    "EMA50 Üzerine Çıktı",
    "score_above":     "Skor ≥",
    "price_below":     "Fiyat <",
    "price_above":     "Fiyat >",
}


# ── Veritabanı kurulumu ───────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                condition_type TEXT NOT NULL,
                condition_value REAL,
                label TEXT,
                created_at INTEGER NOT NULL,
                triggered_at INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                dismissed INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_alert(symbol: str, condition_type: str, condition_value: Optional[float] = None) -> Dict:
    symbol = symbol.upper().strip()
    if condition_type not in CONDITION_LABELS:
        raise ValueError(f"Geçersiz kriter: {condition_type}")

    label_base = CONDITION_LABELS[condition_type]
    label = f"{label_base} {condition_value}" if condition_value is not None else label_base

    alert = {
        "id": str(uuid.uuid4())[:8],
        "symbol": symbol,
        "condition_type": condition_type,
        "condition_value": condition_value,
        "label": label,
        "created_at": int(time.time()),
        "triggered_at": None,
        "is_active": True,
        "dismissed": False,
    }

    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts VALUES (:id,:symbol,:condition_type,:condition_value,:label,:created_at,:triggered_at,:is_active,:dismissed)",
            {**alert, "is_active": 1, "dismissed": 0, "triggered_at": None},
        )
        conn.commit()

    return alert


def list_alerts(include_dismissed: bool = False) -> List[Dict]:
    with _lock, _get_conn() as conn:
        if include_dismissed:
            rows = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE dismissed=0 ORDER BY created_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_triggered(limit: int = 20) -> List[Dict]:
    with _lock, _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE triggered_at IS NOT NULL AND dismissed=0 ORDER BY triggered_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_alert(alert_id: str) -> bool:
    with _lock, _get_conn() as conn:
        cur = conn.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
        conn.commit()
    return cur.rowcount > 0


def dismiss_alert(alert_id: str) -> bool:
    with _lock, _get_conn() as conn:
        cur = conn.execute("UPDATE alerts SET dismissed=1 WHERE id=?", (alert_id,))
        conn.commit()
    return cur.rowcount > 0


def _row_to_dict(row: sqlite3.Row) -> Dict:
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    d["dismissed"] = bool(d["dismissed"])
    return d


# ── Alarm kontrol mantığı ──────────────────────────────────────────────────

def _check_single(alert: Dict, detail: Dict) -> bool:
    ct = alert["condition_type"]
    cv = alert.get("condition_value")

    indicators: Dict[str, Any] = {
        ind["key"]: ind for ind in detail.get("indicators", [])
    }

    def ind_val(key: str) -> Optional[float]:
        return indicators.get(key, {}).get("value")

    def ind_sig(key: str) -> bool:
        return bool(indicators.get(key, {}).get("signal", False))

    if ct == "rsi_below":
        v = ind_val("rsi")
        return v is not None and cv is not None and v < cv

    if ct == "rsi_above":
        v = ind_val("rsi")
        return v is not None and cv is not None and v > cv

    if ct == "macd_cross_up":
        return ind_sig("macd")

    if ct == "macd_cross_down":
        v = ind_val("macd")
        return v is not None and v < 0

    if ct == "bb_lower_touch":
        return ind_sig("bbands")

    if ct == "bb_upper_touch":
        v = ind_val("bbands")
        return v is not None and v > 0.95

    if ct == "ema_cross_up":
        return ind_sig("ema50")

    if ct == "score_above":
        score = detail.get("score")
        return score is not None and cv is not None and score >= cv

    if ct == "price_below":
        price = detail.get("price")
        return price is not None and cv is not None and price < cv

    if ct == "price_above":
        price = detail.get("price")
        return price is not None and cv is not None and price > cv

    return False


def check_alerts(detail_fetcher) -> List[Dict]:
    """Aktif alarmları kontrol eder. Tetiklenenlerı döner.

    detail_fetcher: symbol -> dict  (score_symbol_detailed çıktısı)
    """
    with _lock, _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE is_active=1 AND triggered_at IS NULL AND dismissed=0"
        ).fetchall()
    active = [_row_to_dict(r) for r in rows]

    if not active:
        return []

    symbols = list({a["symbol"] for a in active})
    details: Dict[str, Dict] = {}
    for sym in symbols:
        try:
            details[sym] = detail_fetcher(sym)
        except Exception as exc:
            logger.warning("Alarm kontrol verisi alinamadi %s: %s", sym, exc)

    triggered = []
    now = int(time.time())
    for alert in active:
        sym = alert["symbol"]
        d = details.get(sym)
        if d is None:
            continue
        try:
            fired = _check_single(alert, d)
        except Exception:
            continue

        if fired:
            with _lock, _get_conn() as conn:
                conn.execute(
                    "UPDATE alerts SET triggered_at=?, is_active=0 WHERE id=?",
                    (now, alert["id"]),
                )
                conn.commit()
            alert["triggered_at"] = now
            alert["is_active"] = False
            triggered.append(alert)
            logger.info("Alarm tetiklendi: %s %s", sym, alert["label"])

    return triggered


# ── Arka plan worker ──────────────────────────────────────────────────────────

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_worker(detail_fetcher, interval_seconds: int = 300) -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return

    _stop_event.clear()

    def run():
        logger.info("Alarm worker başlatıldı (interval=%ds)", interval_seconds)
        while not _stop_event.wait(interval_seconds):
            try:
                fired = check_alerts(detail_fetcher)
                if fired:
                    logger.info("%d alarm tetiklendi", len(fired))
            except Exception:
                logger.exception("Alarm worker hatası")

    _worker_thread = threading.Thread(target=run, daemon=True, name="alert-worker")
    _worker_thread.start()


def stop_worker() -> None:
    _stop_event.set()


# ── Başlangıç ─────────────────────────────────────────────────────────────────

init_db()
