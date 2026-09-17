"""The drawdown arithmetic a funded account lives or dies on."""

from __future__ import annotations

import pytest

import statistics

from trading_bot.prop import (
    bootstrap_ruin,
    edge_from_log,
    expectancy_interval,
    INSTRUMENTS,
    PRESETS,
    DrawdownFloor,
    Instrument,
    PropAccount,
    breakeven_win_rate,
    contracts_for_risk,
    expectancy,
    max_risk_per_trade,
    ruin_probability,
)


def account(**overrides) -> PropAccount:
    base = dict(
        name="T", starting_balance=100_000.0, max_loss_limit=3_000.0,
        profit_target=6_000.0, max_minis=12, max_micros=120,
    )
    return PropAccount(**{**base, **overrides})


class TestDrawdownFloor:
    def test_floor_starts_one_limit_below_balance(self):
        book = DrawdownFloor(account())
        assert book.floor == 97_000.0
        assert book.room == 3_000.0

    def test_realized_profit_lifts_the_floor(self):
        book = DrawdownFloor(account())
        book.close_trade(1_000.0)
        assert book.floor == 98_000.0
        assert book.room == 3_000.0  # room is constant while trailing

    def test_floor_stops_at_the_starting_balance(self):
        book = DrawdownFloor(account())
        book.close_trade(10_000.0)
        assert book.floor == 100_000.0  # not 107_000
        assert book.room == 10_000.0  # and room now grows with profit

    def test_unrealized_peak_ratchets_the_floor_intraday(self):
        """The mechanic that makes an intraday account unlike a brokerage one."""
        book = DrawdownFloor(account())
        book.mark(100_800.0)  # trade runs 800 in your favour
        book.close_trade(0.0)  # and you exit flat
        assert book.balance == 100_000.0  # nothing earned
        assert book.floor == 97_800.0  # but 800 of room is gone
        assert book.room == 2_200.0

    def test_end_of_day_trail_ignores_the_unrealized_peak(self):
        book = DrawdownFloor(account(trail="end_of_day"))
        book.mark(100_800.0)
        book.close_trade(0.0)
        assert book.room == 3_000.0  # the round trip was free

    def test_end_of_day_trail_marks_on_close_day(self):
        book = DrawdownFloor(account(trail="end_of_day"))
        book.close_trade(500.0)
        book.close_day()
        assert book.floor == 97_500.0

    def test_touching_the_floor_breaches(self):
        book = DrawdownFloor(account())
        book.close_trade(-3_000.0)
        assert book.breached

    def test_a_loss_short_of_the_floor_does_not_breach(self):
        book = DrawdownFloor(account())
        book.close_trade(-2_999.0)
        assert not book.breached

    def test_an_unrealized_excursion_can_breach_without_a_realized_loss(self):
        book = DrawdownFloor(account())
        book.mark(96_000.0)
        assert book.breached

    def test_rejects_an_unknown_trail_mode(self):
        with pytest.raises(ValueError):
            account(trail="weekly")


class TestContractsForRisk:
    def test_rounds_down_so_a_sizing_error_undershoots(self):
        mes = INSTRUMENTS["MES"]  # 20 ticks = $25, plus $1 round turn
        assert contracts_for_risk(150.0, 20, mes, account()) == 5  # 5 * 26 = 130

    def test_counts_the_round_turn_cost_in_the_loss(self):
        free = Instrument("X", 1.0, 25.0, 0.0, is_micro=True)
        charged = Instrument("X", 1.0, 25.0, 5.0, is_micro=True)
        assert contracts_for_risk(100.0, 1, free, account()) == 4
        assert contracts_for_risk(100.0, 1, charged, account()) == 3

    def test_refuses_rather_than_widening_the_stop(self):
        es = INSTRUMENTS["ES"]  # 20 ticks = $250
        assert contracts_for_risk(150.0, 20, es, account()) == 0

    def test_respects_the_position_cap(self):
        mnq = INSTRUMENTS["MNQ"]
        assert contracts_for_risk(1_000_000.0, 20, mnq, account(max_micros=7)) == 7

    def test_minis_and_micros_use_separate_caps(self):
        es = INSTRUMENTS["ES"]
        acct = account(max_minis=2, max_micros=120)
        assert contracts_for_risk(1_000_000.0, 20, es, acct) == 2

    def test_rejects_a_non_positive_stop(self):
        with pytest.raises(ValueError):
            contracts_for_risk(150.0, 0, INSTRUMENTS["MES"], account())


