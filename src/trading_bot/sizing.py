"""How much to hold once a strategy has decided to be long.

A strategy answers *whether* to hold; a sizer answers *how much*. Keeping the
two apart means any sizer composes with any strategy.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque

from .models import Candle


class PositionSizer(ABC):
    """Turns a candle into the fraction of equity to hold while long."""

    @abstractmethod
    def weight(self, candle: Candle) -> float:
        """Target fraction of equity, where 1.0 is fully invested.

        Called on every candle, including ones spent flat, so the sizer's view
        of the market stays current while it is out of the position.
        """

    def reset(self) -> None:
        """Drop accumulated state so the instance can be reused."""


class FullInvestment(PositionSizer):
    """Hold the whole balance — what the backtest does with no sizer at all."""

    def weight(self, candle: Candle) -> float:
        return 1.0


class VolatilityTarget(PositionSizer):
    """Scale the position so its risk, not its size, stays constant.

    Position weight is ``target_volatility / realized_volatility``, so the
    strategy holds less of a market that is thrashing and more of a calm one.
    The point is not higher returns — it is that a fixed-size position quietly
    takes far more risk in a panic than it does in a drift.

    Realized volatility is the sample standard deviation of the last
    ``lookback`` candle returns, annualized by ``periods_per_year``. Returns
    a weight of 0 until that window fills: with no estimate there is no
    defensible size.

    ``max_leverage`` caps the weight. Above 1.0 it is aspirational — the paper
    account cannot borrow, so a buy is still capped by available cash.
    """

    def __init__(
        self,
        target_volatility: float = 0.15,
        lookback: int = 20,
        max_leverage: float = 1.0,
        periods_per_year: int = 252,
    ) -> None:
        if target_volatility <= 0:
            raise ValueError(
                f"target_volatility must be positive, got {target_volatility}"
            )
        if lookback < 2:
            raise ValueError(f"lookback must be at least 2, got {lookback}")
        if max_leverage <= 0:
            raise ValueError(f"max_leverage must be positive, got {max_leverage}")
        if periods_per_year <= 0:
            raise ValueError(
                f"periods_per_year must be positive, got {periods_per_year}"
            )
        self.target_volatility = target_volatility
        self.lookback = lookback
        self.max_leverage = max_leverage
        self.periods_per_year = periods_per_year
        self.reset()

    def reset(self) -> None:
        self._returns: deque[float] = deque(maxlen=self.lookback)
        self._previous_close: float | None = None

    @property
    def realized_volatility(self) -> float | None:
        """Annualized volatility of the trailing window, or None while warming up."""
        if len(self._returns) < self.lookback:
            return None
        mean = sum(self._returns) / len(self._returns)
        variance = sum((r - mean) ** 2 for r in self._returns) / (len(self._returns) - 1)
        return math.sqrt(variance) * math.sqrt(self.periods_per_year)

    def weight(self, candle: Candle) -> float:
        previous, self._previous_close = self._previous_close, candle.close
        if previous is not None and previous > 0:
            self._returns.append(candle.close / previous - 1.0)

        realized = self.realized_volatility
        if realized is None:
            return 0.0
        if realized <= 0:
            # A market that has not moved at all carries no measurable risk.
            return self.max_leverage
        return min(self.target_volatility / realized, self.max_leverage)
