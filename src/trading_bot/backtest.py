"""A single-symbol, long-only backtest loop.

Signals are acted on at the close of the candle that produced them, which is
the earliest price a live bot could realistically have traded at.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .models import Candle, Fill, Order, Side, Signal
from .portfolio import Portfolio
from .sizing import PositionSizer
from .strategy import Strategy


@dataclass
class BacktestResult:
    symbol: str
    portfolio: Portfolio
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    holdings: list[float] = field(default_factory=list)
    periods_per_year: int = 252

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

    @property
    def returns(self) -> list[float]:
        """Per-candle fractional change in equity."""
        curve = [equity for _, equity in self.equity_curve]
        return [
            curve[i] / curve[i - 1] - 1.0
            for i in range(1, len(curve))
            if curve[i - 1] > 0
        ]

    @property
    def cagr(self) -> float:
        """Compound annual growth rate, from the elapsed calendar time."""
        if len(self.equity_curve) < 2:
            return 0.0
        start, end = self.equity_curve[0], self.equity_curve[-1]
        years = (end[0] - start[0]).days / 365.25
        if years <= 0 or start[1] <= 0:
            return 0.0
        return (end[1] / start[1]) ** (1 / years) - 1.0

    @property
    def sharpe(self) -> float:
        """Annualized return over volatility, against a zero risk-free rate.

        Annualized with `periods_per_year`, which assumes every candle covers
        the same span — true for daily bars, wrong for an irregular series.
        """
        rets = self.returns
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        if variance <= 0:
            return 0.0
        return mean / math.sqrt(variance) * math.sqrt(self.periods_per_year)

    @property
    def exposure(self) -> float:
        """Fraction of candles spent holding a position."""
        if not self.holdings:
            return 0.0
        return sum(1 for quantity in self.holdings if quantity) / len(self.holdings)


def run_backtest(
    candles: Iterable[Candle],
    strategy: Strategy,
    symbol: str = "ASSET",
    portfolio: Portfolio | None = None,
    quantity: float | None = None,
    periods_per_year: int = 252,
    sizer: PositionSizer | None = None,
    rebalance_threshold: float = 0.2,
) -> BacktestResult:
    """Replay ``candles`` through ``strategy``, trading a single long position.

    ``quantity`` fixes the size of every trade; left as ``None``, each buy uses
    the whole cash balance and each sell closes the position.
    ``periods_per_year`` only annualizes the Sharpe ratio — 252 for daily bars,
    12 for monthly.

    Pass a ``sizer`` to hold a varying fraction of equity instead of going
    all-in: the strategy still decides whether to be long, and the sizer decides
    how much. The position is then rebalanced toward that weight whenever it has
    drifted by more than ``rebalance_threshold`` — without a band, a sizer that
    moves a little every day would trade every day and pay for the privilege.
    Anything from 0.05 to 0.3 scored the same on the study data while trading
    25x less often at the wide end, so the band is a turnover dial rather than a
    performance one. Exits are never banded; a strategy that says flat gets flat.
    """
    if sizer is not None and quantity is not None:
        raise ValueError("pass either quantity or sizer, not both")
    portfolio = portfolio if portfolio is not None else Portfolio()
    result = BacktestResult(
        symbol=symbol, portfolio=portfolio, periods_per_year=periods_per_year
    )

    wants_long = False

    for candle in candles:
        signal = strategy.on_candle(candle)
        if signal is Signal.BUY:
            wants_long = True
        elif signal is Signal.SELL:
            wants_long = False

        if sizer is None:
            _trade_all_or_nothing(portfolio, symbol, candle, signal, quantity)
        else:
            target = sizer.weight(candle) if wants_long else 0.0
            _rebalance(portfolio, symbol, candle, target, rebalance_threshold)

        result.equity_curve.append(
            (candle.timestamp, portfolio.equity({symbol: candle.close}))
        )
        result.holdings.append(portfolio.quantity(symbol))

    return result


def _trade_all_or_nothing(
    portfolio: Portfolio,
    symbol: str,
    candle: Candle,
    signal: Signal,
    quantity: float | None,
) -> None:
    """The original behaviour: in with everything, or out entirely."""
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


def _rebalance(
    portfolio: Portfolio,
    symbol: str,
    candle: Candle,
    target_weight: float,
    threshold: float,
) -> None:
    """Move the position toward ``target_weight`` of equity, within a band."""
    price = candle.close
    held = portfolio.quantity(symbol)
    equity = portfolio.equity({symbol: price})
    if equity <= 0 or price <= 0:
        return

    current_weight = held * price / equity
    leaving = target_weight <= 0 and held > 0
    if not leaving and abs(target_weight - current_weight) < threshold:
        return

    delta = target_weight * equity / price - held
    if delta > 0:
        size = min(delta, _affordable(portfolio, price))
        if size > 0:
            portfolio.execute(Order(symbol, Side.BUY, size), price, candle.timestamp)
    elif delta < 0:
        size = min(-delta, held)
        if size > 0:
            portfolio.execute(Order(symbol, Side.SELL, size), price, candle.timestamp)


def _affordable(portfolio: Portfolio, price: float) -> float:
    """Largest quantity buyable with the cash on hand, fees included.

    Shaved by a hair so float rounding cannot push the order past the balance.
    """
    gross = price * (1.0 + portfolio.fee_rate)
    if gross <= 0:
        return 0.0
    return portfolio.cash / gross * (1.0 - 1e-12)
