"""
Configuration module for the EMA paper-trading bot.

Loads environment variables, initializes the CCXT Binance exchange in
sandbox/testnet mode, and exposes global strategy parameters.
"""

import os

import ccxt
from dotenv import load_dotenv

# Load variables from .env in the project root (if present).
load_dotenv()

# ---------------------------------------------------------------------------
# API credentials (required for authenticated endpoints like balance/orders)
# ---------------------------------------------------------------------------
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY: str = os.getenv("BINANCE_SECRET_KEY", "")

# Telegram alerts (optional — leave blank to disable)
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# CCXT exchange instance — Binance spot, sandbox/testnet enabled
# ---------------------------------------------------------------------------
exchange: ccxt.binance = ccxt.binance(
    {
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
)
exchange.set_sandbox_mode(True)

# ---------------------------------------------------------------------------
# Trading & risk parameters
# ---------------------------------------------------------------------------
TRADING_SYMBOL: str = "BTC/USDT"
TIMEFRAME: str = "1h"
RISK_PER_TRADE_PCT: float = 0.01          # Risk 1 % of balance per trade
DAILY_MAX_DRAWDOWN_PCT: float = 0.03      # Halt trading after 3 % daily loss

# Indicator settings
EMA_FAST: int = 20
EMA_SLOW: int = 50
ATR_PERIOD: int = 14
ATR_SL_MULT: float = 1.0                    # Stop-loss distance = 1 × ATR
ATR_TP_MULT: float = 2.0                    # Take-profit distance = 2 × ATR

# Data fetch settings
CANDLE_LIMIT: int = 100
