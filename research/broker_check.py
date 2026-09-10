"""Read-only smoke test against the Alpaca paper sandbox. Places no orders.

    export APCA_API_KEY_ID=...  APCA_API_SECRET_KEY=...
    python research/broker_check.py

Run this before anything is allowed to trade. It proves the credentials work,
the endpoint answers, and the response shapes match what the adapter expects —
which matters because those shapes were written from knowledge of Alpaca's v2
API, not verified against the live service.

It also reconciles the paper run's intended position against what the broker
actually holds. Divergence there is the failure that quietly costs money, so it
is worth seeing before an order is ever sent, not after.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from trading_bot import AlpacaBroker, BrokerError, PaperRun, reconcile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("paper/qqq_sma_10_50_vol25.json"))
    parser.add_argument(
        "--symbol",
        default="QQQ",
        help="what the broker actually trades; the rule is frozen on an index",
    )
    args = parser.parse_args(argv)

    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        print(
            "set APCA_API_KEY_ID and APCA_API_SECRET_KEY (paper keys from "
            "alpaca.markets)",
            file=sys.stderr,
        )
        return 2

    broker = AlpacaBroker(key, secret)
    print(f"endpoint      {broker.base_url}  (paper={broker.is_paper})")

    try:
        account = broker.account()
        held = broker.positions()
    except BrokerError as exc:
        print(f"broker check failed: {exc}", file=sys.stderr)
        return 1

    print(f"cash          {account.cash:>14,.2f} {account.currency}")
    print(f"equity        {account.equity:>14,.2f}")
    print(f"buying power  {account.buying_power:>14,.2f}")
    print(f"positions     {len(held)}")
    for position in held:
        print(f"  {position.symbol:<8}{position.quantity:>12g} @ {position.avg_price:,.2f}")

    if not args.state.exists():
        print(f"\nno paper run at {args.state}; skipping reconciliation")
        return 0

    run = PaperRun.load(args.state)
    expected = run.journal[-1].quantity if run.journal else 0.0
    print(f"\nreconciling {args.state.name} against the broker")
    if run.rule.symbol != args.symbol:
        # The rule is frozen on QQQ, so this is normally silent. It fires if
        # someone points --symbol at something else, which is worth saying out
        # loud: the record would then describe an instrument nobody holds.
        print(
            f"  note: rule is frozen on {run.rule.symbol} but this compares "
            f"against {args.symbol}, a different instrument with its own "
            "price and dividend treatment"
        )

    rows = reconcile({args.symbol: expected}, broker)
    for row in rows:
        print(f"  {row.describe()}")

    drifted = [r for r in rows if not r.matches]
    if drifted:
        print(
            f"\n{len(drifted)} position(s) disagree. Nothing was changed — "
            "reconcile by hand before letting anything trade.",
            file=sys.stderr,
        )
        return 1
    print("\nall positions agree; no orders were placed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        raise SystemExit(0)
