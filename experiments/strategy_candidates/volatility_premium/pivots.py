"""Pure engines for the approved SPY+QQQ options-strategy pivots."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from candidate import (
    LEG_SIDE_FEE,
    LEG_SLIPPAGE,
    MULTIPLIER,
    Contract,
    DataExclusion,
    OptionBar,
    SpreadFrame,
    _t_critical_95,
)

CENT = Decimal("0.01")


@dataclass(frozen=True)
class MomentumFamily:
    name: str
    opening_threshold: Decimal
    trend_sessions: int
    wing_width: Decimal
    minimum_dte: int
    maximum_dte: int
    stop_fraction_of_debit: Decimal
    operational_target_stop: Decimal = Decimal(3)


MOMENTUM_FAMILIES = (
    MomentumFamily(
        "momentum_conservative", Decimal("0.0075"), 20, Decimal(5), 5, 9, Decimal("0.20")
    ),
    MomentumFamily("momentum_balanced", Decimal("0.0050"), 20, Decimal(5), 3, 7, Decimal("0.25")),
    MomentumFamily("momentum_fast", Decimal("0.0030"), 10, Decimal(3), 2, 5, Decimal("0.30")),
)


@dataclass(frozen=True)
class CondorFamily:
    name: str
    compression_ratio: Decimal
    maximum_opening_move: Decimal
    volatility_multiplier: Decimal
    minimum_distance_fraction: Decimal
    wing_width: Decimal
    minimum_dte: int
    maximum_dte: int
    stop_fraction_of_credit: Decimal
    operational_target_stop: Decimal = Decimal(3)


CONDOR_FAMILIES = (
    CondorFamily(
        "condor_wide",
        Decimal("0.80"),
        Decimal("0.0020"),
        Decimal("1.00"),
        Decimal("0.0100"),
        Decimal(5),
        5,
        9,
        Decimal("0.10"),
    ),
    CondorFamily(
        "condor_balanced",
        Decimal("1.00"),
        Decimal("0.0030"),
        Decimal("0.75"),
        Decimal("0.0075"),
        Decimal(5),
        3,
        7,
        Decimal("0.15"),
    ),
    CondorFamily(
        "condor_tight",
        Decimal("1.10"),
        Decimal("0.0040"),
        Decimal("0.50"),
        Decimal("0.0050"),
        Decimal(3),
        2,
        5,
        Decimal("0.20"),
    ),
)


@dataclass(frozen=True)
class StrangleFamily:
    name: str
    opening_threshold: Decimal
    minimum_volatility_ratio: Decimal
    distance_fraction: Decimal
    minimum_dte: int
    maximum_dte: int
    stop_fraction_of_debit: Decimal
    operational_target_stop: Decimal = Decimal(3)


STRANGLE_FAMILIES = (
    StrangleFamily(
        "strangle_conservative",
        Decimal("0.0075"),
        Decimal("1.10"),
        Decimal("0.0025"),
        5,
        9,
        Decimal("0.20"),
    ),
    StrangleFamily(
        "strangle_balanced",
        Decimal("0.0050"),
        Decimal("1.00"),
        Decimal("0.0015"),
        3,
        7,
        Decimal("0.25"),
    ),
    StrangleFamily(
        "strangle_fast",
        Decimal("0.0030"),
        Decimal("0.90"),
        Decimal(0),
        2,
        5,
        Decimal("0.30"),
    ),
)


@dataclass(frozen=True)
class LaggedMarketFeatures:
    session_date: date
    prior_close: Decimal
    trend_sma: Decimal
    volatility_5: Decimal
    volatility_20: Decimal


@dataclass(frozen=True)
class DebitSelection:
    long: Contract
    short: Contract
    expiration: date
    width: Decimal


@dataclass(frozen=True)
class CondorSelection:
    long_put: Contract
    short_put: Contract
    short_call: Contract
    long_call: Contract
    expiration: date
    width: Decimal


@dataclass(frozen=True)
class StrangleSelection:
    put: Contract
    call: Contract
    expiration: date


@dataclass(frozen=True)
class CondorFrame:
    timestamp: datetime
    short_put: OptionBar
    long_put: OptionBar
    short_call: OptionBar
    long_call: OptionBar

    def __post_init__(self) -> None:
        legs = (self.short_put, self.long_put, self.short_call, self.long_call)
        if any(leg.timestamp != self.timestamp for leg in legs):
            raise DataExclusion("CONDOR_LEG_TIMESTAMP_MISMATCH")
        if len({leg.symbol for leg in legs}) != 4:
            raise DataExclusion("CONDOR_LEG_SYMBOLS_NOT_DISTINCT")


@dataclass(frozen=True)
class PivotTrade:
    session_date: str
    symbol: str
    strategy: str
    family: str
    direction: str
    entry_at: datetime
    exit_at: datetime
    entry_value: Decimal
    exit_value: Decimal
    net_pnl: Decimal
    max_loss: Decimal
    return_r: Decimal
    outcome: Literal["target", "stop", "time"]
    stop_risk_dollars: Decimal
    target_dollars: Decimal
    operational_target_stop: Decimal
    modeled_fees: Decimal
    modeled_slippage: Decimal
    synchronized_frames: int
    leg_symbols: tuple[str, ...]


@dataclass(frozen=True)
class PivotMetrics:
    sample_count: int
    wins: int
    losses: int
    flats: int
    hit_rate: Decimal
    net_pnl: Decimal
    expectancy_r: Decimal
    max_drawdown: Decimal
    max_drawdown_r: Decimal
    sample_stddev_r: Decimal
    mean_ci95_lower_r: Decimal
    mean_ci95_upper_r: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: Decimal


@dataclass(frozen=True)
class RollingFold:
    evaluation_month: str
    training_start: date
    training_end: date
    selected_family: str
    selection_metrics: PivotMetrics
    evaluation_metrics: PivotMetrics
    trades: tuple[PivotTrade, ...]


@dataclass(frozen=True)
class RollingResult:
    folds: tuple[RollingFold, ...]
    trades: tuple[PivotTrade, ...]
    metrics: PivotMetrics


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _realized_volatility(prices: Sequence[Decimal]) -> Decimal:
    if len(prices) < 2:
        raise DataExclusion("INSUFFICIENT_VOLATILITY_HISTORY")
    returns = [prices[index] / prices[index - 1] - Decimal(1) for index in range(1, len(prices))]
    mean = sum(returns, Decimal(0)) / len(returns)
    variance = sum(((item - mean) ** 2 for item in returns), Decimal(0)) / len(returns)
    return variance.sqrt()


def lagged_market_features(
    closes: Sequence[tuple[date, Decimal]],
    session_date: date,
    *,
    trend_lookback: int,
) -> LaggedMarketFeatures:
    eligible = [item for item in sorted(closes) if item[0] < session_date]
    required = max(20, trend_lookback)
    if len(eligible) < required:
        raise DataExclusion("INSUFFICIENT_LAGGED_DAILY_HISTORY")
    prices = [item[1] for item in eligible]
    if any(not item.is_finite() or item <= 0 for item in prices[-required:]):
        raise DataExclusion("DAILY_CLOSE_INVALID")
    trend_window = prices[-trend_lookback:]
    return LaggedMarketFeatures(
        session_date=session_date,
        prior_close=prices[-1],
        trend_sma=sum(trend_window, Decimal(0)) / len(trend_window),
        volatility_5=_realized_volatility(prices[-6:]),
        volatility_20=_realized_volatility(prices[-20:]),
    )


def momentum_direction(
    family: MomentumFamily,
    opening_return: Decimal,
    features: LaggedMarketFeatures,
) -> Literal["bullish", "bearish"] | None:
    if opening_return >= family.opening_threshold and features.prior_close > features.trend_sma:
        return "bullish"
    if opening_return <= -family.opening_threshold and features.prior_close < features.trend_sma:
        return "bearish"
    return None


def condor_signal(
    family: CondorFamily,
    opening_return: Decimal,
    features: LaggedMarketFeatures,
) -> bool:
    if features.volatility_20 <= 0:
        return False
    return (
        abs(opening_return) <= family.maximum_opening_move
        and features.volatility_5 / features.volatility_20 <= family.compression_ratio
    )


def expansion_signal(
    family: StrangleFamily,
    opening_return: Decimal,
    features: LaggedMarketFeatures,
) -> bool:
    if features.volatility_20 <= 0:
        return False
    return (
        abs(opening_return) >= family.opening_threshold
        and features.volatility_5 / features.volatility_20 >= family.minimum_volatility_ratio
    )


def select_debit_pair(
    family: MomentumFamily,
    *,
    direction: Literal["bullish", "bearish"],
    session_date: date,
    spot: Decimal,
    contracts: Sequence[Contract],
) -> DebitSelection:
    option_type = "call" if direction == "bullish" else "put"
    eligible = [
        item
        for item in contracts
        if item.option_type == option_type
        and family.minimum_dte <= (item.expiration - session_date).days <= family.maximum_dte
    ]
    if not eligible:
        raise DataExclusion("NO_DEBIT_EXPIRATION_IN_DTE_WINDOW")
    expiration = min(item.expiration for item in eligible)
    chain = [item for item in eligible if item.expiration == expiration]
    long = min(chain, key=lambda item: (abs(item.strike - spot), item.strike))
    if direction == "bullish":
        short_candidates = [
            item for item in chain if item.strike >= long.strike + family.wing_width
        ]
        if not short_candidates:
            raise DataExclusion("NO_CALL_DEBIT_SHORT_STRIKE")
        short = min(short_candidates, key=lambda item: item.strike)
        width = short.strike - long.strike
    else:
        short_candidates = [
            item for item in chain if item.strike <= long.strike - family.wing_width
        ]
        if not short_candidates:
            raise DataExclusion("NO_PUT_DEBIT_SHORT_STRIKE")
        short = max(short_candidates, key=lambda item: item.strike)
        width = long.strike - short.strike
    return DebitSelection(long=long, short=short, expiration=expiration, width=width)


def select_condor_legs(
    family: CondorFamily,
    *,
    session_date: date,
    spot: Decimal,
    volatility_20: Decimal,
    contracts: Sequence[Contract],
) -> CondorSelection:
    eligible_expirations = sorted(
        {
            item.expiration
            for item in contracts
            if family.minimum_dte <= (item.expiration - session_date).days <= family.maximum_dte
        }
    )
    if not eligible_expirations:
        raise DataExclusion("NO_CONDOR_EXPIRATION_IN_DTE_WINDOW")
    expiration = eligible_expirations[0]
    chain = [item for item in contracts if item.expiration == expiration]
    distance = max(
        family.minimum_distance_fraction,
        volatility_20 * family.volatility_multiplier,
    )
    put_target = spot * (Decimal(1) - distance)
    call_target = spot * (Decimal(1) + distance)
    short_put_candidates = [
        item for item in chain if item.option_type == "put" and item.strike <= put_target
    ]
    short_call_candidates = [
        item for item in chain if item.option_type == "call" and item.strike >= call_target
    ]
    if not short_put_candidates or not short_call_candidates:
        raise DataExclusion("NO_CONDOR_SHORT_STRIKES")
    short_put = max(short_put_candidates, key=lambda item: item.strike)
    short_call = min(short_call_candidates, key=lambda item: item.strike)
    long_put_candidates = [
        item
        for item in chain
        if item.option_type == "put" and item.strike <= short_put.strike - family.wing_width
    ]
    long_call_candidates = [
        item
        for item in chain
        if item.option_type == "call" and item.strike >= short_call.strike + family.wing_width
    ]
    if not long_put_candidates or not long_call_candidates:
        raise DataExclusion("NO_CONDOR_LONG_WINGS")
    long_put = max(long_put_candidates, key=lambda item: item.strike)
    long_call = min(long_call_candidates, key=lambda item: item.strike)
    width = max(
        short_put.strike - long_put.strike,
        long_call.strike - short_call.strike,
    )
    return CondorSelection(
        long_put=long_put,
        short_put=short_put,
        short_call=short_call,
        long_call=long_call,
        expiration=expiration,
        width=width,
    )


def select_strangle_legs(
    family: StrangleFamily,
    *,
    session_date: date,
    spot: Decimal,
    contracts: Sequence[Contract],
) -> StrangleSelection:
    expirations = sorted(
        {
            item.expiration
            for item in contracts
            if family.minimum_dte <= (item.expiration - session_date).days <= family.maximum_dte
        }
    )
    if not expirations:
        raise DataExclusion("NO_STRANGLE_EXPIRATION_IN_DTE_WINDOW")
    expiration = expirations[0]
    chain = [item for item in contracts if item.expiration == expiration]
    put_target = spot * (Decimal(1) - family.distance_fraction)
    call_target = spot * (Decimal(1) + family.distance_fraction)
    puts = [item for item in chain if item.option_type == "put" and item.strike <= put_target]
    calls = [item for item in chain if item.option_type == "call" and item.strike >= call_target]
    if not puts or not calls:
        raise DataExclusion("NO_STRANGLE_STRIKES")
    return StrangleSelection(
        put=max(puts, key=lambda item: item.strike),
        call=min(calls, key=lambda item: item.strike),
        expiration=expiration,
    )


def simulate_debit_vertical(
    *,
    session_date: str,
    symbol: str,
    family: MomentumFamily,
    direction: Literal["bullish", "bearish"],
    width: Decimal,
    frames: Sequence[SpreadFrame],
    strategy: str = "directional_debit_momentum",
) -> PivotTrade:
    if len(frames) < 2:
        raise DataExclusion("FEWER_THAN_TWO_SYNCHRONIZED_OPTION_BARS")
    ordered = tuple(sorted(frames, key=lambda item: item.timestamp))
    entry_debit = _money(ordered[0].long.high - ordered[0].short.low + LEG_SLIPPAGE * 2)
    if entry_debit <= 0 or entry_debit >= width:
        raise DataExclusion("DEBIT_OUTSIDE_SPREAD_WIDTH")
    fees = LEG_SIDE_FEE * 4
    maximum_loss = _money(entry_debit * MULTIPLIER + fees)
    stop_risk = maximum_loss * family.stop_fraction_of_debit
    target = stop_risk * family.operational_target_stop
    maximum_profit = (width - entry_debit) * MULTIPLIER - fees
    if maximum_profit < target:
        raise DataExclusion("THREE_TO_ONE_TARGET_EXCEEDS_MAXIMUM_PROFIT")
    selected = ordered[-1]
    exit_credit = Decimal(0)
    outcome: Literal["target", "stop", "time"] = "time"
    for frame in ordered[1:]:
        current_credit = _money(
            max(frame.long.low - frame.short.high - LEG_SLIPPAGE * 2, Decimal(0))
        )
        net = _money((current_credit - entry_debit) * MULTIPLIER - fees)
        selected = frame
        exit_credit = current_credit
        if net >= target:
            outcome = "target"
            break
        if net <= -stop_risk:
            outcome = "stop"
            break
    net_pnl = _money((exit_credit - entry_debit) * MULTIPLIER - fees)
    return PivotTrade(
        session_date=session_date,
        symbol=symbol,
        strategy=strategy,
        family=family.name,
        direction=direction,
        entry_at=ordered[0].timestamp,
        exit_at=selected.timestamp,
        entry_value=entry_debit,
        exit_value=exit_credit,
        net_pnl=net_pnl,
        max_loss=maximum_loss,
        return_r=net_pnl / maximum_loss,
        outcome=outcome,
        stop_risk_dollars=stop_risk,
        target_dollars=target,
        operational_target_stop=target / stop_risk,
        modeled_fees=fees,
        modeled_slippage=LEG_SLIPPAGE * 4 * MULTIPLIER,
        synchronized_frames=len(ordered),
        leg_symbols=(ordered[0].long.symbol, ordered[0].short.symbol),
    )


def simulate_condor(
    *,
    session_date: str,
    symbol: str,
    family: CondorFamily,
    width: Decimal,
    frames: Sequence[CondorFrame],
) -> PivotTrade:
    if len(frames) < 2:
        raise DataExclusion("FEWER_THAN_TWO_SYNCHRONIZED_OPTION_BARS")
    ordered = tuple(sorted(frames, key=lambda item: item.timestamp))
    first = ordered[0]
    entry_credit = _money(
        first.short_put.low
        + first.short_call.low
        - first.long_put.high
        - first.long_call.high
        - LEG_SLIPPAGE * 4
    )

    if entry_credit <= 0 or entry_credit >= width:
        raise DataExclusion("CONDOR_CREDIT_OUTSIDE_WING_WIDTH")
    fees = LEG_SIDE_FEE * 8
    maximum_loss = _money((width - entry_credit) * MULTIPLIER + fees)
    stop_risk = max(entry_credit * MULTIPLIER * family.stop_fraction_of_credit, Decimal(5))
    target = stop_risk * family.operational_target_stop
    maximum_profit = entry_credit * MULTIPLIER - fees
    if maximum_profit < target:
        raise DataExclusion("THREE_TO_ONE_TARGET_EXCEEDS_MAXIMUM_PROFIT")
    selected = ordered[-1]
    exit_debit = Decimal(0)
    outcome: Literal["target", "stop", "time"] = "time"
    for frame in ordered[1:]:
        current_debit = _money(
            max(
                frame.short_put.high
                + frame.short_call.high
                - frame.long_put.low
                - frame.long_call.low
                + LEG_SLIPPAGE * 4,
                Decimal(0),
            )
        )
        net = _money((entry_credit - current_debit) * MULTIPLIER - fees)
        selected = frame
        exit_debit = current_debit
        if net >= target:
            outcome = "target"
            break
        if net <= -stop_risk:
            outcome = "stop"
            break
    net_pnl = _money((entry_credit - exit_debit) * MULTIPLIER - fees)
    return PivotTrade(
        session_date=session_date,
        symbol=symbol,
        strategy="compression_iron_condor",
        family=family.name,
        direction="market_neutral",
        entry_at=ordered[0].timestamp,
        exit_at=selected.timestamp,
        entry_value=entry_credit,
        exit_value=exit_debit,
        net_pnl=net_pnl,
        max_loss=maximum_loss,
        return_r=net_pnl / maximum_loss,
        outcome=outcome,
        stop_risk_dollars=stop_risk,
        target_dollars=target,
        operational_target_stop=target / stop_risk,
        modeled_fees=fees,
        modeled_slippage=LEG_SLIPPAGE * 8 * MULTIPLIER,
        synchronized_frames=len(ordered),
        leg_symbols=(
            first.short_put.symbol,
            first.long_put.symbol,
            first.short_call.symbol,
            first.long_call.symbol,
        ),
    )


def simulate_long_strangle(
    *,
    session_date: str,
    symbol: str,
    family: StrangleFamily,
    frames: Sequence[tuple[OptionBar, OptionBar]],
    strategy: str = "expansion_long_strangle",
) -> PivotTrade:
    if len(frames) < 2:
        raise DataExclusion("FEWER_THAN_TWO_SYNCHRONIZED_OPTION_BARS")
    ordered = tuple(sorted(frames, key=lambda item: item[0].timestamp))
    if any(put.timestamp != call.timestamp for put, call in ordered):
        raise DataExclusion("STRANGLE_LEG_TIMESTAMP_MISMATCH")
    first_put, first_call = ordered[0]
    entry_debit = _money(first_put.high + first_call.high + LEG_SLIPPAGE * 2)
    if entry_debit <= 0:
        raise DataExclusion("STRANGLE_DEBIT_NOT_POSITIVE")
    fees = LEG_SIDE_FEE * 4
    maximum_loss = _money(entry_debit * MULTIPLIER + fees)
    stop_risk = maximum_loss * family.stop_fraction_of_debit
    target = stop_risk * family.operational_target_stop
    selected = ordered[-1]
    exit_credit = Decimal(0)
    outcome: Literal["target", "stop", "time"] = "time"
    for put, call in ordered[1:]:
        current_credit = _money(max(put.low + call.low - LEG_SLIPPAGE * 2, Decimal(0)))
        net = _money((current_credit - entry_debit) * MULTIPLIER - fees)
        selected = (put, call)
        exit_credit = current_credit
        if net >= target:
            outcome = "target"
            break
        if net <= -stop_risk:
            outcome = "stop"
            break
    net_pnl = _money((exit_credit - entry_debit) * MULTIPLIER - fees)
    return PivotTrade(
        session_date=session_date,
        symbol=symbol,
        strategy=strategy,
        family=family.name,
        direction="long_volatility",
        entry_at=first_put.timestamp,
        exit_at=selected[0].timestamp,
        entry_value=entry_debit,
        exit_value=exit_credit,
        net_pnl=net_pnl,
        max_loss=maximum_loss,
        return_r=net_pnl / maximum_loss,
        outcome=outcome,
        stop_risk_dollars=stop_risk,
        target_dollars=target,
        operational_target_stop=target / stop_risk,
        modeled_fees=fees,
        modeled_slippage=LEG_SLIPPAGE * 4 * MULTIPLIER,
        synchronized_frames=len(ordered),
        leg_symbols=(first_put.symbol, first_call.symbol),
    )


def simulate_long_option(
    *,
    session_date: str,
    symbol: str,
    family: MomentumFamily,
    direction: Literal["bullish", "bearish"],
    bars: Sequence[OptionBar],
    strategy: str = "directional_long_momentum",
) -> PivotTrade:
    if len(bars) < 2:
        raise DataExclusion("FEWER_THAN_TWO_OPTION_BARS")
    ordered = tuple(sorted(bars, key=lambda item: item.timestamp))
    if len({item.symbol for item in ordered}) != 1:
        raise DataExclusion("SINGLE_OPTION_SYMBOL_MISMATCH")
    entry_debit = _money(ordered[0].high + LEG_SLIPPAGE)
    if entry_debit <= 0:
        raise DataExclusion("SINGLE_OPTION_DEBIT_NOT_POSITIVE")
    fees = LEG_SIDE_FEE * 2
    maximum_loss = _money(entry_debit * MULTIPLIER + fees)
    stop_risk = maximum_loss * family.stop_fraction_of_debit
    target = stop_risk * family.operational_target_stop
    selected = ordered[-1]
    exit_credit = Decimal(0)
    outcome: Literal["target", "stop", "time"] = "time"
    for option_bar in ordered[1:]:
        current_credit = _money(max(option_bar.low - LEG_SLIPPAGE, Decimal(0)))
        net = _money((current_credit - entry_debit) * MULTIPLIER - fees)
        selected = option_bar
        exit_credit = current_credit
        if net >= target:
            outcome = "target"
            break
        if net <= -stop_risk:
            outcome = "stop"
            break
    net_pnl = _money((exit_credit - entry_debit) * MULTIPLIER - fees)
    return PivotTrade(
        session_date=session_date,
        symbol=symbol,
        strategy=strategy,
        family=family.name,
        direction=direction,
        entry_at=ordered[0].timestamp,
        exit_at=selected.timestamp,
        entry_value=entry_debit,
        exit_value=exit_credit,
        net_pnl=net_pnl,
        max_loss=maximum_loss,
        return_r=net_pnl / maximum_loss,
        outcome=outcome,
        stop_risk_dollars=stop_risk,
        target_dollars=target,
        operational_target_stop=target / stop_risk,
        modeled_fees=fees,
        modeled_slippage=LEG_SLIPPAGE * 2 * MULTIPLIER,
        synchronized_frames=len(ordered),
        leg_symbols=(ordered[0].symbol,),
    )


def summarize_pivots(trades: Sequence[PivotTrade]) -> PivotMetrics:
    ordered = sorted(trades, key=lambda item: (item.session_date, item.symbol, item.entry_at))
    count = len(ordered)
    wins = sum(item.net_pnl > 0 for item in ordered)
    losses = sum(item.net_pnl < 0 for item in ordered)
    net = _money(sum((item.net_pnl for item in ordered), Decimal(0)))
    expectancy = (
        sum((item.return_r for item in ordered), Decimal(0)) / count if count else Decimal(0)
    )
    if count > 1:
        variance = sum(((item.return_r - expectancy) ** 2 for item in ordered), Decimal(0)) / (
            count - 1
        )
        standard_deviation = variance.sqrt()
        margin = _t_critical_95(count - 1) * standard_deviation / Decimal(count).sqrt()
    else:
        standard_deviation = Decimal(0)
        margin = Decimal(0)
    cumulative = Decimal(0)
    peak = Decimal(0)
    drawdown = Decimal(0)
    cumulative_r = Decimal(0)
    peak_r = Decimal(0)
    drawdown_r = Decimal(0)
    for trade in ordered:
        cumulative += trade.net_pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        cumulative_r += trade.return_r
        peak_r = max(peak_r, cumulative_r)
        drawdown_r = max(drawdown_r, peak_r - cumulative_r)
    gross_profit = _money(sum((item.net_pnl for item in ordered if item.net_pnl > 0), Decimal(0)))
    gross_loss = _money(-sum((item.net_pnl for item in ordered if item.net_pnl < 0), Decimal(0)))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss
        else Decimal("Infinity")
        if gross_profit
        else Decimal(0)
    )
    return PivotMetrics(
        sample_count=count,
        wins=wins,
        losses=losses,
        flats=count - wins - losses,
        hit_rate=Decimal(wins) / count if count else Decimal(0),
        net_pnl=net,
        expectancy_r=expectancy,
        max_drawdown=_money(drawdown),
        max_drawdown_r=drawdown_r,
        sample_stddev_r=standard_deviation,
        mean_ci95_lower_r=expectancy - margin,
        mean_ci95_upper_r=expectancy + margin,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
    )


def rolling_walk_forward(
    trades_by_family: Mapping[str, Sequence[PivotTrade]],
    *,
    family_order: Sequence[str],
    evaluation_months: Sequence[str] = ("2026-05", "2026-06", "2026-07", "2026-08"),
) -> RollingResult:
    folds: list[RollingFold] = []
    selected_trades: list[PivotTrade] = []
    training_start = date(2026, 4, 1)
    for month in evaluation_months:
        month_start = date.fromisoformat(f"{month}-01")
        training_end = month_start - timedelta(days=1)
        candidates: list[tuple[str, PivotMetrics, int]] = []
        for index, family in enumerate(family_order):
            training_rows = tuple(
                item
                for item in trades_by_family.get(family, ())
                if training_start <= date.fromisoformat(item.session_date) < month_start
            )
            if training_rows:
                candidates.append((family, summarize_pivots(training_rows), index))
        if not candidates:
            continue
        selected, selection_metrics, _ = max(
            candidates,
            key=lambda item: (
                item[1].expectancy_r,
                item[1].profit_factor,
                -item[1].max_drawdown,
                item[1].sample_count,
                -item[2],
            ),
        )
        evaluation_rows = tuple(
            item
            for item in trades_by_family.get(selected, ())
            if item.session_date.startswith(month)
        )
        selected_trades.extend(evaluation_rows)
        folds.append(
            RollingFold(
                evaluation_month=month,
                training_start=training_start,
                training_end=training_end,
                selected_family=selected,
                selection_metrics=selection_metrics,
                evaluation_metrics=summarize_pivots(evaluation_rows),
                trades=evaluation_rows,
            )
        )
    return RollingResult(
        folds=tuple(folds),
        trades=tuple(selected_trades),
        metrics=summarize_pivots(selected_trades),
    )


def fixed_family_walk_forward(
    trades: Sequence[PivotTrade],
    *,
    family: str,
    evaluation_months: Sequence[str] = ("2026-05", "2026-06", "2026-07", "2026-08"),
) -> RollingResult:
    rows = tuple(item for item in trades if item.family == family)
    folds: list[RollingFold] = []
    evaluation_rows: list[PivotTrade] = []
    training_start = date(2026, 4, 1)
    for month in evaluation_months:
        month_start = date.fromisoformat(f"{month}-01")
        training = tuple(
            item
            for item in rows
            if training_start <= date.fromisoformat(item.session_date) < month_start
        )
        evaluation = tuple(item for item in rows if item.session_date.startswith(month))
        evaluation_rows.extend(evaluation)
        folds.append(
            RollingFold(
                evaluation_month=month,
                training_start=training_start,
                training_end=month_start - timedelta(days=1),
                selected_family=family,
                selection_metrics=summarize_pivots(training),
                evaluation_metrics=summarize_pivots(evaluation),
                trades=evaluation,
            )
        )
    return RollingResult(
        folds=tuple(folds),
        trades=tuple(evaluation_rows),
        metrics=summarize_pivots(evaluation_rows),
    )


def promotion_gates(
    rolling_trades: Sequence[PivotTrade],
    *,
    neighbor_metrics: Mapping[str, PivotMetrics],
) -> dict[str, bool]:
    metrics = summarize_pivots(rolling_trades)
    symbol_metrics = {
        symbol: summarize_pivots([item for item in rolling_trades if item.symbol == symbol])
        for symbol in ("SPY", "QQQ")
    }
    month_metrics = {
        month: summarize_pivots(
            [item for item in rolling_trades if item.session_date.startswith(month)]
        )
        for month in ("2026-05", "2026-06", "2026-07", "2026-08")
    }
    one_and_half_cost_net = sum(
        (
            item.net_pnl - (item.modeled_fees + item.modeled_slippage) * Decimal("0.50")
            for item in rolling_trades
        ),
        Decimal(0),
    )
    largest_profit_share = (
        max((item.net_pnl for item in rolling_trades if item.net_pnl > 0), default=Decimal(0))
        / metrics.gross_profit
        if metrics.gross_profit > 0
        else Decimal("Infinity")
    )
    gates = {
        "operational_target_stop_at_least_3": bool(rolling_trades)
        and all(item.operational_target_stop >= 3 for item in rolling_trades),
        "profit_factor_at_least_2": metrics.profit_factor >= 2,
        "minimum_pooled_sample": metrics.sample_count >= 30,
        "expectancy_at_least_quarter_r": metrics.expectancy_r >= Decimal("0.25"),
        "cross_symbol_or_three_positive_regimes": (
            all(item.sample_count > 0 and item.expectancy_r > 0 for item in symbol_metrics.values())
            or sum(
                item.sample_count > 0 and item.expectancy_r > 0 for item in month_metrics.values()
            )
            >= 3
        ),
        "positive_at_least_60_percent_months": sum(
            item.sample_count > 0 and item.expectancy_r > 0 for item in month_metrics.values()
        )
        >= 3,
        "max_drawdown_at_most_6r": metrics.max_drawdown_r <= Decimal(6),
        "profitable_at_one_and_half_costs": bool(rolling_trades) and one_and_half_cost_net > 0,
        "largest_trade_at_most_25_percent_profit": bool(rolling_trades)
        and largest_profit_share <= Decimal("0.25"),
        "at_least_60_percent_positive_neighbors": sum(
            item.sample_count > 0 and item.expectancy_r > 0 for item in neighbor_metrics.values()
        )
        >= 2,
    }
    gates["promoted"] = all(gates.values())
    return gates


def _group_by_month(trades: Sequence[PivotTrade]) -> dict[str, list[PivotTrade]]:
    grouped: dict[str, list[PivotTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.session_date[:7]].append(trade)
    return dict(sorted(grouped.items()))
