from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PairParameters:
    signal_minute_new_york: int
    min_divergence: Decimal


@dataclass(frozen=True)
class PairSignal:
    session: date
    signal_at: datetime
    completed_at: datetime
    leader: str
    laggard: str
    divergence: Decimal


@dataclass(frozen=True)
class PairBar:
    timestamp: datetime
    long_open: Decimal
    long_high: Decimal
    long_low: Decimal
    long_close: Decimal
    short_open: Decimal
    short_high: Decimal
    short_low: Decimal
    short_close: Decimal


@dataclass(frozen=True)
class PairCosts:
    slippage_bps: Decimal
    fee_per_share: Decimal


@dataclass(frozen=True)
class PairTrade:
    entry_at: datetime
    exit_at: datetime
    long_quantity: int
    short_quantity: int
    long_entry_price: Decimal
    short_entry_price: Decimal
    risk_dollars: Decimal
    net_pnl: Decimal
    return_r: Decimal
    exit_reason: str
    operational_target_stop: Decimal


def _group(rows: Sequence[Bar]) -> dict[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = {}
    for row in sorted(rows, key=lambda item: item.timestamp):
        grouped.setdefault(row.timestamp.date(), []).append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def detect_relative_divergence(
    bars_by_symbol: Mapping[str, Sequence[Bar]], params: PairParameters
) -> tuple[PairSignal, ...]:
    symbols = ("SPY", "QQQ", "IWM")
    grouped = {symbol: _group(bars_by_symbol[symbol]) for symbol in symbols}
    shared = set.intersection(*(set(grouped[symbol]) for symbol in symbols))
    output = []
    for session in sorted(shared):
        target_rows = {}
        for symbol in symbols:
            target = next(
                (
                    row
                    for row in grouped[symbol][session]
                    if row.timestamp.astimezone(NEW_YORK).hour * 60
                    + row.timestamp.astimezone(NEW_YORK).minute
                    == params.signal_minute_new_york
                ),
                None,
            )
            if target is None:
                break
            target_rows[symbol] = target
        if len(target_rows) != len(symbols):
            continue
        returns = {
            symbol: target_rows[symbol].close / grouped[symbol][session][0].open - 1
            for symbol in symbols
        }
        leader = max(symbols, key=lambda symbol: (returns[symbol], symbol))
        laggard = min(symbols, key=lambda symbol: (returns[symbol], symbol))
        divergence = Decimal(str(returns[leader] - returns[laggard]))
        if divergence < params.min_divergence:
            continue
        timestamp = target_rows[leader].timestamp
        output.append(
            PairSignal(
                session=session,
                signal_at=timestamp,
                completed_at=timestamp + timedelta(minutes=5),
                leader=leader,
                laggard=laggard,
                divergence=divergence,
            )
        )
    return tuple(output)


def pair_bracket(
    completed_at: datetime,
    rows: Sequence[PairBar],
    costs: PairCosts,
    notional_per_leg: Decimal,
    risk_dollars: Decimal,
    target_r: Decimal,
    max_holding_bars: int,
) -> PairTrade:
    if min(notional_per_leg, risk_dollars) <= 0 or target_r < 3 or max_holding_bars < 1:
        raise ValueError("invalid pair bracket")
    eligible = tuple(
        sorted((row for row in rows if row.timestamp >= completed_at), key=lambda row: row.timestamp)
    )
    if len(eligible) < 2:
        raise ValueError("insufficient aligned pair bars")
    slip = costs.slippage_bps / Decimal(10_000)
    entry = eligible[0]
    long_entry_raw = Decimal(str(entry.long_close))
    short_entry_raw = Decimal(str(entry.short_close))
    long_quantity = int(notional_per_leg / long_entry_raw)
    short_quantity = int(notional_per_leg / short_entry_raw)
    if min(long_quantity, short_quantity) < 1:
        raise ValueError("notional too small")
    long_entry = long_entry_raw * (Decimal(1) + slip)
    short_entry = short_entry_raw * (Decimal(1) - slip)
    fees = costs.fee_per_share * (long_quantity + short_quantity) * Decimal(2)

    def pnl(long_exit_raw: Decimal, short_exit_raw: Decimal) -> Decimal:
        long_exit = long_exit_raw * (Decimal(1) - slip)
        short_exit = short_exit_raw * (Decimal(1) + slip)
        return (
            (long_exit - long_entry) * long_quantity
            + (short_entry - short_exit) * short_quantity
            - fees
        )

    exit_row = eligible[min(max_holding_bars, len(eligible) - 1)]
    net_pnl = pnl(Decimal(str(exit_row.long_close)), Decimal(str(exit_row.short_close)))
    reason = "timeout"
    for candidate in eligible[1 : max_holding_bars + 1]:
        completed_pnl = pnl(
            Decimal(str(candidate.long_close)), Decimal(str(candidate.short_close))
        )
        if completed_pnl <= -risk_dollars:
            exit_row = candidate
            net_pnl = completed_pnl
            reason = "stop"
            break
        if completed_pnl >= target_r * risk_dollars:
            exit_row = candidate
            net_pnl = target_r * risk_dollars
            reason = "target"
            break
    return PairTrade(
        entry_at=entry.timestamp + timedelta(minutes=5),
        exit_at=exit_row.timestamp + timedelta(minutes=5),
        long_quantity=long_quantity,
        short_quantity=short_quantity,
        long_entry_price=long_entry.quantize(Decimal("0.01")),
        short_entry_price=short_entry.quantize(Decimal("0.01")),
        risk_dollars=risk_dollars,
        net_pnl=net_pnl.quantize(Decimal("0.01")),
        return_r=(net_pnl / risk_dollars).quantize(Decimal("0.0001")),
        exit_reason=reason,
        operational_target_stop=target_r,
    )
