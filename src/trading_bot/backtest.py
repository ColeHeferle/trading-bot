"""Long-only backtest loops, for one symbol or a whole basket.

Signals are acted on at the close of the candle that produced them, which is
the earliest price a live bot could realistically have traded at.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .models import Candle, Fill, Order, Side, Signal
from .portfolio import Portfolio
from .sizing import PositionSizer
from .strategy import Strategy


class EquityMetrics:
    """Performance measures derived from an equity curve.

    Shared by the single-symbol and multi-asset results so both report the
    same numbers computed the same way.
    """

    equity_curve: list[tuple[datetime, float]]
    portfolio: Portfolio
    periods_per_year: int

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


@dataclass
class BacktestResult(EquityMetrics):
    """The outcome of a single-symbol backtest."""

    symbol: str
    portfolio: Portfolio
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    holdings: list[float] = field(default_factory=list)
    periods_per_year: int = 252

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
            _rebalance(
                portfolio,
                symbol,
                candle.close,
                candle.timestamp,
                target,
                rebalance_threshold,
                portfolio.equity({symbol: candle.close}),
            )

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
    price: float,
    timestamp: datetime,
    target_weight: float,
    threshold: float,
    equity: float,
    scale: float = 1.0,
) -> None:
    """Move one position toward ``target_weight`` of ``equity``, within a band.

    ``equity`` is passed in rather than read from the portfolio so a basket can
    size every leg against the same snapshot; otherwise each trade would shift
    the denominator for the legs behind it.

    The band is ``threshold * scale``, where ``scale`` is the share of equity
    this symbol is allowed at all. It has to be relative: a flat 0.2 band
    against a ten-symbol basket, where each leg targets 0.1, would reject every
    entry and the whole basket would sit in cash forever.
    """
    held = portfolio.quantity(symbol)
    if equity <= 0 or price <= 0:
        return

    current_weight = held * price / equity
    leaving = target_weight <= 0 and held > 0
    if not leaving and abs(target_weight - current_weight) < threshold * scale:
        return

    delta = target_weight * equity / price - held
    if delta > 0:
        size = min(delta, _affordable(portfolio, price))
        if _worth_trading(size, price, equity):
            portfolio.execute(Order(symbol, Side.BUY, size), price, timestamp)
    elif delta < 0:
        size = min(-delta, held)
        if _worth_trading(size, price, equity):
            portfolio.execute(Order(symbol, Side.SELL, size), price, timestamp)


def _worth_trading(size: float, price: float, equity: float) -> bool:
    """Ignore dust.

    Once a basket is fully invested its cash sits at effectively zero, and the
    arithmetic there produces vanishingly small residual orders — small enough
    that the safety shave in `_affordable` rounds away and the order overdraws
    by a fraction of a cent. Nothing that small is worth a fill anyway.
    """
    return size > 0 and size * price > equity * 1e-9


def _affordable(portfolio: Portfolio, price: float) -> float:
    """Largest quantity buyable with the cash on hand, fees included.

    Shaved by a hair so float rounding cannot push the order past the balance.
    """
    gross = price * (1.0 + portfolio.fee_rate)
    if gross <= 0 or portfolio.cash <= 0:
        return 0.0
    return portfolio.cash / gross * (1.0 - 1e-12)


@dataclass
class MultiBacktestResult(EquityMetrics):
    """The outcome of a basket backtest."""

    symbols: list[str]
    portfolio: Portfolio
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    invested: list[float] = field(default_factory=list)
    periods_per_year: int = 252

    @property
    def exposure(self) -> float:
        """Average share of equity actually deployed, across the run.

        For a basket this is the fraction of capital at work rather than the
        fraction of bars spent holding — with several symbols the account is
        nearly always holding *something*, which would make that useless.
        """
        if not self.invested:
            return 0.0
        return sum(self.invested) / len(self.invested)

    def fills_for(self, symbol: str) -> list[Fill]:
        return [fill for fill in self.portfolio.fills if fill.symbol == symbol]


def run_multi_backtest(
    data: Mapping[str, Sequence[Candle]],
    strategy_factory: Callable[[], Strategy],
    portfolio: Portfolio | None = None,
    sizer_factory: Callable[[], PositionSizer] | None = None,
    weights: Mapping[str, float] | None = None,
    rebalance_threshold: float = 0.2,
    periods_per_year: int = 252,
) -> MultiBacktestResult:
    """Run one strategy per symbol over a shared cash balance.

    ``strategy_factory`` is called once per symbol, since strategies are
    stateful and must not be shared. ``sizer_factory`` likewise, when given.

    ``rebalance_threshold`` is scaled by each symbol's weight, so the band
    stays proportional to the position it guards however wide the universe gets.

    ``weights`` caps the share of equity each symbol may take, defaulting to an
    equal split. They must not sum past 1.0: the account cannot borrow, so an
    over-allocated basket would simply starve whichever legs traded last. A
    symbol that is flat leaves its share in cash rather than lending it to the
    others, which keeps each leg's risk budget fixed.

    Symbols may cover different date ranges. The loop walks the union of all
    timestamps, only trades a symbol on bars it actually has, and marks
    everything else at its last known close. Within a bar, sells run before
    buys so freed cash is available to the buyers.
    """
    symbols = sorted(data)
    if not symbols:
        raise ValueError("data must contain at least one symbol")

    weights = _resolve_weights(symbols, weights)
    portfolio = portfolio if portfolio is not None else Portfolio()
    result = MultiBacktestResult(
        symbols=symbols, portfolio=portfolio, periods_per_year=periods_per_year
    )

    by_time = {
        symbol: {candle.timestamp: candle for candle in data[symbol]}
        for symbol in symbols
    }
    timeline = sorted({stamp for stamps in by_time.values() for stamp in stamps})

    strategies = {symbol: strategy_factory() for symbol in symbols}
    sizers = (
        {symbol: sizer_factory() for symbol in symbols} if sizer_factory else None
    )
    wants_long = dict.fromkeys(symbols, False)
    last_price: dict[str, float] = {}

    for stamp in timeline:
        targets: dict[str, tuple[float, float]] = {}

        for symbol in symbols:
            candle = by_time[symbol].get(stamp)
            if candle is None:
                continue
            last_price[symbol] = candle.close

            signal = strategies[symbol].on_candle(candle)
            if signal is Signal.BUY:
                wants_long[symbol] = True
            elif signal is Signal.SELL:
                wants_long[symbol] = False

            share = weights[symbol]
            if sizers is not None:
                share *= sizers[symbol].weight(candle)
            targets[symbol] = (candle.close, share if wants_long[symbol] else 0.0)

        equity = portfolio.equity(last_price)

        # Ascending trade value puts the sells first, so a buy funded by a
        # sale in the same bar finds the cash already there.
        ordered = sorted(
            targets.items(),
            key=lambda item: item[1][1] * equity
            - portfolio.quantity(item[0]) * item[1][0],
        )
        for symbol, (price, target) in ordered:
            _rebalance(
                portfolio,
                symbol,
                price,
                stamp,
                target,
                rebalance_threshold,
                equity,
                scale=weights[symbol],
            )

        marked = portfolio.equity(last_price)
        result.equity_curve.append((stamp, marked))
        result.invested.append(
            1.0 - portfolio.cash / marked if marked > 0 else 0.0
        )

    return result


def _resolve_weights(
    symbols: Sequence[str], weights: Mapping[str, float] | None
) -> dict[str, float]:
    if weights is None:
        return {symbol: 1.0 / len(symbols) for symbol in symbols}

    missing = set(symbols) - set(weights)
    if missing:
        raise ValueError(f"weights missing for {sorted(missing)}")
    unknown = set(weights) - set(symbols)
    if unknown:
        raise ValueError(f"weights given for unknown symbols {sorted(unknown)}")
    if any(weight <= 0 for weight in weights.values()):
        raise ValueError("weights must be positive")

    total = sum(weights.values())
    if total > 1.0 + 1e-9:
        raise ValueError(
            f"weights sum to {total:.4f}; the account cannot borrow, so a "
            "basket allocating more than 1.0 would starve its last legs"
        )
    return dict(weights)
