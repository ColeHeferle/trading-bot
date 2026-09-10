"""Act on the frozen rule's current decision. Dry run unless told otherwise.

    python research/trade.py --symbol QQQ                # report only
    python research/trade.py --symbol QQQ --execute      # actually place it

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

Every run is also read by a proofreader (`research/review.py`) that prints what
Claude makes of the planned order. It is advisory in one direction only: it can
raise an objection, it can never clear one, and nothing it says changes the
exit code or whether an order is sent. Pass `--no-review` to skip it.
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

# research/ is a directory of scripts rather than a package, so make the
# sibling importable however this file is invoked. `review` pulls in nothing
# heavier than the standard library until it is actually asked to run.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import review  # noqa: E402


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
    parser.add_argument("--state", type=Path, default=Path("paper/qqq_sma_10_50_vol25.json"))
    parser.add_argument("--live", type=Path, default=Path("paper/live_position.json"))
    parser.add_argument("--execute", action="store_true", help="place the order")
    parser.add_argument("--max-bar-age-days", type=int, default=4)
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="skip the Claude proofreader (it never blocks either way)",
    )
    parser.add_argument("--review-model", default=review.MODEL)
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
    # The run's own target weight, not `quantity > 0`. A rule frozen with a
    # volatility target asks for a different fraction of equity every day, and
    # reading it as a boolean would silently trade the full size instead.
    target_weight = run.target_weight
    broker = AlpacaBroker(key, secret)

    sizing = run.rule.sizer or "fully invested"
    print(f"rule          {run.rule.strategy}{run.rule.params} [{run.rule.fingerprint}]")
    print(f"sizing        {sizing}")
    print(f"decision      {'LONG' if target_weight > 0 else 'FLAT'} at weight "
          f"{target_weight:.2f} as of {latest.timestamp.date()}")
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
            target_weight,
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

    if intent.is_action:
        # Printed every day, because this ceiling now actually binds. It spent
        # a while unable to fire — `submit` passed no price, so there was
        # nothing to multiply — and a limit that starts working is a limit that
        # can refuse an order you were expecting to go through. Seeing the
        # headroom on a dry run beats discovering it on execute day.
        notional = intent.quantity * intent.price
        ceiling = broker.limits.max_order_notional
        over = " — OVER, submit would refuse this" if notional > ceiling else ""
        print(
            f"notional      {notional:,.2f} of {ceiling:,.2f} ceiling{over}"
        )

    if not args.no_review:
        # Two extra reads for the dossier. `plan` fetched these internally and
        # does not hand them back; re-reading them is cheaper than widening its
        # return type for a feature that must never influence it.
        #
        # This runs on no-action days too. Exercising the whole path daily is
        # what catches bugs — the same reason the trade loop itself runs in dry
        # run every day rather than only when there is something to send.
        try:
            review.proofread(
                run,
                intent,
                args.symbol,
                broker.account().equity,
                broker.position(args.symbol).quantity,
                expected,
                datetime.now(),
                model=args.review_model,
            )
        except BrokerError as exc:
            print(f"\nproofreader: not run — broker read failed ({exc})")

    if not intent.is_action:
        return 0

    if not args.execute:
        print("\nDRY RUN — nothing was sent. Pass --execute to place this order.")
        return 0

    order_id = client_order_id(
        run.rule.fingerprint, latest.timestamp, args.symbol, intent.side
    )
    try:
        placed = broker.submit(
            args.symbol, intent.side, intent.quantity, order_id, intent.price
        )
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
