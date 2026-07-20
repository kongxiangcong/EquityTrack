from __future__ import annotations

from pathlib import Path

from trading_platform.application.workflow_ledger import GenericObjectCommit


class LegacyResearchCutoverFixture:
    """Builds otherwise-unrepresentable legacy graphs for migration tests only."""

    def __init__(self, store: object) -> None:
        self._store = store
        self._connection = store.connection
        self._data_root = Path(store.data_root).resolve()

    def remove_decision_graph(self, workflow_run_id: str) -> None:
        members = tuple(
            self._connection.execute(
                "SELECT f.artifact_manifest_id,m.artifact_id,o.sha256,o.relative_path "
                "FROM workflow_run_ref r "
                "JOIN artifact_manifest f ON f.artifact_manifest_id=r.ref_id "
                "JOIN artifact_manifest_member m USING(artifact_manifest_id) "
                "JOIN artifact a USING(artifact_id) "
                "JOIN object_blob o ON o.sha256=a.object_sha256 "
                "WHERE r.workflow_run_id=? AND r.ref_role='decision_view_manifest'",
                (workflow_run_id,),
            )
        )
        manifest_ids = {str(row["artifact_manifest_id"]) for row in members}
        artifact_ids = {str(row["artifact_id"]) for row in members}
        objects = {(str(row["sha256"]), str(row["relative_path"])) for row in members}
        if artifact_ids:
            placeholders = ",".join("?" for _ in artifact_ids)
            manifest_ids.update(
                str(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT artifact_manifest_id FROM artifact_manifest_member "
                    f"WHERE artifact_id IN ({placeholders})",
                    tuple(artifact_ids),
                )
            )
        with self._connection:
            self._connection.execute("DROP TRIGGER artifact_manifest_member_no_delete")
            self._connection.execute("DROP TRIGGER artifact_manifest_no_delete")
            self._connection.execute("DROP TRIGGER object_blob_no_delete")
            for manifest_id in manifest_ids:
                self._connection.execute(
                    "DELETE FROM workflow_run_ref WHERE ref_type='ArtifactManifest' "
                    "AND ref_id=?",
                    (manifest_id,),
                )
                self._connection.execute(
                    "DELETE FROM artifact_manifest_member WHERE artifact_manifest_id=?",
                    (manifest_id,),
                )
                self._connection.execute(
                    "DELETE FROM artifact_manifest WHERE artifact_manifest_id=?",
                    (manifest_id,),
                )
            for artifact_id in artifact_ids:
                self._connection.execute(
                    "DELETE FROM artifact WHERE artifact_id=?", (artifact_id,)
                )
            for sha256, _ in objects:
                self._connection.execute(
                    "DELETE FROM object_blob WHERE sha256=?", (sha256,)
                )
        for _, relative_path in objects:
            path = (self._data_root / relative_path).resolve()
            if path != self._data_root and self._data_root not in path.parents:
                raise AssertionError("legacy fixture object escaped its data root")
            path.unlink(missing_ok=True)

    def decision_ref_count(self, workflow_run_id: str) -> int:
        return int(
            self._connection.execute(
                "SELECT count(*) FROM workflow_run_ref WHERE workflow_run_id=? "
                "AND ref_role='decision_view_manifest'",
                (workflow_run_id,),
            ).fetchone()[0]
        )

    def remove_decision_reference(self, workflow_run_id: str) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM workflow_run_ref WHERE workflow_run_id=? "
                "AND ref_role='decision_view_manifest'",
                (workflow_run_id,),
            )

    def remove_decision_references(self, workflow_run_ids: tuple[str, ...]) -> None:
        for workflow_run_id in workflow_run_ids:
            self.remove_decision_reference(workflow_run_id)

    def remove_decision_manifest(self, workflow_run_id: str) -> str:
        manifest_id = str(
            self._connection.execute(
                "SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? "
                "AND ref_role='decision_view_manifest'",
                (workflow_run_id,),
            ).fetchone()[0]
        )
        with self._connection:
            self._connection.execute("DROP TRIGGER artifact_manifest_member_no_delete")
            self._connection.execute("DROP TRIGGER artifact_manifest_no_delete")
            self.remove_decision_reference(workflow_run_id)
            self._connection.execute(
                "DELETE FROM artifact_manifest_member WHERE artifact_manifest_id=?",
                (manifest_id,),
            )
            self._connection.execute(
                "DELETE FROM artifact_manifest WHERE artifact_manifest_id=?",
                (manifest_id,),
            )
        return manifest_id

    def add_duplicate_source_json(self, research_run_id: str) -> str:
        source = self._connection.execute(
            "SELECT a.object_sha256,a.schema_version FROM research_run_record r "
            "JOIN artifact a ON a.artifact_id=r.canonical_json_artifact_id "
            "WHERE r.research_run_id=?",
            (research_run_id,),
        ).fetchone()
        duplicate_id = "artifact_duplicate_source"
        with self._connection:
            self._connection.execute(
                "INSERT INTO artifact VALUES(?,?,?,?)",
                (
                    duplicate_id,
                    source["object_sha256"],
                    "application/vnd.duplicate+json",
                    source["schema_version"],
                ),
            )
        return duplicate_id

    def hide_exact_source_json(self, research_run_id: str) -> str:
        artifact_id = self.source_json_artifact_id(research_run_id)
        with self._connection:
            self._connection.execute(
                "UPDATE artifact SET schema_version='UnrelatedSource@1' "
                "WHERE artifact_id=?",
                (artifact_id,),
            )
        return artifact_id

    def decision_ref_id(self, workflow_run_id: str) -> str:
        return str(
            self._connection.execute(
                "SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? "
                "AND ref_role='decision_view_manifest'",
                (workflow_run_id,),
            ).fetchone()[0]
        )

    def corrupt_decision_manifest_identity(self, workflow_run_id: str) -> None:
        manifest_id = self.decision_ref_id(workflow_run_id)
        with self._connection:
            self._connection.execute("DROP TRIGGER artifact_manifest_no_update")
            self._connection.execute(
                "UPDATE artifact_manifest SET membership_hash='corrupt' "
                "WHERE artifact_manifest_id=?",
                (manifest_id,),
            )

    def mark_completed_workflow_v1(self, workflow_run_id: str) -> None:
        with self._connection:
            self._connection.execute("DROP TRIGGER workflow_run_identity_immutable")
            self._connection.execute(
                "UPDATE workflow_run SET workflow_version='1',definition_hash='legacy-v1' "
                "WHERE workflow_run_id=?",
                (workflow_run_id,),
            )

    def source_artifact_ids(self, research_run_id: str) -> tuple[str, str]:
        row = self._connection.execute(
            "SELECT canonical_json_artifact_id,html_artifact_id "
            "FROM research_run_record WHERE research_run_id=?",
            (research_run_id,),
        ).fetchone()
        return str(row[0]), str(row[1])

    def source_html_path(self, research_run_id: str) -> Path:
        relative_path = str(
            self._connection.execute(
                "SELECT o.relative_path FROM research_run_record r "
                "JOIN artifact a ON a.artifact_id=r.html_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256 "
                "WHERE r.research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
        path = (self._data_root / relative_path).resolve()
        if path != self._data_root and self._data_root not in path.parents:
            raise AssertionError("source HTML escaped its data root")
        return path

    def add_misleading_source_html(
        self, workflow_run_id: str, research_run_id: str
    ) -> None:
        version = int(
            self._connection.execute(
                "SELECT engine_schema_version FROM research_run_record "
                "WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
        payload = (
            f"<span>Run {research_run_id}-not-exact · Schema v{version}</span>"
        ).encode()
        committed = self._store.workflow_ledger.commit_artifacts(
            GenericObjectCommit(payload)
        )
        with self._connection:
            self._connection.execute(
                "INSERT INTO artifact VALUES(?,?,?,?)",
                (
                    "artifact_misleading_source_html",
                    committed.sha256,
                    "text/html",
                    "ResearchReportHtml@1",
                ),
            )
        self.remove_decision_reference(workflow_run_id)

    def add_misleading_source_schema(
        self, workflow_run_id: str, research_run_id: str
    ) -> None:
        version = int(
            self._connection.execute(
                "SELECT engine_schema_version FROM research_run_record "
                "WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
        payload = (
            f"<span>Run {research_run_id} · Schema v{version}.1</span>"
        ).encode()
        committed = self._store.workflow_ledger.commit_artifacts(
            GenericObjectCommit(payload)
        )
        with self._connection:
            self._connection.execute(
                "INSERT INTO artifact VALUES(?,?,?,?)",
                (
                    "artifact_misleading_source_schema",
                    committed.sha256,
                    "text/html",
                    "ResearchReportHtml@1",
                ),
            )
        self.remove_decision_reference(workflow_run_id)

    def prepare_conflicting_decision_reference(
        self,
        workflow_run_id: str,
        research_run_id: str,
        wrong_source_artifact_id: str,
    ) -> str:
        alternate_manifest_id = str(
            self._connection.execute(
                "SELECT artifact_manifest_id FROM artifact_manifest "
                "WHERE artifact_manifest_id NOT IN ("
                "SELECT ref_id FROM workflow_run_ref WHERE workflow_run_id=? "
                "AND ref_role='decision_view_manifest') LIMIT 1",
                (workflow_run_id,),
            ).fetchone()[0]
        )
        with self._connection:
            self._connection.execute(
                "UPDATE research_run_record SET canonical_json_artifact_id=? "
                "WHERE research_run_id=?",
                (wrong_source_artifact_id, research_run_id),
            )
            self._connection.execute(
                "INSERT INTO workflow_run_ref VALUES(?,?,?,?,?)",
                (
                    workflow_run_id,
                    "decision_view_manifest",
                    "ArtifactManifest",
                    alternate_manifest_id,
                    "created",
                ),
            )
        return wrong_source_artifact_id

    def source_json_artifact_id(self, research_run_id: str) -> str:
        return str(
            self._connection.execute(
                "SELECT canonical_json_artifact_id FROM research_run_record "
                "WHERE research_run_id=?",
                (research_run_id,),
            ).fetchone()[0]
        )