class TestExpectancy:
    def test_breakeven_win_rate_zeroes_the_expectancy(self):
        for reward_risk in (0.5, 1.0, 2.0, 3.0):
            rate = breakeven_win_rate(reward_risk)
            assert expectancy(rate, reward_risk) == pytest.approx(0.0, abs=1e-12)

    def test_costs_raise_the_bar(self):
        assert breakeven_win_rate(1.0, cost_ratio=0.1) > breakeven_win_rate(1.0)

    def test_a_coin_flip_at_even_money_needs_half(self):
        assert breakeven_win_rate(1.0) == pytest.approx(0.5)


class TestRuinProbability:
    def test_outcomes_partition(self):
        est = ruin_probability(account(), 300.0, 0.5, 1.5, trials=2_000)
        assert est.ruin + est.target + est.undecided == pytest.approx(1.0)

    def test_bigger_risk_ruins_more_often_with_a_real_edge(self):
        small = ruin_probability(account(), 200.0, 0.5, 1.5, trials=4_000)
        large = ruin_probability(account(), 600.0, 0.5, 1.5, trials=4_000)
        assert large.ruin > small.ruin

    def test_the_trail_is_worse_than_classical_gamblers_ruin(self):
        """A driftless walk on a *fixed* floor ruins target/(target+room) of
        the time — 6000/9000 = 66.7% here. The trailing floor is strictly
        worse than that, and the gap is what the trail costs a coin flip."""
        est = ruin_probability(account(), 200.0, 0.5, 1.0, trials=8_000, max_trades=2_000)
        assert est.undecided == 0.0
        assert est.ruin > 0.75  # measured ~0.81 against the fixed-floor 0.667

    def test_a_worthless_edge_paying_costs_almost_always_ruins(self):
        est = ruin_probability(
            account(), 200.0, 0.5, 1.0, cost_dollars=8.0, trials=4_000, max_trades=2_000
        )
        assert est.ruin > 0.90

    def test_the_intraday_trail_is_never_kinder_than_end_of_day(self):
        intraday = ruin_probability(account(), 300.0, 0.5, 1.5, give_back=0.5, trials=6_000)
        eod = ruin_probability(
            account(trail="end_of_day"), 300.0, 0.5, 1.5, give_back=0.5, trials=6_000
        )
        assert intraday.ruin >= eod.ruin

    def test_costs_only_hurt(self):
        free = ruin_probability(account(), 300.0, 0.5, 1.5, trials=6_000)
        charged = ruin_probability(account(), 300.0, 0.5, 1.5, cost_dollars=30.0, trials=6_000)
        assert charged.ruin > free.ruin

    def test_is_reproducible_for_a_seed(self):
        kwargs = dict(trials=2_000, seed=7)
        assert ruin_probability(account(), 300.0, 0.5, 1.5, **kwargs) == ruin_probability(
            account(), 300.0, 0.5, 1.5, **kwargs
        )

    def test_needs_a_target(self):
        with pytest.raises(ValueError):
            ruin_probability(account(profit_target=None), 300.0, 0.5, 1.5, trials=10)

    def test_rejects_an_impossible_win_rate(self):
        with pytest.raises(ValueError):
            ruin_probability(account(), 300.0, 1.5, 1.5, trials=10)


class TestTailLosses:
    """A high win rate hides oversized losses; ruin does not."""

    def test_a_tail_raises_ruin_at_an_unchanged_win_rate(self):
        kwargs = dict(trials=6_000, max_trades=1_500, give_back=0.5)
        flat = ruin_probability(account(), 300.0, 0.75, 0.5, **kwargs)
        tailed = ruin_probability(
            account(), 300.0, 0.75, 0.5, tail_rate=0.1, tail_multiple=3.0, **kwargs
        )
        assert tailed.ruin > flat.ruin * 2

    def test_expectancy_barely_moves_while_ruin_doubles(self):
        """The trap: the average stays positive while survival collapses."""
        kwargs = dict(trials=6_000, max_trades=1_500, give_back=0.5)
        flat = ruin_probability(account(), 300.0, 0.75, 0.5, **kwargs)
        tailed = ruin_probability(
            account(), 300.0, 0.75, 0.5, tail_rate=0.1, tail_multiple=3.0, **kwargs
        )
        # Expectancy falls from 0.125R to 0.075R — still positive, still "works",
        # while ruin goes from roughly 1-in-30 to roughly 1-in-3.
        assert expectancy(0.75, 0.5) > 0
        assert flat.ruin < 0.10
        assert tailed.ruin > 0.25

    def test_a_tail_multiple_of_one_is_the_flat_case(self):
        """Drawing the tail consumes a random number, so the paths differ in
        detail; a tail the same size as an ordinary loss must still leave the
        answer alone."""
        kwargs = dict(trials=4_000, seed=3, max_trades=1_000)
        tailed = ruin_probability(
            account(), 300.0, 0.6, 1.0, tail_rate=0.5, tail_multiple=1.0, **kwargs
        )
        flat = ruin_probability(account(), 300.0, 0.6, 1.0, **kwargs)
        assert tailed.ruin == pytest.approx(flat.ruin, abs=0.01)

    def test_a_zero_tail_rate_leaves_the_stream_untouched(self):
        """tail_rate 0 draws nothing, so this one is exactly reproducible."""
        kwargs = dict(trials=4_000, seed=3, max_trades=1_000)
        assert ruin_probability(
            account(), 300.0, 0.6, 1.0, tail_rate=0.0, tail_multiple=9.0, **kwargs
        ) == ruin_probability(account(), 300.0, 0.6, 1.0, **kwargs)

    def test_rejects_a_tail_smaller_than_the_ordinary_loss(self):
        with pytest.raises(ValueError):
            ruin_probability(account(), 300.0, 0.6, 1.0, tail_multiple=0.5, trials=10)

    def test_rejects_an_impossible_tail_rate(self):
        with pytest.raises(ValueError):
            ruin_probability(account(), 300.0, 0.6, 1.0, tail_rate=1.5, trials=10)


