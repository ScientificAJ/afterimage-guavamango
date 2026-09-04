from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from afterimage.contracts.models import MarketRecord

from .option_replay import ReplayFrame, ReplayLegQuote


def accepted_opening_range_records() -> tuple[MarketRecord, ...]:
    base = datetime(2026, 9, 3, 13, 30, tzinfo=UTC)
    bars = [
        (0, 650.00, 651.00, 649.50, 650.50),
        (5, 650.50, 651.50, 650.00, 651.00),
        (10, 651.00, 652.00, 650.80, 651.60),
        (15, 651.60, 652.40, 651.20, 652.10),
        (20, 652.10, 652.60, 651.50, 651.80),
        (25, 651.80, 652.55, 651.20, 651.40),
    ]
    return tuple(
        MarketRecord(
            symbol="SPY",
            timestamp=base + timedelta(minutes=offset),
            received_at=base + timedelta(minutes=offset, seconds=1),
            source="alpaca-recorded",
            feed="iex",
            kind="bar",
            values={"open": open_, "high": high, "low": low, "close": close, "volume": 1_000_000},
        )
        for offset, open_, high, low, close in bars
    )


def accepted_option_frames() -> tuple[ReplayFrame, ...]:
    start = datetime(2026, 9, 3, 14, 0, tzinfo=UTC)
    values = [
        (Decimal("0.72"), Decimal("0.75"), Decimal("0.03"), Decimal("0.05")),
        (Decimal("0.95"), Decimal("0.98"), Decimal("0.03"), Decimal("0.05")),
        (Decimal("1.38"), Decimal("1.42"), Decimal("0.03"), Decimal("0.05")),
    ]
    frames = []
    for index, (long_bid, long_ask, short_bid, short_ask) in enumerate(values):
        at = start + timedelta(minutes=index * 15)
        frames.append(
            ReplayFrame(
                timestamp=at,
                legs=(
                    ReplayLegQuote(
                        symbol="SPY260908P00650000",
                        side="buy",
                        bid=long_bid,
                        ask=long_ask,
                        timestamp=at,
                    ),
                    ReplayLegQuote(
                        symbol="SPY260908P00644000",
                        side="sell",
                        bid=short_bid,
                        ask=short_ask,
                        timestamp=at,
                    ),
                ),
            )
        )
    return tuple(frames)
