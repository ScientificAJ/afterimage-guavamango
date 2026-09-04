from __future__ import annotations

import asyncio
import copy
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy import (
    Bar,
    OptionBar,
    StrategyParams,
    build_dry_run_order,
    candidate_decision,
    generate_session_signal,
    model_option_vertical,
    run_experiment,
    select_contract_pair,
    validate_option_signals,
)


def bars_from_930(
    closes: list[float],
    *,
    opens: list[float] | None = None,
    volumes: list[float] | None = None,
    vwaps: list[float] | None = None,
) -> list[Bar]:
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    opens = opens or [closes[0], *closes[:-1]]
    volumes = volumes or [100.0] * len(closes)
    vwaps = vwaps or closes
    return [
        Bar(
            timestamp=start + timedelta(minutes=5 * index),
            open=opens[index],
            high=max(opens[index], close) + 0.05,
            low=min(opens[index], close) - 0.05,
            close=close,
            volume=volumes[index],
            vwap=vwaps[index],
        )
        for index, close in enumerate(closes)
    ]


def dataset_fixture() -> dict[str, object]:
    def records(start_day: int, sessions: int) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for offset in range(sessions):
            session_start = datetime(2026, 1, start_day + offset, 14, 30, tzinfo=UTC)
            for index in range(20):
                opening = 100.0 + offset + index * 0.10
                close = opening + 0.10
                rows.append(
                    {
                        "symbol": "SPY",
                        "timestamp": (session_start + timedelta(minutes=5 * index))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "kind": "bar",
                        "values": {
                            "open": opening,
                            "high": close + 0.05,
                            "low": opening - 0.05,
                            "close": close,
                            "volume": 100.0,
                            "vwap": opening,
                        },
                    }
                )
        return rows

    return {
        "schema_version": "test",
        "training": {"records": records(5, 9)},
        "holdout": {"records": records(20, 2)},
    }


class SignalTimingTests(unittest.TestCase):
    def test_opening_drive_uses_only_completed_bars_and_fills_next_bar_close(self) -> None:
        # Break caught: using the 10:00 bar in the signal or filling its open.
        bars = bars_from_930(
            [100.10, 100.20, 100.30, 100.40, 100.50, 100.60, 100.80, 100.90],
            opens=[100.0, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.8],
            volumes=[120.0] * 8,
            vwaps=[100.00, 100.08, 100.16, 100.24, 100.32, 100.40, 100.50, 100.60],
        )
        params = StrategyParams(
            family="opening_drive_vwap",
            signal_minutes=30,
            drive_threshold=0.004,
            efficiency_threshold=0.70,
            rel_volume_threshold=1.0,
            breakout_buffer=0.0,
            stop_fraction=0.25,
            target_fraction=0.50,
            hold_minutes=60,
        )

        signal = generate_session_signal(bars, [[100.0] * 8] * 20, params)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.signal_at, datetime(2026, 1, 5, 15, 0, tzinfo=UTC))
        self.assertEqual(signal.entry_at, datetime(2026, 1, 5, 15, 5, tzinfo=UTC))
        self.assertEqual(signal.entry_price, 100.80)
        self.assertEqual(signal.direction, "bullish")
        self.assertEqual(signal.signal_bar_count, 6)

    def test_opening_drive_rejects_a_close_on_the_wrong_side_of_session_vwap(self) -> None:
        # Break caught: dropping the VWAP direction filter.
        bars = bars_from_930(
            [100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7],
            opens=[100.0, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6],
            vwaps=[101.0] * 7,
        )
        params = StrategyParams(
            family="opening_drive_vwap",
            signal_minutes=30,
            drive_threshold=0.004,
            efficiency_threshold=0.70,
            rel_volume_threshold=0.0,
            breakout_buffer=0.0,
            stop_fraction=0.25,
            target_fraction=0.50,
            hold_minutes=60,
        )

        self.assertIsNone(generate_session_signal(bars, [], params))


