from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

from trading_platform.application.workflow_ledger import (
    DurableObject,
    QualificationReceiptCommit,
    QualificationReceiptQuery,
    QualificationReceiptReplay,
    QualificationReceiptReplayQuery,
    WorkflowPersistenceError,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock


class QualificationReceiptStore:
    """Own authoritative qualification command replay and evidence lineage."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        data_root: Path,
        writer_lock: DataRootWriterLock,
        publish_durable: Callable[[bytes], DurableObject],
    ) -> None:
        self._connection = connection
        self._data_root = data_root.resolve()
        self._writer_lock = writer_lock
        self._publish_durable = publish_durable

    @staticmethod
    def _error(code: str, substep: str, subject: str) -> WorkflowPersistenceError:
        return WorkflowPersistenceError(code, substep, subject)

    def commit(self, command: QualificationReceiptCommit) -> str:
        if not command.invocation_id or len(command.request_hash) != 64:
            raise self._error(
                "QUALIFICATION_RECEIPT_COMMAND_INVALID",
                "qualification_receipt.commit",
                command.invocation_id,
            )
        self._validate_payload(
            command.payload,
            command.invocation_id,
            command.request_hash,
            "qualification_receipt.commit",
        )
        with self._writer_lock.acquire(f"qualification:{command.invocation_id}"):
            existing = self._connection.execute(
                "SELECT command_name,request_hash,result_type,result_id "
                "FROM command_receipt WHERE invocation_id=?",
                (command.invocation_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["command_name"] != "provider-qualify@2"
                    or existing["request_hash"] != command.request_hash
                    or existing["result_type"] != "ProviderQualificationReceipt"
                ):
                    raise self._error(
                        "QUALIFICATION_RECEIPT_REPLAY_MISMATCH",
                        "qualification_receipt.commit",
                        command.invocation_id,
                    )
                return str(existing["result_id"])
            published = self._publish_durable(command.payload)
            artifact_id = "artifact_" + canonical_hash(
                {
                    "sha256": published.sha256,
                    "media": "application/json",
                    "schema": "ProviderQualificationReceipt@1",
                }
            )[:24]
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT OR IGNORE INTO object_blob VALUES(?,?,?)",
                    (published.sha256, published.size_bytes, published.relative_path),
                )
                self._connection.execute(
                    "INSERT OR IGNORE INTO artifact VALUES(?,?,?,?)",
                    (artifact_id, published.sha256, "application/json", "ProviderQualificationReceipt@1"),
                )
                self._connection.execute(
                    "INSERT INTO command_receipt VALUES(?,?,?,?,?)",
                    (
                        command.invocation_id,
                        "provider-qualify@2",
                        command.request_hash,
                        "ProviderQualificationReceipt",
                        artifact_id,
                    ),
                )
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
            return artifact_id

    def replay(
        self, query: QualificationReceiptReplayQuery
    ) -> QualificationReceiptReplay | None:
        row = self._connection.execute(
            "SELECT command_name,request_hash,result_type,result_id "
            "FROM command_receipt WHERE invocation_id=?",
            (query.invocation_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"] != "provider-qualify@2"
            or row["request_hash"] != query.request_hash
            or row["result_type"] != "ProviderQualificationReceipt"
        ):
            raise self._error(
                "QUALIFICATION_RECEIPT_REPLAY_MISMATCH",
                "qualification_receipt.replay",
                query.invocation_id,
            )
        artifact_id = str(row["result_id"])
        return QualificationReceiptReplay(
            artifact_id,
            self.load(QualificationReceiptQuery(artifact_id)),
        )

    def load(self, query: QualificationReceiptQuery) -> bytes:
        row = self._connection.execute(
            "SELECT c.invocation_id,c.request_hash,a.object_sha256,a.media_type,"
            "a.schema_version,o.size_bytes,o.relative_path "
            "FROM artifact a JOIN object_blob o ON o.sha256=a.object_sha256 "
            "JOIN command_receipt c ON c.result_id=a.artifact_id "
            "WHERE a.artifact_id=? AND c.command_name='provider-qualify@2' "
            "AND c.result_type='ProviderQualificationReceipt'",
            (query.artifact_id,),
        ).fetchone()
        if (
            row is None
            or row["media_type"] != "application/json"
            or row["schema_version"] != "ProviderQualificationReceipt@1"
        ):
            raise self._error(
                "QUALIFICATION_RECEIPT_NOT_FOUND",
                "qualification_receipt.read",
                query.artifact_id,
            )
        payload = self._verified_object(
            row["object_sha256"], row["size_bytes"], row["relative_path"], query.artifact_id
        )
        self._validate_payload(
            payload,
            str(row["invocation_id"]),
            str(row["request_hash"]),
            "qualification_receipt.read",
        )
        return payload

    def _verified_object(
        self, sha256: str, size_bytes: int, relative_path: str, subject: str
    ) -> bytes:
        relative = PurePosixPath(relative_path)
        path = (self._data_root / Path(*relative.parts)).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_relative_to(self._data_root)
            or not path.is_file()
        ):
            raise self._error(
                "QUALIFICATION_RECEIPT_INTEGRITY_FAILED",
                "qualification_receipt.read",
                subject,
            )
        payload = path.read_bytes()
        if len(payload) != size_bytes or hashlib.sha256(payload).hexdigest() != sha256:
            raise self._error(
                "QUALIFICATION_RECEIPT_INTEGRITY_FAILED",
                "qualification_receipt.read",
                subject,
            )
        return payload

    def _validate_payload(
        self, payload: bytes, invocation_id: str, request_hash: str, substep: str
    ) -> Mapping[str, object]:
        try:
            receipt = json.loads(payload)
            if not isinstance(receipt, dict):
                raise TypeError("receipt object required")
            if (
                receipt.get("schema_version") != "ProviderQualificationReceipt@1"
                or receipt.get("invocation_id") != invocation_id
                or receipt.get("request_fingerprint") != request_hash
            ):
                raise TypeError("receipt command lineage invalid")
            query_policy = receipt["query_policy"]
            source_policy = receipt["source_policy"]
            if receipt["query_policy_identity"] != "query_policy_" + canonical_hash(query_policy)[:24]:
                raise TypeError("query policy identity invalid")
            if receipt["source_policy_identity"] != "source_policy_" + canonical_hash(source_policy)[:24]:
                raise TypeError("source policy identity invalid")
            code_identity = receipt["adapter_code_identity"]
            if not isinstance(code_identity, str) or not code_identity.startswith("sha256:") or len(code_identity) != 71:
                raise TypeError("adapter code identity invalid")
            datetime.fromisoformat(str(receipt["as_of_at"]))
            datetime.fromisoformat(str(receipt["qualified_at"]))
            transport_identity = receipt["transport_identity"]
            if not isinstance(transport_identity, str) or len(transport_identity) != 64:
                raise TypeError("transport identity invalid")
            if receipt["qualification_profile"] not in {"production", "test_loopback"}:
                raise TypeError("qualification profile invalid")
            attempts = receipt["attempts"]
            if not isinstance(attempts, list) or not attempts:
                raise TypeError("attempt evidence missing")
            attempt_ids: set[str] = set()
            for attempt in attempts:
                self._validate_attempt(receipt, attempt, invocation_id)
                attempt_ids.add(str(attempt["attempt_id"]))
            self._validate_snapshot(receipt, attempt_ids)
            return receipt
        except WorkflowPersistenceError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise self._error(
                "QUALIFICATION_RECEIPT_LINEAGE_INVALID",
                substep,
                invocation_id,
            ) from error


    def _validate_attempt(
        self, receipt: Mapping[str, object], attempt: object, invocation_id: str
    ) -> None:
        if not isinstance(attempt, dict):
            raise TypeError("attempt object required")
        row = self._connection.execute(
            "SELECT invocation_id,provider_id,adapter_version,dataset,source_identity,"
            "source_authority,terms_profile,status,raw_sha256,retrieved_at,error_code "
            "FROM provider_attempt WHERE attempt_id=?",
            (attempt["attempt_id"],),
        ).fetchone()
        if row is None:
            raise TypeError("attempt lineage missing")
        expected = {
            "invocation_id": invocation_id,
            "provider_id": receipt["provider_id"],
            "adapter_version": receipt["adapter_version"],
            "dataset": attempt["dataset"],
            "source_identity": receipt["provider_identity"],
            "source_authority": receipt["source_authority"],
            "terms_profile": receipt["terms_profile"],
            "status": attempt["status"],
            "raw_sha256": attempt["raw_sha256"],
            "retrieved_at": attempt["retrieved_at"],
            "error_code": attempt["error_code"],
        }
        if any(row[key] != value for key, value in expected.items()):
            raise TypeError("attempt identity mismatch")
        blocking = tuple(
            str(item[0])
            for item in self._connection.execute(
                "SELECT code FROM data_quality_issue WHERE attempt_id=? "
                "AND severity IN ('blocking','quarantine') ORDER BY code",
                (attempt["attempt_id"],),
            )
        )
        if tuple(attempt["blocking_codes"]) != blocking:
            raise TypeError("attempt blocking evidence mismatch")
        raw_sha256 = attempt["raw_sha256"]
        if raw_sha256 is None:
            if attempt["status"] == "complete":
                raise TypeError("complete attempt raw missing")
            return
        raw = self._connection.execute(
            "SELECT size_bytes,relative_path FROM object_blob WHERE sha256=?",
            (raw_sha256,),
        ).fetchone()
        if raw is None:
            raise TypeError("attempt raw object missing")
        self._verified_object(
            str(raw_sha256), int(raw["size_bytes"]), str(raw["relative_path"]),
            str(attempt["attempt_id"]),
        )

    def _validate_snapshot(
        self, receipt: Mapping[str, object], attempt_ids: set[str]
    ) -> None:
        snapshot_id = receipt["data_snapshot_id"]
        if snapshot_id is None:
            if receipt["status"] == "qualified":
                raise TypeError("qualified receipt snapshot missing")
            return
        row = self._connection.execute(
            "SELECT requested_date,effective_session_date,as_of_at,query_policy_identity,"
            "source_policy_identity,membership_hash,quality_status,coverage_expected,"
            "coverage_eligible,coverage_excluded,coverage_missing FROM data_snapshot "
            "WHERE data_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise TypeError("snapshot lineage missing")
        if (
            row["requested_date"] != receipt["requested_date"]
            or row["effective_session_date"] != receipt["effective_session_date"]
            or row["as_of_at"] != receipt["as_of_at"]
            or row["query_policy_identity"] != receipt["query_policy_identity"]
            or row["source_policy_identity"] != receipt["source_policy_identity"]
        ):
            raise TypeError("snapshot policy lineage mismatch")
        coverage = receipt["coverage"]
        if (
            receipt["snapshot_quality"] != row["quality_status"]
            or coverage["expected"] != row["coverage_expected"]
            or coverage["eligible"] != row["coverage_eligible"]
            or coverage["excluded"] != row["coverage_excluded"]
            or coverage["missing"] != row["coverage_missing"]
        ):
            raise TypeError("snapshot qualification status invalid")
        if receipt["status"] == "qualified" and (
            receipt["sync_status"] not in {"complete", "complete_with_substitution"}
            or row["quality_status"] != "pass"
            or row["coverage_missing"] != 0
        ):
            raise TypeError("qualified snapshot is blocking")
        if receipt["status"] != "qualified" and not receipt["blockers"]:
            raise TypeError("failed receipt blocker missing")
        substitutions = receipt["substitution_receipt_ids"]
        if not isinstance(substitutions, list) or (
            receipt["sync_status"] == "complete_with_substitution" and not substitutions
        ):
            raise TypeError("snapshot substitution evidence invalid")
        members = self._connection.execute(
            "SELECT m.normalized_version_id,m.member_role,m.member_order,"
            "v.source_attempt_id FROM data_snapshot_member m "
            "JOIN normalized_version v USING(normalized_version_id) "
            "WHERE m.data_snapshot_id=? ORDER BY m.member_order",
            (snapshot_id,),
        ).fetchall()
        if not members:
            raise TypeError("snapshot membership missing")
        if [int(member["member_order"]) for member in members] != list(range(len(members))):
            raise TypeError("snapshot membership order invalid")
        membership_hash = canonical_hash(
            [
                {"id": member["normalized_version_id"], "role": member["member_role"]}
                for member in members
            ]
        )
        if membership_hash != row["membership_hash"]:
            raise TypeError("snapshot membership hash mismatch")
        if any(str(member["source_attempt_id"]) not in attempt_ids for member in members):
            raise TypeError("snapshot member attempt lineage invalid")
