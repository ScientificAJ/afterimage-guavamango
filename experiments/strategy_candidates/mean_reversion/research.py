from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from experiments.strategy_candidates.mean_reversion.candidate import (
    OptionPairBar,
    Signal,
)


@dataclass(frozen=True)
class ScoredTrade:
    session: date
    return_r: Decimal
    net_pnl: Decimal


def _next_expiry(session: date, minimum_dte: int = 3) -> date:
    expiry = session + timedelta(days=minimum_dte)
    while expiry.weekday() >= 5:
        expiry += timedelta(days=1)
    return expiry


def _occ_symbol(root: str, expiry: date, right: str, strike: Decimal) -> str:
    strike_code = int(strike * Decimal(1000))
    return f"{root}{expiry:%y%m%d}{right}{strike_code:08d}"


def contract_pair(
    signal: Signal,
    root: str = "SPY",
    width: int = 5,
    minimum_dte: int = 3,
) -> tuple[str, str]:
    """Choose a directional ATM debit vertical with at least three calendar DTE."""
    expiry = _next_expiry(signal.completed_at.date(), minimum_dte)
    atm = signal.reference_price.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if signal.direction == "bullish":
        right = "C"
        short_strike = atm + width
    elif signal.direction == "bearish":
        right = "P"
        short_strike = atm - width
    else:
        raise ValueError("unknown signal direction")
    return (
        _occ_symbol(root, expiry, right, atm),
        _occ_symbol(root, expiry, right, short_strike),
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def pair_option_bars(
    payload: Mapping[str, Any], long_symbol: str, short_symbol: str
) -> tuple[OptionPairBar, ...]:
    bars = payload.get("bars") or {}
    long_rows = {_parse_timestamp(row["t"]): row for row in bars.get(long_symbol, [])}
    short_rows = {_parse_timestamp(row["t"]): row for row in bars.get(short_symbol, [])}
    paired: list[OptionPairBar] = []
    for timestamp in sorted(long_rows.keys() & short_rows.keys()):
        long_row = long_rows[timestamp]
        short_row = short_rows[timestamp]
        paired.append(
            OptionPairBar(
                timestamp=timestamp,
                long_open=Decimal(str(long_row["o"])),
                long_high=Decimal(str(long_row["h"])),
                long_low=Decimal(str(long_row["l"])),
                long_close=Decimal(str(long_row["c"])),
                short_open=Decimal(str(short_row["o"])),
                short_high=Decimal(str(short_row["h"])),
                short_low=Decimal(str(short_row["l"])),
                short_close=Decimal(str(short_row["c"])),
            )
        )
    return tuple(paired)


def select_variant(
    trades: Mapping[str, Sequence[ScoredTrade]],
    train_dates: Sequence[date],
    minimum_samples: int,
) -> str | None:
    """Select on the supplied training sessions; later dates cannot affect the score."""
    allowed = set(train_dates)
    scores: list[tuple[Decimal, Decimal, str]] = []
    for name, rows in trades.items():
        training = tuple(row for row in rows if row.session in allowed)
        if len(training) < minimum_samples:
            continue
        expectancy = sum((row.return_r for row in training), Decimal(0)) / len(training)
        net_pnl = sum((row.net_pnl for row in training), Decimal(0))
        scores.append((expectancy, net_pnl, name))
    if not scores:
        return None
    scores.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return scores[0][2]
