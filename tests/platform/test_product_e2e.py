from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from tests.platform.application_task_fixture import PlatformTaskFixture
from tests.platform.canonical_plan_journey_fixture import (
    ACCOUNT_ID,
    SECURITY_ID,
    application_envelope_bytes,
    arrange_canonical_plan_journey,
    author_draft_payload,
    canonical_research_request,
    fixture_market_runtime,
    register_confirmed_plan_authorities,
)
from trading_platform.application import (
    ApplicationCommandEnvelopeV1,
    ApplicationCommandResult,
    encode_read_model,
)
from trading_platform.application.contracts import (
    SecurityIdentity,
    StartResearchWorkflow,
)
from trading_platform.application.market_contracts import (
    BuildMarketSnapshotCommand,
    EvaluatePlanCommand,
)
from trading_platform.domain.data import (
    FreshnessStatus,
    SnapshotPurpose,
    SyncRequest,
    SyncStatus,
)
from trading_platform.domain.rules import OperandState, OperandValue
from trading_platform.identity import build_code_identity
from trading_platform.operations import PlatformOperations
from trading_platform.valuation_workbook import ValuationWorkbookAdapter


ROOT = Path(__file__).resolve().parents[2]


def _dispatch(
    platform: PlatformTaskFixture, encoded: bytes
) -> ApplicationCommandResult:
    result = platform.application_commands.dispatch(
        ApplicationCommandEnvelopeV1.from_bytes(encoded)
    )
    if not isinstance(result, ApplicationCommandResult):
        raise AssertionError(f"{result.code}: {result.message}")
    return result


def _known(
    operand_id: str,
    value: Decimal | str,
    unit: str,
    evidence_ref: str,
) -> OperandValue:
    return OperandValue(
        operand_id=operand_id,
        value_state=OperandState.KNOWN,
        value=value,
        unit=unit,
        currency=None,
        as_of_identity=evidence_ref,
        evidence_refs=(evidence_ref,),
    )


