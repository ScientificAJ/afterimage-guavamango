from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from afterimage.contracts.models import MarketRecord
from afterimage.research.dataset import (
    ResearchDataset,
    ResearchDatasetError,
    build_research_dataset,
    persist_research_dataset,
)
from afterimage.strategies.registry import StrategyRegistry

ET = ZoneInfo("America/New_York")


class StockBarsGateway(Protocol):
    async def stock_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
    ) -> Sequence[dict[str, Any]]: ...


async def acquire_research_dataset(
    gateway: StockBarsGateway,
    registry: StrategyRegistry,
    *,
    symbol: str,
    training_start: date,
    training_end: date,
    holdout_start: date,
    holdout_end: date,
    embargo_sessions: int,
    private_path: Path,
    public_path: Path,
    received_at: datetime,
) -> ResearchDataset:
    if received_at.tzinfo is None:
        raise ResearchDatasetError("RECEIVED_AT_TIMEZONE_REQUIRED")
    start = datetime.combine(training_start, time.min, tzinfo=ET)
    end = datetime.combine(holdout_end + timedelta(days=1), time.min, tzinfo=ET)
    raw_bars = await gateway.stock_bars(symbol, start, end, "5Min")
    records: list[MarketRecord] = []
    timestamps: set[datetime] = set()
    for raw in raw_bars:
        record = _market_record(raw, symbol=symbol, received_at=received_at)
        eastern = record.timestamp.astimezone(ET)
        if not (time(9, 30) <= eastern.time() <= time(16)):
            continue
        if record.timestamp in timestamps:
            raise ResearchDatasetError("DUPLICATE_MARKET_BAR")
        timestamps.add(record.timestamp)
        records.append(record)
    if not records:
        raise ResearchDatasetError("MARKET_BARS_EMPTY")
    records.sort(key=lambda record: record.timestamp)
    dataset = build_research_dataset(
        records,
        registry,
        training_start=training_start,
        training_end=training_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        embargo_sessions=embargo_sessions,
    )
    persist_research_dataset(dataset, private_path, public_path)
    return dataset


def _market_record(raw: dict[str, Any], *, symbol: str, received_at: datetime) -> MarketRecord:
    required = {"t", "o", "h", "l", "c", "v"}
    if not required.issubset(raw):
        raise ResearchDatasetError("MARKET_BAR_MALFORMED")
    try:
        timestamp = datetime.fromisoformat(str(raw["t"]))
        values = {
            "open": _finite_number(raw["o"]),
            "high": _finite_number(raw["h"]),
            "low": _finite_number(raw["l"]),
            "close": _finite_number(raw["c"]),
            "volume": _finite_number(raw["v"]),
            "trade_count": int(raw.get("n", 0)),
            "vwap": _finite_number(raw.get("vw", raw["c"])),
        }
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchDatasetError("MARKET_BAR_MALFORMED") from exc
    if timestamp.tzinfo is None:
        raise ResearchDatasetError("MARKET_BAR_TIMEZONE_REQUIRED")
    if (
        values["open"] <= 0
        or values["high"] <= 0
        or values["low"] <= 0
        or values["close"] <= 0
        or values["volume"] < 0
        or values["trade_count"] < 0
        or values["vwap"] <= 0
        or values["high"] < max(values["open"], values["low"], values["close"])
        or values["low"] > min(values["open"], values["high"], values["close"])
    ):
        raise ResearchDatasetError("MARKET_BAR_VALUES_INVALID")
    return MarketRecord(
        symbol=symbol,
        timestamp=timestamp,
        received_at=received_at,
        source="alpaca-market-data-api",
        feed="iex",
        kind="bar",
        values=values,
    )


def _finite_number(value: Any) -> float:
    numeric = float(value)
    if not (-float("inf") < numeric < float("inf")):
        raise ValueError("number must be finite")
    return numeric
