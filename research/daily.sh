#!/usr/bin/env bash
# Fetch today's bar and advance the paper run. Safe to run on a schedule:
# both halves are idempotent, so a double-run or a market holiday is a no-op.
#
#   crontab -e
#   0 22 * * 1-5 /path/to/trading-bot/research/daily.sh >> /tmp/paper.log 2>&1
#
# Any arguments are passed to fetch_bars.py, so --source yfinance or --strict
# work here too.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
STATE="${STATE:-paper/qqq_sma_10_50_vol25.json}"
BARS="${BARS:-paper/qqq_bars.csv}"

"$PYTHON" research/fetch_bars.py --out "$BARS" "$@"
"$PYTHON" research/paper_trade.py "$STATE" "$BARS"

# The broker leg runs every day but only reports, unless TRADE=execute is set.
# Exercising the whole path daily is what catches bugs; placing orders is a
# separate decision, so it takes a deliberate environment variable.
#
# The Claude proofreader runs with it and prints what it makes of the planned
# order. It never blocks and never changes the exit code, so REVIEW=off is a
# way to stop paying for it rather than a safety control.
if [ -n "${BROKER_SYMBOL:-}" ]; then
  echo
  ARGS=(--symbol "$BROKER_SYMBOL")
  [ "${TRADE:-dry}" = "execute" ] && ARGS+=(--execute)
  [ "${REVIEW:-on}" = "off" ] && ARGS+=(--no-review)
  "$PYTHON" research/trade.py "${ARGS[@]}"
fi
