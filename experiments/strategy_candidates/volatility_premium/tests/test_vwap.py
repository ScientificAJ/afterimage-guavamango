from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pivots import MOMENTUM_FAMILIES
from vwap import VwapOptionBar, simulate_causal_vwap_long


def vwap_bar(
    timestamp: str, close: str, vwap: str, volume: int = 100, trades: int = 20
) -> VwapOptionBar:
    return VwapOptionBar(
        symbol="CALL",
        timestamp=datetime.fromisoformat(timestamp),
        close=Decimal(close),
        vwap=Decimal(vwap),
        volume=volume,
        trade_count=trades,
    )


def test_causal_vwap_exit_fills_next_bar_after_target_detection() -> None:
    trade = simulate_causal_vwap_long(
        session_date="2026-05-01",
        symbol="SPY",
        family=MOMENTUM_FAMILIES[2],
        direction="bearish",
        bars=(
            vwap_bar("2026-05-01T14:00:00+00:00", "1.00", "1.00"),
            vwap_bar("2026-05-01T14:05:00+00:00", "2.10", "2.00"),
            vwap_bar("2026-05-01T14:10:00+00:00", "1.85", "1.80"),
        ),
    )

    assert trade.entry_value == Decimal("1.02")
    assert trade.exit_value == Decimal("1.78")
    assert trade.exit_at == datetime.fromisoformat("2026-05-01T14:10:00+00:00")
    assert trade.outcome == "target"
    assert trade.net_pnl == Decimal("75.94")
    assert trade.modeled_fees == Decimal("0.06")
    assert trade.modeled_slippage == Decimal("4.00")
    assert trade.operational_target_stop == Decimal(3)


def test_causal_vwap_model_rejects_illiquid_entry_bar() -> None:
    try:
        simulate_causal_vwap_long(
            session_date="2026-05-01",
            symbol="SPY",
            family=MOMENTUM_FAMILIES[2],
            direction="bearish",
            bars=(
                vwap_bar("2026-05-01T14:00:00+00:00", "1.00", "1.00", volume=9),
                vwap_bar("2026-05-01T14:05:00+00:00", "1.20", "1.20"),
            ),
        )
    except ValueError as exc:
        assert str(exc) == "VWAP_ENTRY_LIQUIDITY_FILTER_FALSE"
    else:
        raise AssertionError("illiquid entry was accepted")
