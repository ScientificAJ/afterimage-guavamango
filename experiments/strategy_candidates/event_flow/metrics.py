"""Admission metrics for chronological strategy results."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Metrics:
    sample_count: int
    net_r: Decimal
    expectancy_r: Decimal
    profit_factor: Decimal
    hit_rate: Decimal
    max_drawdown_r: Decimal
    positive_month_fraction: Decimal
    positive_underlyings: int
    largest_win_fraction: Decimal


def summarize_returns(rows: Iterable[tuple[date, str, Decimal]]) -> Metrics:
    ordered = tuple(rows)
    returns = tuple(item[2] for item in ordered)
    sample_count = len(returns)
    gross_win = sum((item for item in returns if item > 0), Decimal(0))
    gross_loss = -sum((item for item in returns if item < 0), Decimal(0))
    profit_factor = gross_win / gross_loss if gross_loss else Decimal("Infinity")
    equity = Decimal(0)
    peak = Decimal(0)
    max_drawdown = Decimal(0)
    for item in returns:
        equity += item
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    monthly: dict[str, Decimal] = defaultdict(Decimal)
    symbols: dict[str, Decimal] = defaultdict(Decimal)
    for session, symbol, result in ordered:
        monthly[f"{session:%Y-%m}"] += result
        symbols[symbol] += result
    positive_month_fraction = (
        Decimal(sum(value > 0 for value in monthly.values())) / Decimal(len(monthly))
        if monthly
        else Decimal(0)
    )
    largest = max((item for item in returns if item > 0), default=Decimal(0))
    return Metrics(
        sample_count=sample_count,
        net_r=sum(returns, Decimal(0)),
        expectancy_r=sum(returns, Decimal(0)) / Decimal(sample_count or 1),
        profit_factor=profit_factor,
        hit_rate=Decimal(sum(item > 0 for item in returns)) / Decimal(sample_count or 1),
        max_drawdown_r=max_drawdown,
        positive_month_fraction=positive_month_fraction,
        positive_underlyings=sum(value > 0 for value in symbols.values()),
        largest_win_fraction=largest / gross_win if gross_win else Decimal(0),
    )
