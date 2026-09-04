from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class MarketDataGateway(Protocol):
    async def stock_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]: ...

    async def option_contracts(self, symbol: str, **filters: Any) -> list[dict[str, Any]]: ...

    async def option_chain(self, symbol: str, **filters: Any) -> dict[str, Any]: ...

    async def option_latest_quotes(self, symbols: list[str]) -> dict[str, Any]: ...


class RecordedMarketData:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture

    async def stock_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]:
        del start, end, timeframe
        return list(self.fixture.get("stock_bars", {}).get(symbol, []))

    async def option_contracts(self, symbol: str, **filters: Any) -> list[dict[str, Any]]:
        del filters
        return list(self.fixture.get("option_contracts", {}).get(symbol, []))

    async def option_chain(self, symbol: str, **filters: Any) -> dict[str, Any]:
        del filters
        return dict(self.fixture.get("option_chains", {}).get(symbol, {}))

    async def option_latest_quotes(self, symbols: list[str]) -> dict[str, Any]:
        quotes = self.fixture.get("option_quotes", {})
        return {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}
