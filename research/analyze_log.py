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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--account", default="TPT100", choices=sorted(PRESETS))
    args = parser.parse_args()

    rows = load(args.csv_path)
    if not rows:
        print("no trades found")
        return 1
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
