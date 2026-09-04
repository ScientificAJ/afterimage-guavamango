from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import (
    CandidateEvent,
    ContractPolicy,
    OptionLeg,
    PayoffPassport,
)
from afterimage.risk.payoff import PayoffError, build_debit_vertical_passport, entry_debit


class OptionSelectionError(RuntimeError):
    pass


class SelectedVertical(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passport: PayoffPassport
    quote_hash: str
    quote_age_seconds: Decimal
    leg_skew_seconds: Decimal
    relative_spread: Decimal
    expiration_date: date
    source: str = "alpaca-option-chain"


def _at(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("quote timestamp is missing")
    return datetime.fromisoformat(value)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _quote(snapshot: dict[str, Any]) -> tuple[Decimal, Decimal, datetime]:
    value = snapshot.get("latestQuote", snapshot.get("latest_quote", {}))
    if not isinstance(value, dict):
        raise TypeError("quote missing")
    bid = _decimal(value.get("bp", value.get("bid_price", 0)))
    ask = _decimal(value.get("ap", value.get("ask_price", 0)))
    timestamp = _at(value.get("t", value.get("timestamp")))
    if bid <= 0 or ask <= bid:
        raise ValueError("crossed or one-sided quote")
    return bid, ask, timestamp


def _relative_spread(bid: Decimal, ask: Decimal) -> Decimal:
    midpoint = (bid + ask) / Decimal(2)
    return (ask - bid) / midpoint if midpoint > 0 else Decimal("Infinity")


def select_debit_vertical(
    candidate: CandidateEvent,
    contracts: list[dict[str, Any]],
    chain: dict[str, Any],
    policy: ContractPolicy,
    observed_at: datetime,
) -> SelectedVertical:
    if observed_at.tzinfo is None:
        raise OptionSelectionError("OBSERVED_AT_MUST_BE_TIMEZONE_AWARE")
    option_type = "put" if candidate.direction == "bearish" else "call"
    structure = "put_debit_vertical" if option_type == "put" else "call_debit_vertical"
    if structure not in policy.permitted_structures:
        raise OptionSelectionError("STRUCTURE_NOT_PERMITTED")
    snapshots = chain.get("snapshots", chain.get("data", {}))
    if not isinstance(snapshots, dict):
        raise OptionSelectionError("MALFORMED_OPTION_CHAIN")
    eligible: list[dict[str, Any]] = []
    for contract in contracts:
        try:
            expiration = date.fromisoformat(str(contract["expiration_date"]))
            dte = (expiration - observed_at.date()).days
            symbol = str(contract["symbol"])
            open_interest = int(contract.get("open_interest", 0) or 0)
            strike = _decimal(contract["strike_price"])
            snapshot = snapshots[symbol]
            if not isinstance(snapshot, dict):
                continue
            bid, ask, quote_at = _quote(snapshot)
            delta = abs(_decimal(snapshot.get("greeks", {}).get("delta", 0)))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        quote_age = Decimal(str((observed_at - quote_at).total_seconds()))
        spread = _relative_spread(bid, ask)
        if not (
            str(contract.get("type", "")).lower() == option_type
            and bool(contract.get("tradable", False))
            and policy.min_dte <= dte <= policy.max_dte
            and open_interest >= policy.min_open_interest
            and Decimal(0) <= quote_age <= Decimal(policy.max_quote_age_seconds)
            and spread <= policy.max_relative_spread
        ):
            continue
        eligible.append(
            {
                "symbol": symbol,
                "expiration": expiration,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "quote_at": quote_at,
                "delta": delta,
                "spread": spread,
                "quote_age": quote_age,
            }
        )
    selections: list[SelectedVertical] = []
    for long_contract in eligible:
        if not policy.min_delta <= long_contract["delta"] <= policy.max_delta:
            continue
        for short_contract in eligible:
            if long_contract["expiration"] != short_contract["expiration"]:
                continue
            width = (
                long_contract["strike"] - short_contract["strike"]
                if option_type == "put"
                else short_contract["strike"] - long_contract["strike"]
            )
            if width <= 0:
                continue
            legs = (
                OptionLeg(
                    symbol=long_contract["symbol"],
                    ratio_qty=1,
                    side="buy",
                    position_intent="buy_to_open",
                    bid=long_contract["bid"],
                    ask=long_contract["ask"],
                    quote_at=long_contract["quote_at"],
                ),
                OptionLeg(
                    symbol=short_contract["symbol"],
                    ratio_qty=1,
                    side="sell",
                    position_intent="sell_to_open",
                    bid=short_contract["bid"],
                    ask=short_contract["ask"],
                    quote_at=short_contract["quote_at"],
                ),
            )
            try:
                debit = entry_debit(legs)
                modeled_costs = Decimal("4.00")
                stop_value = max(Decimal("0.01"), debit * Decimal("0.75"))
                stop_loss = (debit - stop_value) * Decimal(100) + modeled_costs
                target_value = debit + (Decimal(3) * stop_loss + modeled_costs) / Decimal(100)
                if target_value >= width:
                    continue
                passport = build_debit_vertical_passport(
                    structure,
                    legs,
                    width,
                    target_value,
                    stop_value,
                    modeled_costs,
                )
            except PayoffError:
                continue
            if passport.structural_ratio < 3 or passport.operational_ratio < 3:
                continue
            timestamps = [leg.quote_at for leg in legs]
            age = max(long_contract["quote_age"], short_contract["quote_age"])
            skew = Decimal(str((max(timestamps) - min(timestamps)).total_seconds()))
            relative_spread = max(long_contract["spread"], short_contract["spread"])
            if skew > policy.max_leg_timestamp_skew_seconds:
                continue
            selections.append(
                SelectedVertical(
                    passport=passport,
                    quote_hash=canonical_sha256(
                        [leg.model_dump(mode="json") for leg in passport.legs]
                    ),
                    quote_age_seconds=age,
                    leg_skew_seconds=skew,
                    relative_spread=relative_spread,
                    expiration_date=long_contract["expiration"],
                )
            )
    if not selections:
        raise OptionSelectionError("NO_POLICY_COMPLIANT_VERTICAL")
    return min(
        selections,
        key=lambda selection: (
            selection.relative_spread,
            selection.passport.stressed_max_loss,
            selection.expiration_date,
        ),
    )
