from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from trading_platform.domain.workflow import ResearchArtifactView
from trading_platform.persistence.locking import DataRootWriterLock
from trading_platform.research_view import ResearchDecisionViewBuilder


class WorkspaceService:
    """Facade-facing workspace queries and replay-safe local authorization commands."""

    def __init__(
        self,
        connection,
        writer_lock: DataRootWriterLock | None = None,
        research_artifact_reader: Callable[[str], ResearchArtifactView] | None = None,
        research_run_reader: Callable[[str], Mapping[str, object]] | None = None,
    ) -> None:
        self.connection = connection
        self.writer_lock = writer_lock
        self.research_artifact_reader = research_artifact_reader
        self.research_run_reader = research_run_reader
        self.research_view_builder = ResearchDecisionViewBuilder()

    def build(self, security_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._one(
            "SELECT requested_date,effective_session_date,freshness_status,quality_status FROM data_snapshot WHERE data_snapshot_id=?",
            (snapshot_id,),
        )
        workflows = self._all(
            "SELECT w.workflow_run_id,w.status,w.requested_date,w.effective_session_date,w.created_at,w.completed_at,d.disposition AS research_disposition,d.reason_code AS research_reuse_reason,d.policy_version AS research_reuse_policy FROM workflow_run w LEFT JOIN research_reuse_decision d USING(workflow_run_id) ORDER BY w.created_at DESC"
        )
        refs = self._all(
            "SELECT workflow_run_id,ref_role,ref_type,ref_id,disposition FROM workflow_run_ref ORDER BY workflow_run_id,ref_role"
        )
        by_run: dict[str, list[dict[str, Any]]] = {}
        for ref in refs:
            by_run.setdefault(ref.pop("workflow_run_id"), []).append(ref)
        for run in workflows:
            run["refs"] = by_run.get(run["workflow_run_id"], [])
        evaluations = self._all(
            "SELECT e.plan_evaluation_id,e.market_snapshot_id,e.status,e.outcome,e.completeness,e.created_at,e.evaluator_version,e.evaluation_policy_version FROM plan_evaluation e JOIN trade_plan_version p ON p.plan_version_id=e.plan_version_id WHERE p.security_id=? ORDER BY e.created_at",
            (security_id,),
        )
        for evaluation in evaluations:
            evaluation["rules"] = self._all(
                "SELECT rule_order,rule_id,result,reason_code,operands_json,effect,applies_to,observed_at FROM plan_rule_evaluation WHERE plan_evaluation_id=? ORDER BY rule_order",
                (evaluation["plan_evaluation_id"],),
            )
        manifests = self._all(
            "SELECT DISTINCT m.artifact_manifest_id,m.manifest_role,m.producer_type,m.producer_id,m.membership_hash,m.created_at FROM artifact_manifest m JOIN workflow_run_ref r ON r.ref_type='ArtifactManifest' AND r.ref_id=m.artifact_manifest_id JOIN workflow_run w USING(workflow_run_id) JOIN research_reuse_decision d USING(workflow_run_id) JOIN research_run_record rr ON rr.research_run_id=d.research_run_id JOIN research_input_projection p ON p.research_projection_id=rr.research_projection_id WHERE p.security_id=? ORDER BY m.created_at",
            (security_id,),
        )
        for manifest in manifests:
            manifest["members"] = self._all(
                "SELECT member_order,artifact_id,member_role,direction FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order",
                (manifest["artifact_manifest_id"],),
            )
        account_positions = self._all(
            "SELECT a.base_currency,a.initialized_at,s.cash_decimal,s.as_of_date AS snapshot_as_of,s.reconciliation_status,s.limitations_json,s.portfolio_snapshot_id AS account_snapshot_id,p.position_id,p.quantity_decimal,p.available_decimal,p.frozen_decimal,p.source_type,l.cost_price_decimal,o.source_price_decimal,o.source_market_value_decimal,o.source_day_pnl_decimal,o.source_weight_decimal,o.source_as_of,(SELECT h.reconciliation_status FROM account_history_snapshot h WHERE h.account_id=a.account_id ORDER BY h.created_at DESC LIMIT 1) AS latest_import_status FROM account_position p JOIN account a USING(account_id) JOIN account_position_lot l USING(position_id) JOIN account_position_observation o USING(position_id) JOIN portfolio_snapshot s ON s.portfolio_snapshot_id=(SELECT s2.portfolio_snapshot_id FROM portfolio_snapshot s2 WHERE s2.account_id=a.account_id ORDER BY s2.as_of_date DESC,s2.portfolio_snapshot_id DESC LIMIT 1) WHERE p.security_id=? ORDER BY a.initialized_at,p.position_id",
            (security_id,),
        )
        for index, position in enumerate(account_positions, start=1):
            position["account_label"] = f"本地账户 {index}"
            position["limitations"] = json.loads(position.pop("limitations_json"))
            position["relationship"] = "position"
            position["freshness"] = (
                "current_snapshot"
                if position["reconciliation_status"] != "blocked"
                else "blocked"
            )
        return {
            "task": {
                "security_id": security_id,
                "snapshot_id": snapshot_id,
                **(snapshot or {}),
            },
            "research_views": self._research_views(security_id),
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
                    "SELECT data_snapshot_id,snapshot_purpose,requested_date,effective_session_date,as_of_at,freshness_status,quality_status,query_policy_version,source_policy_version FROM data_snapshot WHERE scope_id=? ORDER BY as_of_at",
                    (security_id,),
                ),
                "research_runs": self._all(
                    "SELECT r.research_run_id,r.research_snapshot_id,r.original_cutoff_date,r.status,r.engine_schema_version,r.engine_code_identity,r.canonical_json_artifact_id,r.html_artifact_id FROM research_run_record r JOIN research_input_projection p ON p.research_projection_id=r.research_projection_id WHERE p.security_id=? ORDER BY r.original_cutoff_date",
                    (security_id,),
                ),
                "annotations": self._all(
                    "SELECT v.annotation_version_id,v.annotation_id,v.version_no,v.status,v.created_at,v.annotation_kind,v.style_name,v.data_snapshot_id FROM chart_annotation_version v JOIN chart_annotation a USING(annotation_id) WHERE a.security_id=? ORDER BY v.created_at,v.version_no",
                    (security_id,),
                ),
                "plans": self._all(
                    "SELECT v.plan_version_id,v.plan_id,v.version_no,v.confirmed_at AS created_at,v.user_input_source,v.content_json,r.snapshot_type,r.snapshot_id AS account_snapshot_id,r.snapshot_as_of,r.reconciliation_status FROM trade_plan_version v LEFT JOIN plan_account_snapshot_reference r USING(plan_version_id) WHERE v.security_id=? ORDER BY v.confirmed_at,v.version_no",
                    (security_id,),
                ),
                "account_imports": self._all(
                    "SELECT b.history_import_batch_id,b.window_start,b.window_end,b.result_counts_json,b.quality_issues_json,s.account_history_snapshot_id,s.as_of_date,s.reconciliation_status,s.limitations_json FROM history_import_batch b LEFT JOIN account_history_snapshot s USING(history_import_batch_id) WHERE b.account_id IN (SELECT account_id FROM account_position WHERE security_id=?) ORDER BY b.created_at",
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
        if self.research_artifact_reader is None or self.research_run_reader is None:
            return []
        rows = self.connection.execute(
            "SELECT u.workflow_run_id,w.created_at,d.research_run_id,"
            "r.artifact_kind,r.artifact_record_id "
            "FROM workflow_run_artifact_use u "
            "JOIN workflow_run w USING(workflow_run_id) "
            "JOIN research_reuse_decision d USING(workflow_run_id) "
            "JOIN research_artifact_record r USING(artifact_record_id) "
            "WHERE r.platform_security_id=? "
            "ORDER BY w.created_at,r.rowid",
            (security_id,),
        ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            group = grouped.setdefault(
                row["workflow_run_id"],
                {
                    "research_run_id": row["research_run_id"],
                    "artifacts": {},
                },
            )
            group["artifacts"][row["artifact_kind"]] = row["artifact_record_id"]
        result: list[dict[str, Any]] = []
        for workflow_run_id, group in grouped.items():
            artifact_ids = group["artifacts"]
            required = {"DataSnapshot", "Forecast", "Valuation"}
            if not required.issubset(artifact_ids):
                continue
            view = self.research_view_builder.build(
                workflow_run_id=workflow_run_id,
                data_snapshot=self.research_artifact_reader(
                    artifact_ids["DataSnapshot"]
                ),
                forecast=self.research_artifact_reader(artifact_ids["Forecast"]),
                valuation=self.research_artifact_reader(artifact_ids["Valuation"]),
                simulation=(
                    self.research_artifact_reader(artifact_ids["Simulation"])
                    if "Simulation" in artifact_ids
                    else None
                ),
                market_data_snapshot=(
                    self.research_artifact_reader(
                        artifact_ids["MarketDataSnapshot"]
                    )
                    if "MarketDataSnapshot" in artifact_ids
                    else None
                ),
                market_path=(
                    self.research_artifact_reader(
                        artifact_ids["MarketPathSimulation"]
                    )
                    if "MarketPathSimulation" in artifact_ids
                    else None
                ),
                research_run_payload=self.research_run_reader(
                    group["research_run_id"]
                ),
            )
            result.append(view.to_dict())
        return result

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

    def authorize_update(
        self,
        invocation_id: str,
        security_id: str,
        requested_date: str,
        effective_session_date: str,
    ) -> dict[str, Any]:
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
