from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


CANONICALIZATION_VERSION = "canonical-json@1"


class DatePrecision(str, Enum):
    DATE = "date"


@dataclass(frozen=True)
class CanonicalDate:
    value: date
    precision: DatePrecision = DatePrecision.DATE


def _normalize(value: Any) -> Any:
    if isinstance(value, CanonicalDate):
        return {"$type": "date", "precision": value.precision.value, "value": value.value.isoformat()}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include an offset")
        utc = value.astimezone(timezone.utc)
        return {"$type": "instant", "value": utc.isoformat(timespec="microseconds").replace("+00:00", "Z")}
    if isinstance(value, date):
        return {"$type": "date", "precision": DatePrecision.DATE.value, "value": value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimal must be finite")
        normalized = value.normalize()
        rendered = format(normalized, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return {"$type": "decimal", "value": "0" if rendered == "-0" else rendered}
    if isinstance(value, Enum):
        return {"$type": "enum", "enum": type(value).__name__, "value": value.value}
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical mapping keys must be strings")
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        members = [_normalize(item) for item in value]
        return sorted(members, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    if isinstance(value, float):
        raise TypeError("binary float is not canonical; use Decimal")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    envelope = {"canonicalization_version": CANONICALIZATION_VERSION, "value": _normalize(value)}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
