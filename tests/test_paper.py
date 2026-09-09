from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta

import pytest

from trading_bot import Candle, FullInvestment
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


WARM = FrozenRule(
    strategy="SmaCrossover",
    params={"fast_period": 2, "slow_period": 4},
    symbol="X",
    initial_cash=1000.0,
    fee_rate=0.0,
    # tests.helpers stamps bar i at 2024-01-01 + i days, so this makes bars
    # 0-6 warmup and everything from bar 7 live.
    warmup_until="2024-01-08",
)

CLIMB = [10, 10, 10, 10, 12, 14, 16, 18, 20]


def feed(rule, closes):
    run = PaperRun(rule)
    entries = [run.step(c) for c in make_candles(closes)]
    return run, entries


class TestWarmupValidation:
    def test_rejects_a_date_it_cannot_parse(self):
        with pytest.raises(ValueError, match="warmup_until must be an ISO date"):
            FrozenRule(
                strategy="BuyAndHold", params={}, symbol="X", warmup_until="soon"
            )

    def test_accepts_an_iso_date(self):
        rule = FrozenRule(
            strategy="BuyAndHold", params={}, symbol="X", warmup_until="2026-09-01"
        )
        assert rule.warmup_boundary.year == 2026

    def test_no_warmup_means_everything_is_live(self):
        assert PaperRun(RULE).is_live(make_candles([1])[0].timestamp)


class TestWarmupFingerprint:
    def test_rules_frozen_before_warmup_existed_keep_their_fingerprint(self):
        # `warmup_until=None` is omitted from the hashed payload, so a run
        # started before this feature still loads.
        assert "warmup_until" not in RULE.as_dict()
        explicit_none = FrozenRule(**{**RULE.as_dict(), "warmup_until": None})
        assert explicit_none.fingerprint == RULE.fingerprint

    def test_setting_a_warmup_changes_the_fingerprint(self):
        assert WARM.fingerprint != RULE.fingerprint

    def test_moving_the_warmup_boundary_changes_the_fingerprint(self):
        moved = FrozenRule(**{**WARM.as_dict(), "warmup_until": "2024-01-09"})
        assert moved.fingerprint != WARM.fingerprint


class TestWarmupBehaviour:
    def test_warmup_bars_return_nothing_and_stay_out_of_the_journal(self):
        run, entries = feed(WARM, CLIMB)
        assert entries[:7] == [None] * 7
        assert all(e is not None for e in entries[7:])
        assert len(run.journal) == 2

    def test_warmup_bars_do_not_trade(self):
        run, _ = feed(WARM, CLIMB)
        assert all(f.timestamp >= WARM.warmup_boundary for f in run.fills)

    def test_the_record_starts_at_the_boundary_not_the_first_bar(self):
        run, _ = feed(WARM, CLIMB)
        report = run.report
        assert report.started == WARM.warmup_boundary
        assert report.bars == 2
        assert report.warmup_bars == 7

    def test_a_rule_already_long_enters_on_its_first_live_bar(self):
        # SmaCrossover(2, 4) crosses up during warmup, so the position is taken
        # immediately once the record opens rather than waiting for a new cross.
        run, _ = feed(WARM, CLIMB)
        assert run.journal[0].quantity > 0

    def test_the_benchmark_starts_at_the_boundary_too(self):
        run, _ = feed(WARM, CLIMB)
        # Both sides enter on the same bar, at that bar's close of 18 — not at
        # the 10 the series opened with seven bars earlier.
        assert run.journal[0].benchmark_equity == pytest.approx(1000.0, rel=1e-3)
        assert run.benchmark_fills[0].price == 18
        assert run.benchmark_fills[0].timestamp == WARM.warmup_boundary

    def test_warmup_does_not_inflate_the_elapsed_window(self):
        run, _ = feed(WARM, CLIMB)
        # Two live bars one day apart, not nine.
        assert run.report.elapsed_years == pytest.approx(1 / 365.25, abs=1e-4)

    def test_a_boundary_after_every_bar_leaves_an_empty_record(self):
        rule = FrozenRule(**{**WARM.as_dict(), "warmup_until": "2030-01-01"})
        run, entries = feed(rule, CLIMB)
        assert entries == [None] * len(CLIMB)
        assert run.report.bars == 0
        assert run.report.warmup_bars == len(CLIMB)
        assert run.report.equity == pytest.approx(1000.0)
        assert run.fills == []
        assert run.benchmark_fills == []


