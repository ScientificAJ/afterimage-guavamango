from __future__ import annotations

from datetime import UTC, datetime, timedelta

from afterimage.contracts.models import MarketRecord
from afterimage.strategies.base import MarketFrame
from afterimage.strategies.opening_range_failure import OpeningRangeFailureStrategy


def test_snapshot_identity_excludes_non_market_ingestion_time() -> None:
    market_time = datetime(2026, 9, 4, 13, 30, tzinfo=UTC)

    def record(received_at: datetime) -> MarketRecord:
        return MarketRecord(
            symbol="SPY",
            timestamp=market_time,
            received_at=received_at,
            source="alpaca-cli",
            feed="iex",
            kind="bar",
            values={"open": 1, "high": 2, "low": 1, "close": 2, "volume": 100},
        )

    strategy = OpeningRangeFailureStrategy()
    first = strategy.freeze(
        MarketFrame(symbol="SPY", cutoff=market_time, records=(record(market_time),))
    )
    second = strategy.freeze(
        MarketFrame(
            symbol="SPY",
            cutoff=market_time,
            records=(record(market_time + timedelta(hours=1)),),
        )
    )

    assert first.snapshot_id == second.snapshot_id
