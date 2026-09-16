"""Rolling indicators.

Each function returns a list the same length as its input so results stay
aligned with the candle series; leading entries are ``None`` until enough
history has accumulated.

EXERCISE: the bodies below are yours to write. See exercises/01-indicators.md.
"""

from __future__ import annotations

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """Simple moving average over a trailing window of ``period`` values."""
    raise NotImplementedError("sma: see exercises/01-indicators.md")


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Exponential moving average, seeded with the first ``period``-value SMA."""
    raise NotImplementedError("ema: see exercises/01-indicators.md")


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder's relative strength index."""
    raise NotImplementedError("rsi: see exercises/01-indicators.md")