class TestWarmupPersistence:
    def test_round_trips_and_replays_the_same_way(self):
        run, _ = feed(WARM, CLIMB)
        restored = PaperRun.from_json(run.to_json())

        assert restored.report.bars == run.report.bars
        assert restored.report.warmup_bars == run.report.warmup_bars
        assert restored.report.equity == pytest.approx(run.report.equity)

    def test_resuming_across_the_boundary_matches_an_uninterrupted_run(self):
        part = PaperRun(WARM)
        for candle in make_candles(CLIMB)[:5]:
            part.step(candle)
        resumed = PaperRun.from_json(part.to_json())
        for candle in make_candles(CLIMB)[5:]:
            resumed.step(candle)

        straight, _ = feed(WARM, CLIMB)
        assert resumed.report.equity == pytest.approx(straight.report.equity)
        assert resumed.report.bars == straight.report.bars


class TestFrozenRuleSizing:
    """A frozen rule can name a position sizer, not just a strategy."""

    def rule(self, **kw):
        return FrozenRule(
            strategy="SmaCrossover",
            params={"fast_period": 3, "slow_period": 8},
            symbol="X",
            **kw,
        )

    def test_a_rule_without_a_sizer_is_fully_invested(self):
        assert isinstance(self.rule().build_sizer(), FullInvestment)

    def test_omitting_the_sizer_keeps_the_old_fingerprint(self):
        """Runs frozen before sizers existed must still load.

        The hashed payload omits the key entirely when unset, so adding the
        field cannot silently invalidate a record already being kept.
        """
        payload = self.rule().as_dict()
        assert "sizer" not in payload and "sizer_params" not in payload

    def test_naming_a_sizer_changes_the_fingerprint(self):
        plain = self.rule().fingerprint
        sized = self.rule(
            sizer="VolatilityTarget", sizer_params={"target_volatility": 0.25}
        ).fingerprint
        assert plain != sized

    def test_the_sizer_parameters_are_part_of_the_freeze(self):
        a = self.rule(sizer="VolatilityTarget",
                      sizer_params={"target_volatility": 0.10}).fingerprint
        b = self.rule(sizer="VolatilityTarget",
                      sizer_params={"target_volatility": 0.25}).fingerprint
        assert a != b, "retuning the target must break the freeze"

    def test_an_unknown_sizer_is_refused_at_freeze_time(self):
        with pytest.raises(ValueError, match="unknown sizer"):
            self.rule(sizer="Martingale")

    def test_bad_sizer_parameters_are_refused_at_freeze_time(self):
        """Not months later, on the first bar that tries to size."""
        with pytest.raises(ValueError):
            self.rule(sizer="VolatilityTarget",
                      sizer_params={"target_volatility": -1.0})

    def test_params_without_a_sizer_are_refused(self):
        with pytest.raises(ValueError, match="without a sizer"):
            self.rule(sizer_params={"target_volatility": 0.25})

    def test_a_sized_rule_survives_a_save_and_load(self, tmp_path):
        rule = self.rule(sizer="VolatilityTarget",
                         sizer_params={"target_volatility": 0.25})
        path = tmp_path / "r.json"
        PaperRun(rule).save(path)
        loaded = PaperRun.load(path)
        assert loaded.rule.sizer == "VolatilityTarget"
        assert loaded.rule.sizer_params == {"target_volatility": 0.25}
        assert loaded.rule.fingerprint == rule.fingerprint


