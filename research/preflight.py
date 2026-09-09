"""Say what the bot will do on its first live bar, before it does it.

    python research/preflight.py paper/spy_sma_50_200.json paper/spy_bars.csv

Reads only. Places no orders, contacts no broker, and does not modify the run.

The question it answers is the one that is otherwise unanswerable until a month
of flatness has already gone by: given this backfill, does the rule open long
or flat, and is that a decision it made or an accident of where the history
starts?

Those two flats look identical in every other output. `SmaCrossover` signals on
the crossing, not on the state after it, and the first bar where both averages
exist returns HOLD whatever their order. So a window that sits entirely above
the 200-day average contains no transition, and the rule holds nothing through
a rally it can see perfectly well. Backfilling further — far enough to catch the
cross that began the trend — flips it long. Same rule, same day, opposite
position, decided by nothing but how much history you handed it.

Exit 0 means ready to launch. Exit 1 means something needs fixing first, and
says what.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from trading_bot import BadBar, Candle, PaperRun, Signal, parse_csv


def replay(rule, bars: list[Candle]) -> list[tuple[int, Candle, Signal]]:
    """Every non-HOLD signal the rule produces over `bars`, with its index."""
    strategy = rule.build()
    out = []
    for i, candle in enumerate(bars):
        signal = strategy.on_candle(candle)
        if signal is not Signal.HOLD:
            out.append((i, candle, signal))
    return out


def averages(rule, bars: list[Candle]) -> tuple[float, float] | None:
    """The rule's two averages over the final window, if it has enough bars."""
    slow = rule.params.get("slow_period")
    fast = rule.params.get("fast_period")
    if slow is None or fast is None or len(bars) < slow:
        return None
    closes = [c.close for c in bars]
    return sum(closes[-fast:]) / fast, sum(closes[-slow:]) / slow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("bars", type=Path)
    parser.add_argument(
        "--accept-flat-start",
        action="store_true",
        help="launch flat even though no crossing was witnessed",
    )
    parser.add_argument("--max-bar-age-days", type=int, default=4)
    args = parser.parse_args(argv)

    try:
        run = PaperRun.load(args.state)
        rule = run.rule
        stored = list(run.bars)
        seen = stored[-1].timestamp if stored else None
        fresh = [c for c in parse_csv(args.bars.read_text())
                 if seen is None or c.timestamp > seen]
    except FileNotFoundError as exc:
        print(f"cannot read {exc.filename}", file=sys.stderr)
        return 2
    except (BadBar, ValueError) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 2
    bars = stored + fresh

    print(f"rule          {rule.strategy}{rule.params} [{rule.fingerprint}]")
    print(f"instrument    {rule.symbol}  — these bars must be {rule.symbol}, "
          "not an index that tracks it")
    print(f"bars          {len(bars)} ({len(stored)} already recorded, "
          f"{len(fresh)} new)")
    if not bars:
        print("\nnot ready: no bars at all.")
        return 1
    print(f"span          {bars[0].timestamp.date()} .. "
          f"{bars[-1].timestamp.date()}")

    problems: list[str] = []      # must be fixed
    waivable: list[str] = []      # your call, via --accept-flat-start

    # 1. Enough history for the slow average to exist at all.
    slow = rule.params.get("slow_period")
    if slow is not None and len(bars) < slow:
        problems.append(
            f"{rule.strategy} needs {slow} bars before it can signal and has "
            f"{len(bars)}. Backfill {slow - len(bars)} more."
        )

    # 2. The warmup boundary, and how the bars fall either side of it.
    boundary = rule.warmup_boundary
    if boundary is None:
        warmup, live = bars, []
        print("record opens  immediately — every bar counts as forward evidence")
    else:
        warmup = [c for c in bars if c.timestamp < boundary]
        live = [c for c in bars if c.timestamp >= boundary]
        print(f"record opens  {rule.warmup_until}  "
              f"({len(warmup)} warmup, {len(live)} live)")
        # Only worth saying when the total is sufficient; otherwise it is the
        # same shortfall reported twice.
        if slow is not None and len(bars) >= slow > len(warmup):
            problems.append(
                f"only {len(warmup)} bars land before the {rule.warmup_until} "
                f"boundary, and {slow} are needed to warm the averages. The "
                "rule would spend its first live bars unable to signal, and "
                "those bars would still count as forward record. Backfill "
                "further back, or move the boundary later."
            )

    # 3. Freshness. A stale file means the launch trades on an old price.
    age = (datetime.now() - bars[-1].timestamp).days
    described = (
        f"dated {-age} day{'s' if age != -1 else ''} in the FUTURE"
        if age < 0 else f"{age} day{'s' if age != 1 else ''} old"
    )
    print(f"last bar      {bars[-1].timestamp.date()}  "
          f"({described}, close {bars[-1].close:,.2f})")
    if age < 0:
        # Nothing legitimate produces a bar dated ahead of today. It is a
        # vendor error or a timezone bug, and either way the file is wrong.
        problems.append(
            f"the last bar is dated {bars[-1].timestamp.date()}, which is in "
            "the future. No feed legitimately produces that — check the source "
            "and the timezone handling before trusting any of these bars."
        )
    elif age > args.max_bar_age_days:
        problems.append(
            f"the last bar is {age} days old, over the {args.max_bar_age_days}"
            "-day limit. Fetch before launching; the live loop would refuse "
            "to trade on this."
        )

    # 4. The question this script exists for: what position, and why.
    events = replay(rule, warmup if boundary is not None else bars)
    opening = events[-1] if events else None
    print()
    where = "the warmup window" if boundary is not None else "these bars"
    carries = ("carries across the boundary" if boundary is not None
               else "is where it stands")
    if opening is not None and opening[2] is Signal.BUY:
        print(f"opens         LONG — {opening[2].name} on "
              f"{opening[1].timestamp.date()} {carries}")
    elif opening is not None:
        print(f"opens         FLAT — {opening[2].name} on "
              f"{opening[1].timestamp.date()} is the rule's last word")
    else:
        print("opens         FLAT — but no crossing was ever witnessed")

    print(f"crossings     {len(events)} in {where}")
    for _, candle, signal in events[-3:]:
        print(f"  {signal.name:<5} {candle.timestamp.date()} "
              f"at {candle.close:,.2f}")

    # The dangerous case: flat purely because the window contains no transition.
    if opening is None:
        pair = averages(rule, warmup if boundary is not None else bars)
        if pair is not None:
            fast_avg, slow_avg = pair
            above = fast_avg > slow_avg
            gap = (fast_avg / slow_avg - 1) * 100
            print(f"\naverages      fast {fast_avg:,.2f} vs slow {slow_avg:,.2f}"
                  f"  ({gap:+.2f}%)")
            if above:
                waivable.append(
                    "the fast average is ALREADY ABOVE the slow one, but the "
                    "rule never saw them cross, so it will hold nothing "
                    "through the trend it is looking at. This is an artifact "
                    "of where the backfill starts, not a decision. Backfill "
                    "further back to include the crossing that began this "
                    "trend, or pass --accept-flat-start to launch flat "
                    "deliberately and wait for the next one."
                )
            else:
                print("\nFlat is the honest reading here: the fast average is "
                      "below the slow one,\nso the rule would be flat whether "
                      "or not it saw the crossing.")

    for label, items in (("not ready", problems), ("your call", waivable)):
        if not items:
            continue
        stream = sys.stderr if items is problems else sys.stdout
        print(f"\n{label} ({len(items)}):", file=stream)
        for i, item in enumerate(items, 1):
            print(f"  {i}. {item}", file=stream)

    if problems:
        return 1
    if waivable:
        if not args.accept_flat_start:
            return 1
        print("\n--accept-flat-start given; launching flat is your call.")

    print("\nready to launch. Sizing happens against live broker equity and "
          "price,\nnot the closes above.")
    return 0


def _run(entry) -> int:
    try:
        return entry()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    raise SystemExit(_run(main))
