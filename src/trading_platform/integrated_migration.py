from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from trading_platform.identifiers import digest, parse_time
from trading_platform.portfolio import AccountSnapshot, ExecutionRecord, RiskPolicy
from trading_platform.storage import SQLiteStore, StorageError


ID_KEYS = {
    "AccountSnapshot": "snapshot_id",
    "ExecutionRecord": "execution_id",
    "RiskPolicy": "policy_id",
    "RiskLimitResult": "risk_limit_result_id",
    "EvidenceSet": "evidence_set_id",
    "InvestmentCase": "investment_case_id",
    "ValuationAssessment": "valuation_assessment_id",
    "DecisionCard": "decision_card_id",
    "TradePlanDraft": "draft_id",
    "TradePlan": "trade_plan_id",
    "PlanClosed": "plan_closed_id",
    "PlanEvaluation": "plan_evaluation_id",
    "DecisionTask": "task_id",
    "DecisionReview": "decision_review_id",
}
MUTATIONS = {
    "account.confirm",
    "research.commit",
    "valuation.assess",
    "planning.prepare",
    "planning.confirm",
    "monitor.evaluate",
    "review.commit",
}
COMMAND_RESULT_KINDS = {
    "account.confirm": {"AccountSnapshot"},
    "research.commit": {"InvestmentCase"},
    "valuation.assess": {"ValuationAssessment"},
    "planning.prepare": {"TradePlanDraft"},
    "planning.confirm": {"TradePlan", "PlanClosed"},
    "monitor.evaluate": {"PlanEvaluation"},
    "review.commit": {"DecisionReview"},
}
PLAN_CONTENT_KEYS = (
    "decision_card_id",
    "account_id",
    "security_id",
    "expires_at",
    "review_window_end",
    "rules",
    "plan_family_id",
    "revision",
    "supersedes_plan_id",
    "close_plan_id",
)


class MigrationBlocked(RuntimeError):
    pass