class TestPaperRunSizing:
    def bars(self, n, quiet=0.004, loud=0.03, loud_from=None, loud_to=None):
        rng = random.Random(5)
        out, price, day = [], 100.0, datetime(2026, 1, 1)
        for i in range(n):
            noisy = loud_from is not None and loud_from <= i <= loud_to
            price *= 1 + rng.gauss(0.001, loud if noisy else quiet)
            out.append(Candle(day + timedelta(days=i), price, price * 1.001,
                              price * 0.999, price))
        return out

    def feed(self, rule, bars):
        run = PaperRun(rule)
        for bar in bars:
            run.step(bar)
        return run

    def sized(self, **params):
        return FrozenRule(
            strategy="SmaCrossover", params={"fast_period": 3, "slow_period": 8},
            symbol="X", sizer="VolatilityTarget",
            sizer_params={"target_volatility": 0.15, "lookback": 20, **params},
        )

    def test_the_position_shrinks_when_the_market_turns_violent(self):
        """The whole point of the sizer, measured rather than asserted."""
        bars = self.bars(240, loud_from=90, loud_to=150)
        run = PaperRun(self.sized())
        calm, loud = [], []
        for i, bar in enumerate(bars):
            run.step(bar)
            if not run._long:
                continue
            (loud if 110 <= i <= 150 else calm if i < 90 or i > 190 else []).append(
                run.target_weight
            )
        assert calm and loud, "need both regimes to compare"
        assert sum(loud) / len(loud) < sum(calm) / len(calm) / 2, (
            f"violent {sum(loud)/len(loud):.2f} should be far under "
            f"calm {sum(calm)/len(calm):.2f}"
        )

    def test_the_sizer_sees_bars_the_rule_is_flat_for(self):
        """The bug this test exists for, and it must actually catch it.

        Volatility is a property of the market, not of what we hold. A sizer
        fed only while long is starved through every flat stretch, so when the
        rule turns long again its window is empty and it holds nothing — the
        rule would sit out the entry it just signalled.

        A sustained decline keeps the rule flat throughout, so the window can
        only fill if flat bars reach the sizer.
        """
        rng = random.Random(9)
        price, day, falling = 100.0, datetime(2026, 1, 1), []
        for i in range(80):
            price *= 1 - abs(rng.gauss(0.004, 0.002))
            falling.append(Candle(day + timedelta(days=i), price, price * 1.001,
                                  price * 0.999, price))
        run = self.feed(self.sized(lookback=20), falling)

        assert not run._long, "the fixture must keep the rule flat throughout"
        assert run._sizer.realized_volatility is not None, (
            "the volatility window never filled: the sizer was starved on the "
            "bars the rule was flat for"
        )

    def test_a_flat_rule_targets_zero_however_calm_the_market(self):
        run = self.feed(self.sized(), self.bars(30))
        run._long = False
        run._apply(self.bars(31)[-1])
        assert run.target_weight == 0.0

    def test_an_unsized_run_still_goes_fully_invested(self):
        rule = FrozenRule(strategy="SmaCrossover",
                          params={"fast_period": 3, "slow_period": 8}, symbol="X")
        run = self.feed(rule, self.bars(120))
        assert run.target_weight in (0.0, 1.0)

    def test_the_benchmark_is_never_sized(self):
        """Buy-and-hold is the thing being beaten; sizing it would move the bar."""
        bars = self.bars(200, loud_from=90, loud_to=130)
        plain = self.feed(FrozenRule(strategy="SmaCrossover",
                                     params={"fast_period": 3, "slow_period": 8},
                                     symbol="X"), bars)
        sized = self.feed(self.sized(), bars)
        assert plain.report.benchmark_equity == pytest.approx(
            sized.report.benchmark_equity
        )

    def test_replay_on_load_reproduces_the_sized_run(self, tmp_path):
        bars = self.bars(150, loud_from=60, loud_to=100)
        run = self.feed(self.sized(), bars)
        path = tmp_path / "r.json"
        run.save(path)
        again = PaperRun.load(path)
        assert again.target_weight == pytest.approx(run.target_weight)
        assert again.report.equity == pytest.approx(run.report.equity)
