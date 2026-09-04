"""Acquire split-adjusted 15-minute ETF bars through the authenticated Alpaca CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "data" / "alpaca_15min.json"
ALPACA = Path(__file__).resolve().parents[3] / ".tools" / "bin" / "alpaca"
SYMBOLS = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "TLT", "GLD")
CHUNKS = (
    ("2024-01-02T00:00:00Z", "2025-01-01T00:00:00Z"),
    ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ("2026-01-01T00:00:00Z", "2026-09-04T00:00:00Z"),
)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def fetch_page(symbol: str, start: str, end: str, page_token: str = "") -> dict[str, Any]:
    command = [
        str(ALPACA),
        "data",
        "bars",
        "--symbol",
        symbol,
        "--start",
        start,
        "--end",
        end,
        "--timeframe",
        "15Min",
        "--feed",
        "iex",
        "--adjustment",
        "split",
        "--limit",
        "10000",
        "--quiet",
    ]
    if page_token:
        command.extend(("--page-token", page_token))
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
    return json.loads(completed.stdout)


def fetch_chunk(symbol: str, start: str, end: str) -> tuple[str, str, list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    token = ""
    pages = 0
    while True:
        payload = fetch_page(symbol, start, end, token)
        pages += 1
        rows.extend(payload.get("bars") or [])
        token = payload.get("next_page_token") or ""
        if not token:
            return symbol, start, rows, pages


def main() -> None:
    bars: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in SYMBOLS}
    pages: dict[str, int] = {symbol: 0 for symbol in SYMBOLS}
    jobs = [(symbol, start, end) for symbol in SYMBOLS for start, end in CHUNKS]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_chunk, *job): job for job in jobs}
        for future in as_completed(futures):
            symbol, _start, rows, count = future.result()
            bars[symbol].extend(rows)
            pages[symbol] += count
    for symbol, symbol_bars in bars.items():
        unique = {item["t"]: item for item in symbol_bars}
        bars[symbol] = [unique[key] for key in sorted(unique)]
    content = {
        "schema_version": "afterimage-event-flow-alpaca-bars-v1",
        "source": "authenticated Alpaca CLI 0.0.14 historical stock bars",
        "profile": "afterimage-paper",
        "feed": "iex",
        "adjustment": "split",
        "timeframe": "15Min",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "bounds": {"start": CHUNKS[0][0], "end_exclusive": CHUNKS[-1][1]},
        "symbols": list(SYMBOLS),
        "page_counts": pages,
        "bars": bars,
        "source_command_template": (
            "alpaca data bars --symbol <symbol> --start <start> --end <end> "
            "--timeframe 15Min --feed iex --adjustment split --limit 10000 --quiet"
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
