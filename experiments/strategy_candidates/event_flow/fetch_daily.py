"""Acquire long-horizon daily ETF history through the authenticated Alpaca CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "data" / "alpaca_daily_2015_2026.json"
ALPACA = Path(__file__).resolve().parents[3] / ".tools" / "bin" / "alpaca"
SYMBOLS = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "TLT", "GLD")
START = "2015-01-02T00:00:00Z"
END = "2026-09-04T00:00:00Z"


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def fetch(symbol: str) -> tuple[str, list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    pages = 0
    token = ""
    while True:
        command = [
            str(ALPACA),
            "data",
            "bars",
            "--symbol",
            symbol,
            "--start",
            START,
            "--end",
            END,
            "--timeframe",
            "1Day",
            "--feed",
            "iex",
            "--adjustment",
            "split",
            "--limit",
            "10000",
            "--quiet",
        ]
        if token:
            command.extend(("--page-token", token))
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
        payload = json.loads(completed.stdout)
        rows.extend(payload.get("bars") or [])
        pages += 1
        token = payload.get("next_page_token") or ""
        if not token:
            unique = {item["t"]: item for item in rows}
            return symbol, [unique[key] for key in sorted(unique)], pages


def main() -> None:
    bars: dict[str, list[dict[str, Any]]] = {}
    pages: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, symbol): symbol for symbol in SYMBOLS}
        for future in as_completed(futures):
            symbol, rows, count = future.result()
            bars[symbol] = rows
            pages[symbol] = count
    content = {
        "schema_version": "afterimage-event-flow-alpaca-daily-v1",
        "source": "authenticated Alpaca CLI 0.0.14 historical stock bars",
        "profile": "afterimage-paper",
        "feed": "iex",
        "adjustment": "split",
        "timeframe": "1Day",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "bounds": {"start": START, "end_exclusive": END},
        "symbols": list(SYMBOLS),
        "page_counts": pages,
        "bars": {symbol: bars[symbol] for symbol in SYMBOLS},
        "source_command_template": (
            "alpaca data bars --symbol <symbol> --start 2015-01-02 --end 2026-09-04 "
            "--timeframe 1Day --feed iex --adjustment split --limit 10000 --quiet"
        ),
    }
    content["content_hash"] = canonical_hash(content)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(content, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "hash": content["content_hash"],
                "bars": {k: len(v) for k, v in bars.items()},
                "pages": pages,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
