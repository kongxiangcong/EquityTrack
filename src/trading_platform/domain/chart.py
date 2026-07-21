from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ChartBar:
    market_timestamp: str
    open_decimal: str
    high_decimal: str
    low_decimal: str
    close_decimal: str
    volume_decimal: str


@dataclass(frozen=True)
class ChartSeries:
    security_id: str
    interval: str
    adjustment_mode: str
    data_snapshot_id: str
    factor_snapshot_id: str | None
    effective_session_date: str
    freshness: str
    bars: tuple[ChartBar, ...]


@dataclass(frozen=True)
class AnnotationAnchor:
    market_timestamp: str
    exact_price_decimal: str


@dataclass(frozen=True)
class AnnotationLink:
    link_type: str
    link_id: str
    resolution_status: str = "resolved"


@dataclass(frozen=True)
class AnnotationDraft:
    security_id: str
    interval: str
    adjustment_mode: str
    data_snapshot_id: str
    factor_snapshot_id: str | None
    kind: str
    style: str
    author_id: str
    anchors: tuple[AnnotationAnchor, ...]
    links: tuple[AnnotationLink, ...] = ()


@dataclass(frozen=True)
class AnnotationVersion:
    annotation_id: str
    annotation_version_id: str
    version_no: int
    supersedes_version_id: str | None
    status: str
    draft: AnnotationDraft
    created_at: str
    content_hash: str


@dataclass(frozen=True)
class AnnotationCommand:
    invocation_id: str
    annotation_id: str | None
    expected_version_no: int
    draft: AnnotationDraft | None = None


@dataclass(frozen=True)
class AnnotationLifecycleCommand:
    invocation_id: str
    operation: str
    security_id: str
    data_snapshot_id: str
    author_id: str
    annotation_id: str | None = None
    expected_version_no: int = 0
    kind: str | None = None
    style: str | None = None
    anchors: tuple[AnnotationAnchor, ...] = ()


@dataclass(frozen=True)
class CoordinateMigration:
    invocation_id: str
    annotation_id: str
    expected_version_no: int
    target_interval: str
    target_adjustment_mode: str
    target_data_snapshot_id: str
    target_factor_snapshot_id: str | None
    anchor_mapping: Mapping[str, AnnotationAnchor]


@dataclass(frozen=True)
class CoordinateMigrationResult:
    status: str
    version: AnnotationVersion | None
    reason_code: str | None
