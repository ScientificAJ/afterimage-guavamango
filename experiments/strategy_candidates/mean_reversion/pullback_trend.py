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
class PullbackParameters:
    recent_lookback: int
    min_session_move: Decimal
    min_confirmations: int
    min_volume_ratio: Decimal
    start_minute_new_york: int
    end_minute_new_york: int


def _group(rows: Sequence[Bar]) -> dict[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = {}
    for row in sorted(rows, key=lambda item: item.timestamp):
        grouped.setdefault(row.timestamp.date(), []).append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _vwap(rows: Sequence[Bar]) -> float:
    volume = sum(row.volume for row in rows)
    return sum(((row.high + row.low + row.close) / 3) * row.volume for row in rows) / volume


def _trend(rows: Sequence[Bar], params: PullbackParameters) -> str | None:
    if len(rows) <= params.recent_lookback:
        return None
    current = rows[-1]
    session_move = current.close / rows[0].open - 1
    recent_move = current.close / rows[-params.recent_lookback - 1].close - 1
    threshold = float(params.min_session_move)
    vwap = _vwap(rows)
    if session_move >= threshold and recent_move > 0 and current.close > vwap:
        return "bullish"
    if session_move <= -threshold and recent_move < 0 and current.close < vwap:
        return "bearish"
    return None


def detect_pullback_resumption(
    bars_by_symbol: Mapping[str, Sequence[Bar]], params: PullbackParameters
) -> tuple[UnderlyingSignal, ...]:
    symbols = ("SPY", "QQQ", "IWM")
    if any(symbol not in bars_by_symbol for symbol in symbols):
        raise ValueError("SPY, QQQ, and IWM are required")
    grouped = {symbol: _group(bars_by_symbol[symbol]) for symbol in symbols}
    shared_sessions = set.intersection(*(set(grouped[symbol]) for symbol in symbols))
    output: list[UnderlyingSignal] = []
    for session in sorted(shared_sessions):
        common_timestamps = set.intersection(
            *(set(row.timestamp for row in grouped[symbol][session]) for symbol in symbols)
        )
        signaled: set[str] = set()
        for timestamp in sorted(common_timestamps):
            local = timestamp.astimezone(NEW_YORK)
            minute = local.hour * 60 + local.minute
            if not params.start_minute_new_york <= minute <= params.end_minute_new_york:
                continue
            histories = {
                symbol: tuple(
                    row for row in grouped[symbol][session] if row.timestamp <= timestamp
                )
                for symbol in symbols
            }
            directions = {symbol: _trend(histories[symbol], params) for symbol in symbols}
            for direction in ("bullish", "bearish"):
                matching = tuple(
                    symbol for symbol, value in directions.items() if value == direction
                )
                if len(matching) < params.min_confirmations:
                    continue
                for symbol in matching:
                    if symbol in signaled:
                        continue
                    rows = histories[symbol]
                    if len(rows) < params.recent_lookback + 1:
                        continue
                    previous, current = rows[-2:]
                    average_volume = sum(
                        row.volume for row in rows[-params.recent_lookback - 1 : -1]
                    ) / params.recent_lookback
                    volume_ok = current.volume >= average_volume * float(params.min_volume_ratio)
                    bullish_event = (
                        previous.close < previous.open
                        and current.close > current.open
                        and current.close > previous.high
                    )
                    bearish_event = (
                        previous.close > previous.open
                        and current.close < current.open
                        and current.close < previous.low
                    )
                    if not volume_ok or not (
                        (direction == "bullish" and bullish_event)
                        or (direction == "bearish" and bearish_event)
                    ):
                        continue
                    output.append(
                        UnderlyingSignal(
                            underlying=symbol,
                            signal=Signal(
                                direction=direction,
                                signal_bar_start=timestamp,
                                completed_at=timestamp + timedelta(minutes=5),
                                reference_price=Decimal(str(current.close)),
                                z_score=Decimal(0),
                            ),
                        )
                    )
                    signaled.add(symbol)
    return tuple(output)
