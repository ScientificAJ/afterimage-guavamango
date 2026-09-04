from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import sqrt
from typing import Any, Sequence
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Parameters:
    lookback: int
    z_threshold: Decimal
    min_wick_fraction: Decimal
    earliest_signal_minute_from_open: int = 0
    latest_signal_minute_from_open: int = 390
    require_directional_body: bool = False
    min_volume_ratio: Decimal = Decimal("0")
    max_close_distance_z: Decimal = Decimal("999")


@dataclass(frozen=True)
class Signal:
    direction: str
    signal_bar_start: datetime
    completed_at: datetime
    reference_price: Decimal
    z_score: Decimal


@dataclass(frozen=True)
class Fold:
    train: tuple[date, ...]
    embargo: tuple[date, ...]
    test: tuple[date, ...]


@dataclass(frozen=True)
class OptionPairBar:
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
class Costs:
    slippage_per_leg: Decimal
    fee_per_contract: Decimal


@dataclass(frozen=True)
class OptionTrade:
    entry_at: datetime
    exit_at: datetime
    entry_debit: Decimal
    exit_credit: Decimal
    total_fees: Decimal
    net_pnl: Decimal
    return_r: Decimal


@dataclass(frozen=True)
class Statistics:
    sample_size: int
    net_pnl: Decimal
    expectancy_r: Decimal
    hit_rate: Decimal
    max_drawdown: Decimal


def detect_signals(bars: Sequence[Bar], params: Parameters) -> tuple[Signal, ...]:
    ordered = sorted(bars, key=lambda item: item.timestamp)
    signals: list[Signal] = []
    signaled_dates: set[date] = set()
    for index in range(params.lookback, len(ordered)):
        current = ordered[index]
        if current.timestamp.date() in signaled_dates:
            continue
        local = current.timestamp.astimezone(NEW_YORK)
        minute_from_open = local.hour * 60 + local.minute - (9 * 60 + 30)
        if not (
            params.earliest_signal_minute_from_open
            <= minute_from_open
            <= params.latest_signal_minute_from_open
        ):
            continue
        window = ordered[index - params.lookback : index]
        if any(item.timestamp.date() != current.timestamp.date() for item in window):
            continue
        closes = [item.close for item in window]
        mean = sum(closes) / len(closes)
        variance = sum((value - mean) ** 2 for value in closes) / len(closes)
        deviation = sqrt(variance)
        if deviation <= 0 or current.high <= current.low:
            continue
        average_volume = sum(item.volume for item in window) / len(window)
        if average_volume <= 0:
            continue
        lower = mean - float(params.z_threshold) * deviation
        upper = mean + float(params.z_threshold) * deviation
        close_z = (current.close - mean) / deviation
        lower_wick = (min(current.open, current.close) - current.low) / (
            current.high - current.low
        )
        upper_wick = (current.high - max(current.open, current.close)) / (
            current.high - current.low
        )
        bullish = (
            current.low < lower
            and current.close >= lower
            and lower_wick >= float(params.min_wick_fraction)
            and (
                not params.require_directional_body or current.close > current.open
            )
            and current.volume / average_volume >= float(params.min_volume_ratio)
            and close_z >= -float(params.max_close_distance_z)
        )
        bearish = (
            current.high > upper
            and current.close <= upper
            and upper_wick >= float(params.min_wick_fraction)
            and (
                not params.require_directional_body or current.close < current.open
            )
            and current.volume / average_volume >= float(params.min_volume_ratio)
            and close_z <= float(params.max_close_distance_z)
        )
        if bullish == bearish:
            continue
        excursion = (current.low - mean) / deviation if bullish else (current.high - mean) / deviation
        signals.append(
            Signal(
                direction="bullish" if bullish else "bearish",
                signal_bar_start=current.timestamp,
                completed_at=current.timestamp + timedelta(minutes=5),
                reference_price=Decimal(str(current.close)),
                z_score=Decimal(str(excursion)),
            )
        )
        signaled_dates.add(current.timestamp.date())
    return tuple(signals)


