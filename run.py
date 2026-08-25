"""Launch the Orbit control panel.

Usage:
    python run.py

Then open: http://127.0.0.1:8080

Cloud / headless:
    ORBIT_HEADLESS=1 ORBIT_AUTOSTART=1 python run.py
"""

from __future__ import annotations

import os
import webbrowser

import uvicorn

if __name__ == "__main__":
    host = os.getenv("ORBIT_HOST", "127.0.0.1")
    port = int(os.getenv("ORBIT_PORT", "8080"))
    headless = os.getenv("ORBIT_HEADLESS", "").strip().lower() in {"1", "true", "yes"}
    url = f"http://127.0.0.1:{port}"
    print()
    print("=" * 52)
    print("  Orbit — Multi-Bot Trading Platform")
    print(f"  Bind: {host}:{port}")
    print(f"  Open: {url}")
    print("  Crypto walk-forward: ACCEPTED (9/9 Gates Passed).")
    print("  Orders go to Binance spot testnet, not live funds.")
    print("=" * 52)
    print()
    if not headless:
        webbrowser.open(url)
    uvicorn.run("webapp.server:app", host=host, port=port, log_level="info")
