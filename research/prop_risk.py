"""What a funded prop account permits, and how often it is survived.

    python research/prop_risk.py                      # TPT100 defaults
    python research/prop_risk.py --account TPT50
    python research/prop_risk.py --drawdown 2500 --target 6000

Firm rules change without notice. Override anything that does not match your
own account page rather than trusting the preset.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trading_bot.prop import (  # noqa: E402
    INSTRUMENTS,
    PRESETS,
    contracts_for_risk,
    breakeven_win_rate,
    expectancy,
    max_risk_per_trade,
    ruin_probability,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="TPT100", choices=sorted(PRESETS))
    parser.add_argument("--drawdown", type=float, help="override max loss limit")
    parser.add_argument("--target", type=float, help="override profit target")
    parser.add_argument("--trail", choices=("intraday", "end_of_day"))
    parser.add_argument("--trials", type=int, default=20_000)
    args = parser.parse_args()

    account = PRESETS[args.account]
    overrides = {}
    if args.drawdown is not None:
        overrides["max_loss_limit"] = args.drawdown
    if args.target is not None:
        overrides["profit_target"] = args.target
    if args.trail is not None:
        overrides["trail"] = args.trail
    if overrides:
        account = replace(account, **overrides)

    print(f"# {account.name}: ${account.starting_balance:,.0f} notional")
    print(f"  max loss limit   ${account.max_loss_limit:,.0f} "
          f"({account.max_loss_limit / account.starting_balance:.1%} of notional)")
    print(f"  profit target    ${account.profit_target:,.0f}")
    print(f"  trail            {account.trail}")
    print(f"  position cap     {account.max_minis} minis / {account.max_micros} micros")

    print("\n## How many contracts a stop distance permits")
    budget = account.max_loss_limit * 0.05
    print("Risk budget is a fraction of the DRAWDOWN, not of notional.")
    print(f"At a 5% of drawdown risk budget (${budget:,.0f} per trade):\n")
    print(f"{'instrument':<12}{'stop':>8}{'$/contract':>13}{'contracts':>11}{'actual risk':>13}")
    for sym in ("ES", "MES", "NQ", "MNQ"):
        inst = INSTRUMENTS[sym]
        for stop_ticks in (20, 40):
            n = contracts_for_risk(budget, stop_ticks, inst, account)
            per = inst.ticks_to_dollars(stop_ticks) + inst.round_turn_cost
            print(f"{sym:<12}{stop_ticks:>5}tk{per:>13,.2f}{n:>11}{n * per:>13,.2f}")

    print("\n## Breakeven win rate, after costs")
    print(f"{'reward:risk':<14}{'gross':>10}{'MES 20tk':>12}{'ES 20tk':>11}")
    for rr in (1.0, 1.5, 2.0, 3.0):
        mes = INSTRUMENTS["MES"]
        es = INSTRUMENTS["ES"]
        mes_cost = mes.round_turn_cost / mes.ticks_to_dollars(20)
        es_cost = es.round_turn_cost / es.ticks_to_dollars(20)
        print(f"{rr:<14.1f}{breakeven_win_rate(rr):>10.1%}"
              f"{breakeven_win_rate(rr, mes_cost):>12.1%}"
              f"{breakeven_win_rate(rr, es_cost):>11.1%}")

    print("\n## Probability of reaching the target before the floor reaches you")
    print("Risk fixed at 1R per trade. give_back = fraction of R a LOSING trade")
    print("first runs in your favour, ratcheting the intraday floor.\n")
    for risk in (200.0, 300.0, 500.0):
        print(f"### ${risk:,.0f} risk per trade "
              f"({account.max_loss_limit / risk:.1f} straight losses to failure)")
        print(f"{'win rate':<10}{'R:R':>6}{'give_back':>11}{'ruin':>9}{'target':>9}{'undecided':>11}{'median n':>10}")
        for win_rate, rr in ((0.40, 2.0), (0.50, 1.5), (0.55, 1.0), (0.65, 1.0)):
            for give_back in (0.0, 0.5):
                est = ruin_probability(
                    account, risk, win_rate, rr,
                    give_back=give_back, trials=args.trials,
                )
                median = "-" if est.median_trades_to_target is None else est.median_trades_to_target
                print(f"{win_rate:<10.0%}{rr:>6.1f}{give_back:>11.1f}"
                      f"{est.ruin:>9.1%}{est.target:>9.1%}{est.undecided:>11.1%}{median:>10}")
        print()

    print("## Largest risk per trade holding ruin under 10%")
    print(f"{'win rate':<10}{'R:R':>6}{'expectancy':>12}{'give_back=0':>14}{'give_back=0.5':>15}")
    for win_rate, rr in ((0.40, 2.0), (0.50, 1.5), (0.55, 1.0), (0.65, 1.0), (0.70, 1.0)):
        row = []
        for give_back in (0.0, 0.5):
            risk = max_risk_per_trade(
                account, win_rate, rr, tolerance=0.10, give_back=give_back,
            )
            row.append(f"${risk:,.0f}" if risk >= 1 else "none")
        print(f"{win_rate:<10.0%}{rr:>6.1f}{expectancy(win_rate, rr):>12.2f}R"
              f"{row[0]:>14}{row[1]:>15}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
