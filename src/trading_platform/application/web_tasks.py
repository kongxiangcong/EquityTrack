from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from trading_platform.domain.chart import (
    AnnotationLifecycleCommand,
    AnnotationVersion,
    ChartSeries,
)


@dataclass(frozen=True)
class WorkspaceUpdateCommand:
    invocation_id: str
    security_id: str
    requested_date: str
    effective_session_date: str


class ChartWorkspace(Protocol):
    def get_series(self, security_id: str, snapshot_id: str) -> ChartSeries: ...

    def get_latest_series(self, security_id: str) -> ChartSeries: ...

    def apply(self, command: AnnotationLifecycleCommand) -> AnnotationVersion: ...

    def list_history(self, security_id: str) -> tuple[AnnotationVersion, ...]: ...


class UpdateAuthorizations(Protocol):
    def authorize(self, command: WorkspaceUpdateCommand) -> Mapping[str, Any]: ...


__all__ = [
    "ChartWorkspace",
    "UpdateAuthorizations",
    "WorkspaceUpdateCommand",
]
