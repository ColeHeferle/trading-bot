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


def log(n_trades: int, *, n_days: int, win_rate: float, rr: float,
        escalate: bool = False, all_winning_days: bool = False) -> list[dict]:
    """Synthesise a log with known properties: one account, `n_days` sessions.

    Losses are concentrated on the earliest days so at least one session ends
    negative, which is what the gate requires. `all_winning_days` spreads them
    evenly instead, producing an unbroken winning record.
    """
    rows = []
    wins = round(n_trades * win_rate)
    losses = n_trades - wins
    for i in range(n_trades):
        is_win = i >= losses
        pnl = 100.0 * rr if is_win else -100.0
        if all_winning_days:
            day = (i % n_days) + 1
        else:
            # Losses fill day 1 upward; wins fill the remaining days.
            day = (i % max(1, n_days // 3)) + 1 if not is_win else (i % n_days) + 1
        qty = 5
        if escalate and rows and rows[-1]["pnl"] < 0:
            qty = 9
        rows.append({
            "tradeAccount": "A", "pnl": pnl, "qty": qty,
            "entryDate": f"2026-08-{day:02d}T13:30:{i % 60:02d}.000Z",
            "timeInTrade": "00:00:03",
        })
    rows.sort(key=lambda r: r["entryDate"])
    return rows


class TestGate:
    def test_a_thin_log_is_refused(self, capsys):
        assert analyze_log.gate(log(52, n_days=7, win_rate=0.52, rr=1.36)) == 1
        assert "GATE CLOSED" in capsys.readouterr().out

    def test_a_qualifying_log_opens_the_gate(self, capsys):
        rows = log(200, n_days=30, win_rate=0.60, rr=1.50)
        assert analyze_log.gate(rows) == 0
        assert "GATE OPEN" in capsys.readouterr().out

    def test_size_escalation_closes_the_gate(self, capsys):
        rows = log(200, n_days=30, win_rate=0.60, rr=1.50, escalate=True)
        assert analyze_log.gate(rows) == 1
        assert "no size escalation" in capsys.readouterr().out

    def test_a_marginal_edge_fails_the_t_statistic(self, capsys):
        """A win rate barely above breakeven is not established at any size."""
        rows = log(200, n_days=30, win_rate=0.41, rr=1.50)
        assert analyze_log.gate(rows) == 1

    def test_an_unbroken_winning_record_closes_the_gate(self, capsys):
        """Every other criterion can pass and this one still refuses: a record
        that never had a bad session has not been tested."""
        rows = log(200, n_days=30, win_rate=0.60, rr=1.50, all_winning_days=True)
        assert analyze_log.gate(rows) == 1
        assert "a losing session exists" in capsys.readouterr().out

    def test_a_log_with_no_losses_cannot_be_judged(self, capsys):
        rows = log(200, n_days=30, win_rate=1.0, rr=1.5)
        assert analyze_log.gate(rows) == 1
        assert "cannot be judged" in capsys.readouterr().out

    def test_every_criterion_is_reported_either_way(self, capsys):
        analyze_log.gate(log(200, n_days=30, win_rate=0.60, rr=1.50))
        out = capsys.readouterr().out
        for name in ("sample size", "edge established", "reward:risk", "loss tail",
                     "no size escalation", "sessions", "a losing session exists"):
            assert name in out
