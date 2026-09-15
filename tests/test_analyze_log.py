"""Parsing a broker export, where the format's quirks are the risk."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "research" / "analyze_log.py"
_spec = importlib.util.spec_from_file_location("analyze_log", _PATH)
analyze_log = importlib.util.module_from_spec(_spec)
sys.modules["analyze_log"] = analyze_log
_spec.loader.exec_module(analyze_log)

HEADER = (
    "tradeId,tradeAccount,symbol,entryDate,exitDate,maxQuantity,"
    "pnlDollars,commission,timeInTrade"
)
ROWS = [
    "1,ACCT_A,NQ,2026-08-04T13:30:00.000Z,2026-08-04T13:30:03.000Z,5,-1740.00,20.00,00:00:03",
    "2,ACCT_A,NQ,2026-08-05T13:29:30.000Z,2026-08-05T13:30:13.000Z,4,1120.00,20.00,00:00:43",
    "3,ACCT_B,NQ,2026-08-06T13:37:36.000Z,2026-08-06T13:38:29.000Z,5,-3500.00,25.00,00:00:53",
]


def write(tmp_path: Path, *, title: bool) -> Path:
    path = tmp_path / "trades.csv"
    body = ([f"export_{2026}"] if title else []) + [HEADER, *ROWS]
    path.write_text("\n".join(body) + "\n")
    return path


class TestLoad:
    def test_skips_the_title_line_these_exports_carry(self, tmp_path):
        """The first line has no commas and is not the header. Treating it as
        one silently drops a trade and renames every column."""
        assert len(analyze_log.load(write(tmp_path, title=True))) == 3

    def test_reads_a_plain_header_too(self, tmp_path):
        assert len(analyze_log.load(write(tmp_path, title=False))) == 3

    def test_sorts_into_entry_order(self, tmp_path):
        rows = analyze_log.load(write(tmp_path, title=True))
        assert [r["entryDate"][:10] for r in rows] == sorted(
            r["entryDate"][:10] for r in rows
        )

    def test_parses_pnl_and_quantity_as_numbers(self, tmp_path):
        rows = analyze_log.load(write(tmp_path, title=True))
        assert rows[0]["pnl"] == -1740.00
        assert rows[0]["qty"] == 5

    def test_an_empty_export_is_not_a_crash(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("title\n" + HEADER + "\n")
        assert analyze_log.load(path) == []


class TestReport:
    def test_runs_end_to_end(self, tmp_path, capsys):
        assert analyze_log.main.__call__ is not None
        sys.argv = ["analyze_log.py", str(write(tmp_path, title=True))]
        assert analyze_log.main() == 0
        out = capsys.readouterr().out
        assert "reward:risk" in out
        assert "ACCT_A" in out and "ACCT_B" in out

    def test_reports_a_breach_against_the_account_limit(self, tmp_path, capsys):
        sys.argv = ["analyze_log.py", str(write(tmp_path, title=True))]
        analyze_log.main()
        # ACCT_B's single -3,500 trade exceeds the TPT100 $3,000 limit.
        assert "BREACHED" in capsys.readouterr().out

    def test_an_empty_export_exits_nonzero(self, tmp_path, capsys):
        path = tmp_path / "empty.csv"
        path.write_text("title\n" + HEADER + "\n")
        sys.argv = ["analyze_log.py", str(path)]
        assert analyze_log.main() == 1
