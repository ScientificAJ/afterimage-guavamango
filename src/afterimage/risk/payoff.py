from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from afterimage.contracts.models import OptionLeg, PayoffPassport


class PayoffError(ValueError):
    pass


def entry_debit(legs: Sequence[OptionLeg]) -> Decimal:
    debit = Decimal(0)
    for leg in legs:
        if leg.ask <= leg.bid or leg.bid <= 0:
            raise PayoffError("CROSSED_OR_ONE_SIDED_QUOTE")
        debit += leg.ask if leg.side == "buy" else -leg.bid
    if debit <= 0:
        raise PayoffError("DEFINED_DEBIT_REQUIRED")
    return debit


def build_debit_vertical_passport(
    structure: str,
    legs: Sequence[OptionLeg],
    strike_width: Decimal,
    operational_target_value: Decimal,
    operational_stop_value: Decimal,
    modeled_costs: Decimal = Decimal("4.00"),
) -> PayoffPassport:
    if len(legs) != 2 or {leg.side for leg in legs} != {"buy", "sell"}:
        raise PayoffError("VERTICAL_REQUIRES_ONE_LONG_AND_ONE_SHORT")
    debit = entry_debit(legs)
    max_loss = debit * Decimal(100) + modeled_costs
    max_profit = (strike_width - debit) * Decimal(100) - modeled_costs
    target_profit = (operational_target_value - debit) * Decimal(100) - modeled_costs
    stop_loss = (debit - operational_stop_value) * Decimal(100) + modeled_costs
    if max_profit <= 0 or stop_loss <= 0:
        raise PayoffError("NON_POSITIVE_PAYOFF")
    return PayoffPassport(
        structure=structure,
        legs=tuple(legs),
        entry_net_debit=debit,
        stressed_max_loss=max_loss,
        stressed_max_profit=max_profit,
        structural_ratio=max_profit / max_loss,
        operational_target_profit=target_profit,
        operational_stop_loss=stop_loss,
        operational_ratio=target_profit / stop_loss,
        modeled_costs=modeled_costs,
    )
