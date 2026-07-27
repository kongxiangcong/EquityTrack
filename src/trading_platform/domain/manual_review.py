from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import Mapping

from trading_platform.identity import canonical_hash


class ManualReviewError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReviewOutcome(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    MONITOR = "MONITOR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DRAFT_UPDATE_PROPOSED = "DRAFT_UPDATE_PROPOSED"


@dataclass(frozen=True)
class ManualReviewHolding:
    security_id: str
    position_identity: str
    active_plan_id: str | None
    plan_version_id: str | None
    strategy_version_id: str | None
    sleeve_graph: tuple[Mapping[str, object], ...]
    data_snapshot_ids: tuple[str, ...]
    research_run_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    market_snapshot_ids: tuple[str, ...]
    hard_rule_evaluations: tuple[Mapping[str, object], ...]
    review_rule_routing: tuple[Mapping[str, object], ...]
    conflict_resolution: Mapping[str, object]
    evaluation_resolution: str | None
    unable_reasons: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualReviewContext:
    account_id: str
    account_snapshot_version_id: str
    account_snapshot_hash: str
    account_snapshot_cutoff: str
    estimated_state_hash: str
    calendar_identity: str
    policy_identities: tuple[str, ...]
    holdings: tuple[ManualReviewHolding, ...]


@dataclass(frozen=True)
class ManualPortfolioReviewRun:
    review_run_id: str
    workflow_run_id: str
    account_id: str
    requested_at: str
    selected_complete_session: str
    timezone: str
    window_start_exclusive: str
    window_end_inclusive: str
    prior_successful_review_run_id: str | None
    status: str
    input_fingerprint: str
    created_at: str
    completed_at: str | None = None
    schema_version: str = "ManualPortfolioReviewRun@1"

    def validate(self) -> None:
        try:
            requested = datetime.fromisoformat(self.requested_at)
            start = date.fromisoformat(self.window_start_exclusive)
            selected = date.fromisoformat(self.selected_complete_session)
            created = datetime.fromisoformat(self.created_at)
            completed = (
                datetime.fromisoformat(self.completed_at)
                if self.completed_at is not None
                else None
            )
        except ValueError as error:
            raise ManualReviewError("MANUAL_REVIEW_TIME_INVALID") from error
        if (
            self.schema_version != "ManualPortfolioReviewRun@1"
            or not self.review_run_id
            or not self.workflow_run_id
            or not self.account_id
            or requested.tzinfo is None
            or created.tzinfo is None
            or self.timezone != "Asia/Shanghai"
            or start >= selected
            or requested.date() < selected
            or self.window_end_inclusive != self.selected_complete_session
            or self.status
            not in {
                "queued",
                "running",
                "succeeded",
                "succeeded_with_limits",
                "failed",
            }
            or not self.input_fingerprint
            or (
                self.status in {"queued", "running"}
                and completed is not None
            )
            or (
                self.status
                in {"succeeded", "succeeded_with_limits", "failed"}
                and completed is None
            )
        ):
            raise ManualReviewError("MANUAL_REVIEW_RUN_INVALID")


@dataclass(frozen=True)
class ManualPortfolioReviewItem:
    review_item_id: str
    review_run_id: str
    account_id: str
    security_id: str
    position_identity: str
    account_snapshot_version_id: str
    account_snapshot_hash: str
    estimated_state_hash: str
    active_plan_id: str | None
    plan_version_id: str | None
    strategy_version_id: str | None
    sleeve_graph: tuple[Mapping[str, object], ...]
    data_snapshot_ids: tuple[str, ...]
    research_run_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    market_snapshot_ids: tuple[str, ...]
    hard_rule_evaluations: tuple[Mapping[str, object], ...]
    review_rule_routing: tuple[Mapping[str, object], ...]
    conflict_resolution: Mapping[str, object]
    outcome: ReviewOutcome
    material_changes: tuple[str, ...]
    unable_reasons: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    decision_task_ids: tuple[str, ...]
    plan_impact_assessment_ids: tuple[str, ...]
    plan_change_proposal_ids: tuple[str, ...]
    content_hash: str
    created_at: str
    schema_version: str = "SecurityReviewItem@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key != "content_hash"
        }
        if (
            self.schema_version != "SecurityReviewItem@1"
            or not self.review_item_id
            or not self.review_run_id
            or not self.account_id
            or not self.security_id
            or not self.position_identity
            or not self.account_snapshot_version_id
            or not self.account_snapshot_hash
            or not self.estimated_state_hash
            or self.content_hash != canonical_hash(identity)
            or (
                self.outcome is ReviewOutcome.NO_CHANGE
                and (
                    self.decision_task_ids
                    or self.plan_impact_assessment_ids
                    or self.plan_change_proposal_ids
                )
            )
            or (
                self.outcome is ReviewOutcome.MONITOR
                and self.decision_task_ids
            )
            or (
                self.outcome is ReviewOutcome.DRAFT_UPDATE_PROPOSED
                and not self.plan_change_proposal_ids
            )
        ):
            raise ManualReviewError("MANUAL_REVIEW_ITEM_INVALID")


