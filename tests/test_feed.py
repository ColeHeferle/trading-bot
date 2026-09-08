from __future__ import annotations

from datetime import datetime

import pytest

from trading_bot.feed import (
    BadBar,
    format_csv,
    merge,
    parse_csv,
    parse_stooq,
    validate,
)
from trading_bot.models import Candle

SIMPLE = """date,open,high,low,close,volume
2026-09-01,6400,6450,6390,6440,1000
2026-09-02,6440,6470,6435,6460,1200
"""


def bar(day: int, close: float, **kw) -> Candle:
    return Candle(
        datetime(2026, 9, day),
        kw.get("open", close),
        kw.get("high", close),
        kw.get("low", close),
        close,
        kw.get("volume", 0.0),
    )


class TestParsing:
    def test_reads_a_full_ohlcv_file(self):
        bars = parse_csv(SIMPLE)
        assert len(bars) == 2
        assert bars[0].timestamp == datetime(2026, 9, 1)
        assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (
            6400, 6450, 6390, 6440
        )

    def test_only_date_and_close_are_required(self):
        [only] = parse_csv("date,close\n2026-09-01,6440\n")
        assert only.open == only.high == only.low == only.close == 6440
        assert only.volume == 0.0

    def test_headers_are_case_insensitive(self):
        # Stooq ships `Date,Open,...`; nobody should have to hand-edit that.
        bars = parse_csv("Date,Close\n2026-09-01,6440\n")
        assert bars[0].close == 6440

    def test_sorts_oldest_first(self):
        text = "date,close\n2026-09-03,3\n2026-09-01,1\n2026-09-02,2\n"
        assert [b.close for b in parse_csv(text)] == [1, 2, 3]

    def test_ignores_blank_trailing_lines(self):
        assert len(parse_csv("date,close\n2026-09-01,6440\n\n")) == 1

    def test_empty_input_yields_nothing(self):
        assert parse_csv("") == []
        assert parse_csv("date,close\n") == []

    def test_rejects_an_unparseable_date(self):
        with pytest.raises(BadBar, match="not an ISO date"):
            parse_csv("date,close\nyesterday,6440\n")

    def test_rejects_a_non_numeric_price(self):
        with pytest.raises(BadBar, match="not a number"):
            parse_csv("date,close\n2026-09-01,n/a\n")

    def test_rejects_a_missing_close(self):
        with pytest.raises(BadBar, match="missing 'close'"):
            parse_csv("date,close\n2026-09-01,\n")


class TestValidation:
    def test_accepts_a_sane_bar(self):
        assert validate(bar(1, 100, open=99, high=101, low=98))

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"close": 0}, "non-positive"),
            ({"close": -5}, "non-positive"),
            ({"high": 90, "low": 110}, "below low"),
            ({"open": 120, "high": 105, "low": 95}, "high below open/close"),
            ({"open": 80, "high": 105, "low": 95}, "low above open/close"),
            ({"volume": -1}, "negative volume"),
        ],
    )
    def test_rejects_impossible_bars(self, kwargs, message):
        close = kwargs.pop("close", 100)
        with pytest.raises(BadBar, match=message):
            validate(
                Candle(
                    datetime(2026, 9, 1),
                    kwargs.get("open", close),
                    kwargs.get("high", close),
                    kwargs.get("low", close),
                    close,
                    kwargs.get("volume", 0.0),
                )
            )

    def test_a_bad_row_stops_the_whole_parse(self):
        # Dropping it silently would leave a gap nobody notices.
        text = "date,high,low,close\n2026-09-01,10,20,15\n"
        with pytest.raises(BadBar):
            parse_csv(text)


class TestMerge:
    def test_adds_new_dates(self):
        result = merge([bar(1, 1)], [bar(2, 2), bar(3, 3)])
        assert [b.close for b in result.bars] == [1, 2, 3]
        assert [b.close for b in result.added] == [2, 3]
        assert result.revised == []
        assert result.changed

    def test_re_running_the_same_data_changes_nothing(self):
        first = merge([], parse_csv(SIMPLE))
        again = merge(first.bars, parse_csv(SIMPLE))
        assert again.added == []
        assert again.revised == []
        assert not again.changed
        assert len(again.bars) == 2

    def test_keeps_the_stored_bar_when_a_vendor_restates_it(self):
        stored = [bar(1, 100)]
        result = merge(stored, [bar(1, 111)])

        assert [b.close for b in result.bars] == [100]  # unchanged
        assert result.added == []
        assert len(result.revised) == 1
        was, now = result.revised[0]
        assert (was.close, now.close) == (100, 111)

    def test_a_revision_does_not_block_new_bars_in_the_same_batch(self):
        result = merge([bar(1, 100)], [bar(1, 111), bar(2, 200)])
        assert [b.close for b in result.bars] == [100, 200]
        assert len(result.revised) == 1
        assert len(result.added) == 1

    def test_output_stays_sorted_even_from_unsorted_input(self):
        result = merge([bar(2, 2)], [bar(3, 3), bar(1, 1)])
        assert [b.timestamp for b in result.bars] == sorted(
            b.timestamp for b in result.bars
        )

    def test_merging_into_nothing_takes_everything(self):
        result = merge([], [bar(1, 1), bar(2, 2)])
        assert len(result.bars) == len(result.added) == 2

    def test_an_identical_restatement_is_not_a_revision(self):
        result = merge([bar(1, 100)], [bar(1, 100)])
        assert result.revised == []
        assert result.added == []


class TestRoundTrip:
    def test_format_then_parse_returns_the_same_bars(self):
        original = parse_csv(SIMPLE)
        again = parse_csv(format_csv(original))
        assert [
            (b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in again
        ] == [
            (b.timestamp, b.open, b.high, b.low, b.close, b.volume) for b in original
        ]

    def test_writes_a_header_even_with_no_bars(self):
        assert format_csv([]).strip() == "date,open,high,low,close,volume"

    def test_writes_oldest_first(self):
        text = format_csv([bar(3, 3), bar(1, 1), bar(2, 2)])
        dates = [line.split(",")[0] for line in text.strip().splitlines()[1:]]
        assert dates == sorted(dates)


class TestStooq:
    def test_parses_the_published_format(self):
        text = (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-09-01,6400,6450,6390,6440,0\n"
        )
        [only] = parse_stooq(text)
        assert only.close == 6440

    def test_rejects_the_plain_text_body_an_unknown_symbol_returns(self):
        # Stooq answers a bad symbol with prose and a 200 status.
        with pytest.raises(BadBar, match="does not look like Stooq CSV"):
            parse_stooq("No data\n")

    def test_rejects_an_empty_body(self):
        with pytest.raises(BadBar, match="does not look like Stooq CSV"):
            parse_stooq("")
