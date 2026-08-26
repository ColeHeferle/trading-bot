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

    The 50/200 default is the slowest sensible pairing rather than a tuned one.
    Faster pairings trade far more often, and on twenty years of S&P 500 and
    Nasdaq daily bars the fee drag cost more than the extra signals were worth;
    see `docs/strategy-study.md`.
    """

    def __init__(self, fast_period: int = 50, slow_period: int = 200) -> None:
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


class BuyAndHold(Strategy):
    """Buy on the first candle and never sell.

    Kept in the library on purpose: it is the benchmark any other strategy has
    to beat, and it is easy to talk yourself out of checking. A rule that
    trades less than this one and still trails it is not earning its risk.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._entered = False

    def on_candle(self, candle: Candle) -> Signal:
        if self._entered:
            return Signal.HOLD
        self._entered = True
        return Signal.BUY


class _TrendFollowing(Strategy):
    """Shared plumbing: emit a signal only when the long/flat target flips."""

    def reset(self) -> None:
        self._long: bool | None = None

    def _target(self, candle: Candle) -> bool | None:
        """Return whether to be long, or None while still warming up."""
        raise NotImplementedError

    def on_candle(self, candle: Candle) -> Signal:
        want = self._target(candle)
        if want is None:
            return Signal.HOLD
        was, self._long = self._long, want
        if was is None or was == want:
            return Signal.HOLD
        return Signal.BUY if want else Signal.SELL


class PriceVsSma(_TrendFollowing):
    """Long while price sits above its own moving average, flat below it.

    One average instead of two, so it reacts a step sooner than a crossover at
    the cost of trading more often in a choppy market.
    """

    def __init__(self, period: int = 200) -> None:
        if period <= 0:
            raise ValueError(f"period must be positive, got {period}")
        self.period = period
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._window: deque[float] = deque(maxlen=self.period)
        self._total = 0.0

    def _target(self, candle: Candle) -> bool | None:
        if len(self._window) == self.period:
            self._total -= self._window[0]
        self._window.append(candle.close)
        self._total += candle.close
        if len(self._window) < self.period:
            return None
        return candle.close > self._total / self.period


class TimeSeriesMomentum(_TrendFollowing):
    """Long while price is above where it stood `lookback` candles ago.

    No averaging at all — it compares two prices. That makes it slower to flip
    than either moving-average rule and gives it the steadiest exposure of the
    three over the study window.
    """

    def __init__(self, lookback: int = 252) -> None:
        if lookback <= 0:
            raise ValueError(f"lookback must be positive, got {lookback}")
        self.lookback = lookback
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._history: deque[float] = deque(maxlen=self.lookback + 1)

    def _target(self, candle: Candle) -> bool | None:
        self._history.append(candle.close)
        if len(self._history) <= self.lookback:
            return None
        return candle.close > self._history[0]
