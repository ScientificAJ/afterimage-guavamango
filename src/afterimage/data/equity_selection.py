from __future__ import annotations

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import PayoffPassport
from afterimage.risk.payoff import PayoffError, build_equity_bracket_passport


class EquitySelectionError(ValueError):
    pass


class EquitySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passport: PayoffPassport
    quote_hash: str
    market_quote_hash: str
    quote_age_seconds: Decimal
    relative_spread: Decimal
    bid: Decimal
    ask: Decimal
    quote_at: datetime


def _quote(snapshot: dict[str, Any], symbol: str) -> dict[str, Any]:
    payload: Any = snapshot
    for container in ("snapshots", "data"):
        nested = payload.get(container) if isinstance(payload, dict) else None
        if isinstance(nested, dict) and symbol in nested:
            payload = nested[symbol]
            break
    if isinstance(payload, dict):
        value = payload.get("latestQuote", payload.get("latest_quote"))
        if isinstance(value, dict):
            return value
    raise EquitySelectionError("EQUITY_QUOTE_MISSING")


def _decimal(payload: dict[str, Any], *names: str) -> Decimal:
    for name in names:
        if payload.get(name) is not None:
            return Decimal(str(payload[name]))
    raise EquitySelectionError("EQUITY_QUOTE_MALFORMED")


def select_equity_bracket(
    symbol: str,
    side: Literal["buy", "sell"] | str,
    snapshot: dict[str, Any],
    observed_at: datetime,
    *,
    stop_distance: Decimal,
    stop_distance_fraction: Decimal | None = None,
    minimum_reward_risk: Decimal,
    modeled_round_trip_cost: Decimal,
    modeled_round_trip_cost_fraction: Decimal = Decimal(0),
    maximum_quote_age_seconds: Decimal = Decimal(2),
) -> EquitySelection:
    normalized_symbol = symbol.strip().upper()
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        raise EquitySelectionError("EQUITY_SIDE_INVALID")
    if (
        stop_distance <= 0
        or minimum_reward_risk < 3
        or modeled_round_trip_cost < 0
        or modeled_round_trip_cost_fraction < 0
        or (
            stop_distance_fraction is not None
            and not Decimal(0) < stop_distance_fraction < Decimal(1)
        )
    ):
        raise EquitySelectionError("EQUITY_BRACKET_POLICY_INVALID")
    quote = _quote(snapshot, normalized_symbol)
    bid = _decimal(quote, "bp", "bid_price", "bidPrice")
    ask = _decimal(quote, "ap", "ask_price", "askPrice")
    if bid <= 0 or ask <= bid:
        raise EquitySelectionError("CROSSED_EQUITY_QUOTE")
    timestamp_value = quote.get("t", quote.get("timestamp"))
    if not timestamp_value:
        raise EquitySelectionError("EQUITY_QUOTE_MALFORMED")
    quote_at = datetime.fromisoformat(str(timestamp_value))
    quote_age = Decimal(str(max(0.0, (observed_at - quote_at).total_seconds())))
    if quote_age > maximum_quote_age_seconds:
        raise EquitySelectionError("STALE_EQUITY_QUOTE")
    entry = ask if normalized_side == "buy" else bid
    effective_stop_distance = (
        entry * stop_distance_fraction if stop_distance_fraction is not None else stop_distance
    )
    effective_modeled_cost = modeled_round_trip_cost + entry * modeled_round_trip_cost_fraction
    cent = Decimal("0.01")
    if normalized_side == "buy":
        stop = (entry - effective_stop_distance).quantize(cent, rounding=ROUND_FLOOR)
        actual_stop_distance = entry - stop
        raw_target_distance = (
            minimum_reward_risk * (actual_stop_distance + effective_modeled_cost)
            + effective_modeled_cost
        )
        target = (entry + raw_target_distance).quantize(cent, rounding=ROUND_CEILING)
    else:
        stop = (entry + effective_stop_distance).quantize(cent, rounding=ROUND_CEILING)
        actual_stop_distance = stop - entry
        raw_target_distance = (
            minimum_reward_risk * (actual_stop_distance + effective_modeled_cost)
            + effective_modeled_cost
        )
        target = (entry - raw_target_distance).quantize(cent, rounding=ROUND_FLOOR)
    try:
        passport = build_equity_bracket_passport(
            normalized_symbol,
            normalized_side,
            entry,
            stop,
            target,
            effective_modeled_cost,
        )
    except PayoffError as exc:
        raise EquitySelectionError(str(exc)) from exc
    relative_spread = (ask - bid) / ((ask + bid) / Decimal(2))
    market_quote_hash = canonical_sha256(
        {
            "symbol": normalized_symbol,
            "bid": str(bid),
            "ask": str(ask),
            "quote_at": quote_at.isoformat(),
            "side": normalized_side,
            "stop": str(stop),
            "target": str(target),
            "modeled_round_trip_cost": str(effective_modeled_cost),
            "stop_distance_fraction": (
                str(stop_distance_fraction) if stop_distance_fraction is not None else None
            ),
        }
    )
    quote_hash = canonical_sha256(
        {
            "asset_class": "equity",
            "symbol": normalized_symbol,
            "side": normalized_side,
            "order_class": "bracket",
            "order_type": "limit",
            "reduce_only": False,
            "limit_price": str(entry),
            "take_profit_price": str(target),
            "stop_price": str(stop),
        }
    )
    return EquitySelection(
        passport=passport,
        quote_hash=quote_hash,
        market_quote_hash=market_quote_hash,
        quote_age_seconds=quote_age,
        relative_spread=relative_spread,
        bid=bid,
        ask=ask,
        quote_at=quote_at,
    )
