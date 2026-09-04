from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from experiments.strategy_candidates.mean_reversion.candidate import Bar


@dataclass(frozen=True)
class EquityCosts:
    slippage_bps: Decimal
    fee_per_share: Decimal


@dataclass(frozen=True)
class EquityTrade:
    entry_at: datetime
    exit_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    risk_dollars: Decimal
    net_pnl: Decimal
    return_r: Decimal
    exit_reason: str
    operational_target_stop: Decimal
    stop_price: Decimal
    target_price: Decimal


def underlying_bracket(
    completed_at: datetime,
    rows: Sequence[Bar],
    direction: str,
    costs: EquityCosts,
    risk_distance: Decimal,
    quantity: int,
    target_r: Decimal,
    max_holding_bars: int,
) -> EquityTrade:
    if direction not in {"bullish", "bearish"}:
        raise ValueError("direction must be bullish or bearish")
    if risk_distance <= 0 or quantity < 1 or target_r < 3 or max_holding_bars < 1:
        raise ValueError("invalid bracket dimensions")
    eligible = tuple(
        sorted((row for row in rows if row.timestamp >= completed_at), key=lambda row: row.timestamp)
    )
    if len(eligible) < 2:
        raise ValueError("insufficient post-signal bars")
    slip = costs.slippage_bps / Decimal(10_000)
    fee = costs.fee_per_share
    entry_row = eligible[0]
    raw_entry = Decimal(str(entry_row.close))
    if direction == "bullish":
        entry_price = raw_entry * (Decimal(1) + slip)
        stop_raw = raw_entry - risk_distance
        modeled_stop_fill = stop_raw * (Decimal(1) - slip)
        risk_per_share = entry_price - modeled_stop_fill + fee * 2
        target_fill = entry_price + fee * 2 + target_r * risk_per_share
        target_raw = target_fill / (Decimal(1) - slip)
    else:
        entry_price = raw_entry * (Decimal(1) - slip)
        stop_raw = raw_entry + risk_distance
        modeled_stop_fill = stop_raw * (Decimal(1) + slip)
        risk_per_share = modeled_stop_fill - entry_price + fee * 2
        target_fill = entry_price - fee * 2 - target_r * risk_per_share
        target_raw = target_fill / (Decimal(1) + slip)
    if risk_per_share <= 0 or target_raw <= 0:
        raise ValueError("invalid cost-adjusted bracket")

    exit_row = eligible[min(max_holding_bars, len(eligible) - 1)]
    exit_reason = "timeout"
    raw_exit = Decimal(str(exit_row.close))
    exit_price = raw_exit * (
        Decimal(1) - slip if direction == "bullish" else Decimal(1) + slip
    )
    for candidate in eligible[1 : max_holding_bars + 1]:
        low = Decimal(str(candidate.low))
        high = Decimal(str(candidate.high))
        opened = Decimal(str(candidate.open))
        if direction == "bullish":
            if low <= stop_raw:
                raw_exit = min(opened, stop_raw)
                exit_price = raw_exit * (Decimal(1) - slip)
                exit_reason = "stop"
                exit_row = candidate
                break
            if high >= target_raw:
                exit_price = target_fill
                exit_reason = "target"
                exit_row = candidate
                break
        else:
            if high >= stop_raw:
                raw_exit = max(opened, stop_raw)
                exit_price = raw_exit * (Decimal(1) + slip)
                exit_reason = "stop"
                exit_row = candidate
                break
            if low <= target_raw:
                exit_price = target_fill
                exit_reason = "target"
                exit_row = candidate
                break

    if direction == "bullish":
        pnl_per_share = exit_price - entry_price - fee * 2
    else:
        pnl_per_share = entry_price - exit_price - fee * 2
    net_pnl = pnl_per_share * quantity
    risk_dollars = risk_per_share * quantity
    return EquityTrade(
        entry_at=entry_row.timestamp + timedelta(minutes=5),
        exit_at=exit_row.timestamp + timedelta(minutes=5),
        entry_price=entry_price.quantize(Decimal("0.0001")),
        exit_price=exit_price.quantize(Decimal("0.0001")),
        quantity=quantity,
        risk_dollars=risk_dollars.quantize(Decimal("0.01")),
        net_pnl=net_pnl.quantize(Decimal("0.01")),
        return_r=(net_pnl / risk_dollars).quantize(Decimal("0.0001")),
        exit_reason=exit_reason,
        operational_target_stop=target_r,
        stop_price=stop_raw.quantize(Decimal("0.01")),
        target_price=target_raw.quantize(Decimal("0.01")),
    )


def build_equity_dry_run_order(
    symbol: str,
    direction: str,
    quantity: int,
    entry_price: Decimal,
    target_price: Decimal,
    stop_price: Decimal,
) -> dict[str, Any]:
    if direction not in {"bullish", "bearish"} or quantity < 1:
        raise ValueError("invalid equity bracket")
    payload = {
        "symbol": symbol,
        "qty": str(quantity),
        "side": "buy" if direction == "bullish" else "sell",
        "type": "limit",
        "limit_price": str(entry_price),
        "time_in_force": "day",
        "order_class": "bracket",
        "take_profit": {"limit_price": str(target_price)},
        "stop_loss": {"stop_price": str(stop_price)},
    }
    return {
        "submission_allowed": False,
        "payload": payload,
        "cli_arguments": [
            "order",
            "submit",
            "--symbol",
            symbol,
            "--qty",
            str(quantity),
            "--side",
            payload["side"],
            "--type",
            "limit",
            "--limit-price",
            str(entry_price),
            "--time-in-force",
            "day",
            "--order-class",
            "bracket",
            "--take-profit",
            json.dumps(payload["take_profit"], separators=(",", ":")),
            "--stop-loss",
            json.dumps(payload["stop_loss"], separators=(",", ":")),
            "--quiet",
            "--dry-run",
        ],
    }
