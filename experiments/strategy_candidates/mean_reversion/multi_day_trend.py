from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar, Signal
from experiments.strategy_candidates.mean_reversion.gap_expansion import UnderlyingSignal


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class CarryParameters:
    lookback_sessions: int
    min_return: Decimal
    min_confirmations: int
    signal_minute_new_york: int = 14 * 60 + 45


def _group(rows: Sequence[Bar]) -> dict[date, tuple[Bar, ...]]:
    output: dict[date, list[Bar]] = {}
    for row in sorted(rows, key=lambda item: item.timestamp):
        output.setdefault(row.timestamp.date(), []).append(row)
    return {session: tuple(values) for session, values in output.items()}


def detect_multi_day_trend(
    bars_by_symbol: Mapping[str, Sequence[Bar]], params: CarryParameters
) -> tuple[UnderlyingSignal, ...]:
    symbols = tuple(sorted(bars_by_symbol))
    if len(symbols) < 2:
        raise ValueError("multi-day confirmation requires two or more symbols")
    grouped = {symbol: _group(bars_by_symbol[symbol]) for symbol in symbols}
    shared = tuple(sorted(set.intersection(*(set(grouped[symbol]) for symbol in symbols))))
    output: list[UnderlyingSignal] = []
    for index in range(params.lookback_sessions, len(shared)):
        session = shared[index]
        comparison_session = shared[index - params.lookback_sessions]
        directions: dict[str, str | None] = {}
        cutoff_bars: dict[str, Bar] = {}
        for symbol in symbols:
            cutoff = next(
                (
                    row
                    for row in grouped[symbol][session]
                    if row.timestamp.astimezone(NEW_YORK).hour * 60
                    + row.timestamp.astimezone(NEW_YORK).minute
                    == params.signal_minute_new_york
                ),
                None,
            )
            if cutoff is None:
                directions[symbol] = None
                continue
            comparison_close = grouped[symbol][comparison_session][-1].close
            change = cutoff.close / comparison_close - 1
            threshold = float(params.min_return)
            if change >= threshold:
                directions[symbol] = "bullish"
            elif change <= -threshold:
                directions[symbol] = "bearish"
            else:
                directions[symbol] = None
            cutoff_bars[symbol] = cutoff
        for direction in ("bullish", "bearish"):
            matching = tuple(symbol for symbol, value in directions.items() if value == direction)
            if len(matching) < params.min_confirmations:
                continue
            for symbol in matching:
                cutoff = cutoff_bars[symbol]
                output.append(
                    UnderlyingSignal(
                        underlying=symbol,
                        signal=Signal(
                            direction=direction,
                            signal_bar_start=cutoff.timestamp,
                            completed_at=cutoff.timestamp + timedelta(minutes=5),
                            reference_price=Decimal(str(cutoff.close)),
                            z_score=Decimal(0),
                        ),
                    )
                )
    return tuple(output)
