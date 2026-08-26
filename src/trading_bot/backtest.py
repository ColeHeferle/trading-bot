"""A single-symbol, long-only backtest loop.

Signals are acted on at the close of the candle that produced them, which is
the earliest price a live bot could realistically have traded at.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .models import Candle, Fill, Order, Side, Signal
from .portfolio import Portfolio
from .strategy import Strategy


@dataclass
class BacktestResult:
    symbol: str
    portfolio: Portfolio
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)

    @property
    def fills(self) -> list[Fill]:
        return self.portfolio.fills

    @property
    def final_equity(self) -> float:
        if not self.equity_curve:
            return self.portfolio.initial_cash
        return self.equity_curve[-1][1]

    @property
    def total_return(self) -> float:
        initial = self.portfolio.initial_cash
        return self.final_equity / initial - 1.0 if initial else 0.0

    @property
    def max_drawdown(self) -> float:
        """Largest peak-to-trough drop in equity, as a positive fraction."""
        peak = float("-inf")
        worst = 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, 1.0 - equity / peak)
        return worst


def run_backtest(
    candles: Iterable[Candle],
    strategy: Strategy,
    symbol: str = "ASSET",
    portfolio: Portfolio | None = None,
    quantity: float | None = None,
) -> BacktestResult:
    """Replay ``candles`` through ``strategy``, trading a single long position.

    ``quantity`` fixes the size of every trade; left as ``None``, each buy uses
    the whole cash balance and each sell closes the position.
    """
    portfolio = portfolio if portfolio is not None else Portfolio()
    result = BacktestResult(symbol=symbol, portfolio=portfolio)

    for candle in candles:
        signal = strategy.on_candle(candle)
        held = portfolio.quantity(symbol)

        if signal is Signal.BUY and held == 0:
            size = quantity if quantity is not None else _affordable(portfolio, candle.close)
            if size > 0:
                portfolio.execute(
                    Order(symbol, Side.BUY, size), candle.close, candle.timestamp
                )
        elif signal is Signal.SELL and held > 0:
            size = min(quantity, held) if quantity is not None else held
            if size > 0:
                portfolio.execute(
                    Order(symbol, Side.SELL, size), candle.close, candle.timestamp
                )

        result.equity_curve.append(
            (candle.timestamp, portfolio.equity({symbol: candle.close}))
        )

    return result


def _affordable(portfolio: Portfolio, price: float) -> float:
    """Largest quantity buyable with the cash on hand, fees included.

    Shaved by a hair so float rounding cannot push the order past the balance.
    """
    gross = price * (1.0 + portfolio.fee_rate)
    if gross <= 0:
        return 0.0
    return portfolio.cash / gross * (1.0 - 1e-12)
