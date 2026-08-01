from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from trading_platform.application.workflow_ledger import (
    CommitEvaluationNode,
    DurableObject,
    EvaluationCheckpointResult,
    ResearchEvaluationRecord,
    WorkflowPersistenceError,
)
from trading_platform.domain.research_bundle import (
    verify_research_evaluation_bundle,
)
from trading_platform.domain.workflow import ReferenceDisposition
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock


class _ResearchArtifactCommit:
    """Owns the complete durable research-evaluation checkpoint transaction."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
        publish_durable: Callable[[bytes], DurableObject],
        register_artifact: Callable[[DurableObject, str, str], str],
        assert_mutation_owner: Callable[[str, str, str, str, str], None],
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock
        self._publish_durable = publish_durable
        self._register_artifact = register_artifact
        self._assert_mutation_owner = assert_mutation_owner

    def commit(
        self, command: CommitEvaluationNode
    ) -> EvaluationCheckpointResult:
        try:
            bundle_payload = json.loads(
                command.bundle_json_artifact.payload.decode("utf-8")
            )
            research_payload = json.loads(
                command.research_json_artifact.payload.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkflowPersistenceError(
                "RESEARCH_EVALUATION_PAYLOAD_INVALID",
                "commit_checkpoint",
                command.workflow_run_id,
            ) from error
        if (
            not isinstance(bundle_payload, Mapping)
            or not isinstance(research_payload, Mapping)
            or command.bundle_json_artifact.media_type
            != "application/json"
            or command.bundle_json_artifact.schema_version
            != "ResearchEvaluationBundle@1"
            or command.research_json_artifact.media_type
            != "application/json"
        ):
            raise WorkflowPersistenceError(
                "RESEARCH_EVALUATION_PAYLOAD_INVALID",
                "commit_checkpoint",
                command.workflow_run_id,
            )

        snapshot = self._connection.execute(
            "SELECT source_policy_identity FROM data_snapshot "
            "WHERE data_snapshot_id=?",
            (command.request.data_snapshot_id,),
        ).fetchone()
        snapshot_members = self._connection.execute(
            "SELECT normalized_version_id FROM data_snapshot_member "
            "WHERE data_snapshot_id=? ORDER BY member_order",
            (command.request.data_snapshot_id,),
        ).fetchall()
        if snapshot is None or not snapshot_members:
            raise WorkflowPersistenceError(
                "RESEARCH_EVALUATION_SNAPSHOT_INVALID",
                "commit_checkpoint",
                command.request.data_snapshot_id,
            )
        try:
            verified = verify_research_evaluation_bundle(
                bundle_payload,
                expected_data_snapshot_id=command.request.data_snapshot_id,
                expected_source_policy_identity=str(snapshot[0]),
                expected_snapshot_member_ids=tuple(
                    str(row[0]) for row in snapshot_members
                ),
            )
        except (TypeError, ValueError) as error:
            raise WorkflowPersistenceError(
                "RESEARCH_EVALUATION_PAYLOAD_INVALID",
                "commit_checkpoint",
                command.workflow_run_id,
            ) from error
        if verified.research_run != research_payload:
            raise WorkflowPersistenceError(
                "RESEARCH_EVALUATION_PAYLOAD_INVALID",
                "commit_checkpoint",
                command.workflow_run_id,
            )

        component_artifacts = {
            "forecast": command.forecast_artifact,
            "scenario_valuation": command.scenario_valuation_artifact,
            "valuation_method_route": command.valuation_method_route_artifact,
            "valuation_simulation_decision": (
                command.valuation_simulation_decision_artifact
            ),
            "market_path_decision": command.market_path_decision_artifact,
            "recent_trend_assessment": (
                command.recent_trend_assessment_artifact
            ),
        }
        for component_name, artifact in component_artifacts.items():
            try:
                component_payload = json.loads(
                    artifact.payload.decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise WorkflowPersistenceError(
                    "RESEARCH_COMPONENT_BUNDLE_INVALID",
                    "commit_checkpoint",
                    component_name,
                ) from error
            if (
                not isinstance(component_payload, Mapping)
                or component_payload
                != verified.components[component_name]
                or artifact.media_type != "application/json"
                or artifact.schema_version != "ResearchComponentResult@1"
            ):
                raise WorkflowPersistenceError(
                    "RESEARCH_COMPONENT_BUNDLE_INVALID",
                    "commit_checkpoint",
                    component_name,
                )

        published = {
            "research_bundle_json": self._publish_durable(
                command.bundle_json_artifact.payload
            ),
            "research_json": self._publish_durable(
                command.research_json_artifact.payload
            ),
            "forecast": self._publish_durable(
                command.forecast_artifact.payload
            ),
            "scenario_valuation": self._publish_durable(
                command.scenario_valuation_artifact.payload
            ),
            "valuation_method_route": self._publish_durable(
                command.valuation_method_route_artifact.payload
            ),
            "valuation_simulation_decision": self._publish_durable(
                command.valuation_simulation_decision_artifact.payload
            ),
            "market_path_decision": self._publish_durable(
                command.market_path_decision_artifact.payload
            ),
            "recent_trend_assessment": self._publish_durable(
                command.recent_trend_assessment_artifact.payload
            ),
            "decision_view_json": self._publish_durable(
                command.decision_json_artifact.payload
            ),
            "decision_view_html": self._publish_durable(
                command.decision_html_artifact.payload
            ),
            "decision_view_pdf": self._publish_durable(
                command.decision_pdf_artifact.payload
            ),
            "decision_view_workbook": self._publish_durable(
                command.decision_workbook_artifact.payload
            ),
        }
        plan_json = json.dumps(
            command.request.evaluation_plan.canonical_content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        completed = datetime.now(timezone.utc).isoformat()
        with self._writer_lock.acquire(
            f"research-evaluation-checkpoint:{command.workflow_run_id}"
        ):
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._assert_mutation_owner(
                    command.workflow_run_id,
                    command.workflow_node_run_id,
                    command.workflow_node_attempt_id,
                    command.owner_token,
                    "commit_checkpoint",
                )
                plan_id = command.request.evaluation_plan.identity
                plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
                self._connection.execute(
                    "INSERT OR IGNORE INTO research_evaluation_plan_record "
                    "VALUES(?,?,?,?,?)",
                    (
                        plan_id,
                        command.request.evaluation_plan.schema_version,
                        plan_hash,
                        plan_json,
                        completed,
                    ),
                )
                plan_row = self._connection.execute(
                    "SELECT schema_version,content_hash,canonical_json "
                    "FROM research_evaluation_plan_record "
                    "WHERE evaluation_plan_id=?",
                    (plan_id,),
                ).fetchone()
                if (
                    plan_row is None
                    or plan_row["schema_version"]
                    != command.request.evaluation_plan.schema_version
                    or plan_row["content_hash"] != plan_hash
                    or plan_row["canonical_json"] != plan_json
                ):
                    raise WorkflowPersistenceError(
                        "RESEARCH_EVALUATION_PLAN_IDENTITY_MISMATCH",
                        "commit_checkpoint",
                        plan_id,
                    )
                artifacts = {
                    "research_bundle_json": self._register_artifact(
                        published["research_bundle_json"],
                        command.bundle_json_artifact.media_type,
                        command.bundle_json_artifact.schema_version,
                    ),
                    "research_json": self._register_artifact(
                        published["research_json"],
                        command.research_json_artifact.media_type,
                        command.research_json_artifact.schema_version,
                    ),
                    "forecast": self._register_artifact(
                        published["forecast"],
                        command.forecast_artifact.media_type,
                        command.forecast_artifact.schema_version,
                    ),
                    "scenario_valuation": self._register_artifact(
                        published["scenario_valuation"],
                        command.scenario_valuation_artifact.media_type,
                        command.scenario_valuation_artifact.schema_version,
                    ),
                    "valuation_method_route": self._register_artifact(
                        published["valuation_method_route"],
                        command.valuation_method_route_artifact.media_type,
                        command.valuation_method_route_artifact.schema_version,
                    ),
                    "valuation_simulation_decision": self._register_artifact(
                        published["valuation_simulation_decision"],
                        command.valuation_simulation_decision_artifact.media_type,
                        command.valuation_simulation_decision_artifact.schema_version,
                    ),
                    "market_path_decision": self._register_artifact(
                        published["market_path_decision"],
                        command.market_path_decision_artifact.media_type,
                        command.market_path_decision_artifact.schema_version,
                    ),
                    "recent_trend_assessment": self._register_artifact(
                        published["recent_trend_assessment"],
                        command.recent_trend_assessment_artifact.media_type,
                        command.recent_trend_assessment_artifact.schema_version,
                    ),
                    "decision_view_json": self._register_artifact(
                        published["decision_view_json"],
                        command.decision_json_artifact.media_type,
                        command.decision_json_artifact.schema_version,
                    ),
                    "decision_view_html": self._register_artifact(
                        published["decision_view_html"],
                        command.decision_html_artifact.media_type,
                        command.decision_html_artifact.schema_version,
                    ),
                    "decision_view_pdf": self._register_artifact(
                        published["decision_view_pdf"],
                        command.decision_pdf_artifact.media_type,
                        command.decision_pdf_artifact.schema_version,
                    ),
                    "decision_view_workbook": self._register_artifact(
                        published["decision_view_workbook"],
                        command.decision_workbook_artifact.media_type,
                        command.decision_workbook_artifact.schema_version,
                    ),
                }
                existing = self._connection.execute(
                    "SELECT * FROM research_run_record "
                    "WHERE evaluation_fingerprint=? "
                    "AND engine_code_identity=?",
                    (
                        command.evaluation_fingerprint,
                        command.engine_code_identity,
                    ),
                ).fetchone()
                record = ResearchEvaluationRecord(
                    research_run_id=str(research_payload.get("run_id", "")),
                    evaluation_fingerprint=command.evaluation_fingerprint,
                    evaluation_plan_id=plan_id,
                    data_snapshot_id=command.request.data_snapshot_id,
                    request_fingerprint=hashlib.sha256(
                        json.dumps(
                            command.request.canonical_content,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                    ).hexdigest(),
                    engine_schema_version=int(
                        research_payload.get("schema_version", 0)
                    ),
                    engine_code_identity=command.engine_code_identity,
                    original_cutoff_date=(
                        command.request.evaluation_plan.horizon.as_of
                    ),
                    status=str(research_payload.get("status", "blocked")),
                    canonical_json_artifact_id=artifacts["research_bundle_json"],
                )
                if existing is None:
                    self._connection.execute(
                        "INSERT INTO research_run_record VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            record.research_run_id,
                            record.evaluation_fingerprint,
                            record.evaluation_plan_id,
                            record.data_snapshot_id,
                            record.request_fingerprint,
                            record.engine_schema_version,
                            record.engine_code_identity,
                            record.original_cutoff_date,
                            record.status,
                            record.canonical_json_artifact_id,
                        ),
                    )
                    disposition = ReferenceDisposition.CREATED
                else:
                    record = _evaluation_record(existing)
                    if (
                        record.research_run_id
                        != str(research_payload.get("run_id", ""))
                        or record.canonical_json_artifact_id
                        != artifacts["research_bundle_json"]
                        or record.evaluation_plan_id != plan_id
                        or record.data_snapshot_id
                        != command.request.data_snapshot_id
                    ):
                        raise WorkflowPersistenceError(
                            "RESEARCH_EVALUATION_REUSE_IDENTITY_MISMATCH",
                            "commit_checkpoint",
                            command.workflow_run_id,
                        )
                    disposition = ReferenceDisposition.REUSED
                decision_members = (
                    (
                        artifacts["decision_view_json"],
                        "decision_view_json",
                        "output",
                    ),
                    (
                        artifacts["decision_view_html"],
                        "decision_view_html",
                        "output",
                    ),
                    (
                        artifacts["decision_view_pdf"],
                        "decision_view_pdf",
                        "output",
                    ),
                    (
                        artifacts["decision_view_workbook"],
                        "decision_view_workbook",
                        "output",
                    ),
                )
                decision_identity = [
                    {
                        "artifact_id": artifact_id,
                        "role": role,
                        "direction": direction,
                    }
                    for artifact_id, role, direction in decision_members
                ]
                decision_manifest_id = "manifest_" + canonical_hash(
                    {
                        "role": "workflow_decision_view@3",
                        "producer_type": "WorkflowRun",
                        "producer_id": command.workflow_run_id,
                        "members": decision_identity,
                    }
                )[:24]
                self._connection.execute(
                    "INSERT INTO artifact_manifest VALUES(?,?,?,?,?,?,?)",
                    (
                        decision_manifest_id,
                        "workflow_decision_view@3",
                        "WorkflowRun",
                        command.workflow_run_id,
                        canonical_hash(decision_identity),
                        completed,
                        len(decision_members),
                    ),
                )
                for index, member in enumerate(decision_members):
                    self._connection.execute(
                        "INSERT INTO artifact_manifest_member VALUES(?,?,?,?,?)",
                        (decision_manifest_id, index, *member),
                    )
                members = (
                    (artifacts["research_bundle_json"], "research_bundle_json", "output"),
                    (artifacts["research_json"], "research_run_json", "output"),
                    (artifacts["forecast"], "forecast", "output"),
                    (artifacts["scenario_valuation"], "scenario_valuation", "output"),
                    (artifacts["valuation_method_route"], "valuation_method_route", "output"),
                    (artifacts["valuation_simulation_decision"], "valuation_simulation_decision", "output"),
                    (artifacts["market_path_decision"], "market_path_decision", "output"),
                    (artifacts["recent_trend_assessment"], "recent_trend_assessment", "output"),
                    *decision_members,
                )
                identity = [
                    {
                        "artifact_id": artifact_id,
                        "role": role,
                        "direction": direction,
                    }
                    for artifact_id, role, direction in members
                ]
                manifest_id = "manifest_" + canonical_hash(
                    {
                        "role": "checkpoint",
                        "producer_type": "WorkflowNodeRun",
                        "producer_id": command.workflow_node_run_id,
                        "members": identity,
                    }
                )[:24]
                self._connection.execute(
                    "INSERT INTO artifact_manifest VALUES(?,?,?,?,?,?,?)",
                    (
                        manifest_id,
                        "checkpoint",
                        "WorkflowNodeRun",
                        command.workflow_node_run_id,
                        canonical_hash(identity),
                        completed,
                        len(members),
                    ),
                )
                for index, member in enumerate(members):
                    self._connection.execute(
                        "INSERT INTO artifact_manifest_member VALUES(?,?,?,?,?)",
                        (manifest_id, index, *member),
                    )
                node = self._connection.execute(
                    "UPDATE workflow_node_run SET status='succeeded',"
                    "checkpoint_manifest_id=? WHERE workflow_node_run_id=? "
                    "AND owner_token=? AND status='running'",
                    (
                        manifest_id,
                        command.workflow_node_run_id,
                        command.owner_token,
                    ),
                )
                attempt = self._connection.execute(
                    "UPDATE workflow_node_attempt SET disposition=?,"
                    "completed_at=? WHERE workflow_node_attempt_id=? "
                    "AND owner_token=? AND completed_at IS NULL",
                    (
                        (
                            "reused"
                            if disposition is ReferenceDisposition.REUSED
                            else "succeeded"
                        ),
                        completed,
                        command.workflow_node_attempt_id,
                        command.owner_token,
                    ),
                )
                if node.rowcount != 1 or attempt.rowcount != 1:
                    raise WorkflowPersistenceError(
                        "WORKFLOW_LEASE_LOST",
                        "commit_checkpoint",
                        command.workflow_run_id,
                    )
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
        return EvaluationCheckpointResult(
            record=record,
            disposition=disposition,
            manifest_id=manifest_id,
            decision_manifest_id=decision_manifest_id,
            members=members,
        )


def _evaluation_record(row: Mapping[str, object]) -> ResearchEvaluationRecord:
    return ResearchEvaluationRecord(
        research_run_id=str(row["research_run_id"]),
        evaluation_fingerprint=str(row["evaluation_fingerprint"]),
        evaluation_plan_id=str(row["evaluation_plan_id"]),
        data_snapshot_id=str(row["data_snapshot_id"]),
        request_fingerprint=str(row["request_fingerprint"]),
        engine_schema_version=int(row["engine_schema_version"]),
        engine_code_identity=str(row["engine_code_identity"]),
        original_cutoff_date=str(row["original_cutoff_date"]),
        status=str(row["status"]),
        canonical_json_artifact_id=str(row["canonical_json_artifact_id"]),
    )
