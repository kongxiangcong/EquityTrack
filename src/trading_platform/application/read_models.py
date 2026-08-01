from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Protocol, TypeVar

from trading_platform.identity import canonical_hash

from .plan_presentation import build_plan_decision_summary
from .chart_presentation import build_chart_workspace_projection
from .web_tasks import ChartWorkspace


class ReadModelError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PortfolioWorkspaceViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    account_state_summary: Mapping[str, object]
    unresolved_decision_tasks: tuple[Mapping[str, object], ...]
    material_changes_since_last_review: tuple[str, ...]
    holding_active_plan_summaries: tuple[Mapping[str, object], ...]
    discipline_exception_summary: tuple[Mapping[str, object], ...]
    content_hash: str
    schema_version: str = "PortfolioWorkspaceView@1"

    def validate(self) -> None:
        _validate_view(self, "portfolio_workspace")


@dataclass(frozen=True)
class HoldingWorkspaceViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    security_identity: Mapping[str, object]
    position_summary: Mapping[str, object]
    active_plan_summary: Mapping[str, object] | None
    current_review: Mapping[str, object] | None
    unresolved_decision_tasks: tuple[Mapping[str, object], ...]
    material_evidence_changes: tuple[str, ...]
    key_uncertainties: tuple[str, ...]
    ability_changing_warnings: tuple[str, ...]
    drill_down_links: tuple[Mapping[str, object], ...]
    content_hash: str
    schema_version: str = "HoldingWorkspaceView@1"

    def validate(self) -> None:
        _validate_view(self, "holding_workspace")


@dataclass(frozen=True)
class TradePlanDetailViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    plan_identity: Mapping[str, object]
    decision_summary: Mapping[str, object]
    sleeve_summary: tuple[Mapping[str, object], ...]
    rules: tuple[Mapping[str, object], ...]
    latest_frozen_evaluations: tuple[Mapping[str, object], ...]
    evidence_freshness: tuple[Mapping[str, object], ...]
    rule_states: tuple[Mapping[str, object], ...]
    related_tasks: tuple[Mapping[str, object], ...]
    review_history: tuple[Mapping[str, object], ...]
    change_diffs: tuple[Mapping[str, object], ...]
    confirmation_state: Mapping[str, object] | None
    version_history: tuple[Mapping[str, object], ...]
    diagnostics: Mapping[str, object]
    content_hash: str
    schema_version: str = "TradePlanDetailView@1"

    def validate(self) -> None:
        _validate_view(self, "trade_plan_detail")


@dataclass(frozen=True)
class ReviewWorkspaceViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    review_run: Mapping[str, object] | None
    holding_outcomes: tuple[Mapping[str, object], ...]
    unresolved_or_deferred_tasks: tuple[Mapping[str, object], ...]
    plan_impact_summaries: tuple[Mapping[str, object], ...]
    proposal_summaries: tuple[Mapping[str, object], ...]
    periodic_discipline_review: Mapping[str, object] | None
    diagnostics: Mapping[str, object]
    content_hash: str
    schema_version: str = "ReviewWorkspaceView@1"

    def validate(self) -> None:
        _validate_view(self, "review_workspace")


@dataclass(frozen=True)
class ResearchIndexViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    research_items: tuple[Mapping[str, object], ...]
    content_hash: str
    schema_version: str = "ResearchIndexView@1"

    def validate(self) -> None:
        _validate_view(self, "research_index")


@dataclass(frozen=True)
class ChartWorkspaceViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    frame: Mapping[str, object]
    bars: tuple[Mapping[str, object], ...]
    annotations: tuple[Mapping[str, object], ...]
    annotation_history: tuple[Mapping[str, object], ...]
    content_hash: str
    schema_version: str = "ChartWorkspaceView@1"

    def validate(self) -> None:
        _validate_view(self, "chart_workspace")

@dataclass(frozen=True)
class AccountSnapshotEditorViewV1:
    projection_id: str
    source_ids: tuple[str, ...]
    generated_at: str
    confirmed_snapshot_summary: Mapping[str, object] | None
    current_draft: Mapping[str, object] | None
    field_lineage: tuple[Mapping[str, object], ...]
    validation: Mapping[str, object]
    capability_impacts: tuple[Mapping[str, object], ...]
    canonical_diff: Mapping[str, object] | None
    confirmation_receipt_status: Mapping[str, object] | None
    content_hash: str
    schema_version: str = "AccountSnapshotEditorView@1"

    def validate(self) -> None:
        _validate_view(self, "account_snapshot_editor")


ReadModelView = (
    PortfolioWorkspaceViewV1
    | HoldingWorkspaceViewV1
    | TradePlanDetailViewV1
    | ReviewWorkspaceViewV1
    | ResearchIndexViewV1
    | ChartWorkspaceViewV1
    | AccountSnapshotEditorViewV1
)


class ReadModelProjection(Protocol):
    def portfolio(
        self, account_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]: ...

    def holding(
        self, account_id: str, security_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]: ...

    def plan_detail(
        self, plan_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]: ...

    def review(
        self, account_id: str, review_run_id: str | None
    ) -> tuple[tuple[str, ...], Mapping[str, object]]: ...

    def research_index(
        self, security_id: str | None
    ) -> tuple[tuple[str, ...], Mapping[str, object]]: ...

    def chart_workspace(
        self,
        security_id: str,
        generated_at: str,
        snapshot_id: str | None = None,
    ) -> ChartWorkspaceViewV1:
        return self._build(
            ChartWorkspaceViewV1,
            "ChartWorkspaceView@1",
            "chart_workspace",
            generated_at,
            build_chart_workspace_projection(
                self._chart_workspace, security_id, snapshot_id
            ),
        )

    def account_editor(
        self, account_id: str
    ) -> tuple[tuple[str, ...], Mapping[str, object]]: ...


