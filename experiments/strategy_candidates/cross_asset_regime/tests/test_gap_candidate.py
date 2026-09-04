from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.candidate import Costs, OptionBar, OptionFrame, StockBar
from experiments.strategy_candidates.cross_asset_regime.gap_candidate import (
    GapVariant,
    gap_signal,
    simulate_gap_trade,
)


UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")


def _gap_bars() -> tuple[StockBar, ...]:
    gaps = {"QQQ": "101.0", "IWM": "100.5", "XLK": "100.8", "XLF": "100.4", "XLE": "100.2", "XLV": "99.9", "XLY": "100.3"}
    rows = []
    for symbol in UNIVERSE:
        rows.append(StockBar(symbol, datetime(2026, 1, 20, 20, 45, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100))
        opening = Decimal(gaps[symbol])
        close = opening + (Decimal("0.2") if symbol in {"QQQ", "IWM"} else Decimal("0.05"))
        rows.append(StockBar(symbol, datetime(2026, 1, 21, 14, 30, tzinfo=UTC), opening, close, opening, close, 100))
        rows.append(StockBar(symbol, datetime(2026, 1, 21, 14, 45, tzinfo=UTC), Decimal("50"), Decimal("50"), Decimal("50"), Decimal("50"), 100))
    return tuple(rows)


def test_gap_signal_uses_prior_close_and_completed_first_bar_only() -> None:
    variant = GapVariant("g4_m10_s20", 4, Decimal("0.001"), Decimal("0.20"))
    signal = gap_signal(variant, _gap_bars(), date(2026, 1, 21))
    assert signal is not None
    assert signal.completed_at == datetime(2026, 1, 21, 14, 45, tzinfo=UTC)
    assert signal.direction == "bullish"
    assert signal.underlying == "QQQ"
    assert signal.reference_price == Decimal("101.2")
    assert signal.breadth_count == 6


def test_gap_signal_requires_independent_qqq_and_iwm_first_bar_confirmation() -> None:
    variant = GapVariant("g4_m10_s20", 4, Decimal("0.001"), Decimal("0.20"))
    rows = list(_gap_bars())
    iwm = next(index for index, bar in enumerate(rows) if bar.symbol == "IWM" and bar.timestamp == datetime(2026, 1, 21, 14, 30, tzinfo=UTC))
    original = rows[iwm]
    rows[iwm] = StockBar("IWM", original.timestamp, original.open, original.open, original.open - Decimal("0.2"), original.open - Decimal("0.2"), 100)
    assert gap_signal(variant, tuple(rows), date(2026, 1, 21)) is None


def test_gap_trade_uses_next_bar_opens_and_net_three_to_one_target() -> None:
    variant = GapVariant("g4_m10_s20", 4, Decimal("0.001"), Decimal("0.20"))
    signal = gap_signal(variant, _gap_bars(), date(2026, 1, 21))
    assert signal is not None
    frames = []
    for index in range(8):
        timestamp = signal.completed_at + timedelta(minutes=15 * index)
        if index == 0:
            long_bar = OptionBar("LONG", timestamp, Decimal("2.00"), Decimal("2.10"), Decimal("1.90"), Decimal("2.00"), 10)
            short_bar = OptionBar("SHORT", timestamp, Decimal("1.00"), Decimal("1.10"), Decimal("0.90"), Decimal("1.00"), 10)
        else:
            long_bar = OptionBar("LONG", timestamp, Decimal("3.00"), Decimal("3.10"), Decimal("2.90"), Decimal("3.00"), 10)
            short_bar = OptionBar("SHORT", timestamp, Decimal("1.20"), Decimal("1.30"), Decimal("1.10"), Decimal("1.20"), 10)
        frames.append(OptionFrame(timestamp, long_bar, short_bar))
    trade = simulate_gap_trade(signal, tuple(frames), variant, Costs(Decimal("0.03"), Decimal("0.65")))
    assert trade.entry_debit == Decimal("1.06")
    assert trade.exit_credit == Decimal("1.71")
    assert trade.net_pnl == Decimal("62.40")
    assert trade.outcome == "target"
    assert trade.return_r >= Decimal("3")
