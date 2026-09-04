from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import (
    Bar,
    Costs,
    Fold,
    OptionPairBar,
    Signal,
)
from experiments.strategy_candidates.mean_reversion.gap_expansion import UnderlyingSignal


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class TrendParameters:
    signal_minute_new_york: int
    recent_lookback: int
    min_session_move: Decimal
    min_confirmations: int
    risk_fraction: Decimal
    target_r: Decimal
    max_holding_bars: int


@dataclass(frozen=True)
class BracketTrade:
    entry_at: datetime
    exit_at: datetime
    entry_debit: Decimal
    exit_credit: Decimal
    total_fees: Decimal
    risk_dollars: Decimal
    net_pnl: Decimal
    return_r: Decimal
    exit_reason: str
    operational_target_stop: Decimal


def _vwap(rows: Sequence[Bar]) -> float:
    total_volume = sum(row.volume for row in rows)
    if total_volume <= 0:
        raise ValueError("VWAP requires positive volume")
    return sum(
        ((row.high + row.low + row.close) / 3) * row.volume for row in rows
    ) / total_volume


def _direction(rows: Sequence[Bar], params: TrendParameters) -> str | None:
    if len(rows) <= params.recent_lookback:
        return None
    current = rows[-1]
    session_move = current.close / rows[0].open - 1
    recent_move = current.close / rows[-params.recent_lookback - 1].close - 1
    session_vwap = _vwap(rows)
    threshold = float(params.min_session_move)
    if session_move >= threshold and recent_move > 0 and current.close > session_vwap:
        return "bullish"
    if session_move <= -threshold and recent_move < 0 and current.close < session_vwap:
        return "bearish"
    return None


def detect_cross_index_trend(
    bars_by_symbol: Mapping[str, Sequence[Bar]], params: TrendParameters
) -> tuple[Signal, ...]:
    required = ("SPY", "QQQ", "IWM")
    if any(symbol not in bars_by_symbol for symbol in required):
        raise ValueError("SPY, QQQ, and IWM bars are required")
    by_symbol_and_session: dict[str, dict[date, list[Bar]]] = {}
    for symbol in required:
        sessions: dict[date, list[Bar]] = {}
        for row in sorted(bars_by_symbol[symbol], key=lambda item: item.timestamp):
            sessions.setdefault(row.timestamp.date(), []).append(row)
        by_symbol_and_session[symbol] = sessions

    shared_sessions = set.intersection(
        *(set(by_symbol_and_session[symbol]) for symbol in required)
    )
    signals: list[Signal] = []
    for session in sorted(shared_sessions):
        spy_rows = by_symbol_and_session["SPY"][session]
        targets = [
            row.timestamp
            for row in spy_rows
            if row.timestamp.astimezone(NEW_YORK).hour * 60
            + row.timestamp.astimezone(NEW_YORK).minute
            == params.signal_minute_new_york
        ]
        if not targets:
            continue
        target = targets[0]
        histories: dict[str, tuple[Bar, ...]] = {}
        aligned = True
        for symbol in required:
            history = tuple(
                row
                for row in by_symbol_and_session[symbol][session]
                if row.timestamp <= target
            )
            if not history or history[-1].timestamp != target:
                aligned = False
                break
            histories[symbol] = history
        if not aligned:
            continue
        directions = {symbol: _direction(histories[symbol], params) for symbol in required}
        spy_direction = directions["SPY"]
        if spy_direction is None:
            continue
        confirmations = sum(value == spy_direction for value in directions.values())
        if confirmations < params.min_confirmations:
            continue
        current = histories["SPY"][-1]
        signals.append(
            Signal(
                direction=spy_direction,
                signal_bar_start=target,
                completed_at=target + timedelta(minutes=5),
                reference_price=Decimal(str(current.close)),
                z_score=Decimal(0),
            )
        )
    return tuple(signals)


def detect_cross_index_underlying_trend(
    bars_by_symbol: Mapping[str, Sequence[Bar]], params: TrendParameters
) -> tuple[UnderlyingSignal, ...]:
    required = ("SPY", "QQQ", "IWM")
    if any(symbol not in bars_by_symbol for symbol in required):
        raise ValueError("SPY, QQQ, and IWM bars are required")
    grouped: dict[str, dict[date, list[Bar]]] = {}
    for symbol in required:
        sessions: dict[date, list[Bar]] = {}
        for row in sorted(bars_by_symbol[symbol], key=lambda item: item.timestamp):
            sessions.setdefault(row.timestamp.date(), []).append(row)
        grouped[symbol] = sessions
    shared = set.intersection(*(set(grouped[symbol]) for symbol in required))
    output: list[UnderlyingSignal] = []
    for session in sorted(shared):
        targets = [
            row.timestamp
            for row in grouped["SPY"][session]
            if row.timestamp.astimezone(NEW_YORK).hour * 60
            + row.timestamp.astimezone(NEW_YORK).minute
            == params.signal_minute_new_york
        ]
        if not targets:
            continue
        target = targets[0]
        histories = {
            symbol: tuple(row for row in grouped[symbol][session] if row.timestamp <= target)
            for symbol in required
        }
        if any(not rows or rows[-1].timestamp != target for rows in histories.values()):
            continue
        directions = {symbol: _direction(histories[symbol], params) for symbol in required}
        for direction in ("bullish", "bearish"):
            matching = tuple(
                symbol for symbol, value in directions.items() if value == direction
            )
            if len(matching) < params.min_confirmations:
                continue
            for symbol in matching:
                current = histories[symbol][-1]
                output.append(
                    UnderlyingSignal(
                        underlying=symbol,
                        signal=Signal(
                            direction=direction,
                            signal_bar_start=target,
                            completed_at=target + timedelta(minutes=5),
                            reference_price=Decimal(str(current.close)),
                            z_score=Decimal(0),
                        ),
                    )
                )
    return tuple(output)


