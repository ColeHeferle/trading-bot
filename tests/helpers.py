from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from trading_bot.models import Candle


def make_candles(closes: Sequence[float], start: datetime | None = None) -> list[Candle]:
    """Build a daily candle series from a list of closing prices."""
    start = start or datetime(2024, 1, 1)
    return [
        Candle(
            timestamp=start + timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
        )
        for i, close in enumerate(closes)
    ]