def migrate_synthetic_root(
    source: Path, target_root: Path, *, fault_at: str | None = None
) -> dict[str, Any]:
    source = Path(source)
    target_root = Path(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    backup = target_root / "pre-migration-source.sqlite3"
    _backup_once(source, backup)
    if fault_at == "after_backup":
        raise MigrationBlocked("injected after backup")
    rows, commands = _read(source)
    if fault_at == "after_prepare":
        raise MigrationBlocked("injected after object preparation")
    _validate(rows, commands)
    store = SQLiteStore(target_root)
    if fault_at == "after_schema":
        raise MigrationBlocked("injected after schema preparation")
    marker = store.get("MigrationMarker", "integrated")
    source_digest = _sha256(source)
    if marker is not None:
        if marker["source_digest"] != source_digest:
            raise MigrationBlocked("migration target is already bound to another source")
        return {
            "migrated": 0,
            "commands_migrated": 0,
            "replayed": True,
            "backup_verified": True,
        }
    try:
        with store.transaction():
            for index, (kind, old_id, payload) in enumerate(rows):
                record_id = _record_id(kind, old_id, payload)
                store.put(
                    kind,
                    record_id,
                    payload,
                    account_id=payload.get("account_id"),
                    as_of=payload.get("as_of")
                    or payload.get("confirmed_at")
                    or payload.get("created_at"),
                )
                if index == 0 and fault_at == "after_first_record":
                    raise MigrationBlocked("injected after first record")
            for command in commands:
                store.put_command(
                    command["operation"],
                    command["idempotency_key"],
                    command["request_digest"],
                    command["result_kind"],
                    command["result_id"],
                )
            if fault_at == "after_commands":
                raise MigrationBlocked("injected after idempotency records")
            if fault_at == "before_marker":
                raise MigrationBlocked("injected before migration marker")
            if fault_at == "before_commit":
                raise MigrationBlocked("injected before commit")
            store.put(
                "MigrationMarker",
                "integrated",
                {
                    "marker_id": "integrated",
                    "source_digest": source_digest,
                    "migrated_ids": [old_id for _, old_id, _ in rows],
                    "migrated_command_keys": [
                        [command["operation"], command["idempotency_key"]]
                        for command in commands
                    ],
                },
            )
    except MigrationBlocked:
        raise
    except (sqlite3.Error, StorageError) as error:
        raise MigrationBlocked("target transaction failed") from error
    if fault_at == "after_commit":
        raise MigrationBlocked("injected after commit")
    return {
        "migrated": len(rows),
        "commands_migrated": len(commands),
        "replayed": False,
        "backup_verified": _sha256(source) == _sha256(backup),
    }


def _read(
    source: Path,
) -> tuple[list[tuple[str, str, dict[str, Any]]], list[dict[str, str]]]:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(source)
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise MigrationBlocked("source database is unreadable")
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        rows = []
        if "old_facts" in tables:
            fact_rows = connection.execute(
                "SELECT kind,old_id,payload FROM old_facts ORDER BY rowid"
            ).fetchall()
            rows = [
                (row["kind"], row["old_id"], json.loads(row["payload"]))
                for row in fact_rows
            ]
        commands: list[dict[str, str]] = []
        if "old_commands" in tables:
            command_rows = connection.execute(
                "SELECT operation,idempotency_key,request_digest,result_kind,result_id "
                "FROM old_commands ORDER BY rowid"
            ).fetchall()
            commands = [dict(row) for row in command_rows]
        return rows, commands
    except MigrationBlocked:
        raise
    except (sqlite3.Error, json.JSONDecodeError, TypeError) as error:
        raise MigrationBlocked("source database is unreadable") from error
    finally:
        if connection is not None:
            connection.close()


def _validate(
    rows: list[tuple[str, str, dict[str, Any]]], commands: list[dict[str, str]]
) -> None:
    try:
        if any(not isinstance(payload, dict) for _, _, payload in rows):
            raise MigrationBlocked("source fact is malformed or has a broken relationship")
        if any(kind not in ID_KEYS for kind, _, _ in rows):
            raise MigrationBlocked("source contains an unmapped fact kind")
        record_ids = [(kind, _record_id(kind, old_id, payload)) for kind, old_id, payload in rows]
        if any(count != 1 for count in Counter(record_ids).values()):
            raise MigrationBlocked("source contains duplicate canonical identities")
        ids = set(record_ids)
        records = {
            (kind, _record_id(kind, old_id, payload)): payload
            for kind, old_id, payload in rows
        }
        revisions = Counter(
            (payload["plan_family_id"], payload["revision"])
            for kind, _, payload in rows
            if kind == "TradePlan"
        )
        if any(count > 1 for count in revisions.values()):
            raise MigrationBlocked("duplicate plan revision")
        closed_targets = Counter(
            payload["closed_plan_id"] for kind, _, payload in rows if kind == "PlanClosed"
        )
        if any(count > 1 for count in closed_targets.values()):
            raise MigrationBlocked("a TradePlan is closed more than once")
        superseded_targets = {
            payload["supersedes_plan_id"]
            for kind, _, payload in rows
            if kind == "TradePlan" and payload.get("supersedes_plan_id")
        }
        if superseded_targets.intersection(closed_targets):
            raise MigrationBlocked("a TradePlan is both superseded and closed")

        def require(kind: str, record_id: object, relationship: str) -> None:
            if (kind, str(record_id)) not in ids:
                raise MigrationBlocked(f"{relationship} relationship is broken")

        def record(kind: str, record_id: object) -> dict[str, Any]:
            require(kind, record_id, kind)
            return records[(kind, str(record_id))]

        for kind, _, payload in rows:
            if kind == "AccountSnapshot":
                try:
                    AccountSnapshot.from_dict(payload)
                except (KeyError, TypeError, ValueError) as error:
                    raise MigrationBlocked("AccountSnapshot user confirmation is unknown or malformed") from error
            elif kind == "ExecutionRecord":
                require("AccountSnapshot", payload["base_snapshot_id"], "ExecutionRecord snapshot")
                snapshot = record("AccountSnapshot", payload["base_snapshot_id"])
                try:
                    execution = ExecutionRecord.from_dict(payload)
                except (KeyError, TypeError, ValueError) as error:
                    raise MigrationBlocked("ExecutionRecord user declaration is unknown or malformed") from error
                if execution.account_id != snapshot.get("account_id"):
                    raise MigrationBlocked("ExecutionRecord account relationship is inconsistent")
            elif kind == "RiskPolicy":
                try:
                    RiskPolicy.from_candidate(payload)
                except (KeyError, TypeError, ValueError) as error:
                    raise MigrationBlocked("RiskPolicy user confirmation or limits are invalid") from error
            elif kind == "RiskLimitResult":
                require("RiskPolicy", payload["policy_id"], "RiskLimitResult policy")
                require("AccountSnapshot", payload["input_refs"]["account_snapshot_id"], "RiskLimitResult account")
                for execution_id in payload["input_refs"].get("execution_record_ids", []):
                    require("ExecutionRecord", execution_id, "RiskLimitResult execution")
            elif kind == "InvestmentCase":
                require("EvidenceSet", payload["evidence_set_id"], "InvestmentCase evidence")
            elif kind == "ValuationAssessment":
                require("InvestmentCase", payload["investment_case_id"], "ValuationAssessment case")
                require("EvidenceSet", payload["evidence_set_id"], "ValuationAssessment evidence")
            elif kind == "DecisionCard":
                require("InvestmentCase", payload["investment_case_id"], "DecisionCard case")
                require("RiskLimitResult", payload["risk_limit_result_id"], "DecisionCard risk")
                require("AccountSnapshot", payload["account_snapshot_id"], "DecisionCard account")
                if payload.get("valuation_assessment_id"):
                    require("ValuationAssessment", payload["valuation_assessment_id"], "DecisionCard valuation")
            elif kind == "TradePlanDraft":
                require("DecisionCard", payload["decision_card_id"], "TradePlanDraft card")
            elif kind == "TradePlan":
                require("TradePlanDraft", payload["draft_id"], "TradePlan draft")
                require("DecisionCard", payload["decision_card_id"], "TradePlan card")
                draft = record("TradePlanDraft", payload["draft_id"])
                content = {key: draft.get(key) for key in PLAN_CONTENT_KEYS}
                if draft["content_hash"] != digest(content) or any(
                    payload.get(key) != draft.get(key)
                    for key in (
                        "content_hash",
                        "decision_card_id",
                        "account_id",
                        "security_id",
                        "review_window_end",
                        "rules",
                        "plan_family_id",
                        "revision",
                        "supersedes_plan_id",
                    )
                ):
                    raise MigrationBlocked("TradePlan confirmation content is inconsistent")
                if not payload.get("confirmed_at") or not payload.get("confirmed_by") or not payload.get("confirmation_channel"):
                    raise MigrationBlocked("TradePlan confirmation content is unknown")
                if draft.get("expires_at") and parse_time(payload["confirmed_at"]) > parse_time(draft["expires_at"]):
                    raise MigrationBlocked("TradePlan was confirmed after draft expiry")
                if payload.get("supersedes_plan_id"):
                    require("TradePlan", payload["supersedes_plan_id"], "TradePlan revision")
                    prior = record("TradePlan", payload["supersedes_plan_id"])
                    if prior["plan_family_id"] != payload["plan_family_id"] or int(payload["revision"]) != int(prior["revision"]) + 1:
                        raise MigrationBlocked("TradePlan revision relationship is inconsistent")
                elif int(payload["revision"]) != 1:
                    raise MigrationBlocked("TradePlan revision chain does not start at one")
            elif kind == "PlanClosed":
                require("TradePlan", payload["closed_plan_id"], "PlanClosed plan")
                require("TradePlanDraft", payload["draft_id"], "PlanClosed draft")
                closed_plan = record("TradePlan", payload["closed_plan_id"])
                close_draft = record("TradePlanDraft", payload["draft_id"])
                close_content = {key: close_draft.get(key) for key in PLAN_CONTENT_KEYS}
                if (
                    close_draft.get("content_hash") != digest(close_content)
                    or close_draft.get("close_plan_id") != payload["closed_plan_id"]
                    or payload["plan_family_id"] != closed_plan["plan_family_id"]
                    or close_draft.get("plan_family_id") != closed_plan["plan_family_id"]
                    or close_draft.get("account_id") != closed_plan["account_id"]
                    or close_draft.get("security_id") != closed_plan["security_id"]
                ):
                    raise MigrationBlocked("PlanClosed relationship is inconsistent")
                if not payload.get("closed_at") or not payload.get("closed_by") or not payload.get("channel"):
                    raise MigrationBlocked("PlanClosed confirmation content is unknown")
                if parse_time(payload["closed_at"]) < parse_time(closed_plan["confirmed_at"]):
                    raise MigrationBlocked("PlanClosed predates the confirmed plan")
                if close_draft.get("expires_at") and parse_time(payload["closed_at"]) > parse_time(close_draft["expires_at"]):
                    raise MigrationBlocked("PlanClosed was confirmed after draft expiry")
            elif kind == "PlanEvaluation":
                require("TradePlan", payload["trade_plan_id"], "PlanEvaluation plan")
                require("EvidenceSet", payload["evidence_set_id"], "PlanEvaluation evidence")
            elif kind == "DecisionTask":
                require("TradePlan", payload["trade_plan_id"], "DecisionTask plan")
                require("PlanEvaluation", payload["plan_evaluation_id"], "DecisionTask evaluation")
                evaluation = record("PlanEvaluation", payload["plan_evaluation_id"])
                if evaluation["trade_plan_id"] != payload["trade_plan_id"] or evaluation["status"] != "triggered":
                    raise MigrationBlocked("DecisionTask evaluation relationship is inconsistent")
            elif kind == "DecisionReview":
                require("TradePlan", payload["trade_plan_id"], "DecisionReview plan")
                require("DecisionTask", payload["task_id"], "DecisionReview task")
                task = record("DecisionTask", payload["task_id"])
                if task["trade_plan_id"] != payload["trade_plan_id"]:
                    raise MigrationBlocked("DecisionReview task relationship is inconsistent")
                if payload["review_type"] == "OUTCOME":
                    require("DecisionReview", payload["process_review_id"], "OUTCOME review")
                    process = record("DecisionReview", payload["process_review_id"])
                    plan = record("TradePlan", payload["trade_plan_id"])
                    if process["review_type"] != "PROCESS" or process["trade_plan_id"] != payload["trade_plan_id"] or process["task_id"] != payload["task_id"]:
                        raise MigrationBlocked("OUTCOME review relationship is inconsistent")
                    if parse_time(payload["as_of"]) <= parse_time(plan["review_window_end"]) or parse_time(payload["as_of"]) <= parse_time(process["as_of"]):
                        raise MigrationBlocked("OUTCOME review window is inconsistent")
                elif payload["review_type"] == "PROCESS":
                    plan = record("TradePlan", payload["trade_plan_id"])
                    evaluation = record("PlanEvaluation", task["plan_evaluation_id"])
                    card = record("DecisionCard", plan["decision_card_id"])
                    linked: dict[str, str | None] = {
                        str(payload["trade_plan_id"]): plan.get("confirmed_at"),
                        str(payload["task_id"]): task.get("created_at"),
                        str(card["decision_card_id"]): card.get("as_of"),
                        str(evaluation["plan_evaluation_id"]): evaluation.get("as_of"),
                    }
                    referenced = (
                        ("InvestmentCase", card.get("investment_case_id")),
                        ("ValuationAssessment", card.get("valuation_assessment_id")),
                        ("RiskLimitResult", card.get("risk_limit_result_id")),
                        ("AccountSnapshot", card.get("account_snapshot_id")),
                        ("EvidenceSet", evaluation.get("evidence_set_id")),
                    )
                    for linked_kind, linked_id in referenced:
                        if linked_id is None:
                            continue
                        linked_record = record(linked_kind, linked_id)
                        linked_time = linked_record.get("as_of")
                        if linked_kind == "RiskLimitResult":
                            linked_time = linked_record.get("portfolio_state", {}).get("as_of")
                        linked[str(linked_id)] = linked_time
                    frozen_refs = [str(item) for item in payload.get("frozen_refs", [])]
                    if not frozen_refs or any(ref not in linked for ref in frozen_refs):
                        raise MigrationBlocked("PROCESS frozen references are unrelated")
                    process_time = parse_time(payload["as_of"])
                    if any(
                        linked[ref] is not None and parse_time(str(linked[ref])) > process_time
                        for ref in frozen_refs
                    ):
                        raise MigrationBlocked("PROCESS contains information from after its as_of")
                else:
                    raise MigrationBlocked("DecisionReview type is unknown")

        command_keys = Counter((command["operation"], command["idempotency_key"]) for command in commands)
        if any(count != 1 for count in command_keys.values()):
            raise MigrationBlocked("source contains duplicate idempotency identities")
        for command in commands:
            if command["operation"] not in MUTATIONS:
                raise MigrationBlocked("source contains an unknown application operation")
            if command["result_kind"] not in COMMAND_RESULT_KINDS[command["operation"]]:
                raise MigrationBlocked("application command result kind is inconsistent")
            require(command["result_kind"], command["result_id"], "application command result")
    except MigrationBlocked:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise MigrationBlocked("source fact is malformed or has a broken relationship") from error


def _record_id(kind: str, old_id: str, payload: dict[str, Any]) -> str:
    return str(payload.get(ID_KEYS[kind], old_id))


def _backup_once(source: Path, backup: Path) -> None:
    if backup.exists():
        if _sha256(source) != _sha256(backup):
            raise MigrationBlocked("existing migration backup does not match the source")
        return
    shutil.copy2(source, backup)
    if _sha256(source) != _sha256(backup):
        raise MigrationBlocked("migration backup verification failed")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
