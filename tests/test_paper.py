from __future__ import annotations

import json
import math

import pytest

from trading_bot.paper import (
    FrozenRule,
    PaperRun,
    years_to_detect,
)

from tests.helpers import make_candles

RULE = FrozenRule(
    strategy="SmaCrossover",
    params={"fast_period": 2, "slow_period": 4},
    symbol="X",
    initial_cash=1000.0,
    fee_rate=0.0,
)

RALLY = [10, 10, 10, 10, 12, 14, 16, 18, 20]


class TestFrozenRule:
    def test_rejects_an_unknown_strategy(self):
        with pytest.raises(ValueError, match="unknown strategy"):
            FrozenRule(strategy="Vibes", params={}, symbol="X")

    def test_rejects_bad_parameters_at_freeze_time_not_months_later(self):
        with pytest.raises(ValueError, match="must be less than"):
            FrozenRule(
                strategy="SmaCrossover",
                params={"fast_period": 200, "slow_period": 50},
                symbol="X",
            )

    def test_rejects_non_positive_cash(self):
        with pytest.raises(ValueError, match="initial_cash must be positive"):
            FrozenRule(strategy="BuyAndHold", params={}, symbol="X", initial_cash=0)

    def test_fingerprint_is_stable_for_the_same_rule(self):
        twin = FrozenRule(
            strategy="SmaCrossover",
            params={"fast_period": 2, "slow_period": 4},
            symbol="X",
            initial_cash=1000.0,
            fee_rate=0.0,
        )
        assert twin.fingerprint == RULE.fingerprint

    @pytest.mark.parametrize(
        "change",
        [
            {"params": {"fast_period": 3, "slow_period": 4}},
            {"symbol": "Y"},
            {"fee_rate": 0.001},
            {"initial_cash": 2000.0},
            {"strategy": "BuyAndHold", "params": {}},
        ],
    )
    def test_any_material_change_moves_the_fingerprint(self, change):
        altered = FrozenRule(**{**RULE.as_dict(), **change})
        assert altered.fingerprint != RULE.fingerprint


class TestStepping:
    def test_records_one_journal_entry_per_bar(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)
        assert len(run.journal) == len(RALLY)

    def test_tracks_a_benchmark_alongside_the_rule(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)
        # Buy-and-hold is in from bar one; the crossover waits for its signal.
        assert run.journal[0].benchmark_equity == pytest.approx(1000.0)
        assert run.report.benchmark_equity > run.report.equity

    def test_refuses_a_bar_that_is_not_newer(self):
        run = PaperRun(RULE)
        candles = make_candles(RALLY)
        run.step(candles[0])
        with pytest.raises(ValueError, match="never rewrite history"):
            run.step(candles[0])

    def test_refuses_an_out_of_order_bar(self):
        run = PaperRun(RULE)
        candles = make_candles(RALLY)
        run.step(candles[3])
        with pytest.raises(ValueError, match="not newer"):
            run.step(candles[1])

    def test_enters_the_market_once_the_rule_fires(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)
        assert run.report.trades >= 1
        assert run.journal[-1].quantity > 0


class TestPersistence:
    def test_round_trips_through_json(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)

        restored = PaperRun.from_json(run.to_json())
        assert restored.report.equity == pytest.approx(run.report.equity)
        assert restored.report.bars == run.report.bars
        assert [e.signal for e in restored.journal] == [e.signal for e in run.journal]

    def test_survives_a_restart_and_keeps_accumulating(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY)[:5]:
            run.step(candle)
        saved = run.to_json()

        resumed = PaperRun.from_json(saved)
        for candle in make_candles(RALLY)[5:]:
            resumed.step(candle)

        straight = PaperRun(RULE)
        for candle in make_candles(RALLY):
            straight.step(candle)

        assert resumed.report.equity == pytest.approx(straight.report.equity)

    def test_saves_and_loads_a_file(self, tmp_path):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)
        path = tmp_path / "run.json"
        run.save(path)

        assert PaperRun.load(path).report.equity == pytest.approx(run.report.equity)

    def test_refuses_to_load_a_run_whose_rule_was_edited(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)

        payload = json.loads(run.to_json())
        payload["rule"]["params"] = {"fast_period": 3, "slow_period": 4}

        with pytest.raises(ValueError, match="frozen rule was edited"):
            PaperRun.from_json(json.dumps(payload))

    def test_an_untampered_file_loads_cleanly(self):
        run = PaperRun(RULE)
        run.step(make_candles(RALLY)[0])
        payload = json.loads(run.to_json())
        assert payload["fingerprint"] == RULE.fingerprint
        PaperRun.from_json(json.dumps(payload))


class TestReport:
    def test_empty_run_reports_the_starting_balance(self):
        report = PaperRun(RULE).report
        assert report.bars == 0
        assert report.equity == pytest.approx(1000.0)
        assert report.total_return == pytest.approx(0.0)
        assert report.elapsed_years == pytest.approx(0.0)

    def test_excess_is_measured_against_the_benchmark(self):
        run = PaperRun(RULE)
        for candle in make_candles(RALLY):
            run.step(candle)
        report = run.report
        assert report.excess == pytest.approx(
            report.total_return - report.benchmark_return
        )

    def test_elapsed_years_tracks_the_calendar(self):
        run = PaperRun(RULE)
        for candle in make_candles([10.0] * 366):
            run.step(candle)
        assert run.report.elapsed_years == pytest.approx(1.0, abs=0.01)


class TestYearsToDetect:
    def test_a_strong_edge_is_detectable_within_a_career(self):
        assert years_to_detect(1.0) == pytest.approx(4.0)

    def test_halving_the_edge_quadruples_the_wait(self):
        assert years_to_detect(0.25) == pytest.approx(4 * years_to_detect(0.5))

    def test_the_measured_edge_over_buy_and_hold_is_hopeless(self):
        # IR of 0.046 is what SmaCrossover(50, 200) actually scored against
        # buy-and-hold on twenty years of S&P 500 data.
        assert years_to_detect(0.046) > 1000

    def test_no_edge_never_resolves(self):
        assert years_to_detect(0.0) == math.inf
        assert years_to_detect(-0.3) == math.inf

    def test_a_looser_bar_still_takes_years(self):
        assert years_to_detect(0.5, t_stat=1.64) == pytest.approx(10.76, abs=0.01)