def test_product_e2e_real_gateway_and_restart_recovery() -> None:
    data_root_value = os.environ.get("P5_LIVE_DATA_ROOT")
    author_snapshot_id = os.environ.get("P5_AUTHOR_SNAPSHOT_ID")
    evaluation_snapshot_id = os.environ.get("P5_EVAL_SNAPSHOT_ID")
    if not all(
        (data_root_value, author_snapshot_id, evaluation_snapshot_id)
    ):
        pytest.skip("explicit real-gateway P5 snapshot inputs are required")

    artifact_node = os.environ.get("CODEX_ARTIFACT_NODE")
    artifact_modules = os.environ.get("CODEX_ARTIFACT_NODE_MODULES")
    workbook_projector = (
        ValuationWorkbookAdapter(
            node_executable=Path(artifact_node),
            node_modules=Path(artifact_modules),
            builder_script=(
                ROOT / "scripts" / "render_valuation_xlsx.mjs"
            ),
        )
        if artifact_node and artifact_modules
        else None
    )
    data_root = Path(str(data_root_value)).resolve()
    platform = PlatformTaskFixture(
        data_root,
        workbook_projector=workbook_projector,
    )
    try:
        author_evidence = platform.inspection.snapshot(
            str(author_snapshot_id)
        )
        evaluation_evidence = platform.inspection.snapshot(
            str(evaluation_snapshot_id)
        )
        assert author_evidence.source_policy_identity
        assert evaluation_evidence.source_policy_identity
        assert author_evidence.freshness_status == "valid"
        assert evaluation_evidence.freshness_status == "valid"
        assert author_evidence.coverage_missing == 0
        assert evaluation_evidence.coverage_missing == 0

        research = platform.research.handle(
            StartResearchWorkflow(
                canonical_research_request(
                    invocation_id="p5:research:author:v4",
                    snapshot_id=str(author_snapshot_id),
                    requested_date=author_evidence.requested_date,
                    effective_session_date=(
                        author_evidence.effective_session_date
                    ),
                )
            )
        )
        assert research.recent_trend_assessment_id is not None
        assert research.final_manifest_id is not None
        assert research.json_artifact_id is not None
        assert research.html_artifact_id is not None
        assert research.pdf_artifact_id is not None
        assert research.workbook_artifact_id is not None
        if workbook_projector is None:
            assert research.workbook_media_type == "application/json"
            assert research.workbook_filename == (
                "research-workbook-limitation.json"
            )
        else:
            assert research.workbook_media_type == (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
            assert research.workbook_filename.endswith(".xlsx")
        manifest = platform.archive.manifest(
            research.final_manifest_id
        )
        manifest_roles = {
            str(member["member_role"])
            for member in manifest.members
        }
        assert {
            "decision_view_json",
            "decision_view_html",
            "decision_view_pdf",
            "decision_view_workbook",
        } <= manifest_roles
        source_payload = platform.archive.source_payload(
            research.research_run_id
        )
        assert source_payload["status"] == "completed_with_limits"
        capability_counts = source_payload["summary"]["capability_counts"]
        assert capability_counts["blocked"] > 0
        assert capability_counts["ready_with_estimates"] == 0
        trend = platform.archive.get(
            research.recent_trend_assessment_id
        )
        assert trend.status == "complete"

        authorities = register_confirmed_plan_authorities(platform)
        journey_time = datetime.now().astimezone() + timedelta(minutes=1)
        authored = _dispatch(
            platform,
            application_envelope_bytes(
                invocation_id="p5:plan:author",
                payload=author_draft_payload(
                    account_ref="authoring",
                    security_ref=SECURITY_CODE,
                    requested_at=journey_time.isoformat(),
                ),
            ),
        )
        draft_id = str(authored.result["draft_id"])
        draft_revision = int(authored.result["revision"])
        graph = authored.result["proposed_graph"]
        assert isinstance(graph, dict)
        version = graph["version"]
        assert isinstance(version, dict)
        plan_id = str(version["plan_id"])
        plan_version_id = str(version["plan_version_id"])

        challenge = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="trade_plan.issue_confirmation_challenge@1",
                payload_schema_version="IssuePlanConfirmationChallenge@1",
                invocation_id="p5:plan:challenge",
                actor_type="user",
                expected_revision=draft_revision,
                payload={
                    "draft_id": draft_id,
                    "activation_intent": "confirm_and_activate",
                    "issued_at": (journey_time + timedelta(minutes=1)).isoformat(),
                    "expires_at": (journey_time + timedelta(hours=1)).isoformat(),
                },
            ),
        )
        diff = challenge.result["canonical_diff"]
        assert isinstance(diff, dict)
        confirmed = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="trade_plan.confirm@1",
                payload_schema_version="ConfirmTradePlanDraft@1",
                invocation_id="p5:plan:confirm",
                actor_type="user",
                expected_revision=int(
                    challenge.result["expected_revision"]
                ),
                approval_challenge_id=str(
                    challenge.result["challenge_id"]
                ),
                payload={
                    "expected_draft_hash": str(
                        challenge.result["expected_draft_hash"]
                    ),
                    "expected_diff_hash": str(diff["content_hash"]),
                    "activation_intent": "confirm_and_activate",
                    "approved_at": (journey_time + timedelta(minutes=2)).isoformat(),
                },
            ),
        )
        assert confirmed.result_type == "PlanConfirmationResult"
        replayed_authored = _dispatch(
            platform,
            application_envelope_bytes(
                invocation_id="p5:plan:author",
                payload=author_draft_payload(
                    account_ref="authoring",
                    security_ref=SECURITY_CODE,
                    requested_at=journey_time.isoformat(),
                ),
            ),
        )
        assert replayed_authored.result == authored.result

        market_snapshot = platform.market.build_market_snapshot(
            BuildMarketSnapshotCommand(
                invocation_id="p5:market:snapshot",
                security_id=SECURITY_ID,
                market_scope_id="CN_A_SHARE",
                data_snapshot_id=str(evaluation_snapshot_id),
                market_model_version="cn-a-share-market@1",
                freshness_policy_version="freshness@1",
                code_identity=build_code_identity(
                    ROOT, {"product_e2e": "P5@1"}
                ),
            )
        )
        assert market_snapshot.status.value in {"complete", "limited"}
        complete_sessions = tuple(
            sorted(
                {
                    str(field["period"])
                    for member in evaluation_evidence.member_evidence
                    if member.dataset == "daily"
                    for field in member.extracted_fields
                    if field.get("field_name") == "current_price"
                    and "period" in field
                    and author_evidence.effective_session_date
                    <= str(field["period"])
                    <= evaluation_evidence.effective_session_date
                }
            )
        )
        evaluation = platform.market.evaluate_plan(
            EvaluatePlanCommand(
                invocation_id="p5:plan:evaluate",
                plan_version_id=plan_version_id,
                market_snapshot_id=market_snapshot.market_snapshot_id,
                operands=(
                    _known(
                        "event.session",
                        author_evidence.effective_session_date,
                        "trading_session",
                        str(author_snapshot_id),
                    ),
                    _known(
                        "account.remaining_quantity",
                        Decimal("900"),
                        "share",
                        authorities.account_snapshot_version_id,
                    ),
                ),
                complete_sessions=complete_sessions,
            )
        )
        assert evaluation.resolution.outcome.value == "decision_task"

        review = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="manual_portfolio_review.run@2",
                payload_schema_version="RunManualPortfolioReview@2",
                invocation_id="p5:manual-review",
                payload={
                    "account_id": ACCOUNT_ID,
                    "requested_at": (journey_time + timedelta(minutes=3)).isoformat(),
                    "session_selection": (
                        "latest_proven_complete_session"
                    ),
                },
            ),
        )
        review_run_id = str(review.result["review_run_id"])
        read_model = platform.read_models.plan_detail(
            plan_id, (journey_time + timedelta(minutes=7)).isoformat()
        )
        task_view = next(
            item
            for item in read_model.related_tasks
            if item["status"] in {"open", "deferred"}
        )
        task_id = str(task_view["decision_task_id"])
        review_item = next(
            item
            for item in read_model.review_history
            if item["review_run_id"] == review_run_id
        )
        rule_state = next(
            item
            for item in read_model.rule_states
            if item["rule_class"] == "review"
        )
        execution = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="execution_record.declare@1",
                payload_schema_version="DeclareExecutionRecord@1",
                invocation_id="p5:execution:declare",
                actor_type="user",
                payload={
                    "decision_task_id": task_id,
                    "reason": "synthetic account user-declared execution",
                    "effective_at": "2026-07-30T14:30:00+08:00",
                    "effective_session": "2026-07-30",
                    "intent_type": "decrease",
                    "quantity": "100",
                    "price_state": "unknown",
                    "price_value": None,
                    "fee_state": "unknown",
                    "fee_value": None,
                    "currency": "CNY",
                    "confirmed_at": (journey_time + timedelta(minutes=4)).isoformat(),
                },
            ),
        )
        assert execution.result["verification_status"] == (
            "user_declared_unverified"
        )

        discipline = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="discipline_review.create_draft@2",
                payload_schema_version="CreateDisciplineReviewDraft@2",
                invocation_id="p5:discipline:draft",
                payload={
                    "account_id": ACCOUNT_ID,
                    "period_request": {
                        "period_kind": "custom",
                        "requested_at": (journey_time + timedelta(minutes=5)).isoformat(),
                        "requested_start_date": "2026-07-30",
                        "requested_end_date": "2026-07-30",
                    },
                },
            ),
        )
        confirmed_discipline = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="discipline_review.confirm@1",
                payload_schema_version="ConfirmDisciplineReview@1",
                invocation_id="p5:discipline:confirm",
                actor_type="user",
                expected_revision=int(discipline.result["version_no"]),
                payload={
                    "discipline_review_id": discipline.result[
                        "discipline_review_id"
                    ],
                    "confirmed_at": (journey_time + timedelta(minutes=6)).isoformat(),
                },
            ),
        )

        assessment = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="plan_impact_assessment.create@1",
                payload_schema_version="CreatePlanImpactAssessment@1",
                invocation_id="p5:impact:assessment",
                payload={
                    "review_run_id": review_run_id,
                    "review_item_id": str(review_item["review_item_id"]),
                    "review_rule_id": str(rule_state["rule_id"]),
                    "impact_kind": "unable_to_determine",
                    "materiality": "unable",
                    "uncertainties": [
                        "official thesis evidence was not refreshed in this run"
                    ],
                    "what_changed": (
                        "the frozen market path crossed a plan review boundary"
                    ),
                    "what_would_change_the_view": (
                        "a later complete session with official disclosure evidence"
                    ),
                    "model_identity": "model:product-e2e@1",
                    "policy_identity": "policy:financial-boundary@1",
                    "prompt_identity": "prompt:product-e2e@1",
                    "created_at": (journey_time + timedelta(minutes=8)).isoformat(),
                },
            ),
        )
        proposal = _dispatch(
            platform,
            application_envelope_bytes(
                command_name="plan_change_proposal.create@1",
                payload_schema_version="CreatePlanChangeProposal@1",
                invocation_id="p5:proposal:create",
                payload={
                    "assessment_id": assessment.result["assessment_id"],
                    "proposed_content": {
                        "schema_version": "TradePlanContent@1",
                        "purpose": "periodic-discipline-review-proposal",
                    },
                    "parameters": {"review_source": review_run_id},
                    "created_at": (journey_time + timedelta(minutes=9)).isoformat(),
                },
            ),
        )
        assert proposal.result["status"] == "open"

        result = {
            "schema_version": "ProductE2EResult@1",
            "provider": {
                "identity": "preconfigured_tushare_compatible_non_official",
                "authority": "structured_aggregator",
            },
            "coverage": {
                "complete_data": "real_gateway_main_chain",
                "partial_missing_estimable": (
                    "test_partial_snapshot_uses_only_bounded_traceable_estimates"
                ),
                "local_method_unavailable": "real_gateway_typed_degradation",
                "non_trading_day": (
                    "test_product_boundary_non_trading_day_keeps_plan_unconfirmed"
                ),
                "stale_data": "test_product_boundary_stale_snapshot_fails_closed",
                "duplicate_run_idempotency": "real_gateway_author_replay",
                "unconfirmed_plan": (
                    "test_product_boundary_non_trading_day_keeps_plan_unconfirmed"
                ),
                "restart_recovery": (
                    "real_gateway_main_chain_and_product_restart_recovery"
                ),
            },            "snapshots": {
                "author": str(author_snapshot_id),
                "evaluation": str(evaluation_snapshot_id),
            },
            "research": {
                "workflow_run_id": research.workflow_run_id,
                "manifest_id": research.final_manifest_id,
                "artifact_ids": {
                    "json": research.json_artifact_id,
                    "html": research.html_artifact_id,
                    "pdf": research.pdf_artifact_id,
                    "xlsx": research.workbook_artifact_id,
                },
                "recent_trend_assessment_id": trend.assessment_id,
            },
            "plan": {
                "draft_id": draft_id,
                "plan_version_id": plan_version_id,
                "market_snapshot_id": market_snapshot.market_snapshot_id,
                "evaluation_id": evaluation.plan_evaluation_id,
            },
            "review": {
                "review_run_id": review_run_id,
                "decision_task_id": task_id,
                "execution_record_id": execution.result["execution_record_id"],
                "discipline_review_id": (
                    confirmed_discipline.result["discipline_review_id"]
                ),
                "plan_impact_assessment_id": assessment.result["assessment_id"],
                "plan_change_proposal_id": proposal.result["proposal_id"],
            },
        }
    finally:
        platform.close()

    restarted = PlatformTaskFixture(data_root)
    try:
        replay = _dispatch(
            restarted,
            application_envelope_bytes(
                command_name="execution_record.declare@1",
                payload_schema_version="DeclareExecutionRecord@1",
                invocation_id="p5:execution:declare",
                actor_type="user",
                payload={
                    "decision_task_id": result["review"]["decision_task_id"],
                    "reason": "synthetic account user-declared execution",
                    "effective_at": "2026-07-30T14:30:00+08:00",
                    "effective_session": "2026-07-30",
                    "intent_type": "decrease",
                    "quantity": "100",
                    "price_state": "unknown",
                    "price_value": None,
                    "fee_state": "unknown",
                    "fee_value": None,
                    "currency": "CNY",
                    "confirmed_at": (journey_time + timedelta(minutes=4)).isoformat(),
                },
            ),
        )
        assert replay.result["execution_record_id"] == (
            result["review"]["execution_record_id"]
        )
        restarted_detail = restarted.read_models.plan_detail(
            plan_id, (journey_time + timedelta(minutes=10)).isoformat()
        )
        assert (
            restarted_detail.plan_identity["latest_plan_version_id"]
            == plan_version_id
        )
    finally:
        restarted.close()

    output = data_root.parent / "result.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

