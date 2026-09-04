from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from test_real_holdout import session

from afterimage.research.acquisition import acquire_research_dataset
from afterimage.strategies.registry import default_registry


class BarsGateway:
    def __init__(self, bars: list[dict[str, Any]]) -> None:
        self.bars = bars

    async def stock_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]:
        del symbol, start, end, timeframe
        return self.bars


@pytest.mark.asyncio
async def test_acquisition_persists_hash_bound_real_alpaca_records(tmp_path: Path) -> None:
    records = (
        session(date(2026, 6, 29), "target")
        + session(date(2026, 6, 30), "stop")
        + session(date(2026, 7, 1), "target")
    )
    bars = [
        {
            "t": record.timestamp.isoformat().replace("+00:00", "Z"),
            "o": record.values["open"],
            "h": record.values["high"],
            "l": record.values["low"],
            "c": record.values["close"],
            "v": record.values["volume"],
            "n": 1,
            "vw": record.values["close"],
        }
        for record in records
    ]
    private = tmp_path / "private" / "research.json"
    public = tmp_path / "public" / "manifest.json"

    dataset = await acquire_research_dataset(
        BarsGateway(bars),
        default_registry(),
        symbol="SPY",
        training_start=date(2026, 6, 29),
        training_end=date(2026, 6, 29),
        holdout_start=date(2026, 7, 1),
        holdout_end=date(2026, 7, 1),
        embargo_sessions=1,
        private_path=private,
        public_path=public,
        received_at=datetime(2026, 9, 4, tzinfo=UTC),
    )

    assert dataset.training.records[0].source == "alpaca-market-data-api"
    assert dataset.training.records[0].feed == "iex"
    assert dataset.training.records[0].values["trade_count"] == 1
    assert dataset.holdout.evaluations["opening_range_failure_v1"].rows
    assert private.exists()
    assert public.exists()
