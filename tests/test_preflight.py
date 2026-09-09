"""The preflight check exists to tell two identical-looking flats apart.

A rule that went flat because it saw a death cross, and a rule that is flat
only because its backfill never contained a crossing, print the same thing
everywhere else in this repo. Confusing them costs a month of unexplained
flatness, so these tests pin the distinction rather than the wording.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trading_bot import FrozenRule, PaperRun

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location(
        "preflight", ROOT / "research" / "preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = load_script()


def series(days: int, step, start: float = 400.0, end: datetime | None = None):
    """`days` weekday bars ending today, each close `step(i)` times the last."""
    end = end or datetime.now()
    rows, price, day = [], start, end
    dates = []
    while len(dates) < days:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    for i, when in enumerate(reversed(dates)):
        price *= step(i)
        rows.append((when, price))
    return rows


def write_csv(path: Path, rows) -> Path:
    lines = ["date,open,high,low,close,volume"]
    for when, close in rows:
        lines.append(
            f"{when.date()},{close:.2f},{close * 1.002:.2f},"
            f"{close * 0.998:.2f},{close:.2f},1000"
        )
    path.write_text("\n".join(lines) + "\n")
    return path


def make_rule(tmp_path: Path, warmup_until: str | None = None) -> Path:
    """A frozen SPY rule whose boundary is tomorrow, so all bars are warmup."""
    if warmup_until is None:
        warmup_until = (datetime.now() + timedelta(days=1)).date().isoformat()
    rule = FrozenRule(
        strategy="SmaCrossover",
        params={"fast_period": 50, "slow_period": 200},
        symbol="SPY",
        warmup_until=warmup_until,
    )
    state = tmp_path / "rule.json"
    PaperRun(rule).save(state)
    return state


def run(state: Path, bars: Path, *extra: str) -> int:
    return preflight.main([str(state), str(bars), *extra])


class TestTellsTheTwoFlatsApart:
    def test_uptrend_without_a_crossing_is_not_ready(self, tmp_path, capsys):
        """The failure this script exists for: flat inside a rally it can see."""
        bars = write_csv(tmp_path / "up.csv", series(260, lambda i: 1.0018))
        code = run(make_rule(tmp_path), bars)
        out = capsys.readouterr()
        assert code == 1
        assert "no crossing was ever witnessed" in out.out
        assert "ALREADY ABOVE" in out.out

    def test_flat_after_a_death_cross_is_ready(self, tmp_path, capsys):
        """Flat is a real decision here, so it must not be flagged."""
        rows = series(560, lambda i: 1.0030 if i < 280 else 0.9970)
        bars = write_csv(tmp_path / "down.csv", rows)
        code = run(make_rule(tmp_path), bars)
        out = capsys.readouterr()
        assert code == 0
        assert "FLAT — SELL" in out.out
        assert "ready to launch" in out.out

    def test_golden_cross_in_warmup_opens_long(self, tmp_path, capsys):
        rows = series(560, lambda i: 0.9985 if i < 280 else 1.0035)
        bars = write_csv(tmp_path / "cross.csv", rows)
        code = run(make_rule(tmp_path), bars)
        out = capsys.readouterr()
        assert code == 0
        assert "opens         LONG" in out.out

    def test_the_same_market_flips_on_how_much_history_is_given(
        self, tmp_path, capsys
    ):
        """The point of the whole script, as one test.

        One series, two backfill depths. The short window starts after the
        crossing and so never sees it; the long one contains it. Same rule,
        same final price, opposite opening position — and the shallow run has
        to fail for *that* reason, not for being short of bars.
        """
        rows = series(700, lambda i: 0.9985 if i < 200 else 1.0025)
        deep = write_csv(tmp_path / "deep.csv", rows)
        shallow = write_csv(tmp_path / "shallow.csv", rows[-260:])

        assert run(make_rule(tmp_path), deep) == 0
        deep_out = capsys.readouterr().out
        assert "opens         LONG" in deep_out

        assert run(make_rule(tmp_path), shallow) == 1
        shallow_out = capsys.readouterr()
        assert "no crossing was ever witnessed" in shallow_out.out
        assert "ALREADY ABOVE" in shallow_out.out
        # Not a bar-count failure: 260 bars clears the 200 the rule needs.
        assert "Backfill 0 more" not in shallow_out.err
        assert "needs 200 bars" not in shallow_out.err

    def test_flat_start_can_be_accepted_deliberately(self, tmp_path, capsys):
        bars = write_csv(tmp_path / "up.csv", series(260, lambda i: 1.0018))
        code = run(make_rule(tmp_path), bars, "--accept-flat-start")
        assert code == 0
        assert "your call" in capsys.readouterr().out


class TestRefusesOnBadInput:
    def test_too_few_bars_reports_the_shortfall_once(self, tmp_path, capsys):
        bars = write_csv(tmp_path / "short.csv", series(70, lambda i: 1.001))
        code = run(make_rule(tmp_path), bars)
        err = capsys.readouterr().err
        assert code == 1
        assert "needs 200 bars" in err and "Backfill 130 more" in err
        # One root cause, reported once.
        assert err.count("Backfill") == 1

    def test_stale_bars_block_the_launch(self, tmp_path, capsys):
        old = datetime.now() - timedelta(days=20)
        rows = series(560, lambda i: 0.9985 if i < 280 else 1.0035, end=old)
        bars = write_csv(tmp_path / "stale.csv", rows)
        code = run(make_rule(tmp_path), bars)
        assert code == 1
        assert "days old" in capsys.readouterr().err

    def test_future_dated_bars_block_the_launch(self, tmp_path, capsys):
        ahead = datetime.now() + timedelta(days=10)
        rows = series(560, lambda i: 0.9985 if i < 280 else 1.0035, end=ahead)
        bars = write_csv(tmp_path / "future.csv", rows)
        code = run(make_rule(tmp_path), bars)
        assert code == 1
        assert "in the future" in capsys.readouterr().err

    def test_a_stale_file_does_not_hide_the_unwitnessed_warning(
        self, tmp_path, capsys
    ):
        """An unrelated problem must not suppress the diagnostic."""
        old = datetime.now() - timedelta(days=30)
        bars = write_csv(tmp_path / "both.csv",
                         series(260, lambda i: 1.0018, end=old))
        code = run(make_rule(tmp_path), bars)
        out = capsys.readouterr()
        assert code == 1
        assert "days old" in out.err
        assert "ALREADY ABOVE" in out.out

    def test_missing_file_says_so_without_a_traceback(self, tmp_path, capsys):
        code = run(make_rule(tmp_path), tmp_path / "nope.csv")
        assert code == 2
        assert "cannot read" in capsys.readouterr().err

    def test_no_bars_at_all(self, tmp_path, capsys):
        bars = write_csv(tmp_path / "empty.csv", [])
        assert run(make_rule(tmp_path), bars) == 1
        assert "no bars at all" in capsys.readouterr().out


class TestDoesNotDisturbTheRun:
    def test_the_state_file_is_untouched(self, tmp_path):
        """Preflight must never advance the record it is inspecting."""
        state = make_rule(tmp_path)
        before = state.read_bytes()
        rows = series(560, lambda i: 0.9985 if i < 280 else 1.0035)
        run(state, write_csv(tmp_path / "bars.csv", rows))
        assert state.read_bytes() == before

    def test_bars_already_recorded_are_not_counted_twice(self, tmp_path, capsys):
        state = make_rule(tmp_path)
        rows = series(560, lambda i: 0.9985 if i < 280 else 1.0035)
        bars = write_csv(tmp_path / "bars.csv", rows)

        loaded = PaperRun.load(state)
        from trading_bot import parse_csv

        for candle in parse_csv(bars.read_text()):
            loaded.step(candle)
        loaded.save(state)

        run(state, bars)
        assert f"bars          {len(rows)} ({len(rows)} already recorded, 0 new)" \
            in capsys.readouterr().out


@pytest.mark.parametrize("boundary", [None, "2020-01-01"])
def test_runs_without_a_future_boundary(tmp_path, boundary):
    """A rule with no boundary, or one long past, must still report."""
    rows = series(560, lambda i: 0.9985 if i < 280 else 1.0035)
    bars = write_csv(tmp_path / "bars.csv", rows)
    rule = FrozenRule(
        strategy="SmaCrossover",
        params={"fast_period": 50, "slow_period": 200},
        symbol="SPY",
        warmup_until=boundary,
    )
    state = tmp_path / "r.json"
    PaperRun(rule).save(state)
    assert run(state, bars) in (0, 1)