def test_product_boundary_non_trading_day_keeps_plan_unconfirmed(
    tmp_path: Path,
) -> None:
    with arrange_canonical_plan_journey(
        tmp_path, activate=False
    ) as journey:
        evidence = journey.platform.inspection.snapshot(
            journey.data_snapshot_id
        )
        assert evidence.requested_date == "2026-07-11"
        assert evidence.effective_session_date == "2026-07-10"
        assert journey.challenge_id is None
        assert journey.activation_id is None

        detail = journey.platform.read_models.plan_detail(
            journey.plan_id, journey.review_requested_at
        )
        assert detail.plan_identity["open_draft_id"] == journey.draft_id
        assert detail.plan_identity["latest_plan_version_id"] is None
        assert detail.decision_summary["lifecycle_label"] == "未确认草稿"
        assert detail.decision_summary["horizon"] == {
            "start": "2026-07-11",
            "end": "2028-12-31",
            "review_by": "2026-10-31",
        }
        assert detail.decision_summary["quantities"] == {
            "core_floor": {
                "state": "known",
                "value": "1000",
                "unit": "股",
            },
            "candidate_adjustment": {
                "state": "unknown",
                "value": None,
                "unit": "股",
            },
        }
        assert detail.decision_summary["trigger_conditions"]
        assert detail.decision_summary["risk_constraints"]
        assert detail.decision_summary["evidence_status"]["items"]

        review = _dispatch(
            journey.platform,
            application_envelope_bytes(
                command_name="manual_portfolio_review.run@2",
                payload_schema_version="RunManualPortfolioReview@2",
                invocation_id="p5:unconfirmed:manual-review",
                payload={
                    "account_id": journey.account_id,
                    "requested_at": journey.review_requested_at,
                    "session_selection": (
                        "latest_proven_complete_session"
                    ),
                },
            ),
        )
        assert review.result["selected_complete_session"] == "2026-07-10"
        portfolio = journey.platform.read_models.portfolio(
            journey.account_id, journey.review_requested_at
        )
        tasks = portfolio.unresolved_decision_tasks
        assert len(tasks) == 1
        assert tasks[0]["reason_code"] == "ACTIVE_PLAN_MISSING"