@dataclass(frozen=True)
class ManualPortfolioReviewCheckpoint:
    checkpoint_id: str
    review_run_id: str
    security_id: str
    stage: str
    input_fingerprint: str
    status: str
    manifest_id: str | None
    attempt_no: int
    committed_at: str | None
    schema_version: str = "ReviewCheckpoint@1"

    def validate(self) -> None:
        if (
            self.schema_version != "ReviewCheckpoint@1"
            or not self.checkpoint_id
            or not self.review_run_id
            or not self.security_id
            or not self.stage
            or not self.input_fingerprint
            or self.status
            not in {"pending", "running", "committed", "failed"}
            or self.attempt_no < 1
            or (
                self.status == "committed"
                and (not self.manifest_id or not self.committed_at)
            )
        ):
            raise ManualReviewError("MANUAL_REVIEW_CHECKPOINT_INVALID")


@dataclass(frozen=True)
class ManualPortfolioReviewManifest:
    manifest_id: str
    review_run_id: str
    object_sha256: str
    artifact_manifest_id: str | None
    cutoff_identity: str
    calendar_identity: str
    policy_identities: tuple[str, ...]
    account_snapshot_version_id: str
    estimated_state_hash: str
    active_plan_version_ids: tuple[str, ...]
    data_snapshot_ids: tuple[str, ...]
    research_run_ids: tuple[str, ...]
    market_snapshot_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    rule_evaluator_conflict_versions: tuple[str, ...]
    review_item_ids: tuple[str, ...]
    checkpoint_ids: tuple[str, ...]
    decision_task_ids: tuple[str, ...]
    assessment_ids: tuple[str, ...]
    proposal_ids: tuple[str, ...]
    code_identity: str
    config_identity: str
    content_hash: str
    created_at: str
    schema_version: str = "ManualPortfolioReviewManifest@1"

    def validate(self) -> None:
        identity = {
            key: value
            for key, value in self.__dict__.items()
            if key
            not in {"manifest_id", "object_sha256", "artifact_manifest_id", "content_hash"}
        }
        if (
            self.schema_version != "ManualPortfolioReviewManifest@1"
            or not self.manifest_id
            or not self.review_run_id
            or not self.object_sha256
            or not self.cutoff_identity
            or not self.calendar_identity
            or not self.account_snapshot_version_id
            or not self.estimated_state_hash
            or not self.code_identity
            or not self.config_identity
            or self.content_hash != canonical_hash(identity)
        ):
            raise ManualReviewError("MANUAL_REVIEW_MANIFEST_INVALID")


