from __future__ import annotations

from datetime import UTC, date, datetime

from afterimage.contracts.models import MarketRecord
from afterimage.research.holdout import evaluate_strategy_holdout
from afterimage.strategies.opening_range_failure import OpeningRangeFailureStrategy


def session(day: date, outcome: str) -> tuple[MarketRecord, ...]:
    values = (
        (9, 30, 100.0, 100.4, 99.4, 100.0, 1000),
        (9, 35, 100.0, 100.5, 99.6, 100.1, 1100),
        (9, 40, 100.1, 100.3, 99.5, 100.0, 1200),
        (9, 45, 100.0, 100.8, 99.8, 100.4, 1300),
        (9, 50, 100.4, 100.7, 99.9, 100.2, 1400),
        (9, 55, 100.2, 100.3, 99.8, 100.0, 1500),
        (10, 0, 100.0, 100.35 if outcome == "stop" else 100.05, 99.2, 99.5, 1600),
    )
    return tuple(
        MarketRecord(
            symbol="SPY",
            timestamp=datetime(day.year, day.month, day.day, hour + 4, minute, tzinfo=UTC),
            received_at=datetime(2026, 9, 4, tzinfo=UTC),
            source="alpaca-cli",
            feed="iex",
            kind="bar",
            values={"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        )
        for hour, minute, opn, high, low, close, volume in values
    )


def test_real_holdout_outcomes_are_derived_from_the_observed_post_signal_path() -> None:
    records = session(date(2026, 7, 1), "target") + session(date(2026, 7, 2), "stop")

    result = evaluate_strategy_holdout(records, OpeningRangeFailureStrategy())

    assert [row.session_date for row in result.rows] == [date(2026, 7, 1), date(2026, 7, 2)]
    assert [row.return_r for row in result.rows] == [3, -1]
    assert [row.target_first for row in result.rows] == [True, False]
    assert all(row.direction in {"bullish", "bearish"} for row in result.rows)
    assert all(row.signal_at is not None for row in result.rows)
    assert all(row.signal_price is not None and row.signal_price > 0 for row in result.rows)
    assert result.sessions_scanned == 2
    assert result.signals == 2
    assert result.source_record_count == 14
    assert result.source_hash


def test_real_holdout_does_not_invent_an_outcome_when_no_strategy_signal_exists() -> None:
    records = list(session(date(2026, 7, 1), "target"))
    for index in (3, 4, 5):
        records[index] = records[index].model_copy(
            update={"values": {**records[index].values, "high": 100.4}}
        )

    result = evaluate_strategy_holdout(tuple(records), OpeningRangeFailureStrategy())

    assert result.rows == ()
    assert result.sessions_scanned == 1
    assert result.signals == 0


def test_real_holdout_ignores_extended_hours_bars() -> None:
    regular = session(date(2026, 7, 1), "target")
    premarket = regular[0].model_copy(
        update={
            "timestamp": datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
            "values": {**regular[0].values, "high": 999, "low": 1},
        }
    )

    result = evaluate_strategy_holdout((premarket, *regular), OpeningRangeFailureStrategy())

    assert result.source_record_count == len(regular)
    assert result.rows[0].return_r == 3
