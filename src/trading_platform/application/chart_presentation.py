from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from .web_tasks import ChartWorkspace


def build_chart_workspace_projection(
    workspace: ChartWorkspace,
    security_id: str,
    snapshot_id: str | None = None,
) -> tuple[tuple[str, ...], Mapping[str, object]]:
    """Project one frozen OHLCV frame and its immutable annotations."""
    series = (
        workspace.get_series(security_id, snapshot_id)
        if snapshot_id is not None
        else workspace.get_latest_series(security_id)
    )
    history = tuple(
        version
        for version in workspace.list_history(security_id)
        if version.draft.data_snapshot_id == series.data_snapshot_id
    )
    latest_by_annotation = {}
    for version in history:
        latest_by_annotation[version.annotation_id] = version
    current = tuple(
        version
        for version in latest_by_annotation.values()
        if version.status == "active"
    )
    source_ids = (
        series.data_snapshot_id,
        *(version.annotation_version_id for version in history),
    )
    return tuple(source_ids), {
        "frame": {
            "security_id": series.security_id,
            "interval": series.interval,
            "adjustment_mode": series.adjustment_mode,
            "data_snapshot_id": series.data_snapshot_id,
            "factor_snapshot_id": series.factor_snapshot_id,
            "effective_session_date": series.effective_session_date,
            "freshness": series.freshness,
        },
        "bars": tuple(asdict(bar) for bar in series.bars),
        "annotations": tuple(_annotation(version) for version in current),
        "annotation_history": tuple(
            _annotation(version) for version in history
        ),
    }


def _annotation(version: object) -> Mapping[str, object]:
    draft = version.draft
    return {
        "annotation_id": version.annotation_id,
        "annotation_version_id": version.annotation_version_id,
        "version_no": version.version_no,
        "supersedes_version_id": version.supersedes_version_id,
        "status": version.status,
        "kind": draft.kind,
        "style": draft.style,
        "author_id": draft.author_id,
        "anchors": tuple(asdict(anchor) for anchor in draft.anchors),
        "created_at": version.created_at,
        "content_hash": version.content_hash,
    }


__all__ = ["build_chart_workspace_projection"]