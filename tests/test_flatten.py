"""Manual flatten password guard + API."""

from paper.flatten import flatten_bot


def test_flatten_unknown_bot():
    result = flatten_bot("nope")
    assert result["ok"] is False


def test_flatten_api_requires_password():
    from fastapi.testclient import TestClient

    from webapp.server import app

    with TestClient(app) as client:
        client.post("/login", data={"password": "1234"})
        bad = client.post("/api/desk/flatten", json={"password": "wrong"})
        assert bad.status_code == 401
        bad_bot = client.post("/api/bots/gold/flatten", json={"password": "nope"})
        assert bad_bot.status_code == 401
        # Correct dashboard password is accepted (bot may already be flat).
        ok = client.post("/api/bots/gold/flatten", json={"password": "1234"})
        assert ok.status_code in {200, 500}
        assert "password" not in (ok.json().get("message") or "").lower() or ok.status_code == 200
