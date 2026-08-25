"""Safe Binance Spot Testnet execution helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import ccxt


@dataclass(frozen=True)
class BalanceSnapshot:
    quote_free: float
    quote_total: float
    base_free: float
    base_total: float

    def equity(self, price: float) -> float:
        return self.quote_total + self.base_total * price


@dataclass(frozen=True)
class FillResult:
    order_id: str
    status: str
    side: str
    quantity: float
    average_price: float
    cost: float
    fee: float
    raw: dict[str, Any]


def split_symbol(symbol: str) -> tuple[str, str]:
    base, quote = symbol.split("/", 1)
    return base, quote.split(":", 1)[0]


def fetch_balances(exchange: ccxt.Exchange, symbol: str) -> BalanceSnapshot:
    base, quote = split_symbol(symbol)
    balance = exchange.fetch_balance()
    base_row = balance.get(base, {}) or {}
    quote_row = balance.get(quote, {}) or {}
    return BalanceSnapshot(
        quote_free=float(quote_row.get("free") or 0.0),
        quote_total=float(quote_row.get("total") or 0.0),
        base_free=float(base_row.get("free") or 0.0),
        base_total=float(base_row.get("total") or 0.0),
    )


def client_order_id(symbol: str, candle_ts: object, action: str) -> str:
    seed = f"{symbol}|{candle_ts}|{action}".encode()
    digest = hashlib.sha256(seed).hexdigest()[:20]
    return f"orbit-{action.lower()}-{digest}"[:36]


def normalize_quantity(
    exchange: ccxt.Exchange,
    symbol: str,
    desired_quantity: float,
    price: float,
    *,
    available_quote: float | None = None,
) -> float:
    """Apply cash, precision, amount, and notional constraints."""
    exchange.load_markets()
    market = exchange.market(symbol)
    quantity = max(0.0, desired_quantity)
    if available_quote is not None and price > 0:
        quantity = min(quantity, available_quote * 0.998 / price)
    quantity = float(exchange.amount_to_precision(symbol, quantity))
    limits = market.get("limits") or {}
    min_amount = ((limits.get("amount") or {}).get("min")) or 0.0
    min_cost = ((limits.get("cost") or {}).get("min")) or 0.0
    if quantity <= 0 or quantity < float(min_amount):
        return 0.0
    if price > 0 and quantity * price < float(min_cost):
        return 0.0
    return quantity


def _to_fill(order: dict[str, Any], fallback_price: float) -> FillResult:
    fee_data = order.get("fee") or {}
    quantity = float(order.get("filled") or order.get("amount") or 0.0)
    average = float(order.get("average") or order.get("price") or fallback_price)
    return FillResult(
        order_id=str(order.get("id") or ""),
        status=str(order.get("status") or "unknown"),
        side=str(order.get("side") or ""),
        quantity=quantity,
        average_price=average,
        cost=float(order.get("cost") or quantity * average),
        fee=float(fee_data.get("cost") or 0.0),
        raw=order,
    )


def place_market_order(
    exchange: ccxt.Exchange,
    symbol: str,
    side: str,
    quantity: float,
    reference_price: float,
    order_client_id: str,
) -> FillResult:
    params = {"newClientOrderId": order_client_id}
    order = exchange.create_order(symbol, "market", side, quantity, None, params)
    order_id = order.get("id")
    if order_id and order.get("status") not in {"closed", "canceled"}:
        try:
            order = exchange.fetch_order(order_id, symbol)
        except ccxt.BaseError:
            pass
    return _to_fill(order, reference_price)


def place_protective_oco(
    exchange: ccxt.Exchange,
    symbol: str,
    quantity: float,
    stop_loss: float,
    take_profit: float,
) -> list[str]:
    """Place an exchange-side OCO when CCXT exposes Binance's endpoint."""
    exchange.load_markets()
    market = exchange.market(symbol)
    market_id = market["id"]
    amount = exchange.amount_to_precision(symbol, quantity)
    stop = exchange.price_to_precision(symbol, stop_loss)
    limit_price = exchange.price_to_precision(symbol, stop_loss * 0.999)
    take = exchange.price_to_precision(symbol, take_profit)
    params = {
        "symbol": market_id,
        "side": "SELL",
        "quantity": amount,
        "price": take,
        "stopPrice": stop,
        "stopLimitPrice": limit_price,
        "stopLimitTimeInForce": "GTC",
    }
    endpoint = getattr(exchange, "private_post_order_oco", None)
    if endpoint is None:
        return []
    response = endpoint(params)
    reports = response.get("orderReports") or []
    return [str(item.get("orderId")) for item in reports if item.get("orderId")]


def place_catastrophic_stop(
    exchange: ccxt.Exchange,
    symbol: str,
    quantity: float,
    stop_price: float,
) -> list[str]:
    """Place a fixed exchange-side stop-limit below the software trailing stop."""
    exchange.load_markets()
    market = exchange.market(symbol)
    endpoint = getattr(exchange, "private_post_order", None)
    if endpoint is None:
        return []
    response = endpoint({
        "symbol": market["id"],
        "side": "SELL",
        "type": "STOP_LOSS_LIMIT",
        "quantity": exchange.amount_to_precision(symbol, quantity),
        "stopPrice": exchange.price_to_precision(symbol, stop_price),
        "price": exchange.price_to_precision(symbol, stop_price * 0.995),
        "timeInForce": "GTC",
    })
    order_id = response.get("orderId")
    return [str(order_id)] if order_id else []


def cancel_open_orders(exchange: ccxt.Exchange, symbol: str) -> None:
    """Release base asset locked by protective orders before a market exit."""
    try:
        exchange.cancel_all_orders(symbol)
    except (ccxt.OrderNotFound, ccxt.NotSupported):
        return
