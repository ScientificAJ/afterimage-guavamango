from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.hashing import canonical_sha256
from afterimage.evidence import HistoricalRow

from .dataset import ResearchDataset, ResearchDatasetError, validate_research_dataset

ET = ZoneInfo("America/New_York")


class OptionHistoryGateway(Protocol):
    async def option_contracts(self, symbol: str, **filters: Any) -> Sequence[dict[str, Any]]: ...

    async def option_bars(
        self,
        symbols: tuple[str, ...],
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
    ) -> Sequence[dict[str, Any]]: ...


class OptionTradeBarResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    signal_id: str
    session_date: date
    direction: str
    long_symbol: str
    short_symbol: str
    expiration_date: date
    entry_bar_start_at: datetime
    entry_at: datetime
    terminal_bar_start_at: datetime
    terminal_at: datetime
    entry_debit: Decimal
    terminal_credit: Decimal
    net_pnl_dollars: Decimal
    return_r: Decimal
    target_first: bool | None
    synchronized_bar_pairs: int


class OptionValidationExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    signal_id: str
    session_date: date
    reason: str


class OptionValidationStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    requested_signals: int
    validated_signals: int
    censored_signals: int
    coverage_rate: Decimal
    wins: int
    losses: int
    flats: int
    target_exits: int
    stop_exits: int
    time_exits: int
    minimum_return_r: Decimal
    p25_return_r: Decimal
    median_return_r: Decimal
    p75_return_r: Decimal
    maximum_return_r: Decimal
    sample_stddev_return_r: Decimal
    mean_ci95_lower_r: Decimal
    mean_ci95_upper_r: Decimal
    maximum_drawdown_dollars: Decimal


class OptionValidationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "afterimage-option-trade-bars-v3"
    dataset_hash: str
    holdout_source_hash: str
    strategy_id: str
    source: str = "Alpaca historical option trade bars"
    pricing_basis: str = (
        "next synchronized 5-minute trade-bar closes, available at bar-start+5 minutes; "
        "not bid/ask quotes or contemporaneous fills"
    )
    contract_limitation: str = (
        "Contract metadata is queried after expiration and is not a point-in-time chain snapshot."
    )
    one_way_slippage_per_leg: Decimal = Decimal("0.01")
    validated: int
    excluded: int
    aggregate_net_pnl_dollars: Decimal
    mean_return_r: Decimal
    statistics: OptionValidationStatistics
    results: tuple[OptionTradeBarResult, ...]
    exclusions: tuple[OptionValidationExclusion, ...]
    manifest_hash: str


