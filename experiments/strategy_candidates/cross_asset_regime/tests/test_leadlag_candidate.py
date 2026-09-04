from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.candidate import StockBar
from experiments.strategy_candidates.cross_asset_regime.leadlag_candidate import (
    LeadLagVariant,
    leadlag_signal_at,
)


SYMBOLS = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")


def test_sector_basket_leads_and_selects_same_direction_index_laggard() -> None:
    rows = []
    for symbol in SYMBOLS:
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 14, 30, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100))
        close = Decimal("101") if symbol.startswith("XL") else (Decimal("100.2") if symbol == "QQQ" else Decimal("100.6"))
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 16, 30, tzinfo=UTC), close, close, close, close, 100))
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 16, 45, tzinfo=UTC), Decimal("50"), Decimal("50"), Decimal("50"), Decimal("50"), 100))
    variant = LeadLagVariant("ll_b4_g05_s20", 4, Decimal("0.0005"), Decimal("0.20"))
    signal = leadlag_signal_at(variant, tuple(rows), date(2026, 1, 20), datetime(2026, 1, 20, 16, 30, tzinfo=UTC))
    assert signal is not None
    assert signal.completed_at == datetime(2026, 1, 20, 16, 45, tzinfo=UTC)
    assert signal.direction == "bullish"
    assert signal.underlying == "QQQ"
    assert signal.reference_price == Decimal("100.2")
    assert signal.sector_breadth == 5


def test_leadlag_rejects_an_index_moving_opposite_to_sector_direction() -> None:
    rows = []
    for symbol in SYMBOLS:
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 14, 30, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100))
        close = Decimal("101") if symbol.startswith("XL") else Decimal("99")
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 16, 30, tzinfo=UTC), close, close, close, close, 100))
    variant = LeadLagVariant("ll_b4_g05_s20", 4, Decimal("0.0005"), Decimal("0.20"))
    assert leadlag_signal_at(variant, tuple(rows), date(2026, 1, 20), datetime(2026, 1, 20, 16, 30, tzinfo=UTC)) is None


def test_unrelated_spy_bar_does_not_invalidate_complete_leadlag_window() -> None:
    rows = []
    for symbol in (*SYMBOLS, "SPY"):
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 14, 30, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100))
        close = Decimal("101") if symbol.startswith("XL") else Decimal("100.2")
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 16, 30, tzinfo=UTC), close, close, close, close, 100))
    variant = LeadLagVariant("ll_b4_g05_s20", 4, Decimal("0.0005"), Decimal("0.20"))
    assert leadlag_signal_at(variant, tuple(rows), date(2026, 1, 20), datetime(2026, 1, 20, 16, 30, tzinfo=UTC)) is not None