def build_review_run(
    *,
    workflow_run_id: str,
    account_id: str,
    requested_at: str,
    selected_complete_session: str,
    first_window_start_exclusive: str | None,
    prior_successful: ManualPortfolioReviewRun | None,
    context: ManualReviewContext,
) -> ManualPortfolioReviewRun:
    if (
        prior_successful is None
        and first_window_start_exclusive is None
    ):
        raise ManualReviewError("FIRST_REVIEW_CUTOFF_REQUIRED")
    if (
        prior_successful is None
        and first_window_start_exclusive
        != context.account_snapshot_cutoff
    ):
        raise ManualReviewError("FIRST_REVIEW_CUTOFF_UNPROVEN")
    start = (
        prior_successful.window_end_inclusive
        if prior_successful is not None
        else str(first_window_start_exclusive)
    )
    fingerprint = canonical_hash(
        {
            "account_id": account_id,
            "selected_complete_session": selected_complete_session,
            "window_start_exclusive": start,
            "account_snapshot_version_id": context.account_snapshot_version_id,
            "estimated_state_hash": context.estimated_state_hash,
            "calendar_identity": context.calendar_identity,
            "policy_identities": context.policy_identities,
            "holdings": context.holdings,
        }
    )
    run = ManualPortfolioReviewRun(
        review_run_id="manual_review_"
        + canonical_hash(
            {
                "workflow_run_id": workflow_run_id,
                "input_fingerprint": fingerprint,
            }
        )[:24],
        workflow_run_id=workflow_run_id,
        account_id=account_id,
        requested_at=requested_at,
        selected_complete_session=selected_complete_session,
        timezone="Asia/Shanghai",
        window_start_exclusive=start,
        window_end_inclusive=selected_complete_session,
        prior_successful_review_run_id=(
            prior_successful.review_run_id
            if prior_successful is not None
            else None
        ),
        status="running",
        input_fingerprint=fingerprint,
        created_at=requested_at,
    )
    run.validate()
    return run


def build_review_items(
    run: ManualPortfolioReviewRun,
    context: ManualReviewContext,
) -> tuple[ManualPortfolioReviewItem, ...]:
    items: list[ManualPortfolioReviewItem] = []
    for holding in context.holdings:
        outcome = {
            "no_action": ReviewOutcome.NO_CHANGE,
            "manual_review_required": ReviewOutcome.REVIEW_REQUIRED,
            "decision_task": ReviewOutcome.REVIEW_REQUIRED,
            "blocked": ReviewOutcome.REVIEW_REQUIRED,
        }.get(holding.evaluation_resolution, ReviewOutcome.REVIEW_REQUIRED)
        if (
            holding.active_plan_id is not None
            and holding.evaluation_resolution is None
        ):
            outcome = ReviewOutcome.MONITOR
        unable = holding.unable_reasons
        if holding.active_plan_id is None:
            unable = tuple(sorted(set(unable + ("ACTIVE_PLAN_MISSING",))))
        elif (
            holding.evaluation_resolution is None
            and not unable
        ):
            unable = tuple(
                sorted(set(unable + ("PLAN_EVALUATION_MISSING",)))
            )
        base = ManualPortfolioReviewItem(
            review_item_id="",
            review_run_id=run.review_run_id,
            account_id=run.account_id,
            security_id=holding.security_id,
            position_identity=holding.position_identity,
            account_snapshot_version_id=context.account_snapshot_version_id,
            account_snapshot_hash=context.account_snapshot_hash,
            estimated_state_hash=context.estimated_state_hash,
            active_plan_id=holding.active_plan_id,
            plan_version_id=holding.plan_version_id,
            strategy_version_id=holding.strategy_version_id,
            sleeve_graph=holding.sleeve_graph,
            data_snapshot_ids=holding.data_snapshot_ids,
            research_run_ids=holding.research_run_ids,
            evidence_ids=holding.evidence_ids,
            market_snapshot_ids=holding.market_snapshot_ids,
            hard_rule_evaluations=holding.hard_rule_evaluations,
            review_rule_routing=holding.review_rule_routing,
            conflict_resolution=holding.conflict_resolution,
            outcome=outcome,
            material_changes=(),
            unable_reasons=unable,
            blocked_reasons=holding.blocked_reasons,
            decision_task_ids=(),
            plan_impact_assessment_ids=(),
            plan_change_proposal_ids=(),
            content_hash="",
            created_at=run.requested_at,
        )
        item_id = "review_item_" + canonical_hash(
            {
                "review_run_id": run.review_run_id,
                "security_id": holding.security_id,
            }
        )[:24]
        prepared = replace(base, review_item_id=item_id)
        identity = {
            key: value
            for key, value in prepared.__dict__.items()
            if key != "content_hash"
        }
        prepared = replace(prepared, content_hash=canonical_hash(identity))
        prepared.validate()
        items.append(prepared)
    return tuple(items)


