"""Web helpers."""

from webapp.server import BACKTEST_PERIODS, ROOT, _backtest_note, _json_safe


def test_periods_and_json_safe():
    assert set(BACKTEST_PERIODS) == {"1m", "3m", "6m", "1y"}
    cleaned = _json_safe({"a": float("inf"), "b": [float("nan")], "c": 1})
    assert cleaned["a"] is None and cleaned["b"][0] is None and cleaned["c"] == 1


def test_zero_return_note_explains_cash_regime():
    note = _backtest_note(
        {"trade_count": 0, "cash_time_pct": 100.0, "total_return_pct": 0.0},
        {"regime risk-off": 20},
    )
    assert note and "0 trades" in note and "200-day" in note


def test_zero_return_note_explains_circuit_breakers():
    note = _backtest_note(
        {"trade_count": 0, "cash_time_pct": 100.0, "total_return_pct": 0.0},
        {"market shock": 12},
    )
    assert note and "5-day" in note


def test_password_login_required():
    from fastapi.testclient import TestClient

    from webapp.server import app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 303
        assert home.headers["location"].endswith("/login")
        assert client.get("/api/bots").status_code == 401
        bad = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
        assert bad.status_code == 401
        ok = client.post("/login", data={"password": "1234"}, follow_redirects=False)
        assert ok.status_code == 303
        assert client.get("/").status_code == 200
        assert client.get("/api/bots").status_code == 200


def test_platform_routes_serve_real_bots():
    from fastapi.testclient import TestClient

    from webapp.server import app

    if not (ROOT / "gold_state.json").exists() or not (ROOT / "mnq_state.json").exists():
        return
    with TestClient(app) as client:
        client.post("/login", data={"password": "1234"})
        assert client.get("/").status_code == 200
        assert client.get("/crypto").status_code == 200
        assert client.get("/bot/gold").status_code == 200
        assert client.get("/bot/mnq").status_code == 200
        payload = client.get("/api/bots").json()
        assert payload["ok"] is True
        bots = {row["bot_id"]: row for row in payload["bots"]}
        assert bots["gold"]["mock"] is False
        assert bots["mnq"]["mock"] is False
        assert "Yahoo" in str(bots["gold"].get("data_source"))
        assert "Yahoo" in str(bots["mnq"].get("data_source"))
        assert bots["gold"]["total_return_pct"] > 0
        assert bots["mnq"]["total_return_pct"] > 0
        assert bots["orbit"]["total_return_pct"] == 35.2