class TestMaxRiskPerTrade:
    def test_a_better_edge_permits_more_risk(self):
        weak = max_risk_per_trade(account(), 0.50, 1.0, trials=1_500)
        strong = max_risk_per_trade(account(), 0.65, 1.5, trials=1_500)
        assert strong > weak

    def test_never_exceeds_the_whole_drawdown(self):
        acct = account()
        assert max_risk_per_trade(acct, 0.95, 5.0, trials=800) <= acct.max_loss_limit

    def test_a_losing_edge_has_no_safe_size(self):
        assert max_risk_per_trade(account(), 0.30, 1.0, trials=1_500) < 50.0

    def test_a_tighter_tolerance_permits_less_risk(self):
        loose = max_risk_per_trade(account(), 0.55, 1.5, tolerance=0.25, trials=1_500)
        tight = max_risk_per_trade(account(), 0.55, 1.5, tolerance=0.02, trials=1_500)
        assert tight < loose


class TestPresets:
    def test_every_preset_is_internally_consistent(self):
        for name, acct in PRESETS.items():
            assert acct.name == name
            assert acct.max_loss_limit > 0
            assert acct.profit_target and acct.profit_target > 0
            assert acct.max_micros >= acct.max_minis


class TestBootstrapRuin:
    """Resampling real sessions, and refusing to when the pool cannot support it."""

    @staticmethod
    def pool(n: int = 24, *, losers: int = 8) -> list[list[float]]:
        winning = [[200.0, -120.0, 180.0] for _ in range(n - losers)]
        losing = [[-300.0, -250.0, 100.0] for _ in range(losers)]
        return winning + losing

    def test_refuses_a_pool_too_small_to_resample(self):
        with pytest.raises(ValueError, match="too few to resample"):
            bootstrap_ruin(account(), self.pool(7, losers=2), trials=10)

    def test_refuses_a_pool_with_no_losing_session(self):
        """Six winners out of seven cannot reach the floor at any size, so the
        answer would be 0% ruin by construction rather than by measurement."""
        with pytest.raises(ValueError, match="no losing session"):
            bootstrap_ruin(account(), self.pool(24, losers=0), trials=10)

    def test_outcomes_partition(self):
        est = bootstrap_ruin(account(), self.pool(), trials=2_000)
        assert est.ruin + est.target + est.undecided == pytest.approx(1.0)

    def test_scaling_down_reduces_ruin_for_a_winning_pool(self):
        full = bootstrap_ruin(account(), self.pool(), scale=1.0, trials=4_000)
        small = bootstrap_ruin(account(), self.pool(), scale=0.1, trials=4_000)
        assert small.ruin <= full.ruin

    def test_a_losing_pool_ruins(self):
        est = bootstrap_ruin(account(), self.pool(24, losers=22), trials=4_000)
        assert est.ruin > 0.9

    def test_counts_sessions_not_trades(self):
        est = bootstrap_ruin(account(), self.pool(), trials=4_000)
        if est.median_trades_to_target is not None:
            # 3 trades per session, so a trade count would be ~3x larger.
            assert est.median_trades_to_target < 400

    def test_is_reproducible_for_a_seed(self):
        kwargs = dict(trials=2_000, seed=11)
        assert bootstrap_ruin(account(), self.pool(), **kwargs) == bootstrap_ruin(
            account(), self.pool(), **kwargs
        )

    def test_needs_a_target(self):
        with pytest.raises(ValueError, match="no target"):
            bootstrap_ruin(account(profit_target=None), self.pool(), trials=10)


