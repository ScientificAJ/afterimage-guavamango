from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

EVENT_STREAMS: dict[str, list[dict[str, Any]]] = {}


async def stream_session(session_id: str, last_event_id: int = 0) -> AsyncIterator[dict[str, str]]:
    cursor = last_event_id
    idle_cycles = 0
    while idle_cycles < 15:
        events = EVENT_STREAMS.get(session_id, [])
        while cursor < len(events):
            event = events[cursor]
            cursor += 1
            idle_cycles = 0
            yield {"id": str(cursor), "event": "session", "data": json.dumps(event)}
        idle_cycles += 1
        await asyncio.sleep(0.2)
    yield {"event": "complete", "data": json.dumps({"session_id": session_id})}
