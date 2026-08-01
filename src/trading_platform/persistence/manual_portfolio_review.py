from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from trading_platform.domain.market_time import SHANGHAI_TIMEZONE
from trading_platform.domain.account_state import (
    EstimatedAccountState,
    EstimatedPosition,
)
from trading_platform.domain.manual_review import (
    ManualPortfolioReviewCheckpoint,
    ManualPortfolioReviewItem,
    ManualPortfolioReviewManifest,
    ManualPortfolioReviewRun,
    ManualReviewContext,
    ManualReviewError,
    ManualReviewUniverseMember,
    ProvenCompleteSession,
    ReviewOutcome,
)
from trading_platform.domain.plan_impacts import (
    FrozenPlanImpactEvidence,
    PlanImpactError,
)
from trading_platform.identity import canonical_hash
from trading_platform.domain.decision_tasks import DecisionTask

from .locking import DataRootWriterLock
from .decision_tasks import SQLiteDecisionTaskRepository


class SQLiteManualPortfolioReviewRepository:
    """Owns review evidence reads and atomic journal/checkpoint commits."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock
        self._decision_tasks = SQLiteDecisionTaskRepository(
            connection, writer_lock
        )
        self.fault_injector = None

    def _fault(self, boundary: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(boundary)

    def latest_proven_complete_session(
        self, requested_at: str
    ) -> ProvenCompleteSession:
        try:
            requested = datetime.fromisoformat(requested_at)
        except ValueError as error:
            raise ManualReviewError(
                "MANUAL_REVIEW_TIME_INVALID"
            ) from error
        if requested.tzinfo is None or requested.utcoffset() is None:
            raise ManualReviewError("MANUAL_REVIEW_TIME_INVALID")
        local_date = requested.astimezone(SHANGHAI_TIMEZONE).date()
        rows = self._connection.execute(
            "SELECT s.effective_session_date "
            "AS effective_session_date,s.as_of_at AS as_of_at,"
            "s.last_success_at AS last_success_at,"
            "s.calendar_version AS calendar_version,"
            "s.query_policy_identity AS query_policy_identity,"
            "s.source_policy_identity AS source_policy_identity,"
            "s.data_snapshot_id AS data_snapshot_id "
            "FROM data_snapshot s "
            "JOIN data_snapshot_universe_ref u "
            "ON u.data_snapshot_id=s.data_snapshot_id "
            "JOIN market_universe_version v "
            "ON v.market_universe_version_id="
            "u.market_universe_version_id "
            "WHERE s.market_timezone='Asia/Shanghai' "
            "AND s.snapshot_purpose IN "
            "('research','workflow','market') "
            "AND u.market_scope_id='CN_A_SHARE' "
            "AND v.market_scope_id='CN_A_SHARE' "
            "AND s.quality_status='pass' "
            "AND s.freshness_status='valid' "
            "AND s.coverage_expected>0 "
            "AND s.coverage_eligible>0 "
            "AND s.coverage_missing=0 "
            "AND s.coverage_eligible+s.coverage_excluded="
            "s.coverage_expected "
            "AND EXISTS(SELECT 1 FROM market_universe_member m "
            "WHERE m.market_universe_version_id="
            "u.market_universe_version_id) "
            "AND s.freshness_basis="
            "'effective_complete_session' "
            "ORDER BY s.effective_session_date DESC,s.as_of_at DESC,"
            "s.data_snapshot_id DESC"
        ).fetchall()
        for row in rows:
            try:
                session_date = date.fromisoformat(
                    row["effective_session_date"]
                )
                as_of = datetime.fromisoformat(row["as_of_at"])
                last_success = datetime.fromisoformat(
                    row["last_success_at"]
                )
            except ValueError as error:
                raise ManualReviewError(
                    "PROVEN_COMPLETE_SESSION_TIME_INVALID"
                ) from error
            if (
                as_of.tzinfo is None
                or as_of.utcoffset() is None
                or last_success.tzinfo is None
                or last_success.utcoffset() is None
            ):
                raise ManualReviewError(
                    "PROVEN_COMPLETE_SESSION_TIME_INVALID"
                )
            if (
                session_date <= local_date
                and as_of <= requested
                and last_success <= requested
            ):
                return ProvenCompleteSession(
                    selected_complete_session=(
                        row["effective_session_date"]
                    ),
                    data_snapshot_id=row["data_snapshot_id"],
                    calendar_identity=row["calendar_version"],
                    policy_identities=tuple(
                        sorted(
                            {
                                row["query_policy_identity"],
                                row["source_policy_identity"],
                            }
                        )
                    ),
                )
        raise ManualReviewError(
            "LATEST_PROVEN_COMPLETE_SESSION_UNAVAILABLE"
        )

    def latest_success(
        self, account_id: str
    ) -> ManualPortfolioReviewRun | None:
        row = self._connection.execute(
            "SELECT * FROM manual_portfolio_review_run "
            "WHERE account_id=? AND status IN "
            "('succeeded','succeeded_with_limits') "
            "ORDER BY window_end_inclusive DESC,completed_at DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        return self._run(row) if row is not None else None

    def by_invocation(
        self, invocation_id: str
    ) -> ManualPortfolioReviewRun | None:
        row = self._connection.execute(
            "SELECT * FROM manual_portfolio_review_run WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        return self._run(row) if row is not None else None

    def receipt_hash(self, invocation_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT request_hash FROM application_command_receipt "
            "WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        return str(row["request_hash"]) if row is not None else None

    def context(
        self,
        estimated: EstimatedAccountState,
        session: ProvenCompleteSession,
    ) -> ManualReviewContext:
        positions: dict[str, EstimatedPosition] = {}
        for position in estimated.positions:
            try:
                quantity = Decimal(position.total_quantity)
            except (InvalidOperation, ValueError) as error:
                raise ManualReviewError(
                    "ESTIMATED_POSITION_QUANTITY_INVALID"
                ) from error
            if quantity < 0:
                raise ManualReviewError(
                    "ESTIMATED_POSITION_QUANTITY_INVALID"
                )
            if quantity > 0:
                if position.security_id in positions:
                    raise ManualReviewError(
                        "ESTIMATED_POSITION_DUPLICATE"
                    )
                positions[position.security_id] = position
        watchlist: dict[str, list[str]] = {}
        for row in self._connection.execute(
            "SELECT watchlist_item_id,security_id FROM watchlist_item "
            "WHERE watchlist_id='watchlist_default' "
            "ORDER BY security_id,watchlist_item_id"
        ):
            watchlist.setdefault(row["security_id"], []).append(
                row["watchlist_item_id"]
            )
        members: list[ManualReviewUniverseMember] = []
        security_ids = sorted(set(positions) | set(watchlist))
        for security_id in security_ids:
            position = positions.get(security_id)
            roles = tuple(
                role
                for role, present in (
                    ("holding", position is not None),
                    ("watchlist", security_id in watchlist),
                )
                if present
            )
            universe_member_identity = canonical_hash(
                {
                    "security_id": security_id,
                    "roles": roles,
                    "holding_identity": (
                        canonical_hash(position)
                        if position is not None
                        else None
                    ),
                    "watchlist_item_ids": tuple(
                        watchlist.get(security_id, ())
                    ),
                }
            )
            plan = self._connection.execute(
                "SELECT m.plan_id,m.strategy_version_id,a.plan_version_id "
                "FROM trade_plan_master m "
                "LEFT JOIN plan_activation a ON a.plan_id=m.plan_id "
                "AND a.ended_at IS NULL "
                "WHERE m.account_id=? AND m.security_id=? "
                "AND m.lifecycle_status='active'",
                (estimated.account_id, security_id),
            ).fetchone()
            plan_version_id = (
                str(plan["plan_version_id"])
                if plan is not None
                and plan["plan_version_id"] is not None
                else None
            )
            if plan_version_id is not None:
                from .plans import SQLiteTradePlanRepository

                SQLiteTradePlanRepository(
                    self._connection, self._writer_lock
                ).get_graph(plan_version_id)
            evaluation = (
                self._evaluation(
                    plan_version_id,
                    session.selected_complete_session,
                )
                if plan_version_id is not None
                else None
            )
            sleeves = (
                tuple(
                    dict(row)
                    for row in self._connection.execute(
                        "SELECT sleeve_id,sleeve_kind,"
                        "quantity_budget_state,quantity_budget_value,"
                        "core_floor_state,core_floor_value,"
                        "max_notional_state,max_notional_value,"
                        "max_loss_state,max_loss_value,grid_constraint_id,"
                        "content_hash FROM trade_plan_sleeve "
                        "WHERE plan_version_id=? ORDER BY sleeve_id",
                        (plan_version_id,),
                    )
                )
                if plan_version_id is not None
                else ()
            )
            references = (
                tuple(
                    dict(row)
                    for row in self._connection.execute(
                        "SELECT ref_type,ref_id,resolution_status,"
                        "content_hash "
                        "FROM trade_plan_evidence_reference "
                        "WHERE plan_version_id=? ORDER BY ref_order",
                        (plan_version_id,),
                    )
                )
                if plan_version_id is not None
                else ()
            )
            data_ids = {session.data_snapshot_id}
            research_ids: set[str] = set()
            evidence_ids: set[str] = set()
            for reference in references:
                ref_type = str(reference["ref_type"])
                ref_id = str(reference["ref_id"])
                if ref_type == "data_snapshot":
                    data_ids.add(ref_id)
                elif ref_type in {"research_run", "workflow_run"}:
                    research_ids.add(ref_id)
                else:
                    evidence_ids.add(ref_id)
            market_ids = (
                (str(evaluation["market_snapshot_id"]),)
                if evaluation is not None
                else ()
            )
            hard, routed = self._rule_evaluations(evaluation)
            members.append(
                ManualReviewUniverseMember(
                    security_id=security_id,
                    universe_member_identity=universe_member_identity,
                    universe_roles=roles,
                    active_plan_id=(
                        str(plan["plan_id"]) if plan is not None else None
                    ),
                    plan_version_id=plan_version_id,
                    plan_evaluation_id=(
                        str(evaluation["plan_evaluation_id"])
                        if evaluation is not None
                        else None
                    ),
                    evaluation_reason_code=(
                        str(evaluation["resolution_reason_code"])
                        if evaluation is not None
                        else None
                    ),
                    strategy_version_id=(
                        str(plan["strategy_version_id"])
                        if plan is not None
                        else None
                    ),
                    sleeve_graph=sleeves,
                    data_snapshot_ids=tuple(sorted(data_ids)),
                    research_run_ids=tuple(sorted(research_ids)),
                    evidence_ids=tuple(sorted(evidence_ids)),
                    market_snapshot_ids=market_ids,
                    hard_rule_evaluations=hard,
                    review_rule_routing=routed,
                    conflict_resolution=(
                        json.loads(evaluation["resolution_json"])
                        if evaluation is not None
                        else {}
                    ),
                    evaluation_resolution=(
                        str(evaluation["resolution_outcome"])
                        if evaluation is not None
                        else None
                    ),
                    unable_reasons=(
                        ()
                        if evaluation is not None
                        else ("COMPATIBLE_PLAN_EVALUATION_MISSING",)
                    ),
                    blocked_reasons=(
                        (str(evaluation["resolution_reason_code"]),)
                        if evaluation is not None
                        and evaluation["resolution_outcome"] == "blocked"
                        else ()
                    ),
                )
            )
        cutoff = estimated.derived_from_snapshot_as_of[:10]
        return ManualReviewContext(
            account_id=estimated.account_id,
            account_snapshot_version_id=estimated.derived_from_snapshot_id,
            account_snapshot_hash=estimated.snapshot_graph_seal_hash,
            account_snapshot_cutoff=cutoff,
            estimated_state_hash=estimated.content_hash,
            selected_complete_session=(
                session.selected_complete_session
            ),
            calendar_identity=session.calendar_identity,
            policy_identities=session.policy_identities,
            members=tuple(members),
        )

    def begin(
        self,
        run: ManualPortfolioReviewRun,
        invocation_id: str,
    ) -> ManualPortfolioReviewRun:
        existing = self.by_invocation(invocation_id)
        if existing is not None:
            if (
                existing.input_fingerprint != run.input_fingerprint
                or existing.workflow_run_id != run.workflow_run_id
            ):
                raise ManualReviewError("MANUAL_REVIEW_INVOCATION_CONFLICT")
            if existing.status == "failed":
                with self._writer_lock.acquire(
                    f"manual-review-resume:{existing.review_run_id}"
                ):
                    self._connection.execute(
                        "UPDATE manual_portfolio_review_run "
                        "SET status='running',completed_at=NULL "
                        "WHERE review_run_id=? AND status='failed'",
                        (existing.review_run_id,),
                    )
                    self._connection.commit()
                return replace(existing, status="running", completed_at=None)
            return existing
        with self._writer_lock.acquire(
            f"manual-review-start:{run.account_id}"
        ):
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT INTO manual_portfolio_review_run("
                    "review_run_id,workflow_run_id,invocation_id,account_id,"
                    "requested_at,selected_complete_session,timezone,"
                    "window_start_exclusive,window_end_inclusive,"
                    "prior_successful_review_run_id,status,input_fingerprint,"
                    "created_at,completed_at,schema_version,"
                    "session_selection"
                    ") VALUES(" + ",".join("?" for _ in range(16)) + ")",
                    (
                        run.review_run_id,
                        run.workflow_run_id,
                        invocation_id,
                        run.account_id,
                        run.requested_at,
                        run.selected_complete_session,
                        run.timezone,
                        run.window_start_exclusive,
                        run.window_end_inclusive,
                        run.prior_successful_review_run_id,
                        run.status,
                        run.input_fingerprint,
                        run.created_at,
                        run.completed_at,
                        run.schema_version,
                        run.session_selection,
                    ),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return run

    def commit(
        self,
        *,
        run: ManualPortfolioReviewRun,
        items: tuple[ManualPortfolioReviewItem, ...],
        decision_tasks: tuple[DecisionTask, ...],
        checkpoints: tuple[ManualPortfolioReviewCheckpoint, ...],
        manifest: ManualPortfolioReviewManifest,
        invocation_id: str,
        request_hash: str,
        decision_actor: str,
        interaction_channel: str,
        transport_actor: str,
        terminal_status: str,
        completed_at: str,
    ) -> ManualPortfolioReviewRun:
        manifest.validate()
        for item in items:
            item.validate()
        for task in decision_tasks:
            task.validate()
        for checkpoint in checkpoints:
            checkpoint.validate()
        with self._writer_lock.acquire(
            f"manual-review-commit:{run.review_run_id}"
        ):
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                current = self._connection.execute(
                    "SELECT status,input_fingerprint FROM "
                    "manual_portfolio_review_run WHERE review_run_id=?",
                    (run.review_run_id,),
                ).fetchone()
                if current is None:
                    raise ManualReviewError("MANUAL_REVIEW_NOT_FOUND")
                if current["status"] in {
                    "succeeded",
                    "succeeded_with_limits",
                }:
                    self._connection.rollback()
                    return self.get(run.review_run_id)
                if (
                    current["status"] != "running"
                    or current["input_fingerprint"] != run.input_fingerprint
                ):
                    raise ManualReviewError("MANUAL_REVIEW_STATE_CONFLICT")
                self._insert_manifest(manifest)
                for item in items:
                    self._insert_item(item)
                self._decision_tasks.materialize_in_transaction(
                    decision_tasks
                )
                for checkpoint in checkpoints:
                    self._upsert_checkpoint(checkpoint)
                self._fault("manual_review.before_terminal_update")
                updated = self._connection.execute(
                    "UPDATE manual_portfolio_review_run "
                    "SET status=?,completed_at=? "
                    "WHERE review_run_id=? AND status='running'",
                    (terminal_status, completed_at, run.review_run_id),
                )
                if updated.rowcount != 1:
                    raise ManualReviewError("MANUAL_REVIEW_STATE_CONFLICT")
                self._connection.execute(
                    "INSERT INTO application_command_receipt VALUES("
                    "?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        invocation_id,
                        "manual_portfolio_review.run@2",
                        request_hash,
                        "ManualPortfolioReviewRun",
                        run.account_id,
                        run.review_run_id,
                        terminal_status,
                        decision_actor,
                        interaction_channel,
                        transport_actor,
                        completed_at,
                    ),
                )
                self._fault("manual_review.before_commit")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return replace(
            run, status=terminal_status, completed_at=completed_at
        )

    def fail(
        self, review_run_id: str, completed_at: str
    ) -> ManualPortfolioReviewRun:
        with self._writer_lock.acquire(
            f"manual-review-fail:{review_run_id}"
        ):
            self._connection.execute(
                "UPDATE manual_portfolio_review_run "
                "SET status='failed',completed_at=? "
                "WHERE review_run_id=? AND status='running'",
                (completed_at, review_run_id),
            )
            self._connection.commit()
        return self.get(review_run_id)

    def get(self, review_run_id: str) -> ManualPortfolioReviewRun:
        row = self._connection.execute(
            "SELECT * FROM manual_portfolio_review_run WHERE review_run_id=?",
            (review_run_id,),
        ).fetchone()
        if row is None:
            raise ManualReviewError("MANUAL_REVIEW_NOT_FOUND")
        return self._run(row)

    def manifest(
        self, review_run_id: str
    ) -> ManualPortfolioReviewManifest:
        row = self._connection.execute(
            "SELECT * FROM manual_portfolio_review_manifest "
            "WHERE review_run_id=?",
            (review_run_id,),
        ).fetchone()
        if row is None:
            raise ManualReviewError("MANUAL_REVIEW_MANIFEST_NOT_FOUND")
        return ManualPortfolioReviewManifest(
            manifest_id=row["manifest_id"],
            review_run_id=row["review_run_id"],
            object_sha256=row["object_sha256"],
            artifact_manifest_id=row["artifact_manifest_id"],
            cutoff_identity=row["cutoff_identity"],
            calendar_identity=row["calendar_identity"],
            policy_identities=tuple(json.loads(row["policy_identities_json"])),
            account_snapshot_version_id=row["account_snapshot_version_id"],
            estimated_state_hash=row["estimated_state_hash"],
            active_plan_version_ids=tuple(
                json.loads(row["active_plan_version_ids_json"])
            ),
            data_snapshot_ids=tuple(
                json.loads(row["data_snapshot_ids_json"])
            ),
            research_run_ids=tuple(
                json.loads(row["research_run_ids_json"])
            ),
            market_snapshot_ids=tuple(
                json.loads(row["market_snapshot_ids_json"])
            ),
            evidence_ids=tuple(json.loads(row["evidence_ids_json"])),
            rule_evaluator_conflict_versions=tuple(
                json.loads(row["rule_evaluator_conflict_versions_json"])
            ),
            review_item_ids=tuple(
                json.loads(row["review_item_ids_json"])
            ),
            checkpoint_ids=tuple(
                json.loads(row["checkpoint_ids_json"])
            ),
            decision_task_ids=tuple(
                json.loads(row["decision_task_ids_json"])
            ),
            assessment_ids=tuple(json.loads(row["assessment_ids_json"])),
            proposal_ids=tuple(json.loads(row["proposal_ids_json"])),
            code_identity=row["code_identity"],
            config_identity=row["config_identity"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            schema_version=row["schema_version"],
        )

    def freeze_plan_impact_input(
        self, query
    ) -> FrozenPlanImpactEvidence:
        row = self._connection.execute(
            "SELECT i.*,m.manifest_id,m.content_hash AS manifest_hash "
            "FROM manual_portfolio_review_item i "
            "JOIN manual_portfolio_review_manifest m "
            "ON m.review_run_id=i.review_run_id "
            "JOIN trade_plan_rule p "
            "ON p.plan_version_id=i.plan_version_id "
            "AND p.rule_id=? AND p.rule_class='review' "
            "WHERE i.review_run_id=? AND i.review_item_id=?",
            (
                query.review_rule_id,
                query.review_run_id,
                query.review_item_id,
            ),
        ).fetchone()
        if row is None:
            raise PlanImpactError("PLAN_IMPACT_AUTHORITY_NOT_FOUND")
        routing = tuple(json.loads(row["review_rule_routing_json"]))
        routed = next(
            (
                value
                for value in routing
                if value.get("rule_id") == query.review_rule_id
            ),
            None,
        )
        unable = tuple(json.loads(row["unable_reasons_json"]))
        if routed is None:
            if not unable:
                raise PlanImpactError(
                    "PLAN_IMPACT_REVIEW_RULE_NOT_FROZEN"
                )
            result = "unable_to_determine"
        else:
            result = {
                "triggered": "fail",
                "not_triggered": "pass",
                "unable_to_determine": "unable_to_determine",
                "not_applicable": "unable_to_determine",
                "blocked": "unable_to_determine",
            }.get(str(routed.get("result")))
            if result is None:
                raise PlanImpactError(
                    "PLAN_IMPACT_REVIEW_RULE_NOT_FROZEN"
                )
        identity = {
            "review_run_id": row["review_run_id"],
            "review_item_id": row["review_item_id"],
            "plan_version_id": row["plan_version_id"],
            "review_rule_id": query.review_rule_id,
            "review_rule_result": result,
            "evidence_manifest_id": row["manifest_id"],
            "research_refs": tuple(
                json.loads(row["research_run_ids_json"])
            ),
            "market_refs": tuple(
                json.loads(row["market_snapshot_ids_json"])
            ),
            "industry_refs": (),
            "sector_refs": (),
            "unable_reasons": unable,
            "schema_version": "FrozenPlanImpactEvidence@1",
        }
        frozen = FrozenPlanImpactEvidence(
            **identity,
            authority_content_hash=canonical_hash(identity),
        )
        frozen.validate()
        return frozen

    def _evaluation(
        self, plan_version_id: str, session: str
    ) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT e.* FROM plan_evaluation e "
            "JOIN market_snapshot m USING(market_snapshot_id) "
            "WHERE e.plan_version_id=? "
            "AND m.effective_session_date=? "
            "ORDER BY e.created_at DESC LIMIT 1",
            (plan_version_id, session),
        ).fetchone()

    def _rule_evaluations(
        self, evaluation: sqlite3.Row | None
    ) -> tuple[
        tuple[Mapping[str, object], ...],
        tuple[Mapping[str, object], ...],
    ]:
        if evaluation is None:
            return (), ()
        rows = tuple(
            dict(row)
            for row in self._connection.execute(
                "SELECT r.rule_id,r.result,r.reason_code,"
                "r.evaluation_json,r.replay_hash "
                "FROM plan_rule_evaluation r "
                "JOIN trade_plan_rule p "
                "ON p.plan_version_id=? AND p.rule_id=r.rule_id "
                "WHERE r.plan_evaluation_id=? ORDER BY r.rule_order",
                (
                    evaluation["plan_version_id"],
                    evaluation["plan_evaluation_id"],
                ),
            )
        )
        review_rule_ids = {
            row["rule_id"]
            for row in self._connection.execute(
                "SELECT rule_id FROM trade_plan_rule "
                "WHERE plan_version_id=? AND rule_class='review'",
                (evaluation["plan_version_id"],),
            )
        }
        return (
            tuple(row for row in rows if row["rule_id"] not in review_rule_ids),
            tuple(row for row in rows if row["rule_id"] in review_rule_ids),
        )

    def _insert_manifest(
        self, manifest: ManualPortfolioReviewManifest
    ) -> None:
        self._connection.execute(
            "INSERT INTO manual_portfolio_review_manifest VALUES("
            + ",".join("?" for _ in range(25))
            + ")",
            (
                manifest.manifest_id,
                manifest.review_run_id,
                manifest.object_sha256,
                manifest.artifact_manifest_id,
                manifest.cutoff_identity,
                manifest.calendar_identity,
                self._json(manifest.policy_identities),
                manifest.account_snapshot_version_id,
                manifest.estimated_state_hash,
                self._json(manifest.active_plan_version_ids),
                self._json(manifest.data_snapshot_ids),
                self._json(manifest.research_run_ids),
                self._json(manifest.market_snapshot_ids),
                self._json(manifest.evidence_ids),
                self._json(manifest.rule_evaluator_conflict_versions),
                self._json(manifest.review_item_ids),
                self._json(manifest.checkpoint_ids),
                self._json(manifest.decision_task_ids),
                self._json(manifest.assessment_ids),
                self._json(manifest.proposal_ids),
                manifest.code_identity,
                manifest.config_identity,
                manifest.content_hash,
                manifest.created_at,
                manifest.schema_version,
            ),
        )

    def _insert_item(self, item: ManualPortfolioReviewItem) -> None:
        self._connection.execute(
            "INSERT INTO manual_portfolio_review_item("
            "review_item_id,review_run_id,account_id,security_id,"
            "universe_member_identity,account_snapshot_version_id,"
            "account_snapshot_hash,estimated_state_hash,active_plan_id,"
            "plan_version_id,plan_evaluation_id,evaluation_reason_code,"
            "strategy_version_id,sleeve_graph_json,data_snapshot_ids_json,"
            "research_run_ids_json,evidence_ids_json,"
            "market_snapshot_ids_json,hard_rule_evaluations_json,"
            "review_rule_routing_json,conflict_resolution_json,outcome,"
            "material_changes_json,unable_reasons_json,"
            "blocked_reasons_json,decision_task_ids_json,"
            "plan_impact_assessment_ids_json,"
            "plan_change_proposal_ids_json,content_hash,created_at,"
            "schema_version,universe_roles_json"
            ") VALUES(" + ",".join("?" for _ in range(32)) + ")",
            (
                item.review_item_id,
                item.review_run_id,
                item.account_id,
                item.security_id,
                item.universe_member_identity,
                item.account_snapshot_version_id,
                item.account_snapshot_hash,
                item.estimated_state_hash,
                item.active_plan_id,
                item.plan_version_id,
                item.plan_evaluation_id,
                item.evaluation_reason_code,
                item.strategy_version_id,
                self._json(item.sleeve_graph),
                self._json(item.data_snapshot_ids),
                self._json(item.research_run_ids),
                self._json(item.evidence_ids),
                self._json(item.market_snapshot_ids),
                self._json(item.hard_rule_evaluations),
                self._json(item.review_rule_routing),
                self._json(item.conflict_resolution),
                item.outcome.value,
                self._json(item.material_changes),
                self._json(item.unable_reasons),
                self._json(item.blocked_reasons),
                self._json(item.decision_task_ids),
                self._json(item.plan_impact_assessment_ids),
                self._json(item.plan_change_proposal_ids),
                item.content_hash,
                item.created_at,
                item.schema_version,
                self._json(item.universe_roles),
            ),
        )

    def _upsert_checkpoint(
        self, checkpoint: ManualPortfolioReviewCheckpoint
    ) -> None:
        self._connection.execute(
            "INSERT INTO manual_portfolio_review_checkpoint VALUES("
            "?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(review_run_id,security_id,stage) DO UPDATE SET "
            "input_fingerprint=excluded.input_fingerprint,"
            "status=excluded.status,manifest_id=excluded.manifest_id,"
            "attempt_no=manual_portfolio_review_checkpoint.attempt_no+1,"
            "committed_at=excluded.committed_at",
            (
                checkpoint.checkpoint_id,
                checkpoint.review_run_id,
                checkpoint.security_id,
                checkpoint.stage,
                checkpoint.input_fingerprint,
                checkpoint.status,
                checkpoint.manifest_id,
                checkpoint.attempt_no,
                checkpoint.committed_at,
                checkpoint.schema_version,
            ),
        )

    @staticmethod
    def _run(row: sqlite3.Row) -> ManualPortfolioReviewRun:
        run = ManualPortfolioReviewRun(
            review_run_id=row["review_run_id"],
            workflow_run_id=row["workflow_run_id"],
            account_id=row["account_id"],
            requested_at=row["requested_at"],
            session_selection=row["session_selection"],
            selected_complete_session=row["selected_complete_session"],
            timezone=row["timezone"],
            window_start_exclusive=row["window_start_exclusive"],
            window_end_inclusive=row["window_end_inclusive"],
            prior_successful_review_run_id=row[
                "prior_successful_review_run_id"
            ],
            status=row["status"],
            input_fingerprint=row["input_fingerprint"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            schema_version=row["schema_version"],
        )
        run.validate()
        return run

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


__all__ = ["SQLiteManualPortfolioReviewRepository"]
