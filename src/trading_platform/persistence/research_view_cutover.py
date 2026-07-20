from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from trading_platform.application.workflow_ledger import (
    DecisionViewPayload,
    DurableObject,
    ResearchDecisionMaterialization,
    ResearchDecisionViewMaterializerPort,
)
from trading_platform.domain.workflow import ResearchArtifactView
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock, PersistenceError


class ResearchDecisionViewCutover:
    """Owns proof and atomic repair of the persisted research-view graph."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        data_root: Path,
        writer_lock: DataRootWriterLock,
        publish_durable: Callable[[bytes], DurableObject],
        register_artifact: Callable[[DurableObject, str, str], str],
        research_artifact: Callable[[str], ResearchArtifactView],
        research_payload: Callable[[str], Mapping[str, object]],
        fault: Callable[[str], None],
    ) -> None:
        self._connection = connection
        self._data_root = data_root
        self._writer_lock = writer_lock
        self._publish_durable = publish_durable
        self._register_artifact = register_artifact
        self._research_artifact = research_artifact
        self._research_payload = research_payload
        self._fault = fault

    def decision_payload(self, workflow_run_id: str) -> DecisionViewPayload:
        rows = tuple(
            self._connection.execute(
                "SELECT r.ref_id AS manifest_id,f.artifact_manifest_id,"
                "f.producer_type,f.producer_id,f.membership_hash,f.member_count,"
                "m.member_order,m.member_role,m.direction,m.artifact_id,"
                "a.schema_version,a.object_sha256,o.size_bytes,o.relative_path "
                "FROM workflow_run_ref r "
                "JOIN artifact_manifest f ON f.artifact_manifest_id=r.ref_id "
                "JOIN artifact_manifest_member m ON m.artifact_manifest_id=f.artifact_manifest_id "
                "JOIN artifact a ON a.artifact_id=m.artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256 "
                "WHERE r.workflow_run_id=? AND r.ref_role='decision_view_manifest' "
                "AND r.ref_type='ArtifactManifest' "
                "AND f.manifest_role='workflow_decision_view@1' "
                "ORDER BY m.member_order",
                (workflow_run_id,),
            )
        )
        if (
            len(rows) != 2
            or tuple(row["member_role"] for row in rows)
            != ("decision_view_json", "decision_view_html")
            or tuple(row["member_order"] for row in rows) != (0, 1)
            or tuple(row["direction"] for row in rows) != ("output", "output")
            or rows[0]["schema_version"] != "ResearchDecisionView@2"
            or rows[1]["schema_version"] != "ResearchDecisionHtml@1"
        ):
            raise PersistenceError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Workflow does not own one complete canonical decision view.",
            )
        identity = [
            {
                "artifact_id": str(row["artifact_id"]),
                "role": str(row["member_role"]),
                "direction": str(row["direction"]),
            }
            for row in rows
        ]
        expected_manifest_id = "manifest_" + canonical_hash(
            {
                "role": "workflow_decision_view@1",
                "producer_type": "WorkflowRun",
                "producer_id": workflow_run_id,
                "members": identity,
            }
        )[:24]
        if (
            any(row["artifact_manifest_id"] != row["manifest_id"] for row in rows)
            or any(row["manifest_id"] != expected_manifest_id for row in rows)
            or any(row["producer_type"] != "WorkflowRun" for row in rows)
            or any(row["producer_id"] != workflow_run_id for row in rows)
            or any(row["member_count"] != 2 for row in rows)
            or any(row["membership_hash"] != canonical_hash(identity) for row in rows)
        ):
            raise PersistenceError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Workflow decision manifest identity is not canonical.",
            )
        payloads = []
        for row in rows:
            payload = self._object_payload(str(row["object_sha256"]))
            if len(payload) != row["size_bytes"]:
                raise PersistenceError(
                    "OBJECT_INTEGRITY_FAILED",
                    "Decision view object is missing or corrupt.",
                )
            payloads.append(payload)
        return DecisionViewPayload(
            manifest_id=str(rows[0]["manifest_id"]),
            json_artifact_id=str(rows[0]["artifact_id"]),
            html_artifact_id=str(rows[1]["artifact_id"]),
            json_bytes=payloads[0],
            html_bytes=payloads[1],
        )

    def complete(self) -> bool:
        table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_run'"
        ).fetchone()
        if table is None:
            return True
        successful = tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT workflow_run_id FROM workflow_run "
                "WHERE status IN ('succeeded','succeeded_with_limits')"
            )
        )
        for workflow_run_id in successful:
            try:
                persisted = self.decision_payload(str(workflow_run_id))
                decoded = json.loads(persisted.json_bytes)
            except (PersistenceError, json.JSONDecodeError):
                return False
            if (
                not isinstance(decoded, Mapping)
                or decoded.get("schema_version") != "ResearchDecisionView@2"
                or decoded.get("workflow_run_id") != workflow_run_id
            ):
                return False
        records = tuple(
            self._connection.execute(
                "SELECT research_run_id,canonical_json_artifact_id,html_artifact_id,"
                "engine_schema_version FROM research_run_record"
            )
        )
        for record in records:
            if (
                record["canonical_json_artifact_id"] is None
                or record["html_artifact_id"] is None
            ):
                return False
            try:
                source_json_id, source_html_id, _ = self._unique_source_pair(
                    str(record["research_run_id"])
                )
            except (KeyError, PersistenceError):
                return False
            if (
                source_json_id != record["canonical_json_artifact_id"]
                or source_html_id != record["html_artifact_id"]
            ):
                return False
        return True

    def run(
        self,
        materializer: ResearchDecisionViewMaterializerPort,
        *,
        acquire_lock: bool,
    ) -> None:
        if self.complete():
            return
        workflows = tuple(
            self._connection.execute(
                "SELECT w.workflow_run_id,d.research_run_id,a.object_sha256 AS request_object_sha256 "
                "FROM workflow_run w JOIN research_reuse_decision d USING(workflow_run_id) "
                "JOIN workflow_run_request q USING(workflow_run_id) "
                "JOIN artifact a ON a.artifact_id=q.request_artifact_id "
                "WHERE w.status IN ('succeeded','succeeded_with_limits') "
                "ORDER BY w.created_at,w.workflow_run_id"
            )
        )
        source_pairs: dict[str, tuple[str, str, Mapping[str, object]]] = {}
        decisions: list[tuple[str, str, str | None, str | None, bytes, bytes]] = []
        for workflow in workflows:
            research_run_id = str(workflow["research_run_id"])
            if research_run_id not in source_pairs:
                source_pairs[research_run_id] = self._unique_source_pair(
                    research_run_id
                )
            workflow_run_id = str(workflow["workflow_run_id"])
            existing = self._existing_decision_artifacts(
                workflow_run_id, research_run_id, materializer
            )
            if existing is not None:
                json_id, html_id, json_bytes, html_bytes = existing
                try:
                    expected_html = materializer.expected_html(
                        workflow_run_id, research_run_id, json_bytes
                    )
                except ValueError as error:
                    raise PersistenceError(
                        "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                        "Existing decision view is invalid.",
                    ) from error
                if expected_html != html_bytes:
                    raise PersistenceError(
                        "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                        "Existing decision view identity is invalid.",
                    )
                decisions.append(
                    (workflow_run_id, research_run_id, json_id, html_id, json_bytes, html_bytes)
                )
                continue
            request_bytes = self._object_payload(str(workflow["request_object_sha256"]))
            artifacts = tuple(
                self._research_artifact(str(row[0]))
                for row in self._connection.execute(
                    "SELECT artifact_record_id FROM workflow_run_artifact_use "
                    "WHERE workflow_run_id=? ORDER BY rowid",
                    (workflow_run_id,),
                )
            )
            try:
                decision = materializer.materialize(
                    ResearchDecisionMaterialization(
                        workflow_run_id=workflow_run_id,
                        research_run_id=research_run_id,
                        request_bytes=request_bytes,
                        source_payload=source_pairs[research_run_id][2],
                        artifacts=artifacts,
                    )
                )
            except ValueError as error:
                raise PersistenceError(
                    "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                    "Frozen typed decision inputs are incomplete.",
                ) from error
            decisions.append(
                (
                    workflow_run_id,
                    research_run_id,
                    None,
                    None,
                    decision.json_bytes,
                    decision.html_bytes,
                )
            )

        published: dict[tuple[str, str], DurableObject] = {}
        for workflow_run_id, _, candidate_json_id, candidate_html_id, json_bytes, html_bytes in decisions:
            if candidate_json_id is None:
                published[(workflow_run_id, "json")] = self._publish_durable(json_bytes)
            if candidate_html_id is None:
                published[(workflow_run_id, "html")] = self._publish_durable(html_bytes)
        lock = (
            self._writer_lock.acquire("research-decision-view-cutover")
            if acquire_lock
            else nullcontext()
        )
        with lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                if self._connection.execute(
                    "SELECT 1 FROM workflow_run WHERE status IN ('queued','running') LIMIT 1"
                ).fetchone():
                    raise PersistenceError(
                        "MIGRATION_WORKFLOW_NOT_TERMINAL",
                        "A nonterminal workflow blocks decision-view cutover.",
                    )
                for research_run_id, (source_json_id, source_html_id, _) in source_pairs.items():
                    self._connection.execute(
                        "UPDATE research_run_record SET canonical_json_artifact_id=?,"
                        "html_artifact_id=? WHERE research_run_id=?",
                        (source_json_id, source_html_id, research_run_id),
                    )
                for workflow_run_id, _, decision_json_id, decision_html_id, _, _ in decisions:
                    if decision_json_id is None:
                        decision_json_id = self._register_artifact(
                            published[(workflow_run_id, "json")],
                            "application/json",
                            "ResearchDecisionView@2",
                        )
                    if decision_html_id is None:
                        decision_html_id = self._register_artifact(
                            published[(workflow_run_id, "html")],
                            "text/html",
                            "ResearchDecisionHtml@1",
                        )
                    self._write_manifest(
                        workflow_run_id, decision_json_id, decision_html_id
                    )
                if not self.complete():
                    raise PersistenceError(
                        "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                        "Decision-view cutover did not reach a complete state.",
                    )
                self._fault("research_view_cutover.before_commit")
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def _write_manifest(self, workflow_run_id: str, json_id: str, html_id: str) -> None:
        identity = [
            {"artifact_id": json_id, "role": "decision_view_json", "direction": "output"},
            {"artifact_id": html_id, "role": "decision_view_html", "direction": "output"},
        ]
        manifest_id = "manifest_" + canonical_hash(
            {
                "role": "workflow_decision_view@1",
                "producer_type": "WorkflowRun",
                "producer_id": workflow_run_id,
                "members": identity,
            }
        )[:24]
        existing_refs = tuple(
            self._connection.execute(
                "SELECT ref_type,ref_id FROM workflow_run_ref "
                "WHERE workflow_run_id=? AND ref_role='decision_view_manifest'",
                (workflow_run_id,),
            )
        )
        if existing_refs and (
            len(existing_refs) != 1
            or tuple(existing_refs[0]) != ("ArtifactManifest", manifest_id)
        ):
            raise PersistenceError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Workflow has a conflicting decision-view reference.",
            )
        created_at = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            "INSERT OR IGNORE INTO artifact_manifest VALUES(?,?,?,?,?,?,?)",
            (
                manifest_id,
                "workflow_decision_view@1",
                "WorkflowRun",
                workflow_run_id,
                canonical_hash(identity),
                created_at,
                2,
            ),
        )
        for index, item in enumerate(identity):
            self._connection.execute(
                "INSERT OR IGNORE INTO artifact_manifest_member VALUES(?,?,?,?,?)",
                (manifest_id, index, item["artifact_id"], item["role"], item["direction"]),
            )
        self._connection.execute(
            "INSERT OR IGNORE INTO workflow_run_ref VALUES(?,?,?,?,?)",
            (
                workflow_run_id,
                "decision_view_manifest",
                "ArtifactManifest",
                manifest_id,
                "created",
            ),
        )

    def _object_payload(self, sha256: str) -> bytes:
        row = self._connection.execute(
            "SELECT size_bytes,relative_path FROM object_blob WHERE sha256=?",
            (sha256,),
        ).fetchone()
        if row is None:
            raise PersistenceError("OBJECT_INTEGRITY_FAILED", "Object is missing.")
        path = self._data_root / row["relative_path"]
        payload = path.read_bytes() if path.is_file() else b""
        if len(payload) != row["size_bytes"] or hashlib.sha256(payload).hexdigest() != sha256:
            raise PersistenceError("OBJECT_INTEGRITY_FAILED", "Object is corrupt.")
        return payload

    def _artifact_payload(self, artifact_id: str) -> tuple[sqlite3.Row, bytes]:
        row = self._connection.execute(
            "SELECT a.*,o.size_bytes,o.relative_path FROM artifact a "
            "JOIN object_blob o ON o.sha256=a.object_sha256 WHERE a.artifact_id=?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise PersistenceError("OBJECT_INTEGRITY_FAILED", "Artifact is missing.")
        return row, self._object_payload(str(row["object_sha256"]))

    def _unique_source_pair(
        self, research_run_id: str
    ) -> tuple[str, str, Mapping[str, object]]:
        record = self._connection.execute(
            "SELECT * FROM research_run_record WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        schema = f"ResearchRun@{record['engine_schema_version']}"
        json_candidates: list[tuple[str, Mapping[str, object]]] = []
        for row in self._connection.execute(
            "SELECT artifact_id FROM artifact WHERE schema_version=?", (schema,)
        ):
            _, payload = self._artifact_payload(str(row[0]))
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(decoded, Mapping)
                and decoded.get("run_id") == research_run_id
                and decoded.get("schema_version") == record["engine_schema_version"]
            ):
                json_candidates.append((str(row[0]), decoded))
        html_candidates = [
            str(row[0])
            for row in self._connection.execute(
                "SELECT artifact_id FROM artifact WHERE schema_version IN "
                "('ResearchReportHtml@1','ResearchSourceIdentityHtml@1')"
            )
            for _, payload in (self._artifact_payload(str(row[0])),)
            if self._matches_source_html(
                payload, research_run_id, int(record["engine_schema_version"])
            )
        ]
        if len(json_candidates) != 1 or len(html_candidates) != 1:
            raise PersistenceError(
                "RESEARCH_SOURCE_ARTIFACT_NOT_UNIQUE",
                "Research source artifact pair is not unique.",
            )
        return json_candidates[0][0], html_candidates[0], json_candidates[0][1]

    @staticmethod
    def _matches_source_html(
        payload: bytes, research_run_id: str, engine_schema_version: int
    ) -> bool:
        try:
            document = payload.decode("utf-8")
        except UnicodeDecodeError:
            return False
        escaped = html.escape(research_run_id, quote=True)
        run_tokens = (
            f"Canonical Run {escaped}<",
            f"Run {escaped}</",
            f"Run {escaped} ·",
        )
        schema_tokens = (
            f"Schema v{engine_schema_version}<",
            f"Schema v{engine_schema_version} ·",
        )
        return any(token in document for token in run_tokens) and any(
            token in document for token in schema_tokens
        )

    def _existing_decision_artifacts(
        self,
        workflow_run_id: str,
        research_run_id: str,
        materializer: ResearchDecisionViewMaterializerPort,
    ) -> tuple[str, str, bytes, bytes] | None:
        rows = tuple(
            self._connection.execute(
                "SELECT m.member_role,m.artifact_id FROM artifact_manifest f "
                "JOIN artifact_manifest_member m USING(artifact_manifest_id) "
                "WHERE f.producer_type='WorkflowRun' AND f.producer_id=? "
                "AND f.manifest_role='workflow_decision_view@1' "
                "ORDER BY f.artifact_manifest_id,m.member_order",
                (workflow_run_id,),
            )
        )
        if not rows:
            json_candidates: list[tuple[str, bytes]] = []
            for row in self._connection.execute(
                "SELECT artifact_id FROM artifact WHERE schema_version='ResearchDecisionView@2'"
            ):
                _, payload = self._artifact_payload(str(row[0]))
                try:
                    decoded = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(decoded, Mapping)
                    and decoded.get("workflow_run_id") == workflow_run_id
                    and decoded.get("schema_version") == "ResearchDecisionView@2"
                ):
                    json_candidates.append((str(row[0]), payload))
            if not json_candidates:
                return None
            if len(json_candidates) != 1:
                raise PersistenceError(
                    "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                    "Existing decision JSON is ambiguous.",
                )
            try:
                expected_html = materializer.expected_html(
                    workflow_run_id, research_run_id, json_candidates[0][1]
                )
            except ValueError as error:
                raise PersistenceError(
                    "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                    "Existing decision JSON is invalid.",
                ) from error
            html_candidates = [
                (str(row[0]), payload)
                for row in self._connection.execute(
                    "SELECT artifact_id FROM artifact WHERE schema_version='ResearchDecisionHtml@1'"
                )
                for _, payload in (self._artifact_payload(str(row[0])),)
                if payload == expected_html
            ]
            if len(html_candidates) != 1:
                raise PersistenceError(
                    "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                    "Existing decision HTML is not unique.",
                )
            return (
                json_candidates[0][0],
                html_candidates[0][0],
                json_candidates[0][1],
                html_candidates[0][1],
            )
        if len(rows) != 2 or tuple(row["member_role"] for row in rows) != (
            "decision_view_json",
            "decision_view_html",
        ):
            raise PersistenceError(
                "RESEARCH_VIEW_CUTOVER_INCOMPLETE",
                "Existing decision manifest is ambiguous.",
            )
        _, json_bytes = self._artifact_payload(str(rows[0]["artifact_id"]))
        _, html_bytes = self._artifact_payload(str(rows[1]["artifact_id"]))
        return (
            str(rows[0]["artifact_id"]),
            str(rows[1]["artifact_id"]),
            json_bytes,
            html_bytes,
        )
