from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import orjson
from pydantic import BaseModel


def _default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported canonical value: {type(value)!r}")


def canonical_json(value: Any) -> bytes:
    return orjson.dumps(value, default=_default, option=orjson.OPT_SORT_KEYS | orjson.OPT_UTC_Z)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
