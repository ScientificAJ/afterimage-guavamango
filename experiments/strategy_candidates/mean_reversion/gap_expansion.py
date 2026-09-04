from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar, Signal


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class GapParameters:
    compression_lookback: int
    compression_ratio: Decimal
    min_gap: Decimal
    min_opening_impulse: Decimal
    min_confirmations: int


@dataclass(frozen=True)
class UnderlyingSignal:
    underlying: str
    signal: Signal


def _sessions(rows: Sequence[Bar]) -> dict[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = {}
    for row in sorted(rows, key=lambda item: item.timestamp):
        grouped.setdefault(row.timestamp.date(), []).append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _normalized_range(rows: Sequence[Bar]) -> float:
    return (max(row.high for row in rows) - min(row.low for row in rows)) / rows[-1].close


def detect_gap_expansion(
    bars_by_symbol: Mapping[str, Sequence[Bar]], params: GapParameters
) -> tuple[UnderlyingSignal, ...]:
    symbols = tuple(sorted(bars_by_symbol))
    if len(symbols) < 2:
        raise ValueError("at least two confirmation symbols are required")
    grouped = {symbol: _sessions(bars_by_symbol[symbol]) for symbol in symbols}
    shared = tuple(sorted(set.intersection(*(set(grouped[symbol]) for symbol in symbols))))
    output: list[UnderlyingSignal] = []
    for session_index in range(params.compression_lookback + 1, len(shared)):
        session = shared[session_index]
        directions: dict[str, str | None] = {}
        opening_bars: dict[str, Bar] = {}
        for symbol in symbols:
            current_rows = grouped[symbol][session]
            opening = next(
                (
                    row
                    for row in current_rows
                    if row.timestamp.astimezone(NEW_YORK).hour == 9
                    and row.timestamp.astimezone(NEW_YORK).minute == 30
                ),
                None,
            )
            if opening is None:
                directions[symbol] = None
                continue
            prior_session = shared[session_index - 1]
            prior_rows = grouped[symbol][prior_session]
            older_sessions = shared[
                session_index - params.compression_lookback - 1 : session_index - 1
            ]
            older_ranges = [
                _normalized_range(grouped[symbol][older]) for older in older_sessions
            ]
            average_range = sum(older_ranges) / len(older_ranges)
            compressed = _normalized_range(prior_rows) <= (
                float(params.compression_ratio) * average_range
            )
            gap = opening.open / prior_rows[-1].close - 1
            impulse = opening.close / opening.open - 1
            threshold_gap = float(params.min_gap)
            threshold_impulse = float(params.min_opening_impulse)
            if compressed and gap >= threshold_gap and impulse >= threshold_impulse:
                directions[symbol] = "bullish"
            elif compressed and gap <= -threshold_gap and impulse <= -threshold_impulse:
                directions[symbol] = "bearish"
            else:
                directions[symbol] = None
            opening_bars[symbol] = opening

        for direction in ("bullish", "bearish"):
            matching = tuple(
                symbol for symbol, value in directions.items() if value == direction
            )
            if len(matching) < params.min_confirmations:
                continue
            for symbol in matching:
                opening = opening_bars[symbol]
                output.append(
                    UnderlyingSignal(
                        underlying=symbol,
                        signal=Signal(
                            direction=direction,
                            signal_bar_start=opening.timestamp,
                            completed_at=opening.timestamp + timedelta(minutes=5),
                            reference_price=Decimal(str(opening.close)),
                            z_score=Decimal(0),
                        ),
                    )
                )
    return tuple(output)
