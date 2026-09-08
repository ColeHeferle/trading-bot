"""Act on the frozen rule's current decision. Dry run unless told otherwise.

    python research/trade.py --symbol SPY                # report only
    python research/trade.py --symbol SPY --execute      # actually place it

Default is a dry run. Wiring order placement into a schedule should not also
be the moment it starts placing orders, so the loop exercises the whole path —
credentials, freshness, reconciliation, sizing — and prints what it *would* do
until `--execute` is passed deliberately.

The rule is frozen on an index, which cannot be bought, so `--symbol` is
required rather than defaulted: choosing the instrument you actually trade is
a decision, not something to inherit.

`paper/live_position.json` records what was last intended in broker shares.
That is what reconciliation compares against — the paper run's own holdings are
in index units at index prices, a different instrument entirely.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from trading_bot import (
    AlpacaBroker,
    BrokerError,
    NotSafeToTrade,
    PaperRun,
    client_order_id,
    plan,
)


def load_expected(path: Path) -> float | None:
    if not path.exists():
        return None
    return float(json.loads(path.read_text())["expected_quantity"])


def save_expected(path: Path, symbol: str, quantity: float, order_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "symbol": symbol,
                "expected_quantity": quantity,
                "last_order_id": order_id,
                "updated": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Act on the frozen rule.")
    parser.add_argument("--symbol", required=True, help="the instrument to trade")
    parser.add_argument("--state", type=Path, default=Path("paper/spy_sma_50_200.json"))
    parser.add_argument("--live", type=Path, default=Path("paper/live_position.json"))
    parser.add_argument("--execute", action="store_true", help="place the order")
    parser.add_argument("--max-bar-age-days", type=int, default=4)
    args = parser.parse_args(argv)

    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        print("set APCA_API_KEY_ID and APCA_API_SECRET_KEY", file=sys.stderr)
        return 2

    run = PaperRun.load(args.state)
    if not run.journal:
        print("the paper run has no live bars yet; nothing to act on")
        return 0

    latest = run.journal[-1]
    want_long = latest.quantity > 0
    broker = AlpacaBroker(key, secret)

    print(f"rule          {run.rule.strategy}{run.rule.params} [{run.rule.fingerprint}]")
    print(f"decision      {'LONG' if want_long else 'FLAT'} as of {latest.timestamp.date()}")
    print(f"last close    {latest.close:,.2f} ({run.rule.symbol})")
    if args.symbol == run.rule.symbol:
        print(f"trading       {args.symbol}  (sized on its live price, not this close)")
    else:
        # The record would describe an instrument nobody holds.
        print(
            f"trading       {args.symbol}  (a DIFFERENT instrument to "
            f"{run.rule.symbol};\n                    sized on its own price, "
            "and the record will not match what is held)"
        )

    expected = load_expected(args.live)
    if expected is None:
        print("reconcile     skipped — no live position recorded yet")

    try:
        intent = plan(
            broker,
            args.symbol,
            want_long,
            latest.timestamp,
            datetime.now(),
            expected_quantity=expected,
            max_age_days=args.max_bar_age_days,
        )
    except NotSafeToTrade as exc:
        print(f"\nrefused: {exc}", file=sys.stderr)
        return 1
    except BrokerError as exc:
        print(f"\nbroker error: {exc}", file=sys.stderr)
        return 1

    print(f"\nplan          {intent.describe()}")

    if not intent.is_action:
        return 0

    if not args.execute:
        print("\nDRY RUN — nothing was sent. Pass --execute to place this order.")
        return 0

    order_id = client_order_id(
        run.rule.fingerprint, latest.timestamp, args.symbol, intent.side
    )
    try:
        placed = broker.submit(args.symbol, intent.side, intent.quantity, order_id)
    except BrokerError as exc:
        print(f"\norder failed: {exc}", file=sys.stderr)
        return 1

    print(f"submitted     {placed.status} id={placed.client_order_id}")
    if placed.is_filled:
        print(f"filled        {placed.filled_quantity:g} @ {placed.filled_price:,.2f}")

    # Record intent, not the fill: an order still working is a position we are
    # committed to, and the next run must reconcile against that.
    delta = intent.quantity if intent.side.value == "buy" else -intent.quantity
    save_expected(args.live, args.symbol, (expected or 0.0) + delta, order_id)
    print(f"recorded      expected {args.symbol} position in {args.live}")

    # A market order placed after the close fills at the next session's price,
    # not the close the rule decided on. That gap is real and unmodelled.
    print(
        "\nnote: the rule decided at a close; a market order fills at the next "
        "available price. That slippage is not in any backtest number."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0)
