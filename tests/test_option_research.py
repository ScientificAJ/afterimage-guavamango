from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_real_holdout import session

from afterimage.research import build_research_dataset
from afterimage.research.option_validation import validate_option_trade_bars
from afterimage.strategies.registry import default_registry


class OptionHistoryGateway:
    async def option_contracts(self, symbol: str, **filters: Any) -> list[dict[str, Any]]:
        assert symbol == "SPY"
        assert filters["status"] == "inactive"
        return [
            {
                "symbol": "SPY260703P00100000",
                "expiration_date": "2026-07-03",
                "strike_price": "100",
                "type": "put",
            },
            {
                "symbol": "SPY260703P00094000",
                "expiration_date": "2026-07-03",
                "strike_price": "94",
                "type": "put",
            },
        ]

    async def option_bars(
        self,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
    ) -> list[dict[str, Any]]:
        del start, end, timeframe
        long_symbol, short_symbol = symbols
        return [
            {"symbol": long_symbol, "t": "2026-07-01T14:00:00Z", "c": 2.00},
            {"symbol": short_symbol, "t": "2026-07-01T14:00:00Z", "c": 0.50},
            {"symbol": long_symbol, "t": "2026-07-01T14:40:00Z", "c": 2.60},
            {"symbol": short_symbol, "t": "2026-07-01T14:40:00Z", "c": 0.40},
        ]


@pytest.mark.asyncio
async def test_option_validation_uses_real_contracts_and_trade_bar_pairs(
    tmp_path: Path,
) -> None:
    dataset = build_research_dataset(
        session(date(2026, 6, 29), "target")
        + session(date(2026, 6, 30), "stop")
        + session(date(2026, 7, 1), "target"),
        default_registry(),
        training_start=date(2026, 6, 29),
        training_end=date(2026, 6, 29),
        holdout_start=date(2026, 7, 1),
        holdout_end=date(2026, 7, 1),
        embargo_sessions=1,
    )

    manifest = await validate_option_trade_bars(
        OptionHistoryGateway(),
        dataset,
        strategy_id="opening_range_failure_v1",
        public_path=tmp_path / "option-validation.json",
    )

    assert manifest.validated == 1
    assert manifest.excluded == 0
    assert manifest.results[0].long_symbol == "SPY260703P00100000"
    assert manifest.results[0].short_symbol == "SPY260703P00094000"
    assert manifest.results[0].entry_debit == Decimal("1.52")
    assert manifest.results[0].terminal_credit == Decimal("2.18")
    assert manifest.results[0].net_pnl_dollars == Decimal("66.00")
    assert manifest.results[0].entry_bar_start_at.isoformat() == ("2026-07-01T14:00:00+00:00")
    assert manifest.results[0].entry_at.isoformat() == "2026-07-01T14:05:00+00:00"
    assert manifest.results[0].terminal_at.isoformat() == "2026-07-01T14:45:00+00:00"
    assert manifest.statistics.requested_signals == 1
    assert manifest.statistics.coverage_rate == Decimal(1)
    assert manifest.statistics.wins == 1
    assert manifest.statistics.losses == 0
    assert manifest.statistics.time_exits == 1
    assert manifest.statistics.maximum_drawdown_dollars == Decimal(0)
    assert manifest.statistics.mean_ci95_lower_r == manifest.mean_return_r
    assert manifest.statistics.mean_ci95_upper_r == manifest.mean_return_r
    assert manifest.source == "Alpaca historical option trade bars"
    assert len(manifest.manifest_hash) == 64
    assert (tmp_path / "option-validation.json").exists()