async def validate_option_trade_bars(
    gateway: OptionHistoryGateway,
    dataset: ResearchDataset,
    *,
    strategy_id: str,
    public_path: Path,
) -> OptionValidationManifest:
    validate_research_dataset(dataset)
    evaluation = dataset.holdout.evaluations.get(strategy_id)
    if evaluation is None:
        raise ResearchDatasetError("OPTION_VALIDATION_STRATEGY_MISSING")
    results: list[OptionTradeBarResult] = []
    exclusions: list[OptionValidationExclusion] = []
    for row in evaluation.rows:
        try:
            results.append(await _validate_signal(gateway, dataset.symbol, row, strategy_id))
        except (
            ResearchDatasetError,
            DecimalException,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            exclusions.append(
                OptionValidationExclusion(
                    signal_id=row.private_row_id,
                    session_date=row.session_date,
                    reason=str(exc),
                )
            )
    aggregate = sum((result.net_pnl_dollars for result in results), Decimal(0))
    mean_return = (
        sum((result.return_r for result in results), Decimal(0)) / len(results)
        if results
        else Decimal(0)
    )
    statistics = _validation_statistics(
        results,
        requested_signals=len(evaluation.rows),
        censored_signals=len(exclusions),
    )
    draft = OptionValidationManifest(
        dataset_hash=dataset.dataset_hash,
        holdout_source_hash=dataset.holdout.source_hash,
        strategy_id=strategy_id,
        validated=len(results),
        excluded=len(exclusions),
        aggregate_net_pnl_dollars=aggregate,
        mean_return_r=mean_return,
        statistics=statistics,
        results=tuple(results),
        exclusions=tuple(exclusions),
        manifest_hash="",
    )
    manifest = draft.model_copy(
        update={
            "manifest_hash": canonical_sha256(
                draft.model_dump(mode="json", exclude={"manifest_hash"})
            )
        }
    )
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _quantile(values: Sequence[Decimal], percentile: Decimal) -> Decimal:
    if not values:
        return Decimal(0)
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (Decimal(1) - weight) + ordered[upper] * weight


def _t_critical_95(degrees_of_freedom: int) -> Decimal:
    values = (
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
    if degrees_of_freedom <= len(values):
        return Decimal(values[degrees_of_freedom - 1])
    return Decimal("1.96")


def _validation_statistics(
    results: Sequence[OptionTradeBarResult],
    *,
    requested_signals: int,
    censored_signals: int,
) -> OptionValidationStatistics:
    returns = [item.return_r for item in results]
    mean = sum(returns, Decimal(0)) / len(returns) if returns else Decimal(0)
    if len(returns) > 1:
        variance = sum(((item - mean) ** 2 for item in returns), Decimal(0)) / (len(returns) - 1)
        stddev = variance.sqrt()
        margin = _t_critical_95(len(returns) - 1) * stddev / Decimal(len(returns)).sqrt()
    else:
        stddev = Decimal(0)
        margin = Decimal(0)

    cumulative = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for result in sorted(results, key=lambda item: (item.session_date, item.signal_id)):
        cumulative += result.net_pnl_dollars
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)

    validated = len(results)
    return OptionValidationStatistics(
        requested_signals=requested_signals,
        validated_signals=validated,
        censored_signals=censored_signals,
        coverage_rate=(Decimal(validated) / requested_signals if requested_signals else Decimal(0)),
        wins=sum(item.net_pnl_dollars > 0 for item in results),
        losses=sum(item.net_pnl_dollars < 0 for item in results),
        flats=sum(item.net_pnl_dollars == 0 for item in results),
        target_exits=sum(item.target_first is True for item in results),
        stop_exits=sum(item.target_first is False for item in results),
        time_exits=sum(item.target_first is None for item in results),
        minimum_return_r=min(returns, default=Decimal(0)),
        p25_return_r=_quantile(returns, Decimal("0.25")),
        median_return_r=_quantile(returns, Decimal("0.50")),
        p75_return_r=_quantile(returns, Decimal("0.75")),
        maximum_return_r=max(returns, default=Decimal(0)),
        sample_stddev_return_r=stddev,
        mean_ci95_lower_r=mean - margin,
        mean_ci95_upper_r=mean + margin,
        maximum_drawdown_dollars=maximum_drawdown,
    )


async def _validate_signal(
    gateway: OptionHistoryGateway,
    symbol: str,
    row: HistoricalRow,
    strategy_id: str,
) -> OptionTradeBarResult:
    del strategy_id
    if row.signal_at is None or row.signal_price is None or row.direction is None:
        raise ResearchDatasetError("SIGNAL_METADATA_MISSING")
    if row.direction == "long_volatility":
        raise ResearchDatasetError("LONG_VOLATILITY_STRUCTURE_NOT_SUPPORTED")
    option_type = "put" if row.direction == "bearish" else "call"
    lower = row.signal_price - Decimal(12)
    upper = row.signal_price + Decimal(12)
    contracts = await gateway.option_contracts(
        symbol,
        expiration_date_gte=(row.session_date + timedelta(days=2)).isoformat(),
        expiration_date_lte=(row.session_date + timedelta(days=7)).isoformat(),
        strike_price_gte=str(lower),
        strike_price_lte=str(upper),
        type=option_type,
        status="inactive",
        limit=10000,
    )
    long_contract, short_contract = _select_contracts(contracts, row.signal_price, option_type)
    long_symbol = str(long_contract["symbol"])
    short_symbol = str(short_contract["symbol"])
    exit_at = datetime.combine(row.session_date, time(10, 45), ET).astimezone(row.signal_at.tzinfo)
    bars = await gateway.option_bars((long_symbol, short_symbol), row.signal_at, exit_at, "5Min")
    grouped: dict[str, dict[datetime, Decimal]] = defaultdict(dict)
    for bar in bars:
        contract_symbol = str(bar.get("symbol", ""))
        if contract_symbol not in {long_symbol, short_symbol}:
            raise ResearchDatasetError("OPTION_BAR_SYMBOL_MISMATCH")
        timestamp = datetime.fromisoformat(str(bar["t"]))
        close = Decimal(str(bar["c"]))
        if timestamp.tzinfo is None or not close.is_finite() or close <= 0:
            raise ResearchDatasetError("OPTION_BAR_MALFORMED")
        if row.signal_at <= timestamp < exit_at:
            grouped[contract_symbol][timestamp] = close
    synchronized = sorted(set(grouped[long_symbol]).intersection(grouped[short_symbol]))
    if not synchronized:
        raise ResearchDatasetError("NO_SYNCHRONIZED_OPTION_TRADE_BARS")
    slippage = Decimal("0.01")
    entry_bar_start_at = synchronized[0]
    entry_at = entry_bar_start_at + timedelta(minutes=5)
    raw_entry = grouped[long_symbol][entry_bar_start_at] - grouped[short_symbol][entry_bar_start_at]
    entry_debit = raw_entry + slippage * 2
    if entry_debit <= 0:
        raise ResearchDatasetError("NON_POSITIVE_MODELED_ENTRY_DEBIT")
    risk_unit = max(entry_debit * Decimal("0.20"), Decimal("0.05"))
    target = risk_unit * 3
    stop = -risk_unit
    terminal_bar_start_at = synchronized[-1]
    terminal_at = terminal_bar_start_at + timedelta(minutes=5)
    terminal_credit = Decimal(0)
    pnl = Decimal(0)
    target_first: bool | None = None
    for timestamp in synchronized:
        credit = grouped[long_symbol][timestamp] - grouped[short_symbol][timestamp] - slippage * 2
        observed_pnl = credit - entry_debit
        terminal_bar_start_at = timestamp
        terminal_at = timestamp + timedelta(minutes=5)
        terminal_credit = credit
        pnl = observed_pnl
        if observed_pnl <= stop:
            target_first = False
            break
        if observed_pnl >= target:
            target_first = True
            break
    expiration = date.fromisoformat(str(long_contract["expiration_date"]))
    return OptionTradeBarResult(
        signal_id=row.private_row_id,
        session_date=row.session_date,
        direction=row.direction,
        long_symbol=long_symbol,
        short_symbol=short_symbol,
        expiration_date=expiration,
        entry_bar_start_at=entry_bar_start_at,
        entry_at=entry_at,
        terminal_bar_start_at=terminal_bar_start_at,
        terminal_at=terminal_at,
        entry_debit=entry_debit,
        terminal_credit=terminal_credit,
        net_pnl_dollars=(pnl * 100).quantize(Decimal("0.01")),
        return_r=pnl / risk_unit,
        target_first=target_first,
        synchronized_bar_pairs=len(synchronized),
    )


def _select_contracts(
    contracts: Sequence[dict[str, Any]], signal_price: Decimal, option_type: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed: list[tuple[date, Decimal, dict[str, Any]]] = []
    for contract in contracts:
        try:
            if str(contract.get("type")) != option_type:
                continue
            expiration = date.fromisoformat(str(contract["expiration_date"]))
            strike = Decimal(str(contract["strike_price"]))
            if not strike.is_finite() or not str(contract["symbol"]):
                continue
        except (DecimalException, KeyError, ValueError):
            continue
        parsed.append((expiration, strike, contract))
    if not parsed:
        raise ResearchDatasetError("NO_ELIGIBLE_HISTORICAL_CONTRACTS")
    for expiration in sorted({item[0] for item in parsed}):
        same_expiration = [item for item in parsed if item[0] == expiration]
        long_item = min(same_expiration, key=lambda item: abs(item[1] - signal_price))
        if option_type == "put":
            shorts = [
                item
                for item in same_expiration
                if Decimal(5) <= long_item[1] - item[1] <= Decimal(10)
            ]
        else:
            shorts = [
                item
                for item in same_expiration
                if Decimal(5) <= item[1] - long_item[1] <= Decimal(10)
            ]
        if shorts:
            short_item = min(
                shorts,
                key=lambda item: (abs(abs(item[1] - long_item[1]) - Decimal(6)), item[1]),
            )
            return long_item[2], short_item[2]
    raise ResearchDatasetError("NO_DEFINED_RISK_VERTICAL_AVAILABLE")
