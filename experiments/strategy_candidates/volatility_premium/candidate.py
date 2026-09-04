"""Pure research logic for the isolated SPY put-credit-spread candidate.

Historical prices in this module are conservative bounds derived from option
trade bars.  They are not bid/ask quotes and are not claimed executable fills.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

CENT = Decimal("0.01")
LEG_SIDE_FEE = Decimal("0.03")
LEG_SLIPPAGE = Decimal("0.01")
MULTIPLIER = Decimal(100)


class DataExclusion(ValueError):
    """A named reason why a historical observation cannot be modeled."""


@dataclass(frozen=True)
class Family:
    name: str
    sma_sessions: int
    volatility_multiplier: Decimal
    minimum_distance_fraction: Decimal
    wing_width: Decimal
    minimum_dte: int
    maximum_dte: int


FAMILIES = (
    Family("defensive", 20, Decimal("1.00"), Decimal("0.0100"), Decimal(5), 5, 9),
    Family("balanced", 20, Decimal("0.75"), Decimal("0.0075"), Decimal(5), 5, 9),
    Family("tight", 10, Decimal("0.50"), Decimal("0.0050"), Decimal(3), 3, 7),
)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


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
        prices = (self.open, self.high, self.low, self.close)
        if not self.symbol or self.timestamp.tzinfo is None:
            raise DataExclusion("OPTION_BAR_IDENTITY_INVALID")
        if any(not value.is_finite() or value < 0 for value in prices):
            raise DataExclusion("OPTION_BAR_PRICE_INVALID")
        if self.high < max(self.open, self.low, self.close):
            raise DataExclusion("OPTION_BAR_HIGH_INVALID")
        if self.low > min(self.open, self.high, self.close):
            raise DataExclusion("OPTION_BAR_LOW_INVALID")
        if self.volume < 0:
            raise DataExclusion("OPTION_BAR_VOLUME_INVALID")


@dataclass(frozen=True)
class Contract:
    symbol: str
    expiration: date
    strike: Decimal
    option_type: Literal["put", "call"]


@dataclass(frozen=True)
class DailyFeature:
    session_date: date
    prior_close: Decimal
    sma: Decimal
    daily_volatility_fraction: Decimal


@dataclass(frozen=True)
class SpreadSelection:
    short: Contract
    long: Contract
    expiration: date
    width: Decimal
    target_short_strike: Decimal


@dataclass(frozen=True)
class SpreadFrame:
    timestamp: datetime
    short: OptionBar
    long: OptionBar

    def __post_init__(self) -> None:
        if self.timestamp != self.short.timestamp or self.timestamp != self.long.timestamp:
            raise DataExclusion("LEG_TIMESTAMP_MISMATCH")
        if self.short.symbol == self.long.symbol:
            raise DataExclusion("DUPLICATE_LEG_SYMBOL")


@dataclass(frozen=True)
class Trade:
    session_date: str
    family: str
    short_symbol: str
    long_symbol: str
    width: Decimal
    entry_at: datetime
    exit_at: datetime
    entry_credit: Decimal
    exit_debit: Decimal
    net_pnl: Decimal
    max_loss: Decimal
    return_r: Decimal
    outcome: Literal["target", "stop", "time"]
    modeled_fees: Decimal
    modeled_slippage: Decimal
    synchronized_frames: int


@dataclass(frozen=True)
class Metrics:
    sample_count: int
    wins: int
    losses: int
    flats: int
    hit_rate: Decimal
    net_pnl: Decimal
    expectancy_r: Decimal
    max_drawdown: Decimal
    sample_stddev_r: Decimal
    mean_ci95_lower_r: Decimal
    mean_ci95_upper_r: Decimal


@dataclass(frozen=True)
class FrozenFamily:
    family: Family
    metrics: Metrics
    validation_start: date
    training_cutoff: date


def adverse_entry_credit(frame: SpreadFrame) -> Decimal:
    credit = frame.short.low - frame.long.high - LEG_SLIPPAGE * 2
    return _money(credit)


def adverse_exit_debit(frame: SpreadFrame) -> Decimal:
    debit = frame.short.high - frame.long.low + LEG_SLIPPAGE * 2
    return _money(max(debit, Decimal(0)))


def simulate_trade(
    *,
    session_date: str,
    family: str,
    short_symbol: str,
    long_symbol: str,
    width: Decimal,
    frames: Sequence[SpreadFrame],
    target_credit_fraction: Decimal = Decimal("0.50"),
    stop_credit_multiple: Decimal = Decimal("1.50"),
) -> Trade:
    if not frames:
        raise DataExclusion("NO_SYNCHRONIZED_OPTION_BARS")
    ordered = tuple(sorted(frames, key=lambda item: item.timestamp))
    if any(item.short.symbol != short_symbol for item in ordered):
        raise DataExclusion("SHORT_SYMBOL_MISMATCH")
    if any(item.long.symbol != long_symbol for item in ordered):
        raise DataExclusion("LONG_SYMBOL_MISMATCH")
    entry_credit = adverse_entry_credit(ordered[0])
    if entry_credit <= 0:
        raise DataExclusion("NON_POSITIVE_ADVERSE_ENTRY_CREDIT")
    if width <= entry_credit:
        raise DataExclusion("CREDIT_EXCEEDS_SPREAD_WIDTH")

    target_dollars = entry_credit * MULTIPLIER * target_credit_fraction
    stop_dollars = entry_credit * MULTIPLIER * stop_credit_multiple
    selected = ordered[-1]
    selected_debit = adverse_exit_debit(selected)
    outcome: Literal["target", "stop", "time"] = "time"
    for current in ordered[1:]:
        debit = adverse_exit_debit(current)
        gross = (entry_credit - debit) * MULTIPLIER
        selected = current
        selected_debit = debit
        if gross >= target_dollars:
            outcome = "target"
            break
        if gross <= -stop_dollars:
            outcome = "stop"
            break

    fees = LEG_SIDE_FEE * Decimal(4)
    net_pnl = _money((entry_credit - selected_debit) * MULTIPLIER - fees)
    maximum_loss = _money((width - entry_credit) * MULTIPLIER + fees)
    return Trade(
        session_date=session_date,
        family=family,
        short_symbol=short_symbol,
        long_symbol=long_symbol,
        width=width,
        entry_at=ordered[0].timestamp,
        exit_at=selected.timestamp,
        entry_credit=entry_credit,
        exit_debit=selected_debit,
        net_pnl=net_pnl,
        max_loss=maximum_loss,
        return_r=net_pnl / maximum_loss,
        outcome=outcome,
        modeled_fees=fees,
        modeled_slippage=LEG_SLIPPAGE * Decimal(4) * MULTIPLIER,
        synchronized_frames=len(ordered),
    )


def summarize(trades: Sequence[Trade]) -> Metrics:
    ordered = sorted(trades, key=lambda item: (item.session_date, item.entry_at))
    count = len(ordered)
    net_pnl = _money(sum((item.net_pnl for item in ordered), Decimal(0)))
    expectancy = (
        sum((item.return_r for item in ordered), Decimal(0)) / Decimal(count)
        if count
        else Decimal(0)
    )
    cumulative = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for trade in ordered:
        cumulative += trade.net_pnl
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    wins = sum(item.net_pnl > 0 for item in ordered)
    losses = sum(item.net_pnl < 0 for item in ordered)
    if count > 1:
        variance = sum(
            ((item.return_r - expectancy) ** 2 for item in ordered), Decimal(0)
        ) / Decimal(count - 1)
        standard_deviation = variance.sqrt()
        critical = _t_critical_95(count - 1)
        margin = critical * standard_deviation / Decimal(count).sqrt()
    else:
        standard_deviation = Decimal(0)
        margin = Decimal(0)
    return Metrics(
        sample_count=count,
        wins=wins,
        losses=losses,
        flats=count - wins - losses,
        hit_rate=Decimal(wins) / Decimal(count) if count else Decimal(0),
        net_pnl=net_pnl,
        expectancy_r=expectancy,
        max_drawdown=_money(maximum_drawdown),
        sample_stddev_r=standard_deviation,
        mean_ci95_lower_r=expectancy - margin,
        mean_ci95_upper_r=expectancy + margin,
    )


def _t_critical_95(degrees_of_freedom: int) -> Decimal:
    small_sample_values = (
        "12.706",
        "4.303",
        "3.182",
        "2.776",
        "2.571",
        "2.447",
        "2.365",
        "2.306",
        "2.262",
        "2.228",
        "2.201",
        "2.179",
        "2.160",
        "2.145",
        "2.131",
        "2.120",
        "2.110",
        "2.101",
        "2.093",
        "2.086",
        "2.080",
        "2.074",
        "2.069",
        "2.064",
        "2.060",
        "2.056",
        "2.052",
        "2.048",
        "2.045",
        "2.042",
    )
    if degrees_of_freedom <= 0:
        return Decimal(0)
    if degrees_of_freedom <= len(small_sample_values):
        return Decimal(small_sample_values[degrees_of_freedom - 1])
    return Decimal("1.96")


def daily_features(
    closes: Sequence[tuple[date, Decimal]], session_date: date, *, lookback: int
) -> DailyFeature:
    if lookback < 2:
        raise ValueError("LOOKBACK_TOO_SHORT")
    eligible = sorted(
        ((day, close) for day, close in closes if day < session_date),
        key=lambda item: item[0],
    )
    if len(eligible) < lookback:
        raise DataExclusion("INSUFFICIENT_LAGGED_DAILY_HISTORY")
    window = eligible[-lookback:]
    prices = [item[1] for item in window]
    if any(not price.is_finite() or price <= 0 for price in prices):
        raise DataExclusion("DAILY_CLOSE_INVALID")
    sma = sum(prices, Decimal(0)) / Decimal(len(prices))
    returns = [prices[index] / prices[index - 1] - Decimal(1) for index in range(1, len(prices))]
    mean_return = sum(returns, Decimal(0)) / Decimal(len(returns))
    variance = sum(((value - mean_return) ** 2 for value in returns), Decimal(0)) / Decimal(
        len(returns)
    )
    return DailyFeature(
        session_date=session_date,
        prior_close=prices[-1],
        sma=sma,
        daily_volatility_fraction=variance.sqrt(),
    )


def select_contract_pair(
    family: Family,
    *,
    session_date: date,
    spot: Decimal,
    feature: DailyFeature,
    contracts: Sequence[Contract],
) -> SpreadSelection:
    if spot <= 0 or not spot.is_finite():
        raise DataExclusion("SPOT_INVALID")
    if feature.session_date != session_date:
        raise DataExclusion("FEATURE_SESSION_MISMATCH")
    if feature.prior_close <= feature.sma:
        raise DataExclusion("TREND_FILTER_FAILED")
    distance = max(
        family.minimum_distance_fraction,
        feature.daily_volatility_fraction * family.volatility_multiplier,
    )
    target_short = spot * (Decimal(1) - distance)
    eligible = [
        contract
        for contract in contracts
        if contract.option_type == "put"
        and family.minimum_dte <= (contract.expiration - session_date).days <= family.maximum_dte
    ]
    if not eligible:
        raise DataExclusion("NO_EXPIRATION_IN_DTE_WINDOW")
    expiration = min(contract.expiration for contract in eligible)
    chain = [contract for contract in eligible if contract.expiration == expiration]
    short_candidates = [contract for contract in chain if contract.strike <= target_short]
    if not short_candidates:
        raise DataExclusion("NO_OTM_SHORT_STRIKE")
    short = max(short_candidates, key=lambda contract: contract.strike)
    target_long = short.strike - family.wing_width
    long_candidates = [contract for contract in chain if contract.strike <= target_long]
    if not long_candidates:
        raise DataExclusion("NO_PROTECTIVE_LONG_STRIKE")
    long = max(long_candidates, key=lambda contract: contract.strike)
    width = short.strike - long.strike
    if width < family.wing_width:
        raise DataExclusion("WING_WIDTH_TOO_NARROW")
    return SpreadSelection(
        short=short,
        long=long,
        expiration=expiration,
        width=width,
        target_short_strike=target_short,
    )


def freeze_family(
    trades_by_family: Mapping[str, Sequence[Trade]],
    *,
    training_cutoff: date,
    validation_start: date = date(2026, 4, 1),
) -> FrozenFamily:
    scored: list[tuple[Family, Metrics, int]] = []
    for index, family in enumerate(FAMILIES):
        trades = tuple(
            trade
            for trade in trades_by_family.get(family.name, ())
            if validation_start <= date.fromisoformat(trade.session_date) <= training_cutoff
        )
        if trades:
            scored.append((family, summarize(trades), index))
    if not scored:
        raise DataExclusion("NO_WALK_FORWARD_VALIDATION_TRADES")
    family, metrics, _ = max(
        scored,
        key=lambda item: (
            item[1].expectancy_r,
            -item[1].max_drawdown,
            item[1].sample_count,
            -item[2],
        ),
    )
    return FrozenFamily(
        family=family,
        metrics=metrics,
        validation_start=validation_start,
        training_cutoff=training_cutoff,
    )
