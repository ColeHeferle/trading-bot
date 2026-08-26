"""Rolling indicators.

Each function returns a list the same length as its input so results stay
aligned with the candle series; leading entries are ``None`` until enough
history has accumulated.
"""

from __future__ import annotations

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """Simple moving average over a trailing window of ``period`` values."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")

    out: list[float | None] = []
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Exponential moving average, seeded with the first ``period``-value SMA."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")

    multiplier = 2.0 / (period + 1)
    out: list[float | None] = []
    prev: float | None = None
    for i, value in enumerate(values):
        if i < period - 1:
            out.append(None)
        elif prev is None:
            prev = sum(values[: i + 1]) / period
            out.append(prev)
        else:
            prev = (value - prev) * multiplier + prev
            out.append(prev)
    return out


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder's relative strength index."""
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")

    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out

    gains = losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_from_averages(avg_gain, avg_loss)
    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