def prepare_review_manifest(
    *,
    run: ManualPortfolioReviewRun,
    context: ManualReviewContext,
    items: tuple[ManualPortfolioReviewItem, ...],
    code_identity: str,
    config_identity: str,
    created_at: str,
) -> tuple[
    dict[str, object],
    tuple[ManualPortfolioReviewCheckpoint, ...],
]:
    checkpoint_ids = tuple(
        "review_checkpoint_"
        + canonical_hash(
            {
                "review_run_id": run.review_run_id,
                "security_id": item.security_id,
                "stage": "review_item",
                "input_fingerprint": item.content_hash,
            }
        )[:24]
        for item in items
    )
    identity = {
        "schema_version": "ManualPortfolioReviewManifest@1",
        "review_run_id": run.review_run_id,
        "cutoff_identity": (
            f"{run.window_start_exclusive}..{run.window_end_inclusive}"
        ),
        "calendar_identity": context.calendar_identity,
        "policy_identities": context.policy_identities,
        "account_snapshot_version_id": context.account_snapshot_version_id,
        "estimated_state_hash": context.estimated_state_hash,
        "active_plan_version_ids": tuple(
            sorted(
                {
                    item.plan_version_id
                    for item in items
                    if item.plan_version_id is not None
                }
            )
        ),
        "data_snapshot_ids": _collected_ids(
            items, "data_snapshot_ids"
        ),
        "research_run_ids": _collected_ids(items, "research_run_ids"),
        "market_snapshot_ids": _collected_ids(
            items, "market_snapshot_ids"
        ),
        "evidence_ids": _collected_ids(items, "evidence_ids"),
        "rule_evaluator_conflict_versions": (
            "plan-rule-ast@2",
            "plan-evaluator@2",
            "trade-plan-conflict@1",
        ),
        "review_item_ids": tuple(
            item.review_item_id for item in items
        ),
        "checkpoint_ids": checkpoint_ids,
        "decision_task_ids": (),
        "assessment_ids": (),
        "proposal_ids": (),
        "code_identity": code_identity,
        "config_identity": config_identity,
        "created_at": created_at,
    }
    manifest_id = (
        f"manual_review_manifest_{canonical_hash(identity)[:24]}"
    )
    checkpoints = tuple(
        ManualPortfolioReviewCheckpoint(
            checkpoint_id=checkpoint_id,
            review_run_id=run.review_run_id,
            security_id=item.security_id,
            stage="review_item",
            input_fingerprint=item.content_hash,
            status="committed",
            manifest_id=manifest_id,
            attempt_no=1,
            committed_at=created_at,
        )
        for checkpoint_id, item in zip(
            checkpoint_ids, items, strict=True
        )
    )
    for checkpoint in checkpoints:
        checkpoint.validate()
    return identity, checkpoints


def build_review_manifest(
    *,
    identity: Mapping[str, object],
    manifest_id: str,
    object_sha256: str,
    artifact_manifest_id: str,
) -> ManualPortfolioReviewManifest:
    manifest = ManualPortfolioReviewManifest(
        manifest_id=manifest_id,
        object_sha256=object_sha256,
        artifact_manifest_id=artifact_manifest_id,
        content_hash=canonical_hash(identity),
        **identity,
    )
    manifest.validate()
    return manifest


def _collected_ids(
    items: tuple[ManualPortfolioReviewItem, ...],
    field: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for item in items
                for value in getattr(item, field)
            }
        )
    )


__all__ = [
    "ManualPortfolioReviewCheckpoint",
    "ManualPortfolioReviewItem",
    "ManualPortfolioReviewManifest",
    "ManualPortfolioReviewRun",
    "ManualReviewContext",
    "ManualReviewError",
    "ManualReviewHolding",
    "ReviewOutcome",
    "build_review_manifest",
    "build_review_items",
    "build_review_run",
    "prepare_review_manifest",
]
