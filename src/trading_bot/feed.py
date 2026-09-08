"""Reading, writing and merging bar CSVs.

A forward test is only as trustworthy as the bars that fed it, so the rules
here are deliberately strict:

- a bar that fails a sanity check raises rather than being quietly dropped,
- a bar that contradicts one already stored is reported as a *revision* and the
  stored value is kept, never silently overwritten.

That second rule is the point of the module. Vendors restate history — a
dividend adjustment, a late correction, a different close for the same day —
and a forward test whose past silently changes is not a record of anything.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .models import Candle

FIELDS = ("date", "open", "high", "low", "close", "volume")


class BadBar(ValueError):
    """A row that cannot be trusted as a price bar."""


def _number(row: dict[str, str], key: str, fallback: float | None = None) -> float:
    raw = (row.get(key) or "").strip()
    if not raw:
        if fallback is None:
            raise BadBar(f"missing {key!r} and no close to fall back on: {row}")
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise BadBar(f"{key}={raw!r} is not a number: {row}") from exc


def validate(candle: Candle) -> Candle:
    """Reject bars that cannot be real, loudly.

    A silently dropped bad bar is worse than a crash: the run keeps going and
    the record quietly disagrees with the market.
    """
    prices = (candle.open, candle.high, candle.low, candle.close)
    if any(p <= 0 for p in prices):
        raise BadBar(f"non-positive price on {candle.timestamp.date()}: {prices}")
    if candle.high < candle.low:
        raise BadBar(
            f"high {candle.high} below low {candle.low} on {candle.timestamp.date()}"
        )
    if candle.high < max(candle.open, candle.close):
        raise BadBar(f"high below open/close on {candle.timestamp.date()}")
    if candle.low > min(candle.open, candle.close):
        raise BadBar(f"low above open/close on {candle.timestamp.date()}")
    if candle.volume < 0:
        raise BadBar(f"negative volume on {candle.timestamp.date()}")
    return candle


def parse_csv(text: str) -> list[Candle]:
    """Parse a bar CSV, oldest first.

    Headers are matched case-insensitively, so a vendor file with `Date,Close`
    needs no hand-editing. Only date and close are required; the rest fall back
    to the close, which is what an index series without OHLC looks like.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    bars = []
    for raw in reader:
        row = {
            (k or "").strip().lower(): v
            for k, v in raw.items()
            if k is not None
        }
        stamp = (row.get("date") or "").strip()
        if not stamp:
            continue  # blank trailing line
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError as exc:
            raise BadBar(f"{stamp!r} is not an ISO date") from exc

        close = _number(row, "close")
        bars.append(
            validate(
                Candle(
                    when,
                    _number(row, "open", close),
                    _number(row, "high", close),
                    _number(row, "low", close),
                    close,
                    _number(row, "volume", 0.0),
                )
            )
        )
    return sorted(bars, key=lambda c: c.timestamp)


def format_csv(bars: Iterable[Candle]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(FIELDS)
    for c in sorted(bars, key=lambda c: c.timestamp):
        writer.writerow(
            [c.timestamp.date().isoformat(), c.open, c.high, c.low, c.close, c.volume]
        )
    return out.getvalue()


@dataclass
class MergeResult:
    bars: list[Candle] = field(default_factory=list)
    added: list[Candle] = field(default_factory=list)
    revised: list[tuple[Candle, Candle]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added)


def merge(existing: Sequence[Candle], incoming: Sequence[Candle]) -> MergeResult:
    """Fold `incoming` into `existing`, keeping what was already recorded.

    New dates are added. A date already present is left exactly as stored; if
    the incoming values differ it is reported in `revised` for a human to look
    at. Deciding a vendor's restatement is correct is not something this should
    do on its own at 10pm on a cron schedule.
    """
    stored = {c.timestamp: c for c in existing}
    result = MergeResult(bars=list(existing))

    for candle in sorted(incoming, key=lambda c: c.timestamp):
        previous = stored.get(candle.timestamp)
        if previous is None:
            stored[candle.timestamp] = candle
            result.bars.append(candle)
            result.added.append(candle)
        elif not _same(previous, candle):
            result.revised.append((previous, candle))

    result.bars.sort(key=lambda c: c.timestamp)
    result.added.sort(key=lambda c: c.timestamp)
    return result


def _same(a: Candle, b: Candle) -> bool:
    return (
        a.open == b.open
        and a.high == b.high
        and a.low == b.low
        and a.close == b.close
        and a.volume == b.volume
    )


def parse_stooq(text: str) -> list[Candle]:
    """Parse Stooq's daily CSV, which is `Date,Open,High,Low,Close,Volume`.

    Stooq answers an unknown symbol with a plain-text apology rather than an
    HTTP error, so an unparseable body is far more likely to be that than a
    real format change.
    """
    head = text.strip().splitlines()[:1]
    if not head or "date" not in head[0].lower():
        raise BadBar(
            f"response does not look like Stooq CSV (starts {text[:60]!r}); "
            "an unknown symbol returns a message with a 200 status"
        )
    return parse_csv(text)