_V = TypeVar("_V", bound=ReadModelView)


class ReadModelService:
    """Builds the immutable product presentation contracts from authority reads."""

    def __init__(
        self, projection: ReadModelProjection, chart_workspace: ChartWorkspace
    ) -> None:
        self._projection = projection
        self._chart_workspace = chart_workspace

    def portfolio(
        self, account_id: str, generated_at: str
    ) -> PortfolioWorkspaceViewV1:
        return self._build(
            PortfolioWorkspaceViewV1,
            "PortfolioWorkspaceView@1",
            "portfolio_workspace",
            generated_at,
            self._projection.portfolio(account_id),
        )

    def holding(
        self,
        account_id: str,
        security_id: str,
        generated_at: str,
    ) -> HoldingWorkspaceViewV1:
        return self._build(
            HoldingWorkspaceViewV1,
            "HoldingWorkspaceView@1",
            "holding_workspace",
            generated_at,
            self._projection.holding(account_id, security_id),
        )

    def plan_detail(
        self, plan_id: str, generated_at: str
    ) -> TradePlanDetailViewV1:
        source_ids, payload = self._projection.plan_detail(plan_id)
        enriched = {
            **payload,
            "decision_summary": build_plan_decision_summary(payload),
        }
        return self._build(
            TradePlanDetailViewV1,
            "TradePlanDetailView@1",
            "trade_plan_detail",
            generated_at,
            (source_ids, enriched),
        )

    def review(
        self,
        account_id: str,
        generated_at: str,
        review_run_id: str | None = None,
    ) -> ReviewWorkspaceViewV1:
        return self._build(
            ReviewWorkspaceViewV1,
            "ReviewWorkspaceView@1",
            "review_workspace",
            generated_at,
            self._projection.review(account_id, review_run_id),
        )

    def research_index(
        self, generated_at: str, security_id: str | None = None
    ) -> ResearchIndexViewV1:
        return self._build(
            ResearchIndexViewV1,
            "ResearchIndexView@1",
            "research_index",
            generated_at,
            self._projection.research_index(security_id),
        )

    def chart_workspace(
        self,
        security_id: str,
        generated_at: str,
        snapshot_id: str | None = None,
    ) -> ChartWorkspaceViewV1:
        return self._build(
            ChartWorkspaceViewV1,
            "ChartWorkspaceView@1",
            "chart_workspace",
            generated_at,
            build_chart_workspace_projection(
                self._chart_workspace, security_id, snapshot_id
            ),
        )

    def account_editor(
        self, account_id: str, generated_at: str
    ) -> AccountSnapshotEditorViewV1:
        return self._build(
            AccountSnapshotEditorViewV1,
            "AccountSnapshotEditorView@1",
            "account_snapshot_editor",
            generated_at,
            self._projection.account_editor(account_id),
        )

    @staticmethod
    def _build(
        view_type: type[_V],
        schema_version: str,
        prefix: str,
        generated_at: str,
        projected: tuple[
            tuple[str, ...], Mapping[str, object]
        ],
    ) -> _V:
        try:
            generated = datetime.fromisoformat(generated_at)
        except ValueError as error:
            raise ReadModelError("READ_MODEL_GENERATED_AT_INVALID") from error
        if generated.tzinfo is None:
            raise ReadModelError("READ_MODEL_GENERATED_AT_INVALID")
        source_ids, payload = projected
        normalized_sources = tuple(sorted(set(source_ids)))
        expected_fields = {
            field.name
            for field in fields(view_type)
            if field.name
            not in {
                "projection_id",
                "source_ids",
                "generated_at",
                "content_hash",
                "schema_version",
            }
        }
        if set(payload) != expected_fields:
            raise ReadModelError("READ_MODEL_PROJECTION_FIELDS_INVALID")
        frozen_payload = {
            key: _freeze(value) for key, value in payload.items()
        }
        identity = {
            "schema_version": schema_version,
            "source_ids": normalized_sources,
            "generated_at": generated_at,
            **frozen_payload,
        }
        content_hash = canonical_hash(identity)
        view = view_type(
            projection_id=f"{prefix}_{content_hash[:24]}",
            source_ids=normalized_sources,
            generated_at=generated_at,
            content_hash=content_hash,
            schema_version=schema_version,
            **frozen_payload,
        )
        view.validate()
        return view


def _validate_view(view: ReadModelView, prefix: str) -> None:
    try:
        generated = datetime.fromisoformat(view.generated_at)
    except ValueError as error:
        raise ReadModelError("READ_MODEL_INVALID") from error
    identity = {
        field.name: getattr(view, field.name)
        for field in fields(view)
        if field.name not in {"projection_id", "content_hash"}
    }
    if (
        generated.tzinfo is None
        or tuple(sorted(set(view.source_ids))) != view.source_ids
        or view.content_hash != canonical_hash(identity)
        or view.projection_id
        != f"{prefix}_{view.content_hash[:24]}"
    ):
        raise ReadModelError("READ_MODEL_INVALID")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


__all__ = [
    "AccountSnapshotEditorViewV1",
    "ChartWorkspaceViewV1",
    "HoldingWorkspaceViewV1",
    "PortfolioWorkspaceViewV1",
    "ReadModelError",
    "ReadModelService",
    "ResearchIndexViewV1",
    "ReviewWorkspaceViewV1",
    "TradePlanDetailViewV1",
]
