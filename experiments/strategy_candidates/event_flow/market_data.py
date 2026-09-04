"""Market-data parsing and regular-session aggregation."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .engine import Bar

ET = ZoneInfo("America/New_York")


def parse_cache(path: Path) -> tuple[dict[str, tuple[Bar, ...]], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    parsed: dict[str, tuple[Bar, ...]] = {}
    for symbol, rows in payload["bars"].items():
        parsed[symbol] = tuple(
            Bar(
                symbol=symbol,
                timestamp=datetime.fromisoformat(item["t"]),
                open=Decimal(str(item["o"])),
                high=Decimal(str(item["h"])),
                low=Decimal(str(item["l"])),
                close=Decimal(str(item["c"])),
                volume=int(item["v"]),
            )
            for item in rows
        )
    provenance = {key: value for key, value in payload.items() if key != "bars"}
    return parsed, provenance


def regular_sessions(bars: Sequence[Bar]) -> Mapping[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = defaultdict(list)
    for bar in bars:
        local = bar.timestamp.astimezone(ET)
        if (local.hour, local.minute) < (9, 30) or (local.hour, local.minute) >= (16, 0):
            continue
        grouped[local.date()].append(bar)
    return {
        session: tuple(sorted(rows, key=lambda item: item.timestamp))
        for session, rows in sorted(grouped.items())
    }


def aggregate_daily(bars: Sequence[Bar], *, minimum_bars: int = 20) -> tuple[Bar, ...]:
    result: list[Bar] = []
    for rows in regular_sessions(bars).values():
        if len(rows) < minimum_bars:
            continue
        result.append(
            Bar(
                symbol=rows[0].symbol,
                timestamp=rows[-1].timestamp + timedelta(minutes=15),
                open=rows[0].open,
                high=max(item.high for item in rows),
                low=min(item.low for item in rows),
                close=rows[-1].close,
                volume=sum(item.volume for item in rows),
            )
        )
    return tuple(result)


def _session_timestamp(bar: Bar, at: time) -> datetime:
    # Alpaca daily-bar timestamps encode the trading-session date in UTC while
    # their exact hour moves with DST.  The UTC date is therefore the stable key.
    return datetime.combine(bar.timestamp.date(), at, tzinfo=ET).astimezone(bar.timestamp.tzinfo)


def normalize_daily_opens(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    """Represent each daily OHLC bar at the actual 09:30 ET entry time."""
    return tuple(
        Bar(
            symbol=bar.symbol,
            timestamp=_session_timestamp(bar, time(9, 30)),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    )


def session_close(bar: Bar) -> datetime:
    """Return the causal completion time for a daily regular-session bar."""
    return _session_timestamp(bar, time(16, 0))
