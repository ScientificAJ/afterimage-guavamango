"""Multi-day cross-sectional ETF momentum with causal daily-bar execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal, Sequence

try:
    from .candidate import CENT, ET, DataExclusion
except ImportError:
    from candidate import CENT, ET, DataExclusion  # type: ignore[no-redef]


TRADE_UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    session: date
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class RotationVariant:
    name: str
    momentum_lookback: int
    atr_multiplier: Decimal
    hold_sessions: int


VARIANTS = (
    RotationVariant("md_rs20_a50_h05", 20, Decimal("0.50"), 5),
    RotationVariant("md_rs20_a75_h05", 20, Decimal("0.75"), 5),
    RotationVariant("md_rs40_a50_h05", 40, Decimal("0.50"), 5),
    RotationVariant("md_rs40_a75_h05", 40, Decimal("0.75"), 5),
)


@dataclass(frozen=True)
class RotationSignal:
    session: date
    direction: Literal["bullish", "bearish"]
    underlying: str
    atr: Decimal
    variant: str
    regime: Literal["risk_on", "risk_off"]
    dispersion: Decimal


@dataclass(frozen=True)
class MultiDayCosts:
    slippage_fraction: Decimal = Decimal("0.0001")
    fee_per_share_per_side: Decimal = Decimal("0.005")


@dataclass(frozen=True)
class MultiDayTrade:
    session: date
    variant: str
    direction: str
    underlying: str
    regime: str
    entry_at: datetime
    exit_at: datetime
    shares: int
    raw_entry: Decimal
    entry_fill: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_fill: Decimal
    net_pnl: Decimal
    return_r: Decimal
    outcome: Literal["target", "stop", "time"]
    modeled_fees: Decimal
    modeled_slippage: Decimal
    target_to_stop: Decimal


def _series(bars: Sequence[DailyBar], symbol: str, session: date) -> list[DailyBar]:
    return sorted(
        (bar for bar in bars if bar.symbol == symbol and bar.session <= session),
        key=lambda item: item.session,
    )


def _atr(rows: Sequence[DailyBar], length: int = 14) -> Decimal:
    if len(rows) < length + 1:
        raise DataExclusion("INSUFFICIENT_ATR_HISTORY")
    values = []
    for index in range(len(rows) - length, len(rows)):
        current = rows[index]
        previous = rows[index - 1]
        values.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    value = sum(values, Decimal(0)) / Decimal(length)
    if value <= 0:
        raise DataExclusion("NON_POSITIVE_ATR")
    return value


def rotation_signal(
    variant: RotationVariant, bars: Sequence[DailyBar], session: date
) -> RotationSignal | None:
    all_symbols = ("SPY", *TRADE_UNIVERSE)
    history = {symbol: _series(bars, symbol, session) for symbol in all_symbols}
    minimum = max(51, variant.momentum_lookback + 1)
    if any(len(rows) < minimum or rows[-1].session != session for rows in history.values()):
        raise DataExclusion("INCOMPLETE_DAILY_HISTORY")
    returns = {
        symbol: history[symbol][-1].close / history[symbol][-variant.momentum_lookback - 1].close - Decimal(1)
        for symbol in TRADE_UNIVERSE
    }
    spy = history["SPY"]
    sma50 = sum((row.close for row in spy[-50:]), Decimal(0)) / Decimal(50)
    rising = spy[-1].close > spy[-11].close
    positive = sum(value > 0 for value in returns.values())
    negative = sum(value < 0 for value in returns.values())
    if spy[-1].close > sma50 and rising and positive >= 5:
        direction: Literal["bullish", "bearish"] = "bullish"
        regime: Literal["risk_on", "risk_off"] = "risk_on"
        underlying = sorted(TRADE_UNIVERSE, key=lambda symbol: (-returns[symbol], symbol))[0]
    elif spy[-1].close < sma50 and not rising and negative >= 5:
        direction = "bearish"
        regime = "risk_off"
        underlying = sorted(TRADE_UNIVERSE, key=lambda symbol: (returns[symbol], symbol))[0]
    else:
        return None
    dispersion = max(returns.values()) - min(returns.values())
    if dispersion < Decimal("0.02"):
        return None
    return RotationSignal(
        session=session,
        direction=direction,
        underlying=underlying,
        atr=_atr(history[underlying]),
        variant=variant.name,
        regime=regime,
        dispersion=dispersion,
    )


def _exit_fill(direction: str, raw_price: Decimal, costs: MultiDayCosts) -> Decimal:
    return raw_price * (
        Decimal(1) - costs.slippage_fraction
        if direction == "bullish"
        else Decimal(1) + costs.slippage_fraction
    )


def _bracket(
    direction: str,
    raw_entry: Decimal,
    shares: int,
    stop_distance: Decimal,
    costs: MultiDayCosts,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    if raw_entry <= 0 or shares < 1 or stop_distance <= 0:
        raise DataExclusion("INVALID_MULTIDAY_BRACKET_INPUT")
    fees = costs.fee_per_share_per_side * Decimal(shares) * Decimal(2)
    if direction == "bullish":
        entry_fill = raw_entry * (Decimal(1) + costs.slippage_fraction)
        stop = (raw_entry - stop_distance).quantize(CENT, rounding=ROUND_HALF_UP)
        if stop <= 0:
            raise DataExclusion("NON_POSITIVE_STOP")
        stop_net = (_exit_fill(direction, stop, costs) - entry_fill) * shares - fees
        risk = abs(stop_net)
        raw_target = (entry_fill + (risk * Decimal(3) + fees) / shares) / (Decimal(1) - costs.slippage_fraction)
        target = raw_target.quantize(CENT, rounding=ROUND_CEILING)
        target_net = (_exit_fill(direction, target, costs) - entry_fill) * shares - fees
    elif direction == "bearish":
        entry_fill = raw_entry * (Decimal(1) - costs.slippage_fraction)
        stop = (raw_entry + stop_distance).quantize(CENT, rounding=ROUND_HALF_UP)
        stop_net = (entry_fill - _exit_fill(direction, stop, costs)) * shares - fees
        risk = abs(stop_net)
        raw_target = (entry_fill - (risk * Decimal(3) + fees) / shares) / (Decimal(1) + costs.slippage_fraction)
        target = raw_target.quantize(CENT, rounding=ROUND_FLOOR)
        if target <= 0:
            raise DataExclusion("NON_POSITIVE_TARGET")
        target_net = (entry_fill - _exit_fill(direction, target, costs)) * shares - fees
    else:
        raise DataExclusion("UNKNOWN_DIRECTION")
    if stop_net >= 0 or risk <= 0 or target_net / risk < Decimal(3):
        raise DataExclusion("NET_THREE_R_BRACKET_NOT_ACHIEVED")
    return entry_fill, stop, target, risk, target_net / risk


def simulate_multiday_trade(
    signal: RotationSignal,
    bars: Sequence[DailyBar],
    variant: RotationVariant,
    costs: MultiDayCosts = MultiDayCosts(),
    *,
    notional: Decimal = Decimal("10000"),
) -> MultiDayTrade:
    ordered = sorted(
        (bar for bar in bars if bar.symbol == signal.underlying and bar.session > signal.session),
        key=lambda item: item.session,
    )
    if len(ordered) < variant.hold_sessions:
        raise DataExclusion("INSUFFICIENT_FUTURE_DAILY_BARS")
    entry = ordered[0]
    provisional = entry.open * (
        Decimal(1) + costs.slippage_fraction
        if signal.direction == "bullish"
        else Decimal(1) - costs.slippage_fraction
    )
    shares = int(notional // provisional)
    entry_fill, stop, target, risk, target_to_stop = _bracket(
        signal.direction,
        entry.open,
        shares,
        signal.atr * variant.atr_multiplier,
        costs,
    )
    selected = ordered[variant.hold_sessions - 1]
    raw_exit = selected.close
    outcome: Literal["target", "stop", "time"] = "time"
    for bar in ordered[: variant.hold_sessions]:
        if signal.direction == "bullish":
            if bar.low <= stop:
                selected, raw_exit, outcome = bar, stop, "stop"
                break
            if bar.high >= target:
                selected, raw_exit, outcome = bar, target, "target"
                break
        else:
            if bar.high >= stop:
                selected, raw_exit, outcome = bar, stop, "stop"
                break
            if bar.low <= target:
                selected, raw_exit, outcome = bar, target, "target"
                break
    exit_fill = _exit_fill(signal.direction, raw_exit, costs)
    fees = (costs.fee_per_share_per_side * Decimal(shares) * Decimal(2)).quantize(CENT)
    gross = (
        (exit_fill - entry_fill) * shares
        if signal.direction == "bullish"
        else (entry_fill - exit_fill) * shares
    )
    net = (gross - fees).quantize(CENT)
    slippage = (entry.open * costs.slippage_fraction * shares + raw_exit * costs.slippage_fraction * shares).quantize(CENT)
    return MultiDayTrade(
        session=signal.session,
        variant=variant.name,
        direction=signal.direction,
        underlying=signal.underlying,
        regime=signal.regime,
        entry_at=datetime.combine(entry.session, time(9, 30), ET),
        exit_at=selected.timestamp,
        shares=shares,
        raw_entry=entry.open,
        entry_fill=entry_fill,
        stop_price=stop,
        target_price=target,
        exit_fill=exit_fill,
        net_pnl=net,
        return_r=net / risk,
        outcome=outcome,
        modeled_fees=fees,
        modeled_slippage=slippage,
        target_to_stop=target_to_stop,
    )
