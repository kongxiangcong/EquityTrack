from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from trading_platform.persistence.locking import DataRootWriterLock
from trading_platform.application.workflow_ledger import (
    DecisionViewPayloadQuery,
    ResearchArtifactQuery,
    WorkflowLedgerPort,
    WorkspaceWorkflowQuery,
)
from trading_platform.research_view import ResearchDecisionView, ResearchViewError
from trading_platform.application.web_tasks import WorkspaceUpdateCommand


class WorkspaceService:
    """Own workspace read-model queries and replay-safe local authorization."""

    def __init__(
        self,
        connection,
        workflow_ledger: WorkflowLedgerPort,
        writer_lock: DataRootWriterLock | None = None,
    ) -> None:
        self.connection = connection
        self.writer_lock = writer_lock
        self.workflow_ledger = workflow_ledger

    def build(self, security_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._one(
            "SELECT requested_date,effective_session_date,freshness_status,quality_status FROM data_snapshot WHERE data_snapshot_id=?",
            (snapshot_id,),
        )
        workflow_evidence = self.workflow_ledger.load(
            WorkspaceWorkflowQuery(security_id)
        )
        workflows = [dict(item) for item in workflow_evidence.workflows]
        evaluations = self._all(
            "SELECT e.plan_evaluation_id,e.market_snapshot_id,e.status,e.outcome,e.completeness,e.created_at,e.evaluator_version,e.evaluation_policy_version FROM plan_evaluation e JOIN trade_plan_version p ON p.plan_version_id=e.plan_version_id WHERE p.security_id=? ORDER BY e.created_at",
            (security_id,),
        )
        for evaluation in evaluations:
            evaluation["rules"] = self._all(
                "SELECT rule_order,rule_id,result,reason_code,operands_json,effect,applies_to,observed_at FROM plan_rule_evaluation WHERE plan_evaluation_id=? ORDER BY rule_order",
                (evaluation["plan_evaluation_id"],),
            )
        manifests = [dict(item) for item in workflow_evidence.manifests]
        account_positions = self._all(
            "SELECT a.base_currency,a.initialized_at,"
            "v.account_snapshot_version_id AS account_snapshot_id,"
            "v.as_of_at AS snapshot_as_of,v.as_of_precision,"
            "v.session_semantics,v.source_kind,p.security_id,"
            "p.total_quantity,p.available_quantity_state,"
            "p.available_quantity_value,p.cost_state,p.cost_value,"
            "p.market_value_state,p.market_value_value,"
            "(SELECT h.reconciliation_status FROM account_history_snapshot h "
            "WHERE h.account_id=a.account_id ORDER BY h.created_at DESC LIMIT 1) "
            "AS latest_import_status "
            "FROM account_snapshot_projection_checkpoint c "
            "JOIN account a USING(account_id) "
            "JOIN account_snapshot_version v USING(account_snapshot_version_id) "
            "JOIN account_snapshot_position p USING(account_snapshot_version_id) "
            "WHERE p.security_id=? ORDER BY a.initialized_at,a.account_id",
            (security_id,),
        )
        for index, position in enumerate(account_positions, start=1):
            position["account_label"] = f"本地账户 {index}"
            position["relationship"] = "position"
            position["freshness"] = "latest_confirmed_snapshot"
        return {
            "task": {
                "security_id": security_id,
                "snapshot_id": snapshot_id,
                **(snapshot or {}),
            },
            "research_views": self._research_views(security_id),
            "forecast_registry": self._forecast_registry(
                security_id,
                (snapshot or {}).get("effective_session_date"),
            ),
            "forecast_reviews": self._forecast_reviews(security_id),
            "changes": self._all(
                "SELECT p.plan_id,p.lifecycle_status,a.plan_version_id AS active_version_id,a.started_at AS updated_at FROM trade_plan p LEFT JOIN plan_activation a ON a.plan_id=p.plan_id AND a.ended_at IS NULL WHERE p.security_id=? ORDER BY coalesce(a.started_at,p.created_at) DESC",
                (security_id,),
            ),
            "update_authorizations": self._all(
                "SELECT update_authorization_id,requested_date,effective_session_date,scope,created_at FROM update_authorization WHERE security_id=? ORDER BY created_at DESC",
                (security_id,),
            ),
            "plan_drafts": self._all(
                "SELECT draft_id,plan_id,based_on_version_id,revision,status,content_hash,created_at,updated_at FROM trade_plan_draft WHERE security_id=? ORDER BY updated_at DESC",
                (security_id,),
            ),
            "security_relationship": self._relationship(account_positions),
            "current_positions": account_positions,
            "account_opening_state": account_positions,
            "history": {
                "workflows": workflows,
                "data_snapshots": self._all(
                    "SELECT data_snapshot_id,snapshot_purpose,requested_date,effective_session_date,as_of_at,freshness_status,quality_status,query_policy_identity,source_policy_identity FROM data_snapshot WHERE scope_id=? ORDER BY as_of_at",
                    (security_id,),
                ),
                "research_runs": list(workflow_evidence.research_runs),
                "annotations": self._all(
                    "SELECT v.annotation_version_id,v.annotation_id,v.version_no,v.status,v.created_at,v.annotation_kind,v.style_name,v.data_snapshot_id FROM chart_annotation_version v JOIN chart_annotation a USING(annotation_id) WHERE a.security_id=? ORDER BY v.created_at,v.version_no",
                    (security_id,),
                ),
                "plans": self._all(
                    "SELECT v.plan_version_id,v.plan_id,v.version_no,v.confirmed_at AS created_at,v.user_input_source,v.content_json,r.snapshot_type,r.snapshot_id AS account_snapshot_id,r.snapshot_as_of,r.reconciliation_status FROM trade_plan_version v LEFT JOIN plan_account_snapshot_reference r USING(plan_version_id) WHERE v.security_id=? ORDER BY v.confirmed_at,v.version_no",
                    (security_id,),
                ),
                "account_imports": self._all(
                    "SELECT b.history_import_batch_id,b.window_start,b.window_end,b.result_counts_json,b.quality_issues_json,s.account_history_snapshot_id,s.as_of_date,s.reconciliation_status,s.limitations_json FROM history_import_batch b LEFT JOIN account_history_snapshot s USING(history_import_batch_id) WHERE b.account_id IN (SELECT c.account_id FROM account_snapshot_projection_checkpoint c JOIN account_snapshot_position p USING(account_snapshot_version_id) WHERE p.security_id=?) ORDER BY b.created_at",
                    (security_id,),
                ),
                "market_snapshots": self._all(
                    "SELECT market_snapshot_id,status,requested_date,effective_session_date,created_at FROM market_snapshot WHERE security_id=? ORDER BY created_at",
                    (security_id,),
                ),
                "evaluations": evaluations,
                "artifact_manifests": manifests,
            },
            "boundary": "研究与规则结果用于用户判断，不构成个性化投资建议。",
        }

    def _research_views(self, security_id: str) -> list[dict[str, Any]]:
        evidence = self.workflow_ledger.load(
            WorkspaceWorkflowQuery(security_id)
        )
        workflow_run_ids = {
            str(row["workflow_run_id"]): None
            for row in evidence.workflows
            if row["status"] in {"succeeded", "succeeded_with_limits"}
        }
        result: list[dict[str, Any]] = []
        for workflow_run_id in workflow_run_ids:
            persisted = self.workflow_ledger.load(
                DecisionViewPayloadQuery(workflow_run_id)
            )
            try:
                decoded = json.loads(persisted.json_bytes)
                view = ResearchDecisionView.from_dict(decoded)
            except (json.JSONDecodeError, ResearchViewError) as error:
                raise ResearchViewError("RESEARCH_VIEW_PERSISTED_INVALID") from error
            if view.workflow_run_id != workflow_run_id:
                raise ResearchViewError("RESEARCH_VIEW_IDENTITY_MISMATCH")
            result.append(
                {
                    **view.to_dict(),
                    "html_projection": persisted.html_bytes.decode("utf-8"),
                }
            )
        return result

    def _forecast_reviews(self, security_id: str) -> list[dict[str, Any]]:
        rows = (
            {"artifact_record_id": record_id}
            for record_id in self.workflow_ledger.load(
                WorkspaceWorkflowQuery(security_id)
            ).forecast_review_artifact_record_ids
        )
        reviews: list[dict[str, Any]] = []
        for row in rows:
            artifact = self.workflow_ledger.load(
                ResearchArtifactQuery(row["artifact_record_id"])
            )
            reviews.append(
                {
                    "artifact_record_id": artifact.artifact_record_id,
                    "forecast_artifact_record_id": (
                        artifact.payload.get("original_artifacts", {}).get(
                            "forecast_artifact_record_id"
                        )
                    ),
                    "reviewed_at": artifact.payload.get("reviewed_at"),
                    "status": artifact.status,
                    "model_identity": artifact.model_identity,
                    "reviewer_identity": artifact.payload.get("reviewer_identity"),
                    "numeric_interval_coverage": artifact.payload.get(
                        "numeric_interval_coverage"
                    ),
                    "probability_results": artifact.payload.get(
                        "probability_results",
                        [],
                    ),
                    "numeric_results": artifact.payload.get(
                        "numeric_results",
                        [],
                    ),
                    "driver_error_decomposition": artifact.payload.get(
                        "driver_error_decomposition",
                        [],
                    ),
                    "calibration_version": artifact.payload.get("calibration_version"),
                    "interpretation": artifact.payload.get("interpretation"),
                    "diagnostics": artifact.payload.get("diagnostics", []),
                }
            )
        return reviews

    def _forecast_registry(
        self,
        security_id: str,
        effective_session_date: str | None,
    ) -> list[dict[str, Any]]:
        reviewed_targets = {
            (
                review.get("forecast_artifact_record_id"),
                result.get("event_id" if key == "probability_results" else "target_id"),
            )
            for review in self._forecast_reviews(security_id)
            for key in ("probability_results", "numeric_results")
            for result in review.get(key, [])
            if isinstance(result, Mapping)
        }
        rows = (
            {"artifact_record_id": record_id}
            for record_id in self.workflow_ledger.load(
                WorkspaceWorkflowQuery(security_id)
            ).forecast_artifact_record_ids
        )
        registry: list[dict[str, Any]] = []
        for row in rows:
            artifact = self.workflow_ledger.load(
                ResearchArtifactQuery(row["artifact_record_id"])
            )
            for node in artifact.payload.get("nodes", ()):
                if not isinstance(node, Mapping):
                    continue
                target_id = node.get("node_id")
                review_date = node.get("review_date")
                review_status = (
                    "reviewed"
                    if (
                        artifact.artifact_record_id,
                        target_id,
                    )
                    in reviewed_targets
                    else (
                        "due"
                        if effective_session_date
                        and isinstance(review_date, str)
                        and review_date <= effective_session_date
                        else "registered"
                    )
                )
                registry.append(
                    {
                        "forecast_artifact_record_id": (artifact.artifact_record_id),
                        "target_id": target_id,
                        "kind": node.get("kind"),
                        "label": node.get("label"),
                        "horizon": node.get("horizon"),
                        "review_date": review_date,
                        "review_status": review_status,
                    }
                )
        rank = {"reviewed": 0, "due": 1, "registered": 2}
        return sorted(
            registry,
            key=lambda item: (
                rank[item["review_status"]],
                str(item.get("review_date") or ""),
                str(item.get("target_id") or ""),
            ),
        )

    def _all(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(sql, parameters)]

    def _one(self, sql: str, parameters: tuple[object, ...]) -> dict[str, Any] | None:
        rows = self._all(sql, parameters)
        return rows[0] if rows else None

    def _relationship(self, positions: list[dict[str, Any]]) -> str:
        if positions:
            return "position"
        account_count = self.connection.execute(
            "SELECT count(*) FROM account"
        ).fetchone()[0]
        if account_count == 0:
            return "account_data_missing"
        covered_accounts = self.connection.execute(
            "SELECT count(DISTINCT account_id) FROM account_import_batch"
        ).fetchone()[0]
        if covered_accounts < account_count:
            return "position_data_missing"
        return "watchlist_not_held"

    def authorize(self, command: WorkspaceUpdateCommand) -> dict[str, Any]:
        invocation_id = command.invocation_id
        security_id = command.security_id
        requested_date = command.requested_date
        effective_session_date = command.effective_session_date
        if self.writer_lock is None:
            raise RuntimeError("WORKSPACE_MUTATION_UNAVAILABLE")
        with self.writer_lock.acquire(f"update-authorization:{invocation_id}"):
            existing = self._one(
                "SELECT * FROM update_authorization WHERE invocation_id=?",
                (invocation_id,),
            )
            if existing:
                if (
                    existing["security_id"] != security_id
                    or existing["requested_date"] != requested_date
                    or existing["effective_session_date"] != effective_session_date
                ):
                    raise ValueError("INVOCATION_CONFLICT")
                return existing
            authorization_id = f"update_auth_{uuid.uuid4().hex}"
            created_at = datetime.now(timezone.utc).isoformat()
            with self.connection:
                self.connection.execute(
                    "INSERT INTO update_authorization VALUES(?,?,?,?,?,?,?)",
                    (
                        authorization_id,
                        invocation_id,
                        security_id,
                        requested_date,
                        effective_session_date,
                        "refresh_frozen_inputs",
                        created_at,
                    ),
                )
        return dict(
            self.connection.execute(
                "SELECT * FROM update_authorization WHERE update_authorization_id=?",
                (authorization_id,),
            ).fetchone()
        )
