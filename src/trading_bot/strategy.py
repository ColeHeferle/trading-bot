"""Strategies turn a stream of candles into trading signals.

A strategy is stateful and sees each candle exactly once, in order, so it can
never read a price it would not have had at decision time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from .models import Candle, Signal


class Strategy(ABC):
    """Base class for candle-driven strategies."""

    @abstractmethod
    def on_candle(self, candle: Candle) -> Signal:
        """Consume the next candle and return the signal it produces."""

    def reset(self) -> None:
        """Drop accumulated state so the instance can be reused."""


class SmaCrossover(Strategy):
    """Long when the fast average crosses above the slow one, flat when below.

    Signals fire on the crossing itself, not on the state that follows it, so a
    sustained trend produces one BUY rather than one per candle.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("periods must be positive")
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be less than "
                f"slow_period ({slow_period})"
            )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.reset()

    def reset(self) -> None:
        self._closes: deque[float] = deque(maxlen=self.slow_period)
        self._fast_sum = 0.0
        self._slow_sum = 0.0
        self._was_above: bool | None = None

    def on_candle(self, candle: Candle) -> Signal:
        if len(self._closes) == self.slow_period:
            self._slow_sum -= self._closes[0]
        if len(self._closes) >= self.fast_period:
            self._fast_sum -= self._closes[-self.fast_period]

        self._closes.append(candle.close)
        self._fast_sum += candle.close
        self._slow_sum += candle.close

        if len(self._closes) < self.slow_period:
            return Signal.HOLD

        fast = self._fast_sum / self.fast_period
        slow = self._slow_sum / self.slow_period
        is_above = fast > slow

        was_above, self._was_above = self._was_above, is_above
        if was_above is None or was_above == is_above:
            return Signal.HOLD
        return Signal.BUY if is_above else Signal.SELL
