"""Cash, positions and fills for a long-only paper account."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .models import Fill, Order, Position, Side


class InsufficientFunds(Exception):
    """Raised when an order would overdraw the account."""


class InsufficientPosition(Exception):
    """Raised when a sell would take the position short."""


class Portfolio:
    """Tracks cash and positions as fills are applied.

    Short selling is rejected rather than modelled: a sell is only accepted up
    to the quantity currently held.
    """

    def __init__(self, cash: float = 10_000.0, fee_rate: float = 0.0) -> None:
        if cash < 0:
            raise ValueError(f"cash must not be negative, got {cash}")
        if fee_rate < 0:
            raise ValueError(f"fee_rate must not be negative, got {fee_rate}")
        self.initial_cash = cash
        self.cash = cash
        self.fee_rate = fee_rate
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.realized_pnl = 0.0
        self.total_fees = 0.0

    def position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol))

    def quantity(self, symbol: str) -> float:
        return self.position(symbol).quantity

    def execute(self, order: Order, price: float, timestamp: datetime) -> Fill:
        """Fill ``order`` at ``price`` and apply it to cash and positions."""
        if price <= 0:
            raise ValueError(f"price must be positive, got {price}")

        notional = order.quantity * price
        fee = notional * self.fee_rate
        position = self.positions.setdefault(order.symbol, Position(order.symbol))

        if order.side is Side.BUY:
            if notional + fee > self.cash:
                raise InsufficientFunds(
                    f"need {notional + fee:.2f} to buy {order.quantity} "
                    f"{order.symbol}, have {self.cash:.2f}"
                )
            self.cash -= notional + fee
            total_quantity = position.quantity + order.quantity
            position.avg_price = (
                position.avg_price * position.quantity + notional
            ) / total_quantity
            position.quantity = total_quantity
        else:
            if order.quantity > position.quantity:
                raise InsufficientPosition(
                    f"cannot sell {order.quantity} {order.symbol}, "
                    f"hold {position.quantity}"
                )
            self.cash += notional - fee
            self.realized_pnl += (price - position.avg_price) * order.quantity
            position.quantity -= order.quantity
            if position.is_flat:
                position.avg_price = 0.0

        self.total_fees += fee
        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fee=fee,
            timestamp=timestamp,
        )
        self.fills.append(fill)
        return fill

    def equity(self, prices: Mapping[str, float]) -> float:
        """Cash plus the marked-to-market value of every open position."""
        held = self.positions.values()
        return self.cash + sum(p.market_value(prices[p.symbol]) for p in held if p.quantity)

    def total_return(self, prices: Mapping[str, float]) -> float:
        """Return since inception as a fraction of the starting cash."""
        if self.initial_cash == 0:
            return 0.0
        return self.equity(prices) / self.initial_cash - 1.0
