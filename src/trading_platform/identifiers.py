from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping


def digest(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def identity(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}-{digest(value)[:20]}"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
