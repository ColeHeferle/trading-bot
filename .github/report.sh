#!/usr/bin/env bash
# Run a command, echo its output to the log AND to the workflow's run summary,
# and exit with the command's own status.
#
#   .github/report.sh '## Fetch' python research/fetch_bars.py --out bars.csv
#
# The summary is what makes a scheduled run readable without opening the logs,
# which is most of the point of running the loop on GitHub at all.
#
# The exit status is the reason this is a script rather than an inline
# pipeline. Wrapping a command in `{ ...; echo '```'; } | tee` makes the brace
# group's status that of the trailing echo, so a failing step reports success —
# a fetch that could not reach the vendor, or a broker leg that refused, would
# both look fine. Here the status is captured explicitly and the closing fence
# is written either way.
set -uo pipefail

heading=$1
shift

summary=${GITHUB_STEP_SUMMARY:-/dev/null}

{
    printf '%s\n\n' "$heading"
    printf '```\n'
} >> "$summary"

status=0
"$@" 2>&1 | tee -a "$summary" || status=${PIPESTATUS[0]}

printf '```\n\n' >> "$summary"
exit "$status"
