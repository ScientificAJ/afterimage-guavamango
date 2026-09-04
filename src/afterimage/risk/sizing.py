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


def size_equity_position(
    stressed_loss_per_share: Decimal,
    share_price: Decimal,
    equity: Decimal,
    fixed_loss_cap: Decimal,
    notional_cap: Decimal,
    equity_fraction: Decimal = Decimal("0.005"),
) -> int:
    """Size shares under both the per-trade loss budget and a gross notional ceiling."""
    if min(stressed_loss_per_share, share_price, equity, fixed_loss_cap, notional_cap) <= 0:
        return 0
    allowed_loss = min(fixed_loss_cap, equity * equity_fraction)
    by_loss = int((allowed_loss / stressed_loss_per_share).to_integral_value(rounding=ROUND_FLOOR))
    by_notional = int((notional_cap / share_price).to_integral_value(rounding=ROUND_FLOOR))
    return max(0, min(by_loss, by_notional))
