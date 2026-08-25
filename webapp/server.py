"""Orbit web dashboard.

Launch: python run.py
Open: http://127.0.0.1:8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from orbit import config, controller, data, engine, state, strategy, universe
from webapp.auth import COOKIE_NAME, PUBLIC_PATHS, dashboard_password, is_authenticated, passwords_match, session_token
from backtest.config import BacktestConfig
from backtest.engine import run_backtest
from backtest.metrics import calculate_metrics
from backtest.walk_forward import run_walk_forward

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
CACHE_DIR = ROOT / "data_cache"
WALK_FORWARD_FILE = ROOT / "backtest_output" / "walk_forward.json"
STATE_FILES = {
    "orbit": ROOT / "orbit_state.json",
    "gold": ROOT / "gold_state.json",
    "mnq": ROOT / "mnq_state.json",
}
MOCK_BOTS = {
    "orbit": {
        "bot_id": "orbit",
        "bot_name": "Orbit 1D Crypto Momentum",
        "asset_class": "Crypto Spot",
        "timeframe": "1d",
        "status": "IDLE",
        "total_return_pct": 35.2,
        "sharpe_ratio": 0.50,
        "max_drawdown_pct": -18.9,
        "win_rate_pct": 64.2,
        "profit_factor": 1.34,
        "trade_count": 153,
        "equity_usdt": 13520,
        "equity_curve": [],
        "recent_trades": [],
        "logs": [],
        "accepted": True,
        "mock": True,
    },
    "gold": {
        "bot_id": "gold",
        "bot_name": "Gold 1H Volatility Breakout",
        "asset_class": "XAU/USD",
        "timeframe": "1h",
        "status": "IDLE",
        "total_return_pct": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "win_rate_pct": 0.0,
        "equity_usdt": 100000,
        "equity_curve": [],
        "recent_trades": [],
        "logs": [],
        "mock": True,
    },
    "mnq": {
        "bot_id": "mnq",
        "bot_name": "Nasdaq 15m ORB",
        "asset_class": "MNQ Futures",
        "timeframe": "15m",
        "status": "IDLE",
        "total_return_pct": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "win_rate_pct": 0.0,
        "equity_usdt": 50000,
        "equity_curve": [],
        "recent_trades": [],
        "logs": [],
        "mock": True,
    },
}
BACKTEST_PERIODS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
_backtest_lock = asyncio.Lock()
_wf_lock = threading.Lock()
_wf_thread: threading.Thread | None = None
_wf_status: dict[str, Any] = {"running": False, "error": None}
_log = logging.getLogger("orbit.web")


class SettingsUpdate(BaseModel):
    bot_enabled: bool | None = None
    universe: list[str] | str | None = None
    timeframe: str | None = None
    trend_ema_period: int | None = Field(None, ge=20, le=500)
    fast_ema_period: int | None = Field(None, ge=5, le=200)
    breadth_ema_period: int | None = Field(None, ge=5, le=100)
    rsi_period: int | None = Field(None, ge=2, le=50)
    rsi_threshold: float | None = Field(None, ge=0, le=100)
    full_capacity_rsi: float | None = Field(None, gt=0, le=100)
    defensive_size_mult: float | None = Field(None, gt=0, le=1)
    momentum_lookbacks: list[int] | str | None = None
    volatility_period: int | None = Field(None, ge=5, le=120)
    volume_lookback: int | None = Field(None, ge=5, le=120)
    atr_period: int | None = Field(None, ge=2, le=100)
    rank_buffer: int | None = Field(None, ge=1, le=10)
    max_positions: int | None = Field(None, ge=1, le=10)
    min_hold_days: int | None = Field(None, ge=0, le=60)
    cooldown_days: int | None = Field(None, ge=0, le=30)
    min_momentum: float | None = Field(None, ge=-1.0, le=1.0)
    target_volatility: float | None = Field(None, gt=0.05, le=2.0)
    max_allocation_pct: float | None = Field(None, gt=0, le=1)
    max_portfolio_exposure: float | None = Field(None, gt=0, le=1)
    atr_sl_mult: float | None = Field(None, ge=0.1, le=10)
    trail_atr_mult: float | None = Field(None, ge=0.1, le=20)
    take_profit_atr_mult: float | None = Field(None, ge=0.1, le=20)
    take_profit_fraction: float | None = Field(None, gt=0, le=1)
    min_history_bars: int | None = Field(None, ge=50, le=1000)
    min_dollar_volume: float | None = Field(None, ge=0)
    daily_max_drawdown_pct: float | None = Field(None, ge=0.01, le=0.5)
    flatten_on_drawdown: bool | None = None
    peak_dd_trigger_pct: float | None = Field(None, ge=0.01, le=0.5)
    peak_dd_recover_pct: float | None = Field(None, ge=0.0, le=0.49)
    heat_size_mult: float | None = Field(None, gt=0, le=1)
    heat_max_positions: int | None = Field(None, ge=1, le=10)
    blowoff_rsi: float | None = Field(None, gt=0, le=100)
    blowoff_ema_extension: float | None = Field(None, gt=0, le=2)
    shock_lookback: int | None = Field(None, ge=1, le=30)
    shock_trigger_pct: float | None = Field(None, ge=-0.5, lt=0)
    shock_recover_pct: float | None = Field(None, ge=-0.2, le=0.2)
    shock_trail_atr_mult: float | None = Field(None, ge=0.1, le=20)
    equity_lock_pct: float | None = Field(None, ge=0.05, le=0.5)
    lock_reclaim_rsi: float | None = Field(None, gt=0, le=100)
    slot_expand_rsi: float | None = Field(None, gt=0, le=100)
    rs_lookback: int | None = Field(None, ge=1, le=60)
    rotation_roc_edge: float | None = Field(None, ge=0.0, le=1.0)
    chop_roc_min: float | None = Field(None, ge=-1.0, le=1.0)
    stop_pause_bars: int | None = Field(None, ge=0, le=30)
    late_cycle_buffer: float | None = Field(None, ge=0.0, le=0.2)
    regime_confirm_bars: int | None = Field(None, ge=1, le=5)
    btc_core: bool | None = None
    macro_confirm_bars: int | None = Field(None, ge=1, le=5)
    drift_max_positions: int | None = Field(None, ge=0, le=10)
    drift_max_allocation_pct: float | None = Field(None, gt=0, le=1)
    loop_interval_sec: int | None = Field(None, ge=10, le=3600)


class BacktestRequest(BaseModel):
    period: str = "1m"
    initial_capital: float = Field(10_000.0, gt=0, le=100_000_000)


def _json_safe(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (ValueError, AttributeError):
            pass
    return str(value)


def _normalize_updates(updates: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(updates)
    if "universe" in cleaned:
        cleaned["universe"] = list(universe.parse_universe(cleaned["universe"]))
    if "momentum_lookbacks" in cleaned:
        value = cleaned["momentum_lookbacks"]
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
            cleaned["momentum_lookbacks"] = [int(float(p)) for p in parts]
        else:
            cleaned["momentum_lookbacks"] = [int(v) for v in value]
    return cleaned


def _config_from_settings(settings: dict[str, Any], capital: float) -> BacktestConfig:
    lookbacks = settings.get("momentum_lookbacks") or [7, 14, 30]
    if isinstance(lookbacks, str):
        lookbacks = [int(float(p)) for p in lookbacks.split(",") if p.strip()]
    return BacktestConfig(
        initial_capital=capital,
        universe=tuple(universe.parse_universe(settings.get("universe"))),
        regime_symbol=config.REGIME_SYMBOL,
        trend_ema_period=int(settings["trend_ema_period"]),
        fast_ema_period=int(settings.get("fast_ema_period", 50)),
        breadth_ema_period=int(settings.get("breadth_ema_period", 20)),
        rsi_period=int(settings.get("rsi_period", 14)),
        rsi_threshold=float(settings.get("rsi_threshold", 45.0)),
        full_capacity_rsi=float(settings.get("full_capacity_rsi", 50.0)),
        defensive_size_mult=float(settings.get("defensive_size_mult", 0.50)),
        momentum_lookbacks=tuple(int(v) for v in lookbacks),
        volatility_period=int(settings["volatility_period"]),
        volume_lookback=int(settings["volume_lookback"]),
        atr_period=int(settings["atr_period"]),
        rank_buffer=int(settings["rank_buffer"]),
        max_positions=int(settings.get("max_positions", 1)),
        min_hold_days=int(settings["min_hold_days"]),
        cooldown_days=int(settings["cooldown_days"]),
        min_momentum=float(settings["min_momentum"]),
        target_volatility=float(settings["target_volatility"]),
        max_allocation_pct=float(settings["max_allocation_pct"]),
        max_portfolio_exposure=float(settings.get("max_portfolio_exposure", 0.90)),
        atr_sl_mult=float(settings["atr_sl_mult"]),
        trail_atr_mult=float(settings["trail_atr_mult"]),
        take_profit_atr_mult=float(settings.get("take_profit_atr_mult", 2.0)),
        take_profit_fraction=float(settings.get("take_profit_fraction", 0.50)),
        min_history_bars=int(settings["min_history_bars"]),
        min_dollar_volume=float(settings["min_dollar_volume"]),
        daily_max_drawdown_pct=float(settings["daily_max_drawdown_pct"]),
        peak_dd_trigger_pct=float(settings.get("peak_dd_trigger_pct", 0.10)),
        peak_dd_recover_pct=float(settings.get("peak_dd_recover_pct", 0.04)),
        heat_size_mult=float(settings.get("heat_size_mult", 0.50)),
        heat_max_positions=int(settings.get("heat_max_positions", 1)),
        blowoff_rsi=float(settings.get("blowoff_rsi", 75.0)),
        blowoff_ema_extension=float(settings.get("blowoff_ema_extension", 0.30)),
        shock_lookback=int(settings.get("shock_lookback", 5)),
        shock_trigger_pct=float(settings.get("shock_trigger_pct", -0.08)),
        shock_recover_pct=float(settings.get("shock_recover_pct", 0.0)),
        shock_trail_atr_mult=float(settings.get("shock_trail_atr_mult", 1.0)),
        equity_lock_pct=float(settings.get("equity_lock_pct", 0.15)),
        lock_reclaim_rsi=float(settings.get("lock_reclaim_rsi", 55.0)),
        slot_expand_rsi=float(settings.get("slot_expand_rsi", 55.0)),
        rs_lookback=int(settings.get("rs_lookback", 14)),
        rotation_roc_edge=float(settings.get("rotation_roc_edge", 0.05)),
        chop_roc_min=float(settings.get("chop_roc_min", 0.0)),
        stop_pause_bars=int(settings.get("stop_pause_bars", 0)),
        late_cycle_buffer=float(settings.get("late_cycle_buffer", 0.0)),
        regime_confirm_bars=int(settings.get("regime_confirm_bars", 1)),
        btc_core=bool(settings.get("btc_core", False)),
        macro_confirm_bars=int(settings.get("macro_confirm_bars", 1)),
        drift_max_positions=int(settings.get("drift_max_positions", 1)),
        drift_max_allocation_pct=float(
            settings.get("drift_max_allocation_pct", 0.15)
        ),
    )


def _build_panel(cfg: BacktestConfig, timeframe: str, until: datetime) -> data.Panel:
    symbols = universe.symbols_to_fetch(cfg.universe)
    raw = data.fetch_panel(
        symbols,
        timeframe,
        data.history_start_ms(),
        int(until.timestamp() * 1000),
        cache_dir=CACHE_DIR,
        exchange=config.public_exchange,
    )
    return data.align_panel(data.apply_indicators(raw, **cfg.indicator_params()))


def _run_dashboard_backtest(period: str, capital: float) -> dict[str, Any]:
    settings = state.load_settings()
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=BACKTEST_PERIODS[period])
    cfg = _config_from_settings(settings, capital)
    panel = _build_panel(cfg, str(settings["timeframe"]), until)
    window = panel.slice_dates(
        pd.Timestamp(since).tz_convert("UTC"),
        pd.Timestamp(until).tz_convert("UTC"),
    )
    result = run_backtest(window, cfg)
    metrics = calculate_metrics(result, window, cfg)
    trades = [
        {**t, "entry_time": str(t["entry_time"]), "exit_time": str(t["exit_time"])}
        for t in result.trades[-20:][::-1]
    ]
    return _json_safe({
        "ok": True,
        "period": period,
        "period_label": {
            "1m": "Past month", "3m": "Past 3 months",
            "6m": "Past 6 months", "1y": "Past year",
        }[period],
        "universe_size": len(cfg.universe),
        "timeframe": settings["timeframe"],
        "from": str(window.dates[0]),
        "to": str(window.dates[-1]),
        "candle_count": len(window),
        "metrics": metrics,
        "trades": trades,
        "skipped_signals": result.skipped_signals,
        "note": _backtest_note(metrics, result.skipped_signals),
    })


def _run_walk_forward(capital: float) -> dict[str, Any]:
    settings = state.load_settings()
    cfg = _config_from_settings(settings, capital)
    until = datetime.now(timezone.utc)
    raw = data.fetch_panel(
        universe.symbols_to_fetch(cfg.universe),
        str(settings["timeframe"]),
        data.history_start_ms(),
        int(until.timestamp() * 1000),
        cache_dir=CACHE_DIR,
        exchange=config.public_exchange,
    )
    result = run_walk_forward(raw, cfg)
    view = _json_safe(_walk_forward_view(result))
    WALK_FORWARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    WALK_FORWARD_FILE.write_text(json.dumps(view, indent=2), encoding="utf-8")
    return view


def _walk_forward_view(payload: dict[str, Any]) -> dict[str, Any]:
    agg = payload.get("aggregate") or {}
    folds = []
    for fold in payload.get("folds") or []:
        test = fold.get("test") or {}
        folds.append({
            "test_from": fold.get("test_from"),
            "test_to": fold.get("test_to"),
            "test": {
                "total_return_pct": test.get("total_return_pct"),
                "max_drawdown_pct": test.get("max_drawdown_pct"),
                "trade_count": test.get("trade_count"),
            },
        })
    return {
        "ok": True,
        "aggregate": {
            "return_pct": agg.get("return_pct"),
            "benchmark_return_pct": agg.get("benchmark_return_pct"),
            "sharpe": agg.get("sharpe"),
            "max_drawdown_pct": agg.get("max_drawdown_pct"),
            "profit_factor": agg.get("profit_factor"),
            "trade_count": agg.get("trade_count"),
            "positive_fold_pct": agg.get("positive_fold_pct"),
            "fold_count": agg.get("fold_count"),
        },
        "folds": folds,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.ensure_settings_file()
    config.reload_settings()
    state.append_log("Orbit platform started — http://127.0.0.1:8080", "INFO")
    autostart = os.getenv("ORBIT_AUTOSTART", "").strip().lower() in {"1", "true", "yes"}
    if autostart:
        state.save_settings({"bot_enabled": True})
        config.reload_settings()
        controller.start(engine.run_bot_loop)
        state.append_log("Orbit autostart enabled — trading loop running", "INFO")
    yield
    controller.stop()


app = FastAPI(title="Orbit", lifespan=lifespan)


@app.middleware("http")
async def dashboard_password_gate(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/login"):
        return await call_next(request)
    if is_authenticated(request):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"ok": False, "message": "unauthorized"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": False})


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    expected = dashboard_password()
    if passwords_match(password, expected):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            session_token(),
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
        return response
    return TEMPLATES.TemplateResponse(
        request, "login.html", {"error": True}, status_code=401
    )


@app.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


def _load_bot_state(bot_id: str) -> dict[str, Any]:
    base = dict(MOCK_BOTS.get(bot_id) or {"bot_id": bot_id, "bot_name": bot_id})
    path = STATE_FILES.get(bot_id)
    if path is None or not path.exists():
        base["mock"] = True
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        merged = {**base, **raw, "bot_id": bot_id, "mock": False}
        if not merged.get("equity_curve"):
            merged["equity_curve"] = base.get("equity_curve") or []
        return merged
    except (OSError, json.JSONDecodeError):
        base["mock"] = True
        return base


def _portfolio_payload() -> dict[str, Any]:
    bots = [_load_bot_state(bot_id) for bot_id in ("orbit", "gold", "mnq")]
    combined = sum(float(b.get("equity_usdt") or 0) for b in bots)
    avg_ret = sum(float(b.get("total_return_pct") or 0) for b in bots) / max(len(bots), 1)
    global_dd = min(float(b.get("max_drawdown_pct") or 0) for b in bots)
    live = sum(1 for b in bots if not b.get("mock"))
    health = "healthy" if live == 3 else "degraded" if live else "offline"
    return {
        "ok": True,
        "combined_equity": combined,
        "monthly_pnl_pct": round(avg_ret, 2),
        "global_max_dd_pct": global_dd,
        "system_health": health,
        "bots": bots,
    }


@app.get("/", response_class=HTMLResponse)
async def platform_home(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "platform.html", {})


@app.get("/crypto", response_class=HTMLResponse)
async def crypto_desk(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "settings": state.load_settings(),
            "defaults_json": json.dumps(state.DEFAULT_SETTINGS),
        },
    )


@app.get("/bot/{bot_id}", response_class=HTMLResponse)
async def bot_detail_page(request: Request, bot_id: str) -> HTMLResponse:
    if bot_id == "orbit":
        return await crypto_desk(request)
    if bot_id not in STATE_FILES:
        return HTMLResponse("Unknown bot", status_code=404)
    return TEMPLATES.TemplateResponse(request, "bot_detail.html", {"bot_id": bot_id})


@app.get("/api/bots")
async def api_bots(id: str | None = Query(None)) -> dict[str, Any]:
    if id:
        if id not in STATE_FILES and id not in MOCK_BOTS:
            return {"ok": False, "message": "Unknown bot"}
        return {"ok": True, "bot": _load_bot_state(id)}
    return _portfolio_payload()


@app.get("/api/state")
async def api_state() -> dict[str, Any]:
    s = state.load_state()
    status = controller.status()
    s["bot_running"] = status["running"]
    s["last_error"] = status.get("last_error")
    s["settings"] = state.load_settings()
    return s


@app.get("/api/settings")
async def api_settings() -> dict[str, Any]:
    return state.load_settings()


@app.post("/api/settings")
async def api_update_settings(body: SettingsUpdate) -> dict[str, Any]:
    updates = _normalize_updates(body.model_dump(exclude_none=True))
    saved = state.save_settings(updates)
    config.reload_settings()
    state.append_log(f"Settings saved: {', '.join(updates.keys())}", "INFO")
    return {"ok": True, "settings": saved}


@app.get("/api/rankings")
async def api_rankings() -> JSONResponse:
    try:
        config.reload_settings()
        frames = {}
        for symbol in universe.symbols_to_fetch(config.UNIVERSE):
            try:
                frames[symbol] = data.fetch_ohlcv(symbol=symbol, public=True)
            except Exception:
                continue
        if config.REGIME_SYMBOL not in frames:
            raise ValueError("Could not fetch BTC regime data.")
        regime_row = data.get_completed_candles(frames[config.REGIME_SYMBOL], 1).iloc[-1]
        regime = strategy.evaluate_regime(
            strategy.snapshot_from_series(config.REGIME_SYMBOL, regime_row)
        )
        risk_on, reason = regime.macro_on, regime.reason
        snaps = []
        for symbol in config.UNIVERSE:
            if symbol not in frames:
                continue
            try:
                snaps.append(strategy.snapshot_from_series(
                    symbol, data.get_completed_candles(frames[symbol], 1).iloc[-1]
                ))
            except ValueError:
                continue
        candidates = strategy.evaluate_candidates(snaps)
        live = state.load_state()
        held = list(live.get("active_symbols") or [])
        if not held:
            primary = live.get("position") or {}
            if primary.get("status") == "long" and primary.get("symbol"):
                held = [primary["symbol"]]
        payload = {
            "ok": True,
            "regime": {
                "risk_on": risk_on,
                "allow_new": regime.allow_new,
                "reason": reason,
                "symbol": config.REGIME_SYMBOL,
                "close": float(regime_row["close"]),
                "trend_ema": float(regime_row["trend_ema"]) if pd.notna(regime_row.get("trend_ema")) else None,
                "fast_ema": float(regime_row["fast_ema"]) if pd.notna(regime_row.get("fast_ema")) else None,
                "rsi": float(regime_row["rsi"]) if pd.notna(regime_row.get("rsi")) else None,
                "candle_time": str(regime_row["timestamp"]),
                "blowoff": strategy.is_blowoff(
                    strategy.snapshot_from_series(config.REGIME_SYMBOL, regime_row)
                ),
            },
            "rankings": strategy.rankings_payload(candidates, held),
            "held": held,
        }
        state.update_state(rankings=payload["rankings"], regime=payload["regime"])
        return JSONResponse(payload)
    except (ccxt.BaseError, ValueError) as exc:
        cached = state.load_state()
        return JSONResponse({
            "ok": False,
            "rankings": cached.get("rankings") or [],
            "regime": cached.get("regime") or {},
            "error": str(exc),
        })


@app.post("/api/backtest")
async def api_backtest(body: BacktestRequest) -> JSONResponse:
    if body.period not in BACKTEST_PERIODS:
        return JSONResponse({"ok": False, "message": "Invalid period."}, status_code=422)
    if _backtest_lock.locked():
        return JSONResponse({"ok": False, "message": "Already running."}, status_code=409)
    async with _backtest_lock:
        try:
            response = await asyncio.to_thread(
                _run_dashboard_backtest, body.period, body.initial_capital
            )
            return JSONResponse(response)
        except (ccxt.BaseError, OSError, ValueError) as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)


def _walk_forward_job(capital: float) -> None:
    try:
        _run_walk_forward(capital)
        _wf_status["error"] = None
    except Exception as exc:
        _log.exception("Walk-forward failed")
        _wf_status["error"] = str(exc)
    finally:
        _wf_status["running"] = False


def _load_walk_forward_view() -> dict[str, Any] | None:
    if not WALK_FORWARD_FILE.exists():
        return None
    try:
        payload = json.loads(WALK_FORWARD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("aggregate") is None:
        return None
    return _json_safe(_walk_forward_view(payload))


@app.get("/api/walk-forward")
async def api_walk_forward_get() -> JSONResponse:
    if _wf_status["running"]:
        return JSONResponse({"ok": False, "running": True, "message": "Walk-forward is running."})
    if _wf_status["error"]:
        return JSONResponse({"ok": False, "running": False, "message": _wf_status["error"]})
    view = _load_walk_forward_view()
    if view is None:
        return JSONResponse({"ok": False, "empty": True})
    return JSONResponse(view)


@app.post("/api/walk-forward")
async def api_walk_forward(body: BacktestRequest) -> JSONResponse:
    global _wf_thread
    with _wf_lock:
        if _wf_status["running"] or (_wf_thread is not None and _wf_thread.is_alive()):
            return JSONResponse({"ok": True, "running": True, "message": "Walk-forward is already running."})
        _wf_status["running"] = True
        _wf_status["error"] = None
        _wf_thread = threading.Thread(
            target=_walk_forward_job,
            args=(body.initial_capital,),
            daemon=True,
            name="walk-forward",
        )
        _wf_thread.start()
    return JSONResponse({"ok": True, "running": True, "message": "Walk-forward started."})


def _backtest_note(metrics: dict[str, Any], skipped: dict[str, int]) -> str | None:
    trades = int(metrics.get("trade_count") or 0)
    cash = float(metrics.get("cash_time_pct") or 0.0)
    ret = float(metrics.get("total_return_pct") or 0.0)
    if trades == 0:
        top = max(skipped, key=skipped.get) if skipped else None
        why = {
            "regime risk-off": (
                "BTC was below its 200-day EMA, so Orbit sat in USDT the whole window."
            ),
            "fast regime off": (
                "BTC was below its 50-day EMA (or RSI was weak), so no new entries were allowed."
            ),
            "no qualifying asset": (
                "No coin cleared trend + positive momentum, so the book stayed flat."
            ),
            "cooldown": "Entries were skipped by the post-stop cooldown.",
            "daily loss guard": "The daily loss guard blocked new entries.",
            "blow-off": (
                "BTC was overbought (RSI > 75 or more than 30% above its 50-day EMA), "
                "so new altcoin entries were blocked."
            ),
            "market shock": (
                "BTC's 5-day return was below -8%, so new buys were blocked until "
                "that return turned positive."
            ),
            "risk mitigation": (
                "Portfolio equity was more than 12% below its in-market peak, "
                "so slots 2 and 3 stayed closed."
            ),
            "equity lock": (
                "Portfolio equity dropped 20% from its session peak, so Orbit "
                "flattened to USDT until BTC reclaimed its 50-day EMA with RSI > 55."
            ),
        }.get(top, "Orbit did not open a trade in this window.")
        return (
            f"Return is 0% because there were 0 trades. {why} "
            "Short 1M/3M windows often land entirely inside a cash regime."
        )
    if abs(ret) < 0.05 and cash >= 80:
        return (
            f"Return is near 0% because Orbit spent {cash:.0f}% of the window in USDT. "
            "That is expected in risk-off or fast-regime-off stretches."
        )
    return None


@app.post("/api/bot/start")
async def api_bot_start() -> JSONResponse:
    try:
        state.save_settings({"bot_enabled": True})
        config.reload_settings()
        drawdown = bool((state.load_state().get("drawdown_state") or {}).get("paused"))
        state.update_state(
            trading_paused=drawdown,
            pause_reason="drawdown" if drawdown else None,
        )
        return JSONResponse(controller.start(engine.run_bot_loop))
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)


@app.post("/api/bot/stop")
async def api_bot_stop() -> JSONResponse:
    return JSONResponse(controller.stop())


@app.post("/api/bot/run-once")
async def api_bot_run_once() -> JSONResponse:
    result = controller.run_once(engine.run_single_iteration)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/bot/pause")
async def api_bot_pause() -> dict[str, Any]:
    saved = state.save_settings({"bot_enabled": False})
    config.reload_settings()
    state.update_state(trading_paused=True, pause_reason="manual")
    return {"ok": True, "settings": saved}


@app.post("/api/bot/resume")
async def api_bot_resume() -> dict[str, Any]:
    saved = state.save_settings({"bot_enabled": True})
    config.reload_settings()
    drawdown = bool((state.load_state().get("drawdown_state") or {}).get("paused"))
    state.update_state(
        trading_paused=drawdown,
        pause_reason="drawdown" if drawdown else None,
    )
    return {"ok": True, "settings": saved}


@app.get("/api/candles")
async def api_candles(symbol: str | None = Query(default=None)) -> dict[str, Any]:
    try:
        config.reload_settings()
        chart_symbol = (
            symbol
            or state.load_state().get("chart_symbol")
            or config.REGIME_SYMBOL
        )
        # Always public — sandbox OHLCV is nearly empty.
        df = data.fetch_ohlcv(symbol=chart_symbol, public=True)
        candles = data.candles_for_chart(df.iloc[:-1])
        state.update_state(candles=candles, chart_symbol=chart_symbol)
        return {
            "ok": True,
            "candles": candles,
            "count": len(candles),
            "symbol": chart_symbol,
            "source": "public",
        }
    except (ccxt.BaseError, ValueError) as exc:
        cached = state.load_state().get("candles", [])
        return {"ok": False, "candles": cached, "source": "cache", "error": str(exc)}


@app.get("/api/logs/stream")
async def api_logs_stream() -> StreamingResponse:
    async def generate():
        seen = len(state.load_state().get("logs", []))
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"
        while True:
            logs = state.load_state().get("logs", [])
            while seen < len(logs):
                yield f"data: {json.dumps({'type': 'log', 'entry': logs[seen]})}\n\n"
                seen += 1
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "bot_running": str(controller.is_running())}
