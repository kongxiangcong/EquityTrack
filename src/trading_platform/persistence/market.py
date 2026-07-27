from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from trading_platform.application.market_contracts import BuildMarketSnapshotCommand
from trading_platform.domain.market import (
    Completeness, ComponentStatus, EvaluationStatus,
    MarketBar, MarketComponentView, MarketSnapshotView, MarketError,
    PlanEvaluationView, ReasonCode, SecurityMarketConstraint,
    SnapshotStatus, UniverseMember, compute_components,
)
from trading_platform.domain.conflicts import (
    ConflictResolution,
    ResolutionOutcome,
)
from trading_platform.domain.rules import (
    RuleEvaluation,
    RuleResult,
    candidate_from_dict,
    candidate_to_dict,
    operand_from_dict,
    operand_to_dict,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock


class SQLiteMarketRepository:
    def __init__(self, connection: sqlite3.Connection, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.writer_lock = writer_lock

    def build_market_snapshot(self, command: BuildMarketSnapshotCommand) -> MarketSnapshotView:
        code_identity_hash = canonical_hash(command.code_identity)
        snapshot = self.connection.execute("SELECT * FROM data_snapshot WHERE data_snapshot_id=?", (command.data_snapshot_id,)).fetchone()
        universe_ref = self.connection.execute("SELECT * FROM data_snapshot_universe_ref WHERE data_snapshot_id=?", (command.data_snapshot_id,)).fetchone()
        if snapshot is None or snapshot["scope_id"] != command.security_id:
            raise MarketError("MARKET_DATA_SNAPSHOT_INVALID")
        if command.market_model_version != "cn-a-share-market@1" or command.freshness_policy_version != snapshot["freshness_policy_version"]:
            raise MarketError("MARKET_MODEL_OR_POLICY_UNAVAILABLE")
        if universe_ref is None or universe_ref["market_scope_id"] != command.market_scope_id:
            raise MarketError("MARKET_SNAPSHOT_SCOPE_MISMATCH")
        benchmark = self.connection.execute("SELECT security_id FROM security_identifier WHERE code='000300' AND market='SZSE' AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) ORDER BY valid_from DESC LIMIT 1", (snapshot["effective_session_date"], snapshot["effective_session_date"])).fetchone()
        if benchmark is None:
            raise MarketError("MARKET_BENCHMARK_MISSING")
        universe_row = self.connection.execute("SELECT * FROM market_universe_version WHERE market_universe_version_id=?", (universe_ref["market_universe_version_id"],)).fetchone()
        member_rows = self.connection.execute("SELECT * FROM market_universe_member WHERE market_universe_version_id=? ORDER BY security_id", (universe_ref["market_universe_version_id"],)).fetchall()
        member_identity = [{"security_id": row["security_id"], "listed_from": row["listed_from"], "delisted_after": row["delisted_after"], "st_from": row["st_from"], "st_to": row["st_to"], "source_ref": row["source_ref"]} for row in member_rows]
        if universe_row is None or canonical_hash(member_identity) != universe_row["membership_hash"]:
            raise MarketError("MARKET_UNIVERSE_HASH_MISMATCH")
        universe_members = tuple(UniverseMember(row["security_id"], row["listed_from"], row["delisted_after"], row["source_ref"]) for row in member_rows)
        rows = self.connection.execute("""SELECT o.* FROM data_snapshot_member m JOIN ohlcv_version o USING(normalized_version_id)
            WHERE m.data_snapshot_id=? ORDER BY o.security_id,o.session_date""", (command.data_snapshot_id,)).fetchall()
        bars = tuple(MarketBar(row["security_id"], row["session_date"], Decimal(row["close_decimal"]), Decimal(row["amount_decimal"]) if row["amount_decimal"] is not None else None, row["normalized_version_id"]) for row in rows)
        constraint_rows = self.connection.execute("SELECT * FROM security_market_constraint WHERE data_snapshot_id=? AND session_date=? ORDER BY security_id", (command.data_snapshot_id, snapshot["effective_session_date"])).fetchall()
        constraints = {row["security_id"]: SecurityMarketConstraint(row["security_id"], row["session_date"], bool(row["suspended"]), Decimal(row["limit_up_decimal"]), Decimal(row["limit_down_decimal"]), bool(row["corporate_action_conflict"]), tuple(json.loads(row["evidence_refs_json"]))) for row in constraint_rows}
        status, components = compute_components(command.security_id, benchmark[0], universe_members, bars, snapshot["effective_session_date"], snapshot["freshness_status"], snapshot["quality_status"], constraints)
        universe_identity = {"market_universe_version_id": universe_ref["market_universe_version_id"], "membership_hash": universe_row["membership_hash"], "source_policy_version": universe_row["source_policy_version"], "members": member_identity}
        fingerprint = canonical_hash({"security_id": command.security_id, "market_scope_id": command.market_scope_id, "requested_date": snapshot["requested_date"], "effective_session_date": snapshot["effective_session_date"], "data_snapshot_id": command.data_snapshot_id, "universe": universe_identity, "market_model_version": command.market_model_version, "freshness_policy_version": command.freshness_policy_version, "code_identity_hash": code_identity_hash, "components": components})
        existing = self._market_snapshot_for_fingerprint(fingerprint)
        if existing:
            return self.get_market_snapshot(existing[0])
        market_snapshot_id = f"market_snapshot_{fingerprint[:24]}"
        with self.writer_lock.acquire(f"market-snapshot:{market_snapshot_id}"):
            existing = self._market_snapshot_for_fingerprint(fingerprint)
            if existing:
                return self.get_market_snapshot(existing[0])
            with self.connection:
                self.connection.execute("INSERT INTO market_snapshot(market_snapshot_id,security_id,market_scope_id,requested_date,effective_session_date,data_snapshot_id,market_universe_version_id,market_model_version,freshness_policy_version,code_identity_hash,input_fingerprint,status,component_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (market_snapshot_id, command.security_id, command.market_scope_id, snapshot["requested_date"], snapshot["effective_session_date"], command.data_snapshot_id, universe_ref["market_universe_version_id"], command.market_model_version, command.freshness_policy_version, code_identity_hash, fingerprint, status, len(components), datetime.now(timezone.utc).isoformat()))
                for index, component in enumerate(components):
                    self.connection.execute("INSERT INTO market_snapshot_component(market_snapshot_id,component_order,component_id,status,classification,values_json,reason_code,coverage_expected,coverage_eligible,coverage_excluded,coverage_missing,evidence_refs_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (market_snapshot_id, index, component.component_id, component.status, component.classification, json.dumps(component.values), component.reason_code, component.coverage_expected, component.coverage_eligible, component.coverage_excluded, component.coverage_missing, json.dumps(component.evidence_refs)))
        return self.get_market_snapshot(market_snapshot_id)

    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshotView:
        row = self.connection.execute("SELECT * FROM market_snapshot WHERE market_snapshot_id=?", (market_snapshot_id,)).fetchone()
        if row is None:
            raise MarketError("MARKET_SNAPSHOT_NOT_FOUND")
        components = tuple(MarketComponentView(component_id=item["component_id"], status=ComponentStatus(item["status"]), classification=item["classification"], values=tuple(tuple(pair) for pair in json.loads(item["values_json"])), reason_code=ReasonCode(item["reason_code"]), coverage_expected=item["coverage_expected"], coverage_eligible=item["coverage_eligible"], coverage_excluded=item["coverage_excluded"], coverage_missing=item["coverage_missing"], evidence_refs=tuple(json.loads(item["evidence_refs_json"]))) for item in self.connection.execute("SELECT * FROM market_snapshot_component WHERE market_snapshot_id=? ORDER BY component_order", (market_snapshot_id,)))
        return MarketSnapshotView(market_snapshot_id=row["market_snapshot_id"], security_id=row["security_id"], market_scope_id=row["market_scope_id"], requested_date=row["requested_date"], effective_session_date=row["effective_session_date"], data_snapshot_id=row["data_snapshot_id"], market_universe_version_id=row["market_universe_version_id"], market_model_version=row["market_model_version"], freshness_policy_version=row["freshness_policy_version"], code_identity_hash=row["code_identity_hash"], input_fingerprint=row["input_fingerprint"], status=SnapshotStatus(row["status"]), components=components)

    def save_plan_evaluation(self, evaluation: PlanEvaluationView) -> PlanEvaluationView:
        existing = self._plan_evaluation_for_key(evaluation)
        if existing:
            return self.get_plan_evaluation(existing[0])
        with self.writer_lock.acquire(f"plan-evaluation:{evaluation.plan_evaluation_id}"):
            existing = self._plan_evaluation_for_key(evaluation)
            if existing:
                return self.get_plan_evaluation(existing[0])
            with self.connection:
                resolution_json = json.dumps(
                    {
                        "selected_intent_id": evaluation.resolution.selected_intent_id,
                        "contributing_rule_ids": evaluation.resolution.contributing_rule_ids,
                        "policy_version": evaluation.resolution.policy_version,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.connection.execute(
                    "INSERT INTO plan_evaluation VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        evaluation.plan_evaluation_id,
                        evaluation.plan_version_id,
                        evaluation.market_snapshot_id,
                        evaluation.evaluator_version,
                        evaluation.evaluation_policy_version,
                        evaluation.status.value,
                        evaluation.resolution.outcome.value,
                        evaluation.resolution.reason_code,
                        resolution_json,
                        evaluation.resolution.content_hash,
                        evaluation.completeness.value,
                        len(evaluation.rule_results),
                        evaluation.evaluation_hash,
                        0,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                for index, result in enumerate(evaluation.rule_results):
                    evaluation_json = json.dumps(
                        {
                            "operands": tuple(
                                operand_to_dict(item)
                                for item in result.operands
                            ),
                            "candidate_intent": candidate_to_dict(
                                result.candidate_intent
                            ),
                            "matched_grid_levels": result.matched_grid_levels,
                            "observed_at": result.observed_at,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    self.connection.execute(
                        "INSERT INTO plan_rule_evaluation VALUES(?,?,?,?,?,?,?,?)",
                        (
                            evaluation.plan_evaluation_id,
                            index,
                            result.rule_id,
                            result.result.value,
                            result.reason_code,
                            evaluation_json,
                            result.replay_hash,
                            len(result.evidence_refs),
                        ),
                    )
                    for evidence_index, evidence in enumerate(result.evidence_refs):
                        self.connection.execute("INSERT INTO plan_evaluation_evidence(plan_evaluation_id,rule_order,evidence_order,evidence_ref) VALUES(?,?,?,?)", (evaluation.plan_evaluation_id, index, evidence_index, evidence))
        return self.get_plan_evaluation(evaluation.plan_evaluation_id)

    def get_plan_evaluation(self, evaluation_id: str) -> PlanEvaluationView:
        row = self.connection.execute("SELECT * FROM plan_evaluation WHERE plan_evaluation_id=?", (evaluation_id,)).fetchone()
        if row is None:
            raise MarketError("PLAN_EVALUATION_NOT_FOUND")
        if row["legacy_read_only"]:
            raise MarketError("LEGACY_PLAN_EVALUATION_READ_ONLY")
        results = []
        for item in self.connection.execute("SELECT * FROM plan_rule_evaluation WHERE plan_evaluation_id=? ORDER BY rule_order", (evaluation_id,)):
            evidence = tuple(entry[0] for entry in self.connection.execute("SELECT evidence_ref FROM plan_evaluation_evidence WHERE plan_evaluation_id=? AND rule_order=? ORDER BY evidence_order", (evaluation_id, item["rule_order"])))
            payload = json.loads(item["evaluation_json"])
            results.append(
                RuleEvaluation(
                    rule_id=item["rule_id"],
                    result=RuleResult(item["result"]),
                    reason_code=item["reason_code"],
                    operands=tuple(
                        operand_from_dict(value)
                        for value in payload["operands"]
                    ),
                    candidate_intent=candidate_from_dict(
                        payload["candidate_intent"]
                    ),
                    matched_grid_levels=tuple(
                        payload["matched_grid_levels"]
                    ),
                    observed_at=payload["observed_at"],
                    evidence_refs=evidence,
                    replay_hash=item["replay_hash"],
                )
            )
        resolution_payload = json.loads(row["resolution_json"])
        resolution = ConflictResolution(
            outcome=ResolutionOutcome(row["resolution_outcome"]),
            reason_code=row["resolution_reason_code"],
            selected_intent_id=resolution_payload["selected_intent_id"],
            contributing_rule_ids=tuple(
                resolution_payload["contributing_rule_ids"]
            ),
            policy_version=resolution_payload["policy_version"],
            content_hash=row["resolution_hash"],
        )
        return PlanEvaluationView(
            plan_evaluation_id=row["plan_evaluation_id"],
            plan_version_id=row["plan_version_id"],
            market_snapshot_id=row["market_snapshot_id"],
            evaluator_version=row["evaluator_version"],
            evaluation_policy_version=row["evaluation_policy_version"],
            status=EvaluationStatus(row["status"]),
            completeness=Completeness(row["completeness"]),
            rule_results=tuple(results),
            resolution=resolution,
            evaluation_hash=row["evaluation_hash"],
        )

    def _market_snapshot_for_fingerprint(self, fingerprint: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT market_snapshot_id FROM market_snapshot WHERE input_fingerprint=?", (fingerprint,)).fetchone()

    def _plan_evaluation_for_key(self, evaluation: PlanEvaluationView) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT plan_evaluation_id FROM plan_evaluation "
            "WHERE evaluation_hash=?",
            (evaluation.evaluation_hash,),
        ).fetchone()
