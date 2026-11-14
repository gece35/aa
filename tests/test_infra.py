"""Önbellek, pazar saatleri, tarama kilidi, worker girişi, gunicorn kancası."""

from __future__ import annotations

import pathlib
import runpy
import subprocess
import sys
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── TTLCache ─────────────────────────────────────────────────────────────────

def test_cache_lru_bound_and_ttl(monkeypatch):
    from backend import cache as cache_mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(cache_mod.time, "time", lambda: clock["t"])

    c = cache_mod.TTLCache(ttl_seconds=10, name="t", max_entries=3)
    for i in range(3):
        c.set(f"k{i}", i)
    assert c.get("k0") == 0          # k0 artık en son kullanılan
    c.set("k3", 3)                   # sınır aşıldı → en eski kullanılan (k1) atılır
    assert len(c) == 3
    assert c.get("k1") is None
    assert c.get("k0") == 0 and c.get("k3") == 3

    c.set("long", "x", ttl=100)      # kayda özel ömür
    clock["t"] += 11
    assert c.get("k0") is None       # varsayılan ömür doldu
    assert c.get("long") == "x"
    assert c.age("long") == 89
    clock["t"] += 100
    assert c.get("long") is None and c.age("long") is None


def test_cache_expired_entries_evicted_before_live_ones(monkeypatch):
    from backend import cache as cache_mod

    clock = {"t": 0.0}
    monkeypatch.setattr(cache_mod.time, "time", lambda: clock["t"])
    c = cache_mod.TTLCache(ttl_seconds=5, name="t", max_entries=2)
    c.set("old", 1)
    clock["t"] = 3
    c.set("live", 2, ttl=100)
    clock["t"] = 6                   # "old" süresi doldu
    c.set("new", 3, ttl=100)         # taşma → süresi dolan atılır, canlılar kalır
    assert c.get("live") == 2 and c.get("new") == 3


# ── Pazar saatleri ───────────────────────────────────────────────────────────

def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_market_hours_sessions():
    from backend.market_hours import any_market_open, is_market_open

    monday_morning = _utc(2026, 11, 16, 8, 0)     # İstanbul 11:00, New York 03:00
    assert is_market_open("bist", monday_morning)
    assert not is_market_open("us", monday_morning)

    monday_evening = _utc(2026, 11, 16, 18, 0)    # İstanbul 21:00, New York 13:00
    assert not is_market_open("bist", monday_evening)
    assert is_market_open("us", monday_evening)

    saturday = _utc(2026, 11, 14, 12, 0)
    assert not any_market_open(saturday)
    assert is_market_open("bilinmeyen", saturday)  # bilinmeyen pazar: güvenli taraf


def test_cache_ttl_follows_session():
    from backend.market_hours import cache_ttl, seconds_until_next_open

    open_time = _utc(2026, 11, 16, 8, 0)
    assert cache_ttl("bist", 600, now=open_time) == 600

    friday_night = _utc(2026, 11, 13, 20, 0)      # İstanbul Cuma 23:00
    # Pazartesi 10:00 İstanbul = Pazartesi 07:00 UTC → 59 saat
    assert seconds_until_next_open("bist", friday_night) == 59 * 3600
    assert cache_ttl("bist", 600, now=friday_night) == 6 * 3600   # üst sınır

    just_before_open = _utc(2026, 11, 16, 6, 55)  # açılışa 5 dk
    assert cache_ttl("bist", 600, now=just_before_open) == 600     # alt sınır open_ttl


# ── Tarama: önbellek + tek soğuk tarama ──────────────────────────────────────

def _fake_ohlcv(n=120, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.maximum(close, 5)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open": close * 0.99, "High": close * 1.01, "Low": close * 0.98,
        "Close": close, "Volume": rng.integers(1_000, 10_000, n).astype(float),
    }, index=idx)


def test_scan_chunk_uses_cache_and_partial_scan_not_cached(monkeypatch):
    from backend import scanner
    from backend.cache import scan_cache

    calls = []

    def fake_download(tickers, period="300d", interval="1d"):
        calls.append(list(tickers))
        return {t: _fake_ohlcv(seed=i + 1) for i, t in enumerate(tickers)}

    monkeypatch.setattr(scanner, "download_ohlcv", fake_download)
    monkeypatch.setattr(scanner, "get_index_df", lambda market: None)

    first = scanner.scan_market_chunk("bist", offset=0, limit=5)
    assert first["scored"] == 5 and first["timings"]["fetched"] == 5
    assert first["cache_ttl"] >= 600

    second = scanner.scan_market_chunk("bist", offset=0, limit=5)
    assert second["cached"] is True and second["timings"]["fetched"] == 0
    assert len(calls) == 1            # ikinci çağrı indirme yapmadı

    # Plan limitiyle kırpılmış tam tarama: tüm pazar anahtarına yazılmaz ve
    # sembol önbelleğini kullandığı için yeniden indirme yapmaz
    partial = scanner.scan_market("bist", max_tickers=3)
    assert partial["total"] == 3 and partial["scored"] == 3
    assert [r["score"] for r in partial["results"]] == sorted(
        (r["score"] for r in partial["results"]), reverse=True)
    assert scan_cache.get("scan:bist") is None
    assert len(calls) == 1


def test_concurrent_cold_scans_download_once(monkeypatch):
    from backend import scanner

    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_download(tickers, period="300d", interval="1d"):
        calls.append(len(tickers))
        started.set()
        release.wait(5)
        return {t: _fake_ohlcv(seed=i + 1) for i, t in enumerate(tickers)}

    monkeypatch.setattr(scanner, "download_ohlcv", slow_download)
    monkeypatch.setattr(scanner, "get_index_df", lambda market: None)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(scanner.scan_market_chunk("us", 0, 4)))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    assert started.wait(5)
    release.set()
    for t in threads:
        t.join(10)

    assert len(results) == 3 and all(r["scored"] == 4 for r in results)
    assert len(calls) == 1            # üç eşzamanlı istek, tek indirme


# ── Worker girişi ve gunicorn kancası ────────────────────────────────────────

def test_worker_module_imports_only_stdlib():
    """Argümansız worker bekleme modunda uygulamayı/pandas'ı yüklememeli."""
    code = (
        "import sys, backend.worker; "
        "heavy = [m for m in ('flask', 'pandas', 'yfinance', 'sqlalchemy') if m in sys.modules]; "
        "print(','.join(heavy))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""


def test_scheduler_start_is_idempotent_and_respects_disable(app, monkeypatch):
    from backend import scheduler

    monkeypatch.setenv("SCHEDULER_DISABLED", "1")
    assert scheduler.start(app) is False

    monkeypatch.setenv("SCHEDULER_DISABLED", "0")
    gate = threading.Event()
    monkeypatch.setattr(scheduler, "_loop", lambda _app: gate.wait(5))
    try:
        assert scheduler.start(app) is True
        assert scheduler.is_running() is True
        assert scheduler.start(app) is False      # ikinci kez başlamaz
        assert scheduler.status()["running"] is True
    finally:
        gate.set()
        scheduler._state["thread"].join(5)
    assert scheduler.is_running() is False


def test_gunicorn_conf_single_process_and_hook(app, monkeypatch):
    from backend import scheduler

    conf = runpy.run_path(str(ROOT / "gunicorn.conf.py"))
    assert conf["workers"] == 1
    assert conf["worker_class"] == "gthread"
    assert conf["threads"] >= 2

    started = []
    monkeypatch.setattr(scheduler, "start", lambda a: started.append(a) or True)

    class FakeWorker:
        class log:
            @staticmethod
            def exception(*_a, **_k):
                raise AssertionError("kanca hata logladı")

    conf["post_worker_init"](FakeWorker())
    assert started == [app]
    conf["worker_exit"](None, FakeWorker())      # hata fırlatmamalı