class TestEdgeFromLog:
    """Deriving model parameters from realized P&L without double-counting."""

    def test_reconciles_with_realized_expectancy(self):
        pnls = [200.0, 300.0, -100.0, -120.0, 250.0, -900.0, 180.0, -110.0]
        edge = edge_from_log(pnls)
        assert edge["check"] == pytest.approx(0.0, abs=1e-9)
        assert edge["expectancy"] == pytest.approx(sum(pnls) / len(pnls))

    def test_the_baseline_risk_excludes_the_tail(self):
        """R is the ordinary loss. Averaging the oversized ones into it, and
        then applying a tail on top, counts them twice."""
        pnls = [200.0] * 8 + [-100.0] * 3 + [-1000.0]
        edge = edge_from_log(pnls)
        assert edge["risk"] == pytest.approx(100.0)
        assert edge["tail_multiple"] == pytest.approx(10.0)

    def test_double_counting_understates_the_edge(self):
        """The naive parameterisation is not merely different, it is biased
        against the trader, and the bias grows with the tail."""
        pnls = [200.0] * 8 + [-100.0] * 3 + [-1000.0]
        edge = edge_from_log(pnls)
        losses = [p for p in pnls if p < 0]
        naive_risk = abs(statistics.mean(losses))
        wins = [p for p in pnls if p > 0]
        naive = (
            edge["win_rate"] * (statistics.mean(wins) / naive_risk) * naive_risk
            - (1 - edge["win_rate"])
            * ((1 - edge["tail_rate"]) + edge["tail_rate"] * edge["tail_multiple"])
            * naive_risk
        )
        assert naive < edge["expectancy"]

    def test_a_log_with_no_tail_has_multiple_one(self):
        pnls = [200.0] * 6 + [-100.0, -105.0, -95.0]
        edge = edge_from_log(pnls)
        assert edge["tail_rate"] == 0.0
        assert edge["tail_multiple"] == pytest.approx(1.0)
        assert edge["check"] == pytest.approx(0.0, abs=1e-9)

    def test_needs_both_wins_and_losses(self):
        with pytest.raises(ValueError, match="both wins and losses"):
            edge_from_log([100.0, 200.0])

    def test_refuses_when_every_loss_is_oversized(self):
        with pytest.raises(ValueError, match="no baseline risk"):
            edge_from_log([100.0, -50.0, -50.0], tail_at=0.5)


class TestExpectancyInterval:
    """Bounding a mean by resampling, which the sample can actually support."""

    def test_brackets_the_observed_expectancy(self):
        pnls = [200.0, -100.0, 300.0, -120.0, 150.0, -90.0, 250.0, -110.0]
        result = expectancy_interval(pnls, trials=5_000)
        assert result["low"] < result["expectancy"] < result["high"]

    def test_a_concentrated_record_has_a_low_effective_n(self):
        """One trade carrying the result leaves far fewer effective
        observations than the nominal count suggests."""
        spread = expectancy_interval([100.0, -100.0] * 25, trials=2_000)
        concentrated = expectancy_interval([5000.0] + [10.0, -10.0] * 24 + [10.0], trials=2_000)
        assert spread["effective_n"] > 45
        assert concentrated["effective_n"] < 10
        assert spread["nominal_n"] == concentrated["nominal_n"]

    def test_thresholds_report_the_fraction_above_each(self):
        pnls = [200.0, -100.0, 300.0, -120.0, 150.0, -90.0, 250.0, -110.0]
        result = expectancy_interval(pnls, thresholds=(0.0, 1e9), trials=4_000)
        assert result["above"][0.0] > 0.5
        assert result["above"][1e9] == 0.0

    def test_a_wider_confidence_gives_a_wider_interval(self):
        pnls = [200.0, -100.0, 300.0, -120.0, 150.0, -90.0, 250.0, -110.0]
        narrow = expectancy_interval(pnls, confidence=0.50, trials=8_000)
        wide = expectancy_interval(pnls, confidence=0.99, trials=8_000)
        assert wide["high"] - wide["low"] > narrow["high"] - narrow["low"]

    def test_is_reproducible_for_a_seed(self):
        pnls = [200.0, -100.0, 300.0, -120.0]
        assert expectancy_interval(pnls, trials=2_000, seed=5) == expectancy_interval(
            pnls, trials=2_000, seed=5
        )

    def test_rejects_a_degenerate_sample(self):
        with pytest.raises(ValueError, match="at least two trades"):
            expectancy_interval([100.0])

    def test_rejects_an_impossible_confidence(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            expectancy_interval([100.0, -50.0], confidence=1.5)
