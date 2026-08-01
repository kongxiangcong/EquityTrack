from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class PlanContentRevisionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PlanContentDiff:
    """A deterministic, user-presentable comparison of two plan revisions."""

    added: tuple[Mapping[str, object], ...]
    modified: tuple[Mapping[str, object], ...]
    removed: tuple[Mapping[str, object], ...]
    unchanged: tuple[Mapping[str, object], ...]

    def as_dict(self) -> Mapping[str, object]:
        return {
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
            "unchanged": self.unchanged,
        }


def merge_plan_content(
    base: Mapping[str, object], revision: Mapping[str, object]
) -> Mapping[str, object]:
    """Apply a bounded content revision while preserving contract authority."""

    merged = dict(base)
    for key, value in revision.items():
        if _is_contract_metadata(key):
            if key not in base or base[key] != value:
                raise PlanContentRevisionError(
                    "PLAN_CONTENT_REVISION_CONTRACT_METADATA_DENIED"
                )
            continue
        prior = base.get(key)
        if isinstance(prior, Mapping) and isinstance(value, Mapping):
            merged[key] = merge_plan_content(prior, value)
        else:
            merged[key] = value
    return merged


def compare_plan_content(
    before: Mapping[str, object], after: Mapping[str, object]
) -> PlanContentDiff:
    """Compare complete plan content without exposing contract metadata."""

    buckets: dict[str, list[Mapping[str, object]]] = {
        "added": [],
        "modified": [],
        "removed": [],
        "unchanged": [],
    }
    _compare_mapping(
        _public_mapping(before),
        _public_mapping(after),
        path="",
        buckets=buckets,
    )
    return PlanContentDiff(
        added=tuple(buckets["added"]),
        modified=tuple(buckets["modified"]),
        removed=tuple(buckets["removed"]),
        unchanged=tuple(buckets["unchanged"]),
    )


def _is_contract_metadata(key: str) -> bool:
    return (
        key in {"schema_version", "authoring_schema_version"}
        or key.endswith(
            (
                "_id",
                "_ids",
                "_hash",
                "_ref",
                "_refs",
                "_version",
                "_key",
            )
        )
    )


def _public_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: _public_value(item)
        for key, item in value.items()
        if not _is_contract_metadata(key)
    }


def _public_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _public_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_public_value(item) for item in value)
    return value


def _compare_mapping(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    path: str,
    buckets: dict[str, list[Mapping[str, object]]],
) -> None:
    for key in sorted(set(before) | set(after)):
        item_path = f"{path}.{key}" if path else key
        if key not in before:
            buckets["added"].append(
                {"path": item_path, "value": after[key]}
            )
            continue
        if key not in after:
            buckets["removed"].append(
                {"path": item_path, "value": before[key]}
            )
            continue
        left = before[key]
        right = after[key]
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            if left or right:
                _compare_mapping(
                    left, right, path=item_path, buckets=buckets
                )
            else:
                buckets["unchanged"].append(
                    {"path": item_path, "value": left}
                )
        elif left == right:
            buckets["unchanged"].append(
                {"path": item_path, "value": left}
            )
        else:
            buckets["modified"].append(
                {"path": item_path, "before": left, "after": right}
            )


__all__ = [
    "PlanContentDiff",
    "PlanContentRevisionError",
    "compare_plan_content",
    "merge_plan_content",
]