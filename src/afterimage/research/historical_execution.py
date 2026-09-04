from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from afterimage.contracts.models import ExecutionIntent, MarketRecord
from afterimage.execution.alpaca_gateway import AccountPreflight
from afterimage.strategies.base import MarketFrame


@dataclass(frozen=True)
class HistoricalReplayCase:
    """A causal strategy packet plus separately held-out post-decision bars."""

    signal_date: date
    signal_cutoff: datetime
    causal_frame: MarketFrame
    future_bars: tuple[dict[str, Any], ...]
    published_trade: dict[str, Any]
    source: str
    feed: str
    data_content_hash: str
    result_hash: str


class HistoricalReplayGateway:
    """Causal market-data replay with the official gateway retained for dry-run rendering."""

    def __init__(self, delegate: Any, case: HistoricalReplayCase) -> None:
        self.delegate = delegate
        self.case = case
        self.execution_enabled = False
        self.observed_at = datetime.fromisoformat(str(case.published_trade["entry_at"])).astimezone(
            UTC
        ) + timedelta(minutes=5)

    async def preflight(self, expected_account_id_hash: str) -> AccountPreflight:
        checked: AccountPreflight = await self.delegate.preflight(expected_account_id_hash)
        account = checked.account.model_copy(update={"timestamp": self.observed_at})
        return checked.model_copy(
            update={
                "account": account,
                "market_open": True,
                "clock": {
                    "is_open": True,
                    "timestamp": self.observed_at.isoformat(),
                    "historical_replay": True,
                    "causal_signal_cutoff": self.case.signal_cutoff.isoformat(),
                },
            }
        )

    async def stock_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1Day",
    ) -> list[dict[str, Any]]:
        if timeframe != "1Day" or end > self.case.signal_cutoff:
            raise ValueError("HISTORICAL_REPLAY_CAUSAL_BOUNDARY_VIOLATION")
        return [
            {
                "t": record.timestamp.isoformat(),
                "o": record.values["open"],
                "h": record.values["high"],
                "l": record.values["low"],
                "c": record.values["close"],
                "v": record.values["volume"],
            }
            for record in self.case.causal_frame.records
            if record.symbol == symbol and start <= record.timestamp <= end
        ]

    async def stock_snapshot(self, symbol: str) -> dict[str, Any]:
        if symbol != str(self.case.published_trade["symbol"]):
            raise ValueError("HISTORICAL_REPLAY_CANDIDATE_MISMATCH")
        ask = Decimal(str(self.case.published_trade["entry_fill"]))
        raw_entry = Decimal(str(self.case.published_trade["raw_entry"]))
        bid = raw_entry * (Decimal(1) - Decimal("0.0001"))
        return {
            "symbol": symbol,
            "source": self.case.source,
            "feed": self.case.feed,
            "pricing_basis": "next-session Alpaca daily open plus declared 1bp entry slippage",
            "latestQuote": {
                "bp": str(bid),
                "ap": str(ask),
                "t": self.observed_at.isoformat(),
            },
        }

    async def dry_run_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, Any]:
        result = await self.delegate.dry_run_order(intent, client_order_id)
        return {
            **result,
            "submitted": False,
            "historical_replay": True,
            "claim": "official Alpaca CLI dry-run rendering; no order submitted",
        }