class OptionAccountingTests(unittest.TestCase):
    def test_real_history_adapter_validates_a_signal_without_order_authority(self) -> None:
        # Break caught: option validation depending on an execution call or losing symbol attribution.
        signal_at = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)

        class ReadOnlyGateway:
            async def option_contracts(
                self, symbol: str, **filters: object
            ) -> list[dict[str, object]]:
                self.assert_never_called = False
                return [
                    {
                        "symbol": "LONG",
                        "expiration_date": "2026-08-05",
                        "strike_price": "754",
                        "type": "call",
                    },
                    {
                        "symbol": "SHORT",
                        "expiration_date": "2026-08-05",
                        "strike_price": "760",
                        "type": "call",
                    },
                ]

            async def option_bars(
                self, symbols: tuple[str, ...], start: datetime, end: datetime, timeframe: str
            ) -> list[dict[str, object]]:
                del symbols, start, end, timeframe
                return [
                    {
                        "symbol": "LONG",
                        "t": signal_at.isoformat(),
                        "o": 1.9,
                        "h": 2.1,
                        "l": 1.8,
                        "c": 2.0,
                    },
                    {
                        "symbol": "SHORT",
                        "t": signal_at.isoformat(),
                        "o": 0.48,
                        "h": 0.55,
                        "l": 0.45,
                        "c": 0.5,
                    },
                    {
                        "symbol": "LONG",
                        "t": (signal_at + timedelta(minutes=5)).isoformat(),
                        "o": 2.5,
                        "h": 2.7,
                        "l": 2.4,
                        "c": 2.6,
                    },
                    {
                        "symbol": "SHORT",
                        "t": (signal_at + timedelta(minutes=5)).isoformat(),
                        "o": 0.38,
                        "h": 0.45,
                        "l": 0.35,
                        "c": 0.4,
                    },
                ]

        manifest = asyncio.run(
            validate_option_signals(
                ReadOnlyGateway(),
                [
                    {
                        "session_date": "2026-08-03",
                        "direction": "bullish",
                        "signal_at": "2026-08-03T14:00:00Z",
                        "signal_price": 753.61,
                    }
                ],
            )
        )

        self.assertEqual(manifest["requested_signals"], 1)
        self.assertEqual(manifest["validated_signals"], 1)
        self.assertEqual(manifest["results"][0]["long_symbol"], "LONG")
        self.assertAlmostEqual(manifest["net_pnl_dollars"], 59.40)

    def test_contract_pair_is_earliest_expiry_atm_long_and_six_point_short(self) -> None:
        # Break caught: retrospective cherry-picking of expiry/width or non-ATM longs.
        contracts = [
            {
                "symbol": "LATE754",
                "expiration_date": "2026-08-07",
                "strike_price": "754",
                "type": "call",
            },
            {
                "symbol": "LATE760",
                "expiration_date": "2026-08-07",
                "strike_price": "760",
                "type": "call",
            },
            {
                "symbol": "EARLY753",
                "expiration_date": "2026-08-05",
                "strike_price": "753",
                "type": "call",
            },
            {
                "symbol": "EARLY754",
                "expiration_date": "2026-08-05",
                "strike_price": "754",
                "type": "call",
            },
            {
                "symbol": "EARLY759",
                "expiration_date": "2026-08-05",
                "strike_price": "759",
                "type": "call",
            },
            {
                "symbol": "EARLY760",
                "expiration_date": "2026-08-05",
                "strike_price": "760",
                "type": "call",
            },
        ]

        long_contract, short_contract = select_contract_pair(
            contracts,
            signal_price=753.61,
            direction="bullish",
        )

        self.assertEqual(long_contract["symbol"], "EARLY754")
        self.assertEqual(short_contract["symbol"], "EARLY760")

    def test_vertical_uses_next_synchronized_closes_and_deducts_all_costs(self) -> None:
        # Break caught: same-bar lookahead or omitting exit slippage/fee reserve.
        signal_at = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
        option_bars = {
            "LONG": [
                OptionBar(signal_at, 1.90, 2.10, 1.80, 2.00),
                OptionBar(signal_at + timedelta(minutes=5), 2.50, 2.70, 2.40, 2.60),
            ],
            "SHORT": [
                OptionBar(signal_at, 0.48, 0.55, 0.45, 0.50),
                OptionBar(signal_at + timedelta(minutes=5), 0.38, 0.45, 0.35, 0.40),
            ],
        }

        trade = model_option_vertical(
            signal_at=signal_at,
            long_symbol="LONG",
            short_symbol="SHORT",
            bars=option_bars,
            stop_fraction=0.25,
            target_fraction=0.40,
            hold_minutes=60,
            slippage_per_leg=0.02,
            fee_per_contract_side=0.65,
        )

        self.assertEqual(trade.entry_at, signal_at + timedelta(minutes=5))
        self.assertAlmostEqual(trade.entry_debit, 1.54)
        self.assertAlmostEqual(trade.exit_credit, 2.16)
        self.assertAlmostEqual(trade.net_pnl_dollars, 59.40)
        self.assertEqual(trade.exit_reason, "target")
        self.assertAlmostEqual(trade.risk_dollars, 41.10)
        self.assertAlmostEqual(trade.return_r, 59.40 / 41.10)


class SelectionIsolationTests(unittest.TestCase):
    def test_holdout_mutation_cannot_change_selected_variant(self) -> None:
        # Break caught: selecting/tuning on the reserved holdout.
        fixture = dataset_fixture()
        changed = copy.deepcopy(fixture)
        for row in changed["holdout"]["records"]:
            row["values"]["close"] *= 0.90
            row["values"]["low"] = min(row["values"]["low"], row["values"]["close"])

        first = run_experiment(fixture)
        second = run_experiment(changed)

        self.assertEqual(
            first["selection"]["selected_variant_id"], second["selection"]["selected_variant_id"]
        )
        self.assertEqual(first["selection"]["selection_data"], "training_walk_forward_only")
        self.assertNotEqual(first["oos"]["net_pnl_dollars"], second["oos"]["net_pnl_dollars"])


class DryRunPayloadTests(unittest.TestCase):
    def test_promotion_fails_closed_when_oos_option_sample_is_too_small(self) -> None:
        # Break caught: promoting a lucky one-trade holdout.
        decision = candidate_decision(
            training_proxy={"sample_count": 21, "expectancy_r": 0.10},
            walk_forward_folds=[
                {"sample_count": 5, "expectancy_r": 0.10},
                {"sample_count": 5, "expectancy_r": 0.20},
                {"sample_count": 5, "expectancy_r": -0.05},
            ],
            oos_options={"sample_count": 1, "expectancy_r": 1.2},
        )

        self.assertEqual(decision["status"], "no_candidate")
        self.assertIn("oos_option_sample_at_least_10", decision["failed_gates"])

    def test_payload_is_exact_mleg_limit_and_non_executable(self) -> None:
        # Break caught: emitting a mutating request or malformed leg intent.
        payload = build_dry_run_order(
            direction="bullish",
            long_symbol="SPY260909C00800000",
            short_symbol="SPY260909C00806000",
            quantity=1,
            limit_price=1.54,
            client_order_id="afterimage-trend-dry-run",
        )

        self.assertEqual(
            payload,
            {
                "dry_run": True,
                "transport": "alpaca-mcp-local-validation",
                "client_order_id": "afterimage-trend-dry-run",
                "order_class": "mleg",
                "type": "limit",
                "time_in_force": "day",
                "qty": "1",
                "limit_price": "1.54",
                "legs": [
                    {
                        "symbol": "SPY260909C00800000",
                        "ratio_qty": "1",
                        "side": "buy",
                        "position_intent": "buy_to_open",
                    },
                    {
                        "symbol": "SPY260909C00806000",
                        "ratio_qty": "1",
                        "side": "sell",
                        "position_intent": "sell_to_open",
                    },
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
