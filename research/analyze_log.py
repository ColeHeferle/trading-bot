"""Judge a real trade log the way the account will judge it.

    python research/analyze_log.py completed_trades.csv

Reads a Tradovate/TakeProfitTrader "completed trades" export and reports the
things that decide whether an account survives: the reward-to-risk ratio
against the one its win rate requires, the loss tail, and the drawdown each
account number actually ran.

It exists because a win rate is the statistic traders quote and the one that
settles least. Everything here is measured from realized P&L — nothing is
assumed, and nothing is taken on the trader's description of their own record.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trading_bot.prop import PRESETS  # noqa: E402


def load(path: Path) -> list[dict]:
    """Read the export, skipping the title line these files carry above the header."""
    lines = path.read_text().splitlines()
    if lines and "," not in lines[0]:
        lines = lines[1:]
    rows = []
    for row in csv.DictReader(lines):
        row["pnl"] = float(row["pnlDollars"])
        row["qty"] = int(row["maxQuantity"])
        rows.append(row)
    rows.sort(key=lambda r: r["entryDate"])
    return rows


def gate(rows: list[dict]) -> int:
    """Judge a log against the criteria for sizing up, and refuse on any failure.

    These exist as code rather than as a remembered intention because the
    decision they gate — trading larger — is the one a good run makes tempting
    and a bad run makes urgent. A threshold written down after the fact is not
    a threshold.

    Every bar is a floor, not a target, and all of them must clear. Passing
    means the edge is established well enough to size on; it does not mean the
    edge is large.
    """
    pnl = [r["pnl"] for r in rows]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    if not wins or not losses:
        print("GATE: FAIL — a log with no wins or no losses cannot be judged")
        return 1

    win_rate = len(wins) / len(rows)
    avg_win, avg_loss = statistics.mean(wins), abs(statistics.mean(losses))
    reward_risk = avg_win / avg_loss
    breakeven = 1 / (1 + reward_risk)
    margin = win_rate - breakeven
    standard_error = math.sqrt(win_rate * (1 - win_rate) / len(rows))
    t_stat = margin / standard_error if standard_error else 0.0

    tail = [l for l in losses if abs(l) >= 2 * avg_loss]
    tail_size = statistics.mean([abs(l) for l in tail]) / avg_loss if tail else 1.0

    after_win, after_loss = [], []
    for previous, current in zip(rows, rows[1:]):
        (after_loss if previous["pnl"] < 0 else after_win).append(current["qty"])
    escalation = (
        statistics.mean(after_loss) - statistics.mean(after_win)
        if after_win and after_loss else 0.0
    )

    by_day: dict[str, float] = defaultdict(float)
    for row in rows:
        by_day[row["entryDate"][:10]] += row["pnl"]
    losing_sessions = sum(1 for total in by_day.values() if total < 0)

    checks = [
        ("sample size", len(rows) >= 108, f"{len(rows)} trades", "need 108 for t=2"),
        ("edge established", t_stat >= 2.0, f"t = {t_stat:.2f}", "need t >= 2.00"),
        ("reward:risk", reward_risk > (1 - win_rate) / win_rate,
         f"{reward_risk:.3f}", f"need > {(1 - win_rate) / win_rate:.3f}"),
        ("loss tail", tail_size <= 2.78, f"{tail_size:.2f}x average",
         "need <= 2.78x, the level already achieved"),
        ("no size escalation", escalation <= 0.0, f"{escalation:+.2f} contracts after a loss",
         "need <= 0.00"),
        ("sessions", len(by_day) >= 20, f"{len(by_day)} sessions",
         "need 20 before a bootstrap means anything"),
        ("a losing session exists", losing_sessions >= 1, f"{losing_sessions} losing sessions",
         "an unbroken winning record cannot be falsified"),
    ]

    print(f"## Phase 1 gate — {len(rows)} trades over {len(by_day)} sessions\n")
    for name, ok, actual, requirement in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {name:<24}{actual:<32}{requirement}")
    failed = [name for name, ok, *_ in checks if not ok]
    if failed:
        print(f"\n  GATE CLOSED — {len(failed)} of {len(checks)} criteria unmet: "
              f"{', '.join(failed)}.\n  Do not increase position size.")
        return 1
    print("\n  GATE OPEN — every criterion met. Sizing up is defensible on this evidence.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--account", default="TPT100", choices=sorted(PRESETS))
    parser.add_argument("--only-account", help="restrict to one tradeAccount id")
    parser.add_argument("--gate", action="store_true",
                        help="judge the log against the Phase 1 criteria and exit non-zero on failure")
    args = parser.parse_args()

    rows = load(args.csv_path)
    if args.only_account:
        rows = [r for r in rows if r["tradeAccount"] == args.only_account]
    if not rows:
        print("no trades found")
        return 1
    if args.gate:
        return gate(rows)
    limit = PRESETS[args.account].max_loss_limit

    pnl = [r["pnl"] for r in rows]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    win_rate = len(wins) / len(rows)
    avg_win, avg_loss = statistics.mean(wins), abs(statistics.mean(losses))
    required = (1 - win_rate) / win_rate

    days = sorted({r["entryDate"][:10] for r in rows})
    print(f"## {len(rows)} trades over {len(days)} sessions, {days[0]} to {days[-1]}\n")
    print(f"  win rate        {win_rate:.1%}  ({len(wins)}W / {len(losses)}L)")
    print(f"  net P&L         ${sum(pnl):,.2f}")
    print(f"  expectancy      ${sum(pnl) / len(rows):,.2f} per trade")
    print(f"  avg win         ${avg_win:,.2f}")
    print(f"  avg loss        ${avg_loss:,.2f}")
    print(f"  reward:risk     {avg_win / avg_loss:.3f}   needs > {required:.3f} at this win rate"
          f"   {'PASS' if avg_win / avg_loss > required else 'FAIL'}")

    print("\n## The loss tail\n")
    print(f"  median loss     ${abs(statistics.median(losses)):,.2f}")
    print(f"  largest loss    ${abs(min(losses)):,.2f}  "
          f"({abs(min(losses)) / avg_loss:.1f}x the average)")
    big = [l for l in losses if abs(l) >= limit / 3]
    if big:
        print(f"  losses >= ${limit / 3:,.0f} (a third of the drawdown): {len(big)}")
        print(f"  they cost ${abs(sum(big)):,.2f}, which is "
              f"{abs(sum(big)) / sum(wins):.0%} of every winning trade combined")

    print("\n## Per account number\n")
    accounts: OrderedDict[str, list[dict]] = OrderedDict()
    for row in rows:
        accounts.setdefault(row["tradeAccount"], []).append(row)
    print(f"  {'account':<24}{'first':>12}{'last':>12}{'trades':>8}{'net':>12}{'peak DD':>11}")
    for name, trades in accounts.items():
        balance = peak = 0.0
        worst = 0.0
        for trade in trades:
            balance += trade["pnl"]
            peak = max(peak, balance)
            worst = min(worst, balance - peak)
        flag = "  BREACHED" if abs(worst) > limit else ""
        print(f"  {name:<24}{trades[0]['entryDate'][:10]:>12}{trades[-1]['entryDate'][:10]:>12}"
              f"{len(trades):>8}{sum(t['pnl'] for t in trades):>12,.2f}{worst:>11,.2f}{flag}")
    if len(accounts) > 1:
        print(f"\n  {len(accounts)} account numbers across {len(days)} sessions. An account number"
              "\n  changes when the previous one ended. Read the breaches above as the reason.")

    print("\n## Consistency: no session may be half of total profit\n")
    by_day: dict[str, float] = defaultdict(float)
    for row in rows:
        by_day[row["entryDate"][:10]] += row["pnl"]
    for name, trades in accounts.items():
        totals: dict[str, float] = defaultdict(float)
        for trade in trades:
            totals[trade["entryDate"][:10]] += trade["pnl"]
        net = sum(totals.values())
        if net <= 0:
            continue
        best_day, best = max(totals.items(), key=lambda kv: kv[1])
        share = best / net
        need = max(0.0, 2 * best - net)
        verdict = "OK" if share < 0.50 else f"VIOLATION — needs ${need:,.2f} more on other days"
        print(f"  {name}  best day {best_day} ${best:,.2f} = {share:.0%} of ${net:,.2f}   {verdict}")

    print("\n## Execution profile\n")
    seconds = []
    for row in rows:
        h, m, s = row["timeInTrade"].split(":")
        seconds.append(int(h) * 3600 + int(m) * 60 + int(s))
    quick = sum(1 for s in seconds if s <= 10)
    print(f"  median hold     {statistics.median(seconds):.0f}s")
    print(f"  {quick}/{len(rows)} trades ({quick / len(rows):.0%}) lasted 10 seconds or less")
    opening = sum(1 for r in rows if r["entryDate"][11:16] < "13:33" and r["entryDate"][11:13] == "13")
    print(f"  {opening}/{len(rows)} trades ({opening / len(rows):.0%}) entered in the first three"
          " minutes of the cash session")
    print(f"  position sizes  {dict(sorted(Counter(r['qty'] for r in rows).items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