def test_product_boundary_stale_snapshot_fails_closed(
    tmp_path: Path,
) -> None:
    provider, query_policy, source_policy = fixture_market_runtime()
    source_policy = replace(
        source_policy,
        routes=tuple(
            replace(route, freshness_max_stale_days=0)
            for route in source_policy.routes
        ),
    )
    platform = PlatformTaskFixture(
        tmp_path,
        provider=provider,
        query_policy=query_policy,
        source_policy=source_policy,
    )
    try:
        platform.watchlist.add(
            "p5:stale:watchlist",
            SecurityIdentity(
                SECURITY_ID,
                "SZSE",
                "002897",
                "CNY",
                "2017-09-07",
            ),
        )
        assert platform.data is not None
        result = platform.data.sync(
            SyncRequest(
                "p5:stale:sync",
                SECURITY_ID,
                "002897",
                "2026-07-12",
                datetime(2026, 7, 12, tzinfo=timezone.utc),
                "Asia/Shanghai",
                "SZSE",
                SnapshotPurpose.RESEARCH,
                ("trade_cal", "market_universe", "daily"),
                True,
                False,
            )
        )
        assert result.status is SyncStatus.BLOCKED
        assert result.snapshot_id is None
        assert result.freshness is FreshnessStatus.STALE
        assert result.stale_by_days == 1
    finally:
        platform.close()

