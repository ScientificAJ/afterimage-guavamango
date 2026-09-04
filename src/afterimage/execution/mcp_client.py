from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from afterimage.contracts.hashing import canonical_sha256


@dataclass(frozen=True)
class MCPProcess:
    command: str = "uvx"
    args: tuple[str, ...] = (
        "alpaca-mcp-server",
        "--transport",
        "stdio",
        "--env-file",
        ".env",
    )
    env: dict[str, str] = field(default_factory=dict)


class MCPClient:
    def __init__(self, process: MCPProcess) -> None:
        self.process = process
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self.tool_schemas: dict[str, str] = {}

    async def connect(self) -> None:
        if self._session is not None:
            return
        self._stack = AsyncExitStack()
        environment = {**os.environ, **self.process.env, "ALPACA_PAPER_TRADE": "true"}
        parameters = StdioServerParameters(
            command=self.process.command,
            args=list(self.process.args),
            env=environment,
        )
        read_stream, write_stream = await self._stack.enter_async_context(stdio_client(parameters))
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        await self.list_tools()

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def list_tools(self) -> list[str]:
        if self._session is None:
            raise RuntimeError("MCP client is not connected")
        response = await self._session.list_tools()
        self.tool_schemas = {
            tool.name: canonical_sha256(tool.inputSchema) for tool in response.tools
        }
        return sorted(self.tool_schemas)

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("MCP client is not connected")
        if name not in self.tool_schemas:
            raise RuntimeError(f"MCP tool is unavailable: {name}")
        result = await self._session.call_tool(name, arguments or {})
        if result.isError:
            text = " ".join(getattr(item, "text", "") for item in result.content)
            raise RuntimeError(f"MCP {name} failed: {text[:500]}")
        text_blocks = [
            getattr(item, "text", "") for item in result.content if getattr(item, "text", "")
        ]
        if not text_blocks:
            return {}
        combined = "\n".join(text_blocks)
        try:
            parsed = json.loads(combined)
        except json.JSONDecodeError:
            return {"text": combined}
        return parsed if isinstance(parsed, dict) else {"items": parsed}