def load_historical_replay_case(
    cache_path: str | Path,
    result_path: str | Path,
    signal_date: date,
) -> HistoricalReplayCase:
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    if not isinstance(cache, dict) or not isinstance(result, dict):
        raise TypeError("HISTORICAL_REPLAY_PAYLOAD_INVALID")
    bars_by_symbol = cache.get("bars")
    trades = result.get("rolling_oos", {}).get("trades")
    if not isinstance(bars_by_symbol, dict) or not isinstance(trades, list):
        raise TypeError("HISTORICAL_REPLAY_DATA_MISSING")
    matches = [
        item
        for item in trades
        if isinstance(item, dict)
        and datetime.fromisoformat(str(item.get("signal_at"))).date() == signal_date
    ]
    if len(matches) != 1:
        raise ValueError("HISTORICAL_REPLAY_SIGNAL_NOT_UNIQUE")
    trade = matches[0]
    signal_cutoff = datetime.fromisoformat(str(trade["signal_at"])).astimezone(UTC)
    lookback_start = signal_cutoff - timedelta(days=365)
    received_at = signal_cutoff
    records: list[MarketRecord] = []
    for symbol, raw_bars in bars_by_symbol.items():
        if not isinstance(symbol, str) or not isinstance(raw_bars, list):
            raise TypeError("HISTORICAL_REPLAY_BARS_INVALID")
        for raw in raw_bars:
            if not isinstance(raw, dict):
                raise TypeError("HISTORICAL_REPLAY_BAR_INVALID")
            timestamp = datetime.fromisoformat(str(raw["t"])).astimezone(UTC)
            if lookback_start <= timestamp <= signal_cutoff:
                records.append(
                    MarketRecord(
                        symbol=symbol,
                        timestamp=timestamp,
                        received_at=received_at,
                        source=str(cache.get("source", "authenticated Alpaca historical bars")),
                        feed=str(cache.get("feed", "iex")),
                        kind="bar",
                        values={
                            "open": raw["o"],
                            "high": raw["h"],
                            "low": raw["l"],
                            "close": raw["c"],
                            "volume": raw["v"],
                        },
                    )
                )
    symbol = str(trade["symbol"])
    symbol_bars = bars_by_symbol.get(symbol)
    if not isinstance(symbol_bars, list):
        raise TypeError("HISTORICAL_REPLAY_SYMBOL_MISSING")
    future = tuple(
        {**raw, "t": datetime.fromisoformat(str(raw["t"])).astimezone(UTC).isoformat()}
        for raw in symbol_bars
        if isinstance(raw, dict)
        and datetime.fromisoformat(str(raw["t"])).astimezone(UTC) > signal_cutoff
    )[:5]
    if not records or not future:
        raise ValueError("HISTORICAL_REPLAY_WINDOW_INCOMPLETE")
    return HistoricalReplayCase(
        signal_date=signal_date,
        signal_cutoff=signal_cutoff,
        causal_frame=MarketFrame(
            symbol=str(trade["symbol"]),
            cutoff=signal_cutoff,
            records=tuple(sorted(records, key=lambda item: (item.timestamp, item.symbol))),
            context={},
        ),
        future_bars=future,
        published_trade=trade,
        source=str(cache.get("source", "authenticated Alpaca historical bars")),
        feed=str(cache.get("feed", "iex")),
        data_content_hash=str(cache.get("content_hash", "")),
        result_hash=str(result.get("result_hash", "")),
    )


def reveal_equity_outcome(
    case: HistoricalReplayCase,
    *,
    entry_price: Decimal,
    stop_price: Decimal,
    target_price: Decimal,
    modeled_cost_per_share: Decimal,
    quantity: int,
) -> dict[str, Any]:
    """Reveal post-signal Alpaca bars only after an order vector has been frozen."""

    if not (quantity > 0 and stop_price < entry_price < target_price):
        raise ValueError("HISTORICAL_REPLAY_ORDER_VECTOR_INVALID")
    outcome = "time"
    exit_price = Decimal(str(case.future_bars[-1]["c"]))
    exit_at = str(case.future_bars[-1]["t"])
    for bar in case.future_bars:
        low = Decimal(str(bar["l"]))
        high = Decimal(str(bar["h"]))
        if low <= stop_price:
            outcome = "stop"
            exit_price = stop_price
            exit_at = str(bar["t"])
            break
        if high >= target_price:
            outcome = "target"
            exit_price = target_price
            exit_at = str(bar["t"])
            break
    risk_per_share = entry_price - stop_price + modeled_cost_per_share
    net_per_share = exit_price - entry_price - modeled_cost_per_share
    modeled_net_pnl = net_per_share * Decimal(quantity)
    realized_r = net_per_share / risk_per_share
    return {
        "outcome": outcome,
        "entry_price": str(entry_price),
        "stop_price": str(stop_price),
        "target_price": str(target_price),
        "exit_price": str(exit_price),
        "exit_at": exit_at,
        "quantity": quantity,
        "modeled_cost_per_share": str(modeled_cost_per_share),
        "modeled_net_pnl_dollars": str(modeled_net_pnl.quantize(Decimal("0.01"))),
        "realized_r": str(realized_r),
        "future_bar_count": len(case.future_bars),
        "same_bar_ambiguity": "stop_first",
        "future_bars_revealed_after_decision": True,
        "claim": "historical execution replay on real Alpaca bars; not broker P&L",
    }
