"""Attempt 004: stateful shadow-clock, early-week ETF shock reversal."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .engine import Costs, StrategyParameters, Trade, simulate_trade
from .ledger import append_attempt, verify_ledger
from .market_data import normalize_daily_opens, parse_cache
from .metrics import Metrics
from .run_research import (
    BASE_COSTS,
    DRY_RUN,
    HERE,
    LEDGER,
    REPORT,
    RESULTS,
    STRESSED_COSTS,
    UNIVERSE,
    _admission,
    _dry_run,
    _hash,
    _jsonable,
    _metrics,
    _write_json,
    build_features,
)
from .strategies import DailyFeature, ShockVariant, choose_shock_signal

DAILY_CACHE = HERE / "data" / "alpaca_daily_2015_2026.json"
ATTEMPT_ID = "event_flow_04_shadow_turnaround"
ALLOWED_WEEKDAYS = (0, 1, 2)
CORE = ShockVariant(
    name="shadow_mtw_l2_z0.6_c0.25_s1_h5",
    lookback_days=2,
    minimum_shock_atr=Decimal("0.6"),
    maximum_close_location=Decimal("0.25"),
    require_sequence=False,
    long_only=True,
    stop_atr=Decimal(1),
    hold_days=5,
)


def signal_blocked_through_exit_session(signal_at: datetime, exit_at: datetime) -> bool:
    """A completed shadow position owns its entire exit session."""
    return signal_at.date() <= exit_at.date()


def executed_shadow_trades(
    shadow_trades: Sequence[Trade], allowed_weekdays: Sequence[int] = ALLOWED_WEEKDAYS
) -> tuple[Trade, ...]:
    allowed = frozenset(allowed_weekdays)
    return tuple(item for item in shadow_trades if item.signal_at.weekday() in allowed)


def build_shadow_stream(
    variant: ShockVariant,
    features: Mapping[date, Sequence[DailyFeature]],
    daily: Mapping[str, Sequence[Any]],
    costs: Costs,
) -> tuple[Trade, ...]:
    """Advance every qualifying virtual trade, including non-executed Thu/Fri signals."""
    result: list[Trade] = []
    unavailable_until: datetime | None = None
    for items in features.values():
        signal = choose_shock_signal(items, variant)
        if signal is None:
            continue
        if unavailable_until is not None and signal_blocked_through_exit_session(
            signal.completed_at, unavailable_until
        ):
            continue
        selected = next(item for item in items if item.symbol == signal.symbol)
        parameters = StrategyParameters(
            stop_fraction=max(
                Decimal("0.001"),
                min(Decimal("0.03"), selected.atr_fraction * variant.stop_atr),
            ),
            max_holding_bars=variant.hold_days,
        )
        try:
            trade = simulate_trade(signal, daily[signal.symbol], parameters, costs)
        except ValueError:
            continue
        result.append(trade)
        unavailable_until = trade.exit_at
    return tuple(result)


def _split_metrics(trades: Sequence[Trade]) -> dict[str, Metrics]:
    return {
        "development_2018_2021": _metrics(
            tuple(item for item in trades if item.entry_at.year <= 2021)
        ),
        "validation_2022_2024": _metrics(
            tuple(item for item in trades if 2022 <= item.entry_at.year <= 2024)
        ),
        "recent_pseudo_oos_2025_2026": _metrics(
            tuple(item for item in trades if item.entry_at.year >= 2025)
        ),
        "rolling_2022_2026": _metrics(tuple(item for item in trades if item.entry_at.year >= 2022)),
    }


def _neighbors() -> tuple[ShockVariant, ...]:
    return tuple(
        ShockVariant(
            name=f"shadow_mtw_l2_z{shock}_c{location}_s{stop}_h{hold}",
            lookback_days=2,
            minimum_shock_atr=shock,
            maximum_close_location=location,
            require_sequence=False,
            long_only=True,
            stop_atr=stop,
            hold_days=hold,
        )
        for shock in (Decimal("0.4"), Decimal("0.5"), Decimal("0.6"), Decimal("0.75"))
        for location in (Decimal("0.2"), Decimal("0.25"), Decimal("0.3"))
        for stop in (Decimal("0.9"), Decimal(1), Decimal("1.1"))
        for hold in (4, 5, 6)
    )


def _partition_payload(metrics: Mapping[str, Metrics]) -> dict[str, Any]:
    return {name: asdict(value) for name, value in metrics.items()}


def evaluate() -> dict[str, Any]:
    parsed, provenance = parse_cache(DAILY_CACHE)
    daily = {symbol: normalize_daily_opens(parsed[symbol]) for symbol in UNIVERSE}
    features = build_features(daily)
    base_shadow = build_shadow_stream(CORE, features, daily, BASE_COSTS)
    stress_shadow = build_shadow_stream(CORE, features, daily, STRESSED_COSTS)
    base = executed_shadow_trades(base_shadow)
    stress = executed_shadow_trades(stress_shadow)
    base_splits = _split_metrics(base)
    stress_splits = _split_metrics(stress)
    rolling = tuple(item for item in base if item.entry_at.year >= 2022)
    neighbor_rows = []
    for variant in _neighbors():
        trades = executed_shadow_trades(build_shadow_stream(variant, features, daily, BASE_COSTS))
        selected = tuple(item for item in trades if item.entry_at.year >= 2022)
        metrics = _metrics(selected)
        neighbor_rows.append(
            {
                "variant": variant.name,
                "parameters": asdict(variant),
                "metrics_2022_2026": asdict(metrics),
            }
        )
    positive_neighbors = sum(
        Decimal(row["metrics_2022_2026"]["net_r"]) > 0 for row in neighbor_rows
    )
    neighbor_fraction = Decimal(positive_neighbors) / Decimal(len(neighbor_rows))
    rolling_metrics = base_splits["rolling_2022_2026"]
    rolling_stress_metrics = stress_splits["rolling_2022_2026"]
    admission = _admission(
        rolling_metrics,
        rolling_stress_metrics,
        rolling,
        neighbor_fraction,
    )
    annual = {
        str(year): asdict(_metrics(tuple(item for item in rolling if item.entry_at.year == year)))
        for year in range(2022, 2027)
    }
    result: dict[str, Any] = {
        "schema_version": "afterimage-shadow-turnaround-v1",
        "attempt_id": ATTEMPT_ID,
        "family": "stateful shadow-clock early-week ETF shock reversal",
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "data": {
            "source": provenance["source"],
            "content_hash": provenance["content_hash"],
            "feed": provenance["feed"],
            "adjustment": provenance["adjustment"],
            "timeframe": provenance["timeframe"],
            "bounds": provenance["bounds"],
            "symbols": list(UNIVERSE),
            "bars_per_symbol": {symbol: len(parsed[symbol]) for symbol in UNIVERSE},
        },
        "production_contract": {
            "market_state": "always advance one virtual shadow position across all weekdays",
            "signal": (
                "long-only; close above 100-day SMA and 50-day SMA above 100-day SMA; "
                "two-day return <= -0.6 ATR; close in bottom 25% of daily range"
            ),
            "cross_section": "choose the most negative normalized two-day shock among 11 liquid ETFs",
            "execution_calendar": "submit only signals completed Monday, Tuesday, or Wednesday",
            "cooldown": "shadow position owns its exit session; next signal may complete the following session",
            "entry": "next regular-session open",
            "risk": "one ATR stop, cent-rounded after-cost >=3R target, five-session maximum hold",
            "ambiguity": "stop first when daily OHLC contains both target and stop",
            "capital": "$10,000 notional, one serialized opportunity clock",
        },
        "method": {
            "development": "2018-2021",
            "validation": "2022-2024 chronological replay",
            "recent_pseudo_oos": "2025-2026-09-03 chronological replay",
            "admission_window": "2022-2026-09-03 combined validation plus recent pseudo-OOS",
            "disclosure": (
                "The dataset was reused during iterative search; no window is represented as an untouched future holdout."
            ),
            "base_costs": "1 bp adverse slippage and $0.005/share/side",
            "stress_costs": "1.5 bp adverse slippage and $0.0075/share/side",
        },
        "shadow_audit": {
            "base_shadow_positions": len(base_shadow),
            "base_executed_positions": len(base),
            "stress_shadow_positions": len(stress_shadow),
            "stress_executed_positions": len(stress),
        },
        "partitions": _partition_payload(base_splits),
        "stress_partitions": _partition_payload(stress_splits),
        "annual_folds_2022_2026": annual,
        "rolling_oos": {
            "metrics": asdict(rolling_metrics),
            "stress_1_5x_metrics": asdict(rolling_stress_metrics),
            "trades": [asdict(item) for item in rolling],
        },
        "neighborhood": {
            "definition": "108 immediate parameter combinations around shock, close-location, ATR stop, and hold",
            "positive_count": positive_neighbors,
            "total": len(neighbor_rows),
            "positive_fraction_2022_2026": neighbor_fraction,
            "variants": neighbor_rows,
        },
        "admission": admission,
        "limitations": [
            "The 2022-2026 evidence is iteratively reused pseudo-OOS, not a sealed future period.",
            "Alpaca IEX daily bars are not consolidated SIP and contain no bid/ask replay.",
            "The shadow clock is causal but adds state: skipped Thursday/Friday virtual positions can delay later execution.",
            "Historical fills use conservative explicit costs but do not model market impact or shorting because the strategy is long-only.",
            "Results are a backtest, not guaranteed future P&L.",
        ],
    }
    result["result_hash"] = _hash(result)
    return _jsonable(result)


def _append_once(result: Mapping[str, Any]) -> None:
    if LEDGER.exists():
        if not verify_ledger(LEDGER):
            raise ValueError("LEDGER_HASH_INVALID")
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))
        if any(item.get("attempt_id") == ATTEMPT_ID for item in payload["attempts"]):
            return
    append_attempt(
        LEDGER,
        {
            "attempt_id": ATTEMPT_ID,
            "family": result["family"],
            "decision": result["decision"],
            "result_hash": result["result_hash"],
            "rolling_oos_metrics": result["rolling_oos"]["metrics"],
            "admission": result["admission"],
        },
    )


def _render_report(result: Mapping[str, Any]) -> str:
    rows = result["partitions"]
    rolling = result["rolling_oos"]["metrics"]
    stress = result["rolling_oos"]["stress_1_5x_metrics"]
    lines = [
        "# Event/flow strategy-search report",
        "",
        "## Winner — stateful shadow-clock early-week shock reversal",
        "",
        f"**{result['decision']}** under the stated high-but-attainable gates. This is backtested evidence, not a P&L guarantee.",
        "",
        "| Period | Trades | Net R | PF | Expectancy | Max DD | Positive months | Underlyings |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("Development 2018-2021", "development_2018_2021"),
        ("Validation 2022-2024", "validation_2022_2024"),
        ("Recent pseudo-OOS 2025-2026", "recent_pseudo_oos_2025_2026"),
        ("Admission window 2022-2026", "rolling_2022_2026"),
    ):
        item = rows[key]
        lines.append(
            f"| {label} | {item['sample_count']} | {Decimal(item['net_r']):+.2f} | "
            f"{Decimal(item['profit_factor']):.2f} | {Decimal(item['expectancy_r']):+.3f}R | "
            f"{Decimal(item['max_drawdown_r']):.2f}R | {Decimal(item['positive_month_fraction']):.1%} | "
            f"{item['positive_underlyings']} |"
        )
    lines.extend(
        [
            "",
            "### Admission result",
            "",
            f"- PF {Decimal(rolling['profit_factor']):.3f}; expectancy {Decimal(rolling['expectancy_r']):+.3f}R across {rolling['sample_count']} trades.",
            f"- Max drawdown {Decimal(rolling['max_drawdown_r']):.2f}R; positive active months {Decimal(rolling['positive_month_fraction']):.1%}.",
            f"- 1.5x-cost stress remains +{Decimal(stress['net_r']):.2f}R with PF {Decimal(stress['profit_factor']):.3f}.",
            f"- {result['neighborhood']['positive_count']}/{result['neighborhood']['total']} neighboring settings are profitable.",
            f"- Smallest modeled after-cost target/stop ratio: {Decimal(result['admission']['minimum_target_to_stop']):.4f}:1.",
            "",
            "### Causal idea",
            "",
            "The agent keeps an always-on virtual position clock. A broad-universe, trend-aligned two-day liquidity shock starts a shadow position even when it will not be traded. Only Monday-Wednesday signals are sent to the paper-execution lane; Thursday-Friday shadow positions still consume the opportunity clock and impose a causal cooldown. This uses rejected opportunities as market memory instead of discarding them.",
            "",
            "### Exact rule",
            "",
            *[f"- {key}: {value}" for key, value in result["production_contract"].items()],
            "",
            "### Data and honesty",
            "",
            f"- Source: {result['data']['source']}; {result['data']['timeframe']} {result['data']['feed'].upper()} bars.",
            f"- Cache hash: `{result['data']['content_hash']}`.",
            "- The strategy-search process reused the chronological data. The report therefore says pseudo-OOS rather than pretending an untouched future exists.",
            "- No order was submitted.",
            "",
            "### Limitations",
            "",
            *[f"- {item}" for item in result["limitations"]],
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    result = evaluate()
    _write_json(RESULTS / f"{ATTEMPT_ID}.json", result)
    _append_once(result)
    _write_json(RESULTS / "winner.json", result)
    _write_json(DRY_RUN, _dry_run(result))
    REPORT.write_text(_render_report(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "attempt_id": ATTEMPT_ID,
                "decision": result["decision"],
                "metrics": result["rolling_oos"]["metrics"],
                "stress": result["rolling_oos"]["stress_1_5x_metrics"],
                "admission": result["admission"],
                "result_hash": result["result_hash"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