def make_walk_forward_folds(
    sessions: Sequence[date], min_train: int, test_size: int, embargo: int
) -> tuple[Fold, ...]:
    if min_train < 1 or test_size < 1 or embargo < 0:
        raise ValueError("invalid walk-forward dimensions")
    ordered = tuple(sorted(set(sessions)))
    folds: list[Fold] = []
    train_end = min_train
    while train_end + embargo + test_size <= len(ordered):
        test_start = train_end + embargo
        test_end = test_start + test_size
        folds.append(
            Fold(
                train=ordered[:train_end],
                embargo=ordered[train_end:test_start],
                test=ordered[test_start:test_end],
            )
        )
        train_end = test_end
    return tuple(folds)


def conservative_round_trip(
    completed_at: datetime,
    rows: Sequence[OptionPairBar],
    costs: Costs,
    max_holding_bars: int,
    fill_model: str = "bar_extremes",
) -> OptionTrade:
    if max_holding_bars < 1:
        raise ValueError("max_holding_bars must be positive")
    eligible = tuple(
        sorted((row for row in rows if row.timestamp >= completed_at), key=lambda x: x.timestamp)
    )
    if len(eligible) <= max_holding_bars:
        raise ValueError("insufficient paired option bars")
    entry = eligible[0]
    exit_bar = eligible[max_holding_bars]
    slip = costs.slippage_per_leg
    if fill_model == "bar_extremes":
        entry_debit = entry.long_high + slip - (entry.short_low - slip)
        exit_credit = exit_bar.long_low - slip - (exit_bar.short_high + slip)
        entry_at = entry.timestamp
        exit_at = exit_bar.timestamp
    elif fill_model == "next_bar_close":
        entry_debit = entry.long_close + slip - (entry.short_close - slip)
        exit_credit = exit_bar.long_close - slip - (exit_bar.short_close + slip)
        entry_at = entry.timestamp + timedelta(minutes=5)
        exit_at = exit_bar.timestamp + timedelta(minutes=5)
    else:
        raise ValueError("unknown fill model")
    total_fees = costs.fee_per_contract * Decimal(4)
    net_pnl = (exit_credit - entry_debit) * Decimal(100) - total_fees
    capital_at_risk = entry_debit * Decimal(100) + costs.fee_per_contract * Decimal(2)
    return OptionTrade(
        entry_at=entry_at,
        exit_at=exit_at,
        entry_debit=entry_debit.quantize(Decimal("0.01")),
        exit_credit=exit_credit.quantize(Decimal("0.01")),
        total_fees=total_fees.quantize(Decimal("0.01")),
        net_pnl=net_pnl.quantize(Decimal("0.01")),
        return_r=(net_pnl / capital_at_risk) if capital_at_risk > 0 else Decimal(0),
    )


def summarize(pnl_dollars: Sequence[Decimal], returns_r: Sequence[Decimal]) -> Statistics:
    if len(pnl_dollars) != len(returns_r):
        raise ValueError("P&L and R series must have equal length")
    sample_size = len(pnl_dollars)
    if sample_size == 0:
        return Statistics(0, Decimal(0), Decimal(0), Decimal(0), Decimal(0))
    equity = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for pnl in pnl_dollars:
        equity += pnl
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    return Statistics(
        sample_size=sample_size,
        net_pnl=sum(pnl_dollars, Decimal(0)),
        expectancy_r=sum(returns_r, Decimal(0)) / sample_size,
        hit_rate=Decimal(sum(1 for pnl in pnl_dollars if pnl > 0)) / sample_size,
        max_drawdown=maximum_drawdown,
    )


def build_dry_run_order(
    direction: str,
    long_symbol: str,
    short_symbol: str,
    limit_price: Decimal,
    client_order_id: str,
) -> dict[str, Any]:
    if direction not in {"bullish", "bearish"}:
        raise ValueError("direction must be bullish or bearish")
    payload = {
        "qty": "1",
        "type": "limit",
        "limit_price": str(limit_price),
        "time_in_force": "day",
        "order_class": "mleg",
        "client_order_id": client_order_id,
        "legs": [
            {
                "symbol": long_symbol,
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": short_symbol,
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ],
    }
    legs = json.dumps(payload["legs"], separators=(",", ":"))
    return {
        "submission_allowed": False,
        "payload": payload,
        "cli_arguments": [
            "order",
            "submit",
            "--qty",
            "1",
            "--type",
            "limit",
            "--limit-price",
            str(limit_price),
            "--time-in-force",
            "day",
            "--order-class",
            "mleg",
            "--client-order-id",
            client_order_id,
            "--legs",
            legs,
            "--quiet",
            "--dry-run",
        ],
    }