def test_product_restart_recovery_preserves_canonical_plan(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    journey = arrange_canonical_plan_journey(live, activate=True)
    plan_id = journey.plan_id
    plan_version_id = journey.plan_version_id
    generated_at = journey.review_requested_at
    before = encode_read_model(
        journey.platform.read_models.plan_detail(plan_id, generated_at)
    )
    journey.close()

    restarted = PlatformTaskFixture(live)
    try:
        after = encode_read_model(
            restarted.read_models.plan_detail(plan_id, generated_at)
        )
        assert after == before
        assert (
            restarted.read_models.plan_detail(plan_id, generated_at)
            .plan_identity["latest_plan_version_id"]
            == plan_version_id
        )
    finally:
        restarted.close()

    evidence_root = os.environ.get("TDK_ACCEPTANCE_EVIDENCE_ROOT")
    if evidence_root:
        (Path(evidence_root) / "restart-replay.json").write_text(
            json.dumps(
                {
                    "schema_version": "ProductRestartReplayEvidence@1",
                    "status": "passed",
                    "plan_id": plan_id,
                    "plan_version_id": plan_version_id,
                    "read_model_sha256": hashlib.sha256(before).hexdigest(),
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )


def test_product_backup_restore_preserves_canonical_plan(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    journey = arrange_canonical_plan_journey(live, activate=True)
    plan_id = journey.plan_id
    plan_version_id = journey.plan_version_id
    generated_at = journey.review_requested_at
    before = encode_read_model(
        journey.platform.read_models.plan_detail(plan_id, generated_at)
    )
    journey.close()

    archive = tmp_path / "backup" / "product-e2e.zip"
    backup = PlatformOperations(live).backup(archive)
    restored = tmp_path / "restored"
    restore = PlatformOperations.restore(archive, restored)
    assert backup["status"] == "succeeded"
    assert restore["status"] == "succeeded"
    assert restore["doctor_status"] == "passed"

    rebuilt = PlatformTaskFixture(restored)
    try:
        after = encode_read_model(
            rebuilt.read_models.plan_detail(plan_id, generated_at)
        )
        assert after == before
        assert (
            rebuilt.read_models.plan_detail(plan_id, generated_at)
            .plan_identity["latest_plan_version_id"]
            == plan_version_id
        )
    finally:
        rebuilt.close()

    evidence_root = os.environ.get("TDK_ACCEPTANCE_EVIDENCE_ROOT")
    if evidence_root:
        (Path(evidence_root) / "backup-restore.json").write_text(
            json.dumps(
                {
                    "schema_version": "ProductBackupRestoreEvidence@1",
                    "status": "passed",
                    "backup_name": archive.name,
                    "backup_sha256": hashlib.sha256(
                        archive.read_bytes()
                    ).hexdigest(),
                    "restored_root_distinct": restored != live,
                    "doctor_status": restore["doctor_status"],
                    "plan_id": plan_id,
                    "plan_version_id": plan_version_id,
                    "read_model_sha256": hashlib.sha256(after).hexdigest(),
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )