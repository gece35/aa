"""Zamanlayıcının alarm işi + salt-okunur /api/alerts/triggered ucu + sağlık ucu."""

from __future__ import annotations

import pytest


@pytest.fixture()
def alert_setup(app, make_user):
    from backend.alerts import create_alert

    from datetime import timedelta

    from backend.db import db
    from backend.models import Alert
    from backend.security import now_utc

    uid, email, password = make_user()
    with app.app_context():
        above = create_alert(uid, "THYAO.IS", "price_above", 100.0)
        below = create_alert(uid, "AAPL", "price_below", 50.0)
        # Önceden kurulmuş alarmlar gibi davransınlar ("yeni kurulan alarm" kuralı devreye girmesin)
        for alert_id in (above["id"], below["id"]):
            db.session.get(Alert, alert_id).created_at = now_utc() - timedelta(hours=3)
        db.session.commit()
    return {"uid": uid, "email": email, "password": password, "above": above["id"], "below": below["id"]}


@pytest.fixture()
def sent_mails(monkeypatch):
    sent = []
    import backend.email as email_mod

    monkeypatch.setattr(email_mod, "send_alert_triggered",
                        lambda to, symbol, label: sent.append((to, symbol)) or True)
    return sent


def test_alert_fires_once_with_single_batched_download(app, alert_setup, sent_mails):
    from backend import scheduler
    from backend.db import db
    from backend.models import Alert

    fetch_calls = []

    def fake_prices(symbols):
        fetch_calls.append(sorted(symbols))
        return {"THYAO.IS": 120.0, "AAPL": 60.0}   # yalnızca THYAO koşulu sağlanır

    with app.app_context():
        assert scheduler.check_price_alerts(force=True, price_fetcher=fake_prices) == 1
        # İkinci geçiş: aynı alarm tekrar tetiklenmez, e-posta tekrar gitmez
        assert scheduler.check_price_alerts(force=True, price_fetcher=fake_prices) == 0

        fired = db.session.get(Alert, alert_setup["above"])
        pending = db.session.get(Alert, alert_setup["below"])
        assert fired.triggered_at is not None and fired.is_active is False
        assert pending.triggered_at is None and pending.is_active is True

    assert sent_mails == [(alert_setup["email"], "THYAO.IS")]
    assert fetch_calls[0] == ["AAPL", "THYAO.IS"]   # tüm semboller tek çağrıda
    assert fetch_calls[1] == ["AAPL"]               # tetiklenen artık sorulmaz


def test_claim_is_atomic(app, alert_setup):
    from datetime import datetime, timezone

    from backend import scheduler

    with app.app_context():
        now = datetime.now(timezone.utc)
        assert scheduler._claim_alert(alert_setup["above"], now) is True
        assert scheduler._claim_alert(alert_setup["above"], now) is False


def test_no_download_when_markets_closed(app, alert_setup, sent_mails, monkeypatch):
    from backend import scheduler

    monkeypatch.setattr(scheduler, "is_market_open", lambda market, now=None: False)

    def boom(symbols):
        raise AssertionError("pazar kapalıyken fiyat indirilmemeli")

    with app.app_context():
        assert scheduler.check_price_alerts(price_fetcher=boom) == 0
    assert sent_mails == []


def test_new_alert_is_checked_once_even_if_market_closed(app, alert_setup, sent_mails, monkeypatch):
    """Pazar kapalıyken kurulan ve koşulu zaten sağlanan alarm açılışı beklemez."""
    from backend import scheduler
    from backend.alerts import create_alert

    monkeypatch.setattr(scheduler, "is_market_open", lambda market, now=None: False)
    with app.app_context():
        create_alert(alert_setup["uid"], "GARAN.IS", "price_above", 10.0)
        seen = []

        def fake_prices(symbols):
            seen.extend(symbols)
            return {"GARAN.IS": 25.0}

        assert scheduler.check_price_alerts(price_fetcher=fake_prices) == 1
    assert seen == ["GARAN.IS"]                       # eski alarmlar sorulmadı
    assert sent_mails == [(alert_setup["email"], "GARAN.IS")]


def test_only_open_market_symbols_are_checked(app, alert_setup, sent_mails, monkeypatch):
    from backend import scheduler

    monkeypatch.setattr(scheduler, "is_market_open", lambda market, now=None: market == "us")
    seen = []

    def fake_prices(symbols):
        seen.extend(symbols)
        return {"AAPL": 40.0}

    with app.app_context():
        assert scheduler.check_price_alerts(price_fetcher=fake_prices) == 1
    assert seen == ["AAPL"]
    assert sent_mails == [(alert_setup["email"], "AAPL")]


def test_run_due_jobs_cleans_unverified_but_keeps_admins(app, make_user, sent_mails, monkeypatch):
    from datetime import timedelta

    from backend import scheduler
    from backend.db import db
    from backend.models import User
    from backend.security import now_utc

    stale_id, _, _ = make_user("stale@example.com", verified=False)
    admin_id, _, _ = make_user("admin@example.com", verified=False, is_admin=True)
    fresh_id, _, _ = make_user("fresh@example.com", verified=False)
    ok_id, _, _ = make_user("ok@example.com", verified=True)

    with app.app_context():
        old = now_utc() - timedelta(days=30)
        for uid in (stale_id, admin_id, ok_id):
            db.session.get(User, uid).created_at = old
        db.session.commit()

        monkeypatch.setattr(scheduler, "_last_prices", lambda symbols: {})
        out = scheduler.run_due_jobs(force=True)
        assert out["skipped"] is False and out["cleaned"] == 1

        assert db.session.get(User, stale_id) is None
        assert db.session.get(User, admin_id) is not None
        assert db.session.get(User, fresh_id) is not None
        assert db.session.get(User, ok_id) is not None


def test_triggered_endpoint_is_read_only(app, client, alert_setup, login, monkeypatch):
    import app as app_module
    from backend import data_fetcher, scheduler

    def boom(*_a, **_k):
        raise AssertionError("/api/alerts/triggered yfinance çağırmamalı")

    monkeypatch.setattr(app_module, "download_ohlcv", boom)
    monkeypatch.setattr(data_fetcher, "download_ohlcv", boom)

    assert client.get("/api/alerts/triggered").status_code == 401   # misafir

    login(alert_setup["email"], alert_setup["password"])
    r = client.get("/api/alerts/triggered")
    assert r.status_code == 200 and r.get_json()["triggered"] == []

    with app.app_context():
        from datetime import datetime, timezone
        assert scheduler._claim_alert(alert_setup["above"], datetime.now(timezone.utc))

    data = client.get("/api/alerts/triggered").get_json()
    assert [a["id"] for a in data["triggered"]] == [alert_setup["above"]]
    ts = data["triggered"][0]["triggered_at"]
    assert client.get(f"/api/alerts/triggered?since={ts}").get_json()["triggered"] == []
    assert len(client.get(f"/api/alerts/triggered?since={ts - 10}").get_json()["triggered"]) == 1


def test_health_reports_db_schema_and_scheduler(client):
    r = client.get("/api/health")
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["db"] is True
    assert body["schema"] and body["schema"] == body["schema_head"]
    assert body["schema_ok"] is True
    assert body["scheduler"]["running"] is False       # testte zamanlayıcı kapalı
    assert body["migration"]["error"] is None
    mem = body["memory_mb"]
    assert set(mem) == {"rss", "peak", "container"}
    # Linux'ta sayı, diğer sistemlerde None — ama asla hata değil
    assert all(v is None or v > 0 for v in mem.values())


def test_procinfo_parses_proc_and_cgroup(monkeypatch, tmp_path):
    from backend import procinfo

    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmHWM:\t  262144 kB\nVmRSS:\t  204800 kB\n", encoding="ascii")
    cgroup = tmp_path / "memory.current"
    cgroup.write_text("314572800\n", encoding="ascii")

    real_open = open

    def fake_open(path, *a, **kw):
        if path == "/proc/self/status":
            return real_open(status, *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(procinfo, "_CGROUP_FILES", (str(tmp_path / "yok"), str(cgroup)))
    assert procinfo.memory_mb() == {"rss": 200.0, "peak": 256.0, "container": 300.0}
