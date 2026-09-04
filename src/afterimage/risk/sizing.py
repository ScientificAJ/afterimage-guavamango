from decimal import ROUND_FLOOR, Decimal


def size_defined_risk_position(
    stressed_loss_per_spread: Decimal,
    equity: Decimal,
    fixed_cap: Decimal = Decimal(500),
    equity_fraction: Decimal = Decimal("0.005"),
    liquidity_cap: int = 10,
) -> int:
    if stressed_loss_per_spread <= 0 or equity <= 0:
        return 0
    allowed = min(fixed_cap, equity * equity_fraction)
    sized = int((allowed / stressed_loss_per_spread).to_integral_value(rounding=ROUND_FLOOR))
    return max(0, min(sized, liquidity_cap))