def make_rolling_folds(
    sessions: Sequence[date],
    train_size: int,
    embargo: int,
    test_size: int,
    step: int,
) -> tuple[Fold, ...]:
    if min(train_size, test_size, step) < 1 or embargo < 0:
        raise ValueError("invalid rolling-fold dimensions")
    ordered = tuple(sorted(set(sessions)))
    folds: list[Fold] = []
    train_start = 0
    while train_start + train_size + embargo + test_size <= len(ordered):
        train_end = train_start + train_size
        test_start = train_end + embargo
        test_end = test_start + test_size
        folds.append(
            Fold(
                train=ordered[train_start:train_end],
                embargo=ordered[train_end:test_start],
                test=ordered[test_start:test_end],
            )
        )
        train_start += step
    return tuple(folds)


def bracket_round_trip(
    completed_at: datetime,
    rows: Sequence[OptionPairBar],
    costs: Costs,
    risk_fraction: Decimal,
    target_r: Decimal,
    max_holding_bars: int,
    bar_minutes: int = 5,
) -> BracketTrade:
    if risk_fraction <= 0 or target_r < 3 or max_holding_bars < 1 or bar_minutes < 1:
        raise ValueError("bracket requires positive risk, target >= 3R, and holding bars")
    eligible = tuple(
        sorted((row for row in rows if row.timestamp >= completed_at), key=lambda row: row.timestamp)
    )
    if len(eligible) < 2:
        raise ValueError("insufficient synchronized option bars")
    slip = costs.slippage_per_leg
    entry_row = eligible[0]
    entry_debit = entry_row.long_close + slip - (entry_row.short_close - slip)
    if entry_debit <= 0 or entry_debit >= Decimal("5"):
        raise ValueError("invalid debit-spread entry")
    total_fees = costs.fee_per_contract * Decimal(4)
    risk_dollars = entry_debit * Decimal(100) * risk_fraction
    target_credit = entry_debit + (
        total_fees + target_r * risk_dollars
    ) / Decimal(100)
    stop_credit = entry_debit + (total_fees - risk_dollars) / Decimal(100)

    exit_row = eligible[min(max_holding_bars, len(eligible) - 1)]
    exit_credit = exit_row.long_close - slip - (exit_row.short_close + slip)
    exit_reason = "timeout"
    for candidate in eligible[1 : max_holding_bars + 1]:
        candidate_credit = candidate.long_close - slip - (candidate.short_close + slip)
        if candidate_credit >= target_credit:
            exit_row = candidate
            exit_credit = target_credit
            exit_reason = "target"
            break
        if candidate_credit <= stop_credit:
            exit_row = candidate
            exit_credit = candidate_credit
            exit_reason = "stop"
            break

    net_pnl = (exit_credit - entry_debit) * Decimal(100) - total_fees
    return BracketTrade(
        entry_at=entry_row.timestamp + timedelta(minutes=bar_minutes),
        exit_at=exit_row.timestamp + timedelta(minutes=bar_minutes),
        entry_debit=entry_debit.quantize(Decimal("0.01")),
        exit_credit=exit_credit.quantize(Decimal("0.01")),
        total_fees=total_fees.quantize(Decimal("0.01")),
        risk_dollars=risk_dollars.quantize(Decimal("0.01")),
        net_pnl=net_pnl.quantize(Decimal("0.01")),
        return_r=(net_pnl / risk_dollars).quantize(Decimal("0.0001")),
        exit_reason=exit_reason,
        operational_target_stop=target_r,
    )


def performance(pnl: Sequence[Decimal]) -> dict[str, Any]:
    if not pnl:
        return {
            "sample_size": 0,
            "net_pnl": Decimal(0),
            "hit_rate": Decimal(0),
            "gross_profit": Decimal(0),
            "gross_loss": Decimal(0),
            "profit_factor": None,
            "max_drawdown": Decimal(0),
        }
    gross_profit = sum((value for value in pnl if value > 0), Decimal(0))
    gross_loss = -sum((value for value in pnl if value < 0), Decimal(0))
    equity = peak = drawdown = Decimal(0)
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "sample_size": len(pnl),
        "net_pnl": sum(pnl, Decimal(0)),
        "hit_rate": Decimal(sum(value > 0 for value in pnl)) / len(pnl),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown": drawdown,
    }
