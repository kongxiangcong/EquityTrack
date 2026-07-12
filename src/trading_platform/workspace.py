from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from trading_platform.persistence.locking import DataRootWriterLock


class WorkspaceService:
    """Facade-facing workspace queries and replay-safe local authorization commands."""

    def __init__(self, connection, writer_lock: DataRootWriterLock | None = None) -> None:
        self.connection = connection
        self.writer_lock = writer_lock

    def build(self, security_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._one("SELECT requested_date,effective_session_date,freshness_status,quality_status FROM data_snapshot WHERE data_snapshot_id=?", (snapshot_id,))
        workflows = self._all("SELECT w.workflow_run_id,w.status,w.requested_date,w.effective_session_date,w.created_at,w.completed_at,d.disposition AS research_disposition,d.reason_code AS research_reuse_reason,d.policy_version AS research_reuse_policy FROM workflow_run w LEFT JOIN research_reuse_decision d USING(workflow_run_id) ORDER BY w.created_at DESC")
        refs = self._all("SELECT workflow_run_id,ref_role,ref_type,ref_id,disposition FROM workflow_run_ref ORDER BY workflow_run_id,ref_role")
        by_run: dict[str, list[dict[str, Any]]] = {}
        for ref in refs:
            by_run.setdefault(ref.pop("workflow_run_id"), []).append(ref)
        for run in workflows:
            run["refs"] = by_run.get(run["workflow_run_id"], [])
        evaluations = self._all("SELECT e.plan_evaluation_id,e.market_snapshot_id,e.status,e.outcome,e.completeness,e.created_at,e.evaluator_version,e.evaluation_policy_version FROM plan_evaluation e JOIN trade_plan_version p ON p.plan_version_id=e.plan_version_id WHERE p.security_id=? ORDER BY e.created_at", (security_id,))
        for evaluation in evaluations:
            evaluation["rules"] = self._all("SELECT rule_order,rule_id,result,reason_code,operands_json,effect,applies_to,observed_at FROM plan_rule_evaluation WHERE plan_evaluation_id=? ORDER BY rule_order", (evaluation["plan_evaluation_id"],))
        manifests = self._all("SELECT DISTINCT m.artifact_manifest_id,m.manifest_role,m.producer_type,m.producer_id,m.membership_hash,m.created_at FROM artifact_manifest m JOIN workflow_run_ref r ON r.ref_type='ArtifactManifest' AND r.ref_id=m.artifact_manifest_id JOIN workflow_run w USING(workflow_run_id) JOIN research_reuse_decision d USING(workflow_run_id) JOIN research_run_record rr ON rr.research_run_id=d.research_run_id JOIN research_input_projection p ON p.research_projection_id=rr.research_projection_id WHERE p.security_id=? ORDER BY m.created_at", (security_id,))
        for manifest in manifests:
            manifest["members"] = self._all("SELECT member_order,artifact_id,member_role,direction FROM artifact_manifest_member WHERE artifact_manifest_id=? ORDER BY member_order", (manifest["artifact_manifest_id"],))
        return {
            "task": {"security_id": security_id, "snapshot_id": snapshot_id, **(snapshot or {})},
            "changes": self._all("SELECT p.plan_id,p.lifecycle_status,a.plan_version_id AS active_version_id,a.started_at AS updated_at FROM trade_plan p LEFT JOIN plan_activation a ON a.plan_id=p.plan_id AND a.ended_at IS NULL WHERE p.security_id=? ORDER BY coalesce(a.started_at,p.created_at) DESC", (security_id,)),
            "update_authorizations": self._all("SELECT update_authorization_id,requested_date,effective_session_date,scope,created_at FROM update_authorization WHERE security_id=? ORDER BY created_at DESC", (security_id,)),
            "plan_drafts": self._all("SELECT draft_id,plan_id,based_on_version_id,revision,status,content_hash,created_at,updated_at FROM trade_plan_draft WHERE security_id=? ORDER BY updated_at DESC", (security_id,)),
            "history": {
                "workflows": workflows,
                "data_snapshots": self._all("SELECT data_snapshot_id,snapshot_purpose,requested_date,effective_session_date,as_of_at,freshness_status,quality_status,query_policy_version,source_policy_version FROM data_snapshot WHERE scope_id=? ORDER BY as_of_at", (security_id,)),
                "research_runs": self._all("SELECT r.research_run_id,r.research_snapshot_id,r.original_cutoff_date,r.status,r.engine_schema_version,r.engine_code_identity,r.canonical_json_artifact_id,r.html_artifact_id FROM research_run_record r JOIN research_input_projection p ON p.research_projection_id=r.research_projection_id WHERE p.security_id=? ORDER BY r.original_cutoff_date", (security_id,)),
                "annotations": self._all("SELECT v.annotation_version_id,v.annotation_id,v.version_no,v.status,v.created_at,v.annotation_kind,v.style_name,v.data_snapshot_id FROM chart_annotation_version v JOIN chart_annotation a USING(annotation_id) WHERE a.security_id=? ORDER BY v.created_at,v.version_no", (security_id,)),
                "plans": self._all("SELECT plan_version_id,plan_id,version_no,confirmed_at AS created_at,user_input_source,content_json FROM trade_plan_version WHERE security_id=? ORDER BY confirmed_at,version_no", (security_id,)),
                "market_snapshots": self._all("SELECT market_snapshot_id,status,requested_date,effective_session_date,created_at FROM market_snapshot WHERE security_id=? ORDER BY created_at", (security_id,)),
                "evaluations": evaluations,
                "artifact_manifests": manifests,
            },
            "boundary": "研究与规则结果用于用户判断，不构成个性化投资建议。",
        }

    def _all(self, sql: str, parameters: tuple[object, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(sql, parameters)]

    def _one(self, sql: str, parameters: tuple[object, ...]) -> dict[str, Any] | None:
        rows = self._all(sql, parameters)
        return rows[0] if rows else None

    def authorize_update(self, invocation_id: str, security_id: str, requested_date: str, effective_session_date: str) -> dict[str, Any]:
        if self.writer_lock is None:
            raise RuntimeError("WORKSPACE_MUTATION_UNAVAILABLE")
        with self.writer_lock.acquire(f"update-authorization:{invocation_id}"):
            existing = self._one("SELECT * FROM update_authorization WHERE invocation_id=?", (invocation_id,))
            if existing:
                if existing["security_id"] != security_id or existing["requested_date"] != requested_date or existing["effective_session_date"] != effective_session_date:
                    raise ValueError("INVOCATION_CONFLICT")
                return existing
            authorization_id = f"update_auth_{uuid.uuid4().hex}"
            created_at = datetime.now(timezone.utc).isoformat()
            with self.connection:
                self.connection.execute("INSERT INTO update_authorization VALUES(?,?,?,?,?,?,?)", (authorization_id, invocation_id, security_id, requested_date, effective_session_date, "refresh_frozen_inputs", created_at))
        return dict(self.connection.execute("SELECT * FROM update_authorization WHERE update_authorization_id=?", (authorization_id,)).fetchone())
