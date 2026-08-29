from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from trading_platform.result import FrozenValue, freeze_value, thaw_value


@dataclass(frozen=True)
class EvidenceItem:
    name: str
    value: FrozenValue = None
    source_id: str | None = None
    missing_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name}
        if self.missing_reason is not None:
            result["missing_reason"] = self.missing_reason
        else:
            result.update(value=thaw_value(self.value), source_id=self.source_id)
        return result


@dataclass(frozen=True)
class EvidenceSet:
    evidence_set_id: str
    as_of: str
    items: tuple[EvidenceItem, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_set_id": self.evidence_set_id,
            "as_of": self.as_of,
            "items": [item.as_dict() for item in self.items],
        }


def build_evidence_set(as_of: str, raw_items: Iterable[Mapping[str, Any]]) -> EvidenceSet:
    by_name: dict[str, EvidenceItem] = {}
    for raw in raw_items:
        if str(raw.get("as_of")) != as_of:
            raise ValueError("all evidence must share the EvidenceSet as_of")
        has_value = "value" in raw or "source_id" in raw
        has_missing = raw.get("missing_reason") is not None
        if has_value == has_missing or (has_value and ("value" not in raw or not raw.get("source_id"))):
            raise ValueError("EvidenceItem requires exactly one of value with source_id or missing_reason")
        item = EvidenceItem(
            name=str(raw.get("name", "")).strip(),
            value=freeze_value(raw.get("value")),
            source_id=str(raw["source_id"]) if raw.get("source_id") else None,
            missing_reason=str(raw["missing_reason"]) if has_missing else None,
        )
        if not item.name:
            raise ValueError("evidence name is required")
        existing = by_name.get(item.name)
        if existing is not None and existing != item:
            raise ValueError(f"conflicting duplicate evidence: {item.name}")
        by_name[item.name] = item
    items = tuple(by_name[name] for name in sorted(by_name))
    canonical = {"as_of": as_of, "items": [item.as_dict() for item in items]}
    return EvidenceSet(f"evidence-{_digest(canonical)[:20]}", as_of, items)


def evidence_set_from_dict(value: Mapping[str, Any]) -> EvidenceSet:
    items = [dict(item, as_of=value["as_of"]) for item in value.get("items", [])]
    built = build_evidence_set(str(value["as_of"]), items)
    if value.get("evidence_set_id") not in (None, built.evidence_set_id):
        raise ValueError("EvidenceSet identity does not match its content")
    return built


class FixtureEvidenceAdapter:
    """Offline Adapter with explicit, deterministic synthetic outcomes."""

    def collect(self, mode: str, as_of: str) -> EvidenceSet:
        if mode == "failure":
            raise RuntimeError("fixture provider failure")
        item_as_of = "2035-04-01T08:00:00+00:00" if mode == "stale" else as_of
        items: list[dict[str, Any]] = [
            {"name": "market_price", "value": "17.50", "source_id": "fixture-source-price", "as_of": item_as_of},
            {"name": "free_cash_flow", "value": "420", "source_id": "fixture-source-fcf", "as_of": item_as_of},
        ]
        if mode == "missing":
            items[1] = {"name": "free_cash_flow", "missing_reason": "fixture omission", "as_of": item_as_of}
        if mode == "conflict":
            items.append({"name": "market_price", "value": "99", "source_id": "fixture-source-conflict", "as_of": item_as_of})
        return build_evidence_set(item_as_of, items)


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
