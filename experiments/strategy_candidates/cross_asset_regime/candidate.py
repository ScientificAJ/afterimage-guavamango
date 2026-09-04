"""Pure cross-asset breadth signal and conservative option-spread research logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Mapping, Sequence
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
CENT = Decimal("0.01")
MULTIPLIER = Decimal(100)
UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")
ROTATION_UNDERLYINGS = ("QQQ", "IWM")
MINIMUM_MEAN_MOVE = Decimal("0.0010")


class DataExclusion(ValueError):
    """A stable reason why an observation cannot be evaluated."""


@dataclass(frozen=True)
class Variant:
    name: str
    breadth_required: int
    require_spy_regime: bool
    hold_bars: int
    exit_mode: Literal["fixed", "target_stop_3r"] = "fixed"


VARIANTS = (
    Variant("b5_plain_h07", 5, False, 7),
    Variant("b5_plain_h21", 5, False, 21),
    Variant("b6_spy10_h07", 6, True, 7),
    Variant("b6_spy10_h21", 6, True, 21),
    Variant("b5_plain_h07_3r", 5, False, 7, "target_stop_3r"),
    Variant("b5_plain_h21_3r", 5, False, 21, "target_stop_3r"),
    Variant("b6_spy10_h07_3r", 6, True, 7, "target_stop_3r"),
    Variant("b6_spy10_h21_3r", 6, True, 21, "target_stop_3r"),
)


@dataclass(frozen=True)
class StockBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Signal:
    session: date
    completed_at: datetime
    direction: Literal["bullish", "bearish"]
    underlying: Literal["QQQ", "IWM"]
    reference_price: Decimal
    breadth_count: int
    mean_return: Decimal
    variant: str


@dataclass(frozen=True)
class Contract:
    symbol: str
    underlying: str
    expiration: date
    strike: Decimal
    option_type: Literal["call", "put"]


@dataclass(frozen=True)
class Vertical:
    long: Contract
    short: Contract
    width: Decimal


@dataclass(frozen=True)
class OptionBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        if not self.symbol or self.timestamp.tzinfo is None:
            raise DataExclusion("OPTION_BAR_IDENTITY_INVALID")
        prices = (self.open, self.high, self.low, self.close)
        if any(not value.is_finite() or value < 0 for value in prices):
            raise DataExclusion("OPTION_BAR_PRICE_INVALID")
        if self.high < max(prices) or self.low > min(prices):
            raise DataExclusion("OPTION_BAR_OHLC_INVALID")
        if self.volume < 0:
            raise DataExclusion("OPTION_BAR_VOLUME_INVALID")


@dataclass(frozen=True)
class OptionFrame:
    timestamp: datetime
    long: OptionBar
    short: OptionBar

    def __post_init__(self) -> None:
        if self.timestamp != self.long.timestamp or self.timestamp != self.short.timestamp:
            raise DataExclusion("LEG_TIMESTAMP_MISMATCH")
        if self.long.symbol == self.short.symbol:
            raise DataExclusion("DUPLICATE_LEG_SYMBOL")


@dataclass(frozen=True)
class Costs:
    slippage_per_leg: Decimal = Decimal("0.03")
    fee_per_contract: Decimal = Decimal("0.65")


@dataclass(frozen=True)
class Trade:
    session: date
    variant: str
    direction: str
    underlying: str
    long_symbol: str
    short_symbol: str
    entry_at: datetime
    exit_at: datetime
    entry_debit: Decimal
    exit_credit: Decimal
    net_pnl: Decimal
    return_r: Decimal
    modeled_fees: Decimal
    modeled_slippage: Decimal
    outcome: Literal["target", "stop", "time"] = "time"


@dataclass(frozen=True)
class ScoredTrade:
    session: date
    return_r: Decimal
    net_pnl: Decimal


@dataclass(frozen=True)
class Metrics:
    sample_count: int
    wins: int
    losses: int
    flats: int
    hit_rate: Decimal
    net_pnl: Decimal
    profit_factor: Decimal
    expectancy_r: Decimal
    max_drawdown: Decimal
    sample_stddev_r: Decimal
    mean_ci95_lower_r: Decimal
    mean_ci95_upper_r: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _session_points(
    bars: Sequence[StockBar], session: date
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    opens: dict[str, Decimal] = {}
    closes: dict[str, Decimal] = {}
    for bar in bars:
        local = bar.timestamp.astimezone(ET)
        if local.date() != session or bar.symbol not in UNIVERSE:
            continue
        if local.time() == time(9, 30):
            opens[bar.symbol] = bar.open
        elif local.time() == time(10, 15):
            closes[bar.symbol] = bar.close
    if set(opens) != set(UNIVERSE) or set(closes) != set(UNIVERSE):
        raise DataExclusion("INCOMPLETE_SYNCHRONIZED_STOCK_BREADTH")
    if any(value <= 0 or not value.is_finite() for value in (*opens.values(), *closes.values())):
        raise DataExclusion("INVALID_STOCK_PRICE")
    return opens, closes


def _spy_regime(
    daily_closes: Sequence[tuple[date, Decimal]], session: date
) -> Literal["bullish", "bearish", "flat"]:
    eligible = [value for day, value in sorted(daily_closes) if day < session]
    if len(eligible) < 10:
        raise DataExclusion("INSUFFICIENT_LAGGED_SPY_HISTORY")
    window = eligible[-10:]
    average = sum(window, Decimal(0)) / Decimal(10)
    if window[-1] > average:
        return "bullish"
    if window[-1] < average:
        return "bearish"
    return "flat"


def signal_for_session(
    variant: Variant,
    bars: Sequence[StockBar],
    spy_daily_closes: Sequence[tuple[date, Decimal]],
    session: date,
) -> Signal | None:
    opens, closes = _session_points(bars, session)
    returns = {symbol: closes[symbol] / opens[symbol] - Decimal(1) for symbol in UNIVERSE}
    positive = sum(value > 0 for value in returns.values())
    negative = sum(value < 0 for value in returns.values())
    mean_return = sum(returns.values(), Decimal(0)) / Decimal(len(UNIVERSE))
    if positive >= variant.breadth_required and mean_return >= MINIMUM_MEAN_MOVE:
        direction: Literal["bullish", "bearish"] = "bullish"
        underlying = sorted(ROTATION_UNDERLYINGS, key=lambda symbol: (-returns[symbol], symbol))[0]
        breadth_count = positive
    elif negative >= variant.breadth_required and mean_return <= -MINIMUM_MEAN_MOVE:
        direction = "bearish"
        underlying = sorted(ROTATION_UNDERLYINGS, key=lambda symbol: (returns[symbol], symbol))[0]
        breadth_count = negative
    else:
        return None
    if variant.require_spy_regime and _spy_regime(spy_daily_closes, session) != direction:
        return None
    return Signal(
        session=session,
        completed_at=datetime.combine(session, time(10, 30), ET),
        direction=direction,
        underlying=underlying,  # type: ignore[arg-type]
        reference_price=closes[underlying],
        breadth_count=breadth_count,
        mean_return=mean_return,
        variant=variant.name,
    )


def select_vertical(signal: Signal, contracts: Sequence[Contract]) -> Vertical:
    option_type: Literal["call", "put"] = "call" if signal.direction == "bullish" else "put"
    eligible = [
        item
        for item in contracts
        if item.underlying == signal.underlying
        and item.option_type == option_type
        and 3 <= (item.expiration - signal.session).days <= 9
    ]
    if not eligible:
        raise DataExclusion("NO_ELIGIBLE_CONTRACTS")
    expiration = min(item.expiration for item in eligible)
    same_expiry = [item for item in eligible if item.expiration == expiration]
    for long_contract in sorted(
        same_expiry, key=lambda item: (abs(item.strike - signal.reference_price), item.strike, item.symbol)
    ):
        target = long_contract.strike + (Decimal(5) if option_type == "call" else Decimal(-5))
        matches = sorted(
            (item for item in same_expiry if item.strike == target), key=lambda item: item.symbol
        )
        if matches:
            short_contract = matches[0]
            return Vertical(long_contract, short_contract, abs(short_contract.strike - long_contract.strike))
    raise DataExclusion("NO_EXACT_FIVE_DOLLAR_VERTICAL")


def simulate_trade(
    signal: Signal,
    long_contract: Contract,
    short_contract: Contract,
    frames: Sequence[OptionFrame],
    *,
    hold_bars: int,
    costs: Costs = Costs(),
    exit_mode: Literal["fixed", "target_stop_3r"] = "fixed",
) -> Trade:
    if hold_bars < 1:
        raise ValueError("HOLD_BARS_MUST_BE_POSITIVE")
    ordered = tuple(
        sorted(
            (
                frame
                for frame in frames
                if frame.timestamp >= signal.completed_at
                and frame.long.symbol == long_contract.symbol
                and frame.short.symbol == short_contract.symbol
            ),
            key=lambda item: item.timestamp,
        )
    )
    if len(ordered) <= hold_bars:
        raise DataExclusion("INSUFFICIENT_SYNCHRONIZED_OPTION_BARS")
    entry = ordered[0]
    slippage = costs.slippage_per_leg * Decimal(2)
    entry_debit = _money(entry.long.high - entry.short.low + slippage)
    if entry_debit <= 0 or entry_debit >= Decimal(5):
        raise DataExclusion("INVALID_ADVERSE_ENTRY_DEBIT")
    exit_frame = ordered[hold_bars]
    exit_credit = _money(max(Decimal(0), exit_frame.long.low - exit_frame.short.high - slippage))
    outcome: Literal["target", "stop", "time"] = "time"
    if exit_mode == "target_stop_3r":
        stop_credit, target_credit = target_stop_levels(entry_debit, costs)
        if target_credit >= Decimal(5) - slippage:
            raise DataExclusion("THREE_R_TARGET_EXCEEDS_VERTICAL_CAP")
        for frame in ordered[1 : hold_bars + 1]:
            adverse_credit = _money(max(Decimal(0), frame.long.low - frame.short.high - slippage))
            if adverse_credit <= stop_credit:
                exit_frame = frame
                exit_credit = adverse_credit
                outcome = "stop"
                break
            if adverse_credit >= target_credit:
                exit_frame = frame
                exit_credit = target_credit
                outcome = "target"
                break
    elif exit_mode != "fixed":
        raise ValueError("UNKNOWN_EXIT_MODE")
    fees = _money(costs.fee_per_contract * Decimal(4))
    net_pnl = _money((exit_credit - entry_debit) * MULTIPLIER - fees)
    risk_dollars = entry_debit * MULTIPLIER + costs.fee_per_contract * Decimal(2)
    return Trade(
        session=signal.session,
        variant=signal.variant,
        direction=signal.direction,
        underlying=signal.underlying,
        long_symbol=long_contract.symbol,
        short_symbol=short_contract.symbol,
        entry_at=entry.timestamp,
        exit_at=exit_frame.timestamp,
        entry_debit=entry_debit,
        exit_credit=exit_credit,
        net_pnl=net_pnl,
        return_r=net_pnl / risk_dollars,
        modeled_fees=fees,
        modeled_slippage=_money(costs.slippage_per_leg * Decimal(4) * MULTIPLIER),
        outcome=outcome,
    )


def target_stop_levels(entry_debit: Decimal, costs: Costs = Costs()) -> tuple[Decimal, Decimal]:
    """Return nominal exit credits whose modeled net reward/risk is at least 3:1."""
    if entry_debit <= 0:
        raise ValueError("POSITIVE_ENTRY_DEBIT_REQUIRED")
    round_trip_fees = costs.fee_per_contract * Decimal(4)
    loss_budget = entry_debit * MULTIPLIER * Decimal("0.25")
    raw_stop = entry_debit + (-loss_budget + round_trip_fees) / MULTIPLIER
    stop_credit = max(Decimal(0), raw_stop.quantize(CENT, rounding=ROUND_CEILING))
    nominal_stop_net = (stop_credit - entry_debit) * MULTIPLIER - round_trip_fees
    if nominal_stop_net >= 0:
        raise DataExclusion("STOP_NOT_BELOW_BREAKEVEN")
    required_profit = abs(nominal_stop_net) * Decimal(3)
    raw_target = entry_debit + (required_profit + round_trip_fees) / MULTIPLIER
    target_credit = raw_target.quantize(CENT, rounding=ROUND_CEILING)
    return stop_credit, target_credit


def enforce_non_overlapping(trades: Sequence[Trade]) -> tuple[Trade, ...]:
    accepted: list[Trade] = []
    occupied_until: datetime | None = None
    for trade in sorted(trades, key=lambda item: (item.entry_at, item.variant, item.underlying)):
        if occupied_until is not None and trade.entry_at < occupied_until:
            continue
        accepted.append(trade)
        occupied_until = trade.exit_at
    return tuple(accepted)


def summarize(rows: Sequence[Trade | ScoredTrade]) -> Metrics:
    ordered = tuple(sorted(rows, key=lambda item: item.session))
    count = len(ordered)
    net_pnl = _money(sum((item.net_pnl for item in ordered), Decimal(0)))
    expectancy = sum((item.return_r for item in ordered), Decimal(0)) / Decimal(count) if count else Decimal(0)
    wins = sum(item.net_pnl > 0 for item in ordered)
    losses = sum(item.net_pnl < 0 for item in ordered)
    gross_profit = sum((item.net_pnl for item in ordered if item.net_pnl > 0), Decimal(0))
    gross_loss = abs(sum((item.net_pnl for item in ordered if item.net_pnl < 0), Decimal(0)))
    profit_factor = gross_profit / gross_loss if gross_loss else (Decimal("Infinity") if gross_profit else Decimal(0))
    cumulative = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for item in ordered:
        cumulative += item.net_pnl
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    if count > 1:
        variance = sum(((item.return_r - expectancy) ** 2 for item in ordered), Decimal(0)) / Decimal(count - 1)
        deviation = variance.sqrt()
        margin = Decimal("1.96") * deviation / Decimal(count).sqrt()
    else:
        deviation = Decimal(0)
        margin = Decimal(0)
    return Metrics(
        sample_count=count,
        wins=wins,
        losses=losses,
        flats=count - wins - losses,
        hit_rate=Decimal(wins) / Decimal(count) if count else Decimal(0),
        net_pnl=net_pnl,
        profit_factor=profit_factor,
        expectancy_r=expectancy,
        max_drawdown=_money(maximum_drawdown),
        sample_stddev_r=deviation,
        mean_ci95_lower_r=expectancy - margin,
        mean_ci95_upper_r=expectancy + margin,
    )


def select_on_training(
    rows_by_variant: Mapping[str, Sequence[ScoredTrade]],
    training_dates: Sequence[date],
    *,
    minimum_samples: int,
) -> str | None:
    allowed = set(training_dates)
    scores: list[tuple[Decimal, Decimal, str]] = []
    for name, rows in rows_by_variant.items():
        training = tuple(item for item in rows if item.session in allowed)
        if len(training) < minimum_samples:
            continue
        expectancy = sum((item.return_r for item in training), Decimal(0)) / Decimal(len(training))
        net_pnl = sum((item.net_pnl for item in training), Decimal(0))
        scores.append((expectancy, net_pnl, name))
    if not scores:
        return None
    return sorted(scores, key=lambda item: (-item[0], -item[1], item[2]))[0][2]
