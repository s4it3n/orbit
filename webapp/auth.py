"""Dashboard password gate (cookie session)."""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Request

COOKIE_NAME = "orbit_session"
PUBLIC_PATHS = {"/login", "/logout", "/api/health"}
PUBLIC_PREFIXES = ("/login", "/static/")


def dashboard_password() -> str:
    token = os.getenv("ORBIT_DASHBOARD_TOKEN", "").strip()
    password = os.getenv("ORBIT_DASHBOARD_PASSWORD", "").strip()
    return password or token or "1234"


def session_token() -> str:
    return hashlib.sha256(f"orbit-dashboard|{dashboard_password()}".encode("utf-8")).hexdigest()


def passwords_match(got: str, expected: str) -> bool:
    left = got.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        hmac.compare_digest(right, right)
        return False
    return hmac.compare_digest(left, right)


def is_authenticated(request: Request) -> bool:
    got = request.cookies.get(COOKIE_NAME) or ""
    expected = session_token()
    return passwords_match(got, expected)
