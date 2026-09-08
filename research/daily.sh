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
STATE="${STATE:-paper/spx_sma_50_200.json}"
BARS="${BARS:-paper/spx_bars.csv}"

"$PYTHON" research/fetch_bars.py --out "$BARS" "$@"
"$PYTHON" research/paper_trade.py "$STATE" "$BARS"
