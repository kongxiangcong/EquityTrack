from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Mapping

from trading_platform.domain.approvals import (
    ActivationIntent,
    CanonicalPlanDiff,
    PlanConfirmationChallenge,
    UserApprovalReceipt,
)

from trading_platform.domain.plans import (
    ActiveTradePlan,
    CoreFloor,
    CoreSleeve,
    GridSleeve,
    PlanActivation,
    PlanActivated,
    PlanDraftRejected,
    PlanValidationError,
    ProposedTradePlanVersion,
    PlanVersionConfirmed,
    TradePlanDraft,
    TradePlanGraph,
    TradePlanDraftGraph,
    TradePlanMaster,
    TradePlanMasterId,
    TradePlanRule,
    TradePlanVersion,
    build_trade_plan_draft,
)
from trading_platform.domain.rules import (
    GridConstraint,
    RuleClass,
    RulePriority,
    RuleScope,
    ast_from_dict,
    ast_to_dict,
    candidate_from_dict,
    candidate_to_dict,
)
from trading_platform.identity import canonical_hash

from .locking import DataRootWriterLock

if TYPE_CHECKING:
    from trading_platform.application.trade_plan_authoring import (
        ConfirmTradePlanVersion,
        _CreateTradePlanDraft,
        IssuePlanConfirmationChallenge,
        PlanConfirmationResult,
        RejectTradePlanDraft,
        _ReviseTradePlanDraft,
    )

class SQLiteTradePlanRepository:
    """Owns atomic Model B graph sealing, activation, and exact reconstruction."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock

    def create_draft(
        self, command: "_CreateTradePlanDraft"
    ) -> TradePlanDraft:
        draft = command.draft
        draft.validate()
        if (
            draft.status != "open"
            or draft.decision_actor != command.actor.decision_actor
            or draft.interaction_channel
            != command.actor.interaction_channel
            or draft.transport_actor != command.actor.transport_actor
        ):
            raise PlanValidationError("PLAN_DRAFT_CREATE_INVALID")
        request_hash = canonical_hash(command)
        replay = self._command_receipt(
            command.invocation_id, request_hash
        )
        if replay is not None:
            return self._load_draft(replay["aggregate_id"])
        with self._writer_lock.acquire(
            f"trade-plan-draft:{draft.plan_id}"
        ):
            replay = self._command_receipt(
                command.invocation_id, request_hash
            )
            if replay is not None:
                return self._load_draft(replay["aggregate_id"])
            master = TradePlanMaster(
                plan_id=TradePlanMasterId(
                    draft.account_id,
                    draft.security_id,
                    str(draft.plan_id),
                ),
                strategy_version_id=draft.strategy_version_id,
                lifecycle_status="inactive",
                transition_seq=0,
                created_at=draft.created_at,
            )
            master.validate()
            try:
                with self._connection:
                    existing_master = self._connection.execute(
                        "SELECT * FROM trade_plan_master WHERE plan_id=?",
                        (draft.plan_id,),
                    ).fetchone()
                    if existing_master is None:
                        self._connection.execute(
                            "INSERT INTO trade_plan_master "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (
                                draft.plan_id,
                                draft.account_id,
                                draft.security_id,
                                draft.strategy_version_id,
                                "inactive",
                                0,
                                draft.created_at,
                                0,
                            ),
                        )
                    elif (
                        existing_master["account_id"] != draft.account_id
                        or existing_master["security_id"]
                        != draft.security_id
                        or existing_master["strategy_version_id"]
                        != draft.strategy_version_id
                        or existing_master["legacy_read_only"]
                    ):
                        raise PlanValidationError(
                            "PLAN_MASTER_IDENTITY_CONFLICT"
                        )
                    self._insert_draft(draft)
                    self._insert_command_receipt(
                        invocation_id=command.invocation_id,
                        command_name="UpsertOpenTradePlanDraft",
                        request_hash=request_hash,
                        result_type="TradePlanDraft",
                        aggregate_id=draft.draft_id,
                        revision_or_version_id=str(draft.revision),
                        actor=command.actor,
                        created_at=draft.created_at,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanValidationError(
                    "PLAN_DRAFT_STORAGE_CONFLICT"
                ) from error
        return self._load_draft(draft.draft_id)

    def revise_draft(
        self, command: "_ReviseTradePlanDraft"
    ) -> TradePlanDraft:
        current = self._load_draft(command.draft_id)
        candidate = self._revised_draft(current, command)
        request_hash = canonical_hash(command)
        replay = self._command_receipt(
            command.invocation_id, request_hash
        )
        if replay is not None:
            return self._load_draft(command.draft_id)
        with self._writer_lock.acquire(
            f"trade-plan-draft:{command.draft_id}"
        ):
            current = self._load_draft(command.draft_id)
            if (
                current.status != "open"
                or current.revision != command.expected_revision
            ):
                raise PlanValidationError("PLAN_DRAFT_REVISION_CONFLICT")
            candidate = self._revised_draft(current, command)
            try:
                with self._connection:
                    self._connection.execute(
                        "UPDATE plan_confirmation_challenge "
                        "SET status='superseded' "
                        "WHERE draft_id=? AND status='issued'",
                        (command.draft_id,),
                    )
                    changed = self._connection.execute(
                        "UPDATE trade_plan_draft SET revision=?,"
                        "parameters_json=?,content_json=?,"
                        "proposed_graph_json=?,"
                        "proposed_graph_seal_hash=?,content_hash=?,"
                        "updated_at=?,decision_actor=?,"
                        "interaction_channel=?,transport_actor=? "
                        "WHERE draft_id=? AND status='open' "
                        "AND revision=?",
                        (
                            candidate.revision,
                            self._json(candidate.parameters),
                            self._json(candidate.content),
                            self._json(
                                self._encode_draft_graph(
                                    candidate.proposed_graph
                                )
                            ),
                            candidate.proposed_graph.version.graph_seal_hash,
                            candidate.content_hash,
                            candidate.updated_at,
                            candidate.decision_actor,
                            candidate.interaction_channel,
                            candidate.transport_actor,
                            candidate.draft_id,
                            command.expected_revision,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise PlanValidationError(
                            "PLAN_DRAFT_REVISION_CONFLICT"
                        )
                    self._insert_command_receipt(
                        invocation_id=command.invocation_id,
                        command_name="UpsertOpenTradePlanDraft",
                        request_hash=request_hash,
                        result_type="TradePlanDraft",
                        aggregate_id=candidate.draft_id,
                        revision_or_version_id=str(
                            candidate.revision
                        ),
                        actor=command.actor,
                        created_at=candidate.updated_at,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanValidationError(
                    "PLAN_DRAFT_STORAGE_CONFLICT"
                ) from error
        return self._load_draft(command.draft_id)

    def reject_draft(
        self, command: "RejectTradePlanDraft"
    ) -> PlanDraftRejected:
        request_hash = canonical_hash(command)
        replay = self._command_receipt(
            command.invocation_id, request_hash
        )
        if replay is not None:
            draft = self._load_draft(command.draft_id)
            return self._rejected_event(
                command.draft_id,
                str(draft.plan_id),
                command.expected_revision,
                command.rejected_at,
            )
        with self._writer_lock.acquire(
            f"trade-plan-draft:{command.draft_id}"
        ):
            draft = self._load_draft(command.draft_id)
            if (
                draft.status != "open"
                or draft.revision != command.expected_revision
                or not command.actor.decision_actor.startswith("user:")
            ):
                raise PlanValidationError("PLAN_DRAFT_REJECTION_DENIED")
            event = self._rejected_event(
                draft.draft_id,
                str(draft.plan_id),
                draft.revision,
                command.rejected_at,
            )
            with self._connection:
                self._connection.execute(
                    "UPDATE plan_confirmation_challenge "
                    "SET status='cancelled' "
                    "WHERE draft_id=? AND status='issued'",
                    (draft.draft_id,),
                )
                self._connection.execute(
                    "UPDATE trade_plan_draft SET status='rejected',"
                    "updated_at=? WHERE draft_id=? AND status='open'",
                    (command.rejected_at, draft.draft_id),
                )
                self._insert_event(
                    event.event_id,
                    "PlanDraftRejected",
                    "TradePlanDraft",
                    draft.draft_id,
                    {
                        "plan_id": draft.plan_id,
                        "revision": draft.revision,
                    },
                    command.rejected_at,
                )
                self._insert_command_receipt(
                    invocation_id=command.invocation_id,
                    command_name="RejectTradePlanDraft",
                    request_hash=request_hash,
                    result_type="PlanDraftRejected",
                    aggregate_id=draft.draft_id,
                    revision_or_version_id=str(draft.revision),
                    actor=command.actor,
                    created_at=command.rejected_at,
                )
        return event

    def issue_challenge(
        self, command: "IssuePlanConfirmationChallenge"
    ) -> PlanConfirmationChallenge:
        draft = self._load_draft(command.draft_id)
        request_hash = canonical_hash(command)
        replay = self._command_receipt(
            command.invocation_id, request_hash
        )
        if replay is not None:
            return self._load_challenge(
                replay["revision_or_version_id"]
            )
        if (
            draft.status != "open"
            or draft.revision != command.expected_revision
            or not command.actor.decision_actor.startswith("user:")
        ):
            raise PlanValidationError("PLAN_CHALLENGE_ISSUE_DENIED")
        diff = self._canonical_diff(draft)
        challenge_id = (
            "plan_confirmation_challenge_"
            + canonical_hash(
                {
                    "draft_id": draft.draft_id,
                    "revision": draft.revision,
                    "intent": command.activation_intent,
                    "invocation_id": command.invocation_id,
                }
            )[:24]
        )
        prototype = PlanConfirmationChallenge(
            challenge_id=challenge_id,
            plan_id=str(draft.plan_id),
            draft_id=draft.draft_id,
            expected_revision=draft.revision,
            expected_draft_hash=draft.content_hash,
            expected_graph_seal_hash=(
                draft.proposed_graph.version.graph_seal_hash
            ),
            canonical_diff=diff,
            activation_intent=command.activation_intent,
            decision_actor=command.actor.decision_actor,
            interaction_channel=command.actor.interaction_channel,
            transport_actor=command.actor.transport_actor,
            issued_at=command.issued_at,
            expires_at=command.expires_at,
            status="issued",
            content_hash="",
        )
        challenge = replace(
            prototype,
            content_hash=canonical_hash(prototype.identity_payload()),
        )
        challenge.validate()
        with self._writer_lock.acquire(
            f"trade-plan-draft:{draft.draft_id}"
        ):
            current = self._load_draft(draft.draft_id)
            if (
                current.status != "open"
                or current.revision != draft.revision
                or current.content_hash != draft.content_hash
            ):
                raise PlanValidationError(
                    "PLAN_DRAFT_REVISION_CONFLICT"
                )
            with self._connection:
                self._connection.execute(
                    "UPDATE plan_confirmation_challenge "
                    "SET status='superseded' "
                    "WHERE draft_id=? AND status='issued'",
                    (draft.draft_id,),
                )
                self._insert_challenge(challenge)
                self._insert_command_receipt(
                    invocation_id=command.invocation_id,
                    command_name="IssuePlanConfirmationChallenge",
                    request_hash=request_hash,
                    result_type="PlanConfirmationChallenge",
                    aggregate_id=draft.draft_id,
                    revision_or_version_id=challenge.challenge_id,
                    actor=command.actor,
                    created_at=command.issued_at,
                )
        return self._load_challenge(challenge.challenge_id)

    def confirm_plan(
        self, command: "ConfirmTradePlanVersion"
    ) -> "PlanConfirmationResult":
        from trading_platform.application.trade_plan_authoring import (
            PlanConfirmationResult,
        )

        request_hash = canonical_hash(command)
        replay = self._command_receipt(
            command.invocation_id, request_hash
        )
        if replay is not None:
            graph = self.get_graph(replay["revision_or_version_id"])
            receipt = self._load_approval_by_invocation(
                command.invocation_id
            )
            active = (
                self._activation_result(
                    command.invocation_id, graph
                )
                if receipt.activation_intent
                is ActivationIntent.CONFIRM_AND_ACTIVATE
                else None
            )
            return PlanConfirmationResult(graph, receipt, active)
        challenge = self._load_challenge(command.challenge_id)
        draft = self._load_draft(challenge.draft_id)
        self._validate_confirmation(command, challenge, draft)
        receipt = self._build_approval_receipt(
            command, challenge
        )
        graph = draft.proposed_graph.confirm(
            confirmed_at=command.approved_at,
            user_approval_receipt_id=receipt.approval_receipt_id,
        )
        version = graph.version
        with self._writer_lock.acquire(
            f"trade-plan-confirm:{challenge.plan_id}"
        ):
            try:
                with self._connection:
                    self._insert_approval_receipt(receipt)
                    consumed = self._connection.execute(
                        "UPDATE plan_confirmation_challenge "
                        "SET status='consumed',consumed_at=?,"
                        "consumed_by_receipt_id=? "
                        "WHERE challenge_id=? AND status='issued'",
                        (
                            command.approved_at,
                            receipt.approval_receipt_id,
                            challenge.challenge_id,
                        ),
                    ).rowcount
                    if consumed != 1:
                        raise PlanValidationError(
                            "PLAN_CHALLENGE_NOT_ISSUED"
                        )
                    self._validate_seal_authority(graph)
                    self._insert_version(version)
                    self._insert_graph_children(graph)
                    self._connection.execute(
                        "UPDATE trade_plan_version SET graph_sealed=1 "
                        "WHERE plan_version_id=?",
                        (version.plan_version_id,),
                    )
                    persisted_graph = self.get_graph(
                        version.plan_version_id
                    )
                    self._connection.execute(
                        "UPDATE trade_plan_draft SET status='confirmed',"
                        "updated_at=? WHERE draft_id=? AND status='open'",
                        (command.approved_at, draft.draft_id),
                    )
                    confirmed_event = self._confirmed_event(
                        persisted_graph, receipt, command.approved_at
                    )
                    self._insert_event(
                        confirmed_event.event_id,
                        "PlanVersionConfirmed",
                        "TradePlanMaster",
                        challenge.plan_id,
                        {
                            "plan_version_id": version.plan_version_id,
                            "approval_receipt_id": (
                                receipt.approval_receipt_id
                            ),
                        },
                        command.approved_at,
                    )
                    active = (
                        self._activate_confirmed_version(
                            persisted_graph, receipt, command
                        )
                        if command.activation_intent
                        is ActivationIntent.CONFIRM_AND_ACTIVATE
                        else None
                    )
                    self._insert_command_receipt(
                        invocation_id=command.invocation_id,
                        command_name="ConfirmTradePlanVersion",
                        request_hash=request_hash,
                        result_type="PlanConfirmationResult",
                        aggregate_id=challenge.plan_id,
                        revision_or_version_id=(
                            version.plan_version_id
                        ),
                        actor=command.actor,
                        created_at=command.approved_at,
                    )
            except sqlite3.IntegrityError as error:
                if (
                    "trade_plan_master.account_id" in str(error)
                    or "one_active_master_per_account_security"
                    in str(error)
                ):
                    raise PlanValidationError(
                        "ACTIVE_MASTER_OWNERSHIP_CONFLICT"
                    ) from error
                raise PlanValidationError(
                    "PLAN_CONFIRMATION_STORAGE_CONFLICT"
                ) from error
        return PlanConfirmationResult(
            persisted_graph,
            receipt,
            active,
        )

    def get_master(self, plan_id: str) -> TradePlanMaster:
        row = self._master_row(plan_id)
        if row["legacy_read_only"]:
            raise PlanValidationError("LEGACY_PLAN_READ_ONLY")
        master = TradePlanMaster(
            plan_id=TradePlanMasterId(
                account_id=row["account_id"],
                security_id=row["security_id"],
                value=row["plan_id"],
            ),
            strategy_version_id=row["strategy_version_id"],
            lifecycle_status=row["lifecycle_status"],
            transition_seq=row["transition_seq"],
            created_at=row["created_at"],
        )
        master.validate()
        return master

    def get_version(self, plan_version_id: str) -> TradePlanVersion:
        row = self._connection.execute(
            "SELECT * FROM trade_plan_version WHERE plan_version_id=?",
            (plan_version_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("PLAN_VERSION_NOT_FOUND")
        if row["legacy_read_only"]:
            raise PlanValidationError("LEGACY_PLAN_READ_ONLY")
        version = TradePlanVersion(
            plan_version_id=row["plan_version_id"],
            plan_id=row["plan_id"],
            version_no=row["version_no"],
            supersedes_version_id=row["supersedes_version_id"],
            strategy_version_id=row["strategy_version_id"],
            investment_thesis_version_id=row[
                "investment_thesis_version_id"
            ],
            account_snapshot_version_id=row[
                "account_snapshot_version_id"
            ],
            data_snapshot_id=row["data_snapshot_id"],
            horizon_start=row["horizon_start"],
            horizon_end=row["horizon_end"],
            review_by=row["review_by"],
            risk_policy_version_id=row["risk_policy_version_id"],
            metric_catalog_version=row["metric_catalog_version"],
            evaluator_policy_version=row["evaluator_policy_version"],
            conflict_policy_version=row["conflict_policy_version"],
            ast_version=row["ast_version"],
            content=json.loads(row["content_json"]),
            content_hash=row["content_hash"],
            graph_seal_hash=row["graph_seal_hash"],
            confirmed_at=row["confirmed_at"],
            user_approval_receipt_id=row["user_approval_receipt_id"],
        )
        version.validate()
        return version

    def get_graph(self, plan_version_id: str) -> TradePlanGraph:
        version = self.get_version(plan_version_id)
        graph = TradePlanGraph(
            version=version,
            sleeves=tuple(
                self._decode_sleeve(row)
                for row in self._connection.execute(
                    "SELECT s.*,g.lower_price,g.upper_price,g.level_count,"
                    "g.quantity_per_level,g.total_quantity_budget,"
                    "g.price_basis,g.trigger_mode,"
                    "g.cooldown_trading_sessions,g.lot_size,"
                    "g.generated_levels_hash,g.content_hash "
                    "AS grid_content_hash "
                    "FROM trade_plan_sleeve s "
                    "LEFT JOIN grid_constraint g "
                    "USING(grid_constraint_id) "
                    "WHERE s.plan_version_id=? ORDER BY s.sleeve_id",
                    (plan_version_id,),
                )
            ),
            rules=tuple(
                self._decode_rule(row)
                for row in self._connection.execute(
                    "SELECT * FROM trade_plan_rule "
                    "WHERE plan_version_id=? ORDER BY rule_order",
                    (plan_version_id,),
                )
            ),
            evidence_references=tuple(
                self._decode_reference(row)
                for row in self._connection.execute(
                    "SELECT * FROM trade_plan_evidence_reference "
                    "WHERE plan_version_id=? ORDER BY ref_order",
                    (plan_version_id,),
                )
            ),
            adjusted_price_evidence=tuple(
                self._decode_adjusted(row)
                for row in self._connection.execute(
                    "SELECT * FROM trade_plan_adjusted_price_evidence "
                    "WHERE plan_version_id=? "
                    "ORDER BY rule_id,condition_path",
                    (plan_version_id,),
                )
            ),
        )
        graph.validate()
        return graph

    def get_open_draft(
        self, account_id: str, security_id: str
    ) -> TradePlanDraft | None:
        rows = self._connection.execute(
            "SELECT draft_id FROM trade_plan_draft "
            "WHERE account_id=? AND security_id=? AND status='open' "
            "ORDER BY created_at,draft_id",
            (account_id, security_id),
        ).fetchall()
        if len(rows) > 1:
            raise PlanValidationError(
                "PLAN_OPEN_DRAFT_OWNERSHIP_CONFLICT"
            )
        if not rows:
            return None
        return self._load_draft(rows[0]["draft_id"])

    def get_draft_by_invocation(
        self, invocation_id: str
    ) -> TradePlanDraft | None:
        row = self._connection.execute(
            "SELECT command_name,result_type,aggregate_id,"
            "revision_or_version_id,created_at "
            "FROM application_command_receipt WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"]
            != "UpsertOpenTradePlanDraft"
            or row["result_type"] != "TradePlanDraft"
        ):
            raise PlanValidationError("INVOCATION_CONFLICT")
        draft = self._load_draft(row["aggregate_id"])
        if str(draft.revision) != row["revision_or_version_id"]:
            raise PlanValidationError("INVOCATION_CONFLICT")
        replay = replace(
            draft,
            status="open",
            updated_at=str(row["created_at"]),
        )
        replay.validate()
        return replay

    def get_active_master(
        self, account_id: str, security_id: str
    ) -> ActiveTradePlan:
        row = self._connection.execute(
            "SELECT plan_id FROM trade_plan_master "
            "WHERE account_id=? AND security_id=? "
            "AND lifecycle_status='active'",
            (account_id, security_id),
        ).fetchone()
        if row is None:
            raise PlanValidationError("ACTIVE_PLAN_NOT_FOUND")
        return self.get_active_master_by_plan(row["plan_id"])

    def get_active_master_by_plan(self, plan_id: str) -> ActiveTradePlan:
        master = self.get_master(plan_id)
        row = self._connection.execute(
            "SELECT * FROM plan_activation "
            "WHERE plan_id=? AND ended_at IS NULL",
            (plan_id,),
        ).fetchone()
        if row is None:
            return ActiveTradePlan(master, None, None)
        activation = PlanActivation(
            activation_id=row["activation_id"],
            plan_id=row["plan_id"],
            plan_version_id=row["plan_version_id"],
            activated_event_id=row["activated_event_id"],
            activated_at=row["activated_at"],
            ended_event_id=row["ended_event_id"],
            ended_at=row["ended_at"],
            end_reason=row["end_reason"],
            user_approval_receipt_id=row["user_approval_receipt_id"],
            command_invocation_id=row["command_invocation_id"],
        )
        return ActiveTradePlan(
            master,
            activation,
            self.get_version(activation.plan_version_id),
        )

    def list_activations(self, plan_id: str) -> tuple[PlanActivation, ...]:
        return tuple(
            PlanActivation(
                activation_id=row["activation_id"],
                plan_id=row["plan_id"],
                plan_version_id=row["plan_version_id"],
                activated_event_id=row["activated_event_id"],
                activated_at=row["activated_at"],
                ended_event_id=row["ended_event_id"],
                ended_at=row["ended_at"],
                end_reason=row["end_reason"],
                user_approval_receipt_id=row["user_approval_receipt_id"],
                command_invocation_id=row["command_invocation_id"],
            )
            for row in self._connection.execute(
                "SELECT * FROM plan_activation WHERE plan_id=? "
                "ORDER BY activated_at,activation_id",
                (plan_id,),
            )
        )

    def _insert_draft(self, draft: TradePlanDraft) -> None:
        self._connection.execute(
            "INSERT INTO trade_plan_draft VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                draft.draft_id,
                draft.plan_id,
                draft.account_id,
                draft.security_id,
                draft.strategy_version_id,
                draft.based_on_version_id,
                draft.revision,
                draft.status,
                self._json(draft.parameters),
                self._json(draft.content),
                self._json(self._encode_draft_graph(draft.proposed_graph)),
                draft.proposed_graph.version.graph_seal_hash,
                draft.content_hash,
                draft.created_at,
                draft.updated_at,
                draft.decision_actor,
                draft.interaction_channel,
                draft.transport_actor,
            ),
        )

    def _load_draft(self, draft_id: str) -> TradePlanDraft:
        row = self._connection.execute(
            "SELECT * FROM trade_plan_draft WHERE draft_id=?",
            (draft_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("PLAN_DRAFT_NOT_FOUND")
        if not row["proposed_graph_json"] or row["proposed_graph_json"] == "{}":
            raise PlanValidationError("LEGACY_PLAN_DRAFT_READ_ONLY")
        draft = TradePlanDraft(
            draft_id=row["draft_id"],
            plan_id=row["plan_id"],
            account_id=row["account_id"],
            security_id=row["security_id"],
            strategy_version_id=row["strategy_version_id"],
            based_on_version_id=row["based_on_version_id"],
            revision=row["revision"],
            status=row["status"],
            parameters=json.loads(row["parameters_json"]),
            content=json.loads(row["content_json"]),
            proposed_graph=self._decode_draft_graph(
                json.loads(row["proposed_graph_json"])
            ),
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            decision_actor=row["decision_actor"],
            interaction_channel=row["interaction_channel"],
            transport_actor=row["transport_actor"],
        )
        draft.validate()
        if (
            draft.proposed_graph.version.graph_seal_hash
            != row["proposed_graph_seal_hash"]
        ):
            raise PlanValidationError("PLAN_DRAFT_GRAPH_MISMATCH")
        return draft

    def _revised_draft(
        self,
        current: TradePlanDraft,
        command: "_ReviseTradePlanDraft",
    ) -> TradePlanDraft:
        graph = command.proposed_graph
        graph.validate()
        if (
            graph.version.plan_id != current.plan_id
            or graph.version.strategy_version_id
            != current.strategy_version_id
            or graph.version.supersedes_version_id
            != current.based_on_version_id
        ):
            raise PlanValidationError("PLAN_DRAFT_GRAPH_MISMATCH")
        prepared = build_trade_plan_draft(
            draft_id=current.draft_id,
            account_id=current.account_id,
            security_id=current.security_id,
            proposed_graph=graph,
            parameters=command.parameters,
            created_at=command.updated_at,
            decision_actor=command.actor.decision_actor,
            interaction_channel=command.actor.interaction_channel,
            transport_actor=command.actor.transport_actor,
        )
        candidate = replace(
            prepared,
            revision=current.revision + 1,
            created_at=current.created_at,
        )
        candidate.validate()
        return candidate

    def _insert_challenge(
        self, challenge: PlanConfirmationChallenge
    ) -> None:
        self._connection.execute(
            "INSERT INTO plan_confirmation_challenge VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                challenge.challenge_id,
                challenge.schema_version,
                challenge.plan_id,
                challenge.draft_id,
                challenge.expected_revision,
                challenge.expected_draft_hash,
                challenge.expected_graph_seal_hash,
                self._json(
                    {
                        "schema_version": (
                            challenge.canonical_diff.schema_version
                        ),
                        "based_on_graph_seal_hash": (
                            challenge.canonical_diff
                            .based_on_graph_seal_hash
                        ),
                        "proposed_graph_seal_hash": (
                            challenge.canonical_diff
                            .proposed_graph_seal_hash
                        ),
                        "changed_components": (
                            challenge.canonical_diff.changed_components
                        ),
                        "content_hash": (
                            challenge.canonical_diff.content_hash
                        ),
                    }
                ),
                challenge.canonical_diff.content_hash,
                challenge.activation_intent.value,
                challenge.decision_actor,
                challenge.interaction_channel,
                challenge.transport_actor,
                challenge.issued_at,
                challenge.expires_at,
                challenge.status,
                None,
                None,
                challenge.content_hash,
            ),
        )

    def _canonical_diff(
        self, draft: TradePlanDraft
    ) -> CanonicalPlanDiff:
        proposed = draft.proposed_graph
        if draft.based_on_version_id is None:
            changed = (
                "version",
                "sleeves",
                "rules",
                "evidence",
            )
            base_hash = None
        else:
            base = self.get_graph(draft.based_on_version_id)
            base_hash = base.version.graph_seal_hash
            changed = tuple(
                name
                for name, different in (
                    (
                        "version",
                        base.version.content_hash
                        != proposed.version.content_hash,
                    ),
                    (
                        "sleeves",
                        tuple(
                            item.content_hash
                            for item in base.sleeves
                        )
                        != tuple(
                            item.content_hash
                            for item in proposed.sleeves
                        ),
                    ),
                    (
                        "rules",
                        tuple(
                            item.content_hash for item in base.rules
                        )
                        != tuple(
                            item.content_hash
                            for item in proposed.rules
                        ),
                    ),
                    (
                        "evidence",
                        (
                            base.evidence_references,
                            base.adjusted_price_evidence,
                        )
                        != (
                            proposed.evidence_references,
                            proposed.adjusted_price_evidence,
                        ),
                    ),
                )
                if different
            )
        return CanonicalPlanDiff.build(
            based_on_graph_seal_hash=base_hash,
            proposed_graph_seal_hash=(
                proposed.version.graph_seal_hash
            ),
            changed_components=changed,
        )

    def _load_challenge(
        self, challenge_id: str
    ) -> PlanConfirmationChallenge:
        row = self._connection.execute(
            "SELECT * FROM plan_confirmation_challenge "
            "WHERE challenge_id=?",
            (challenge_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("PLAN_CHALLENGE_NOT_FOUND")
        payload = json.loads(row["canonical_diff_json"])
        diff = CanonicalPlanDiff(
            based_on_graph_seal_hash=payload[
                "based_on_graph_seal_hash"
            ],
            proposed_graph_seal_hash=payload[
                "proposed_graph_seal_hash"
            ],
            changed_components=tuple(payload["changed_components"]),
            content_hash=payload["content_hash"],
            schema_version=payload["schema_version"],
        )
        challenge = PlanConfirmationChallenge(
            challenge_id=row["challenge_id"],
            plan_id=row["plan_id"],
            draft_id=row["draft_id"],
            expected_revision=row["expected_revision"],
            expected_draft_hash=row["expected_content_hash"],
            expected_graph_seal_hash=row[
                "expected_graph_seal_hash"
            ],
            canonical_diff=diff,
            activation_intent=ActivationIntent(
                row["activation_intent"]
            ),
            decision_actor=row["decision_actor"],
            interaction_channel=row["interaction_channel"],
            transport_actor=row["transport_actor"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            content_hash=row["content_hash"],
        )
        challenge.validate()
        return challenge

    def _build_approval_receipt(
        self,
        command: "ConfirmTradePlanVersion",
        challenge: PlanConfirmationChallenge,
    ) -> UserApprovalReceipt:
        receipt_id = (
            "user_approval_receipt_"
            + canonical_hash(
                {
                    "challenge_id": challenge.challenge_id,
                    "invocation_id": command.invocation_id,
                }
            )[:24]
        )
        prototype = UserApprovalReceipt(
            approval_receipt_id=receipt_id,
            challenge_id=challenge.challenge_id,
            plan_id=challenge.plan_id,
            draft_id=challenge.draft_id,
            approved_revision=challenge.expected_revision,
            approved_draft_hash=challenge.expected_draft_hash,
            approved_graph_seal_hash=(
                challenge.expected_graph_seal_hash
            ),
            approved_diff_hash=(
                challenge.canonical_diff.content_hash
            ),
            activation_intent=challenge.activation_intent,
            decision_actor=command.actor.decision_actor,
            interaction_channel=command.actor.interaction_channel,
            transport_actor=command.actor.transport_actor,
            command_invocation_id=command.invocation_id,
            approved_at=command.approved_at,
            content_hash="",
        )
        receipt = replace(
            prototype,
            content_hash=canonical_hash(prototype.identity_payload()),
        )
        receipt.validate()
        return receipt

    def _insert_approval_receipt(
        self, receipt: UserApprovalReceipt
    ) -> None:
        self._connection.execute(
            "INSERT INTO user_approval_receipt VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                receipt.approval_receipt_id,
                receipt.schema_version,
                receipt.challenge_id,
                receipt.plan_id,
                receipt.draft_id,
                receipt.approved_revision,
                receipt.approved_draft_hash,
                receipt.approved_graph_seal_hash,
                receipt.approved_diff_hash,
                receipt.activation_intent.value,
                receipt.decision_actor,
                receipt.interaction_channel,
                receipt.transport_actor,
                receipt.command_invocation_id,
                receipt.approved_at,
                receipt.content_hash,
            ),
        )

    def _load_approval_by_invocation(
        self, invocation_id: str
    ) -> UserApprovalReceipt:
        row = self._connection.execute(
            "SELECT * FROM user_approval_receipt "
            "WHERE command_invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("USER_APPROVAL_RECEIPT_NOT_FOUND")
        receipt = UserApprovalReceipt(
            approval_receipt_id=row["user_approval_receipt_id"],
            challenge_id=row["challenge_id"],
            plan_id=row["plan_id"],
            draft_id=row["draft_id"],
            approved_revision=row["approved_revision"],
            approved_draft_hash=row["approved_draft_hash"],
            approved_graph_seal_hash=row[
                "approved_graph_seal_hash"
            ],
            approved_diff_hash=row["approved_diff_hash"],
            activation_intent=ActivationIntent(
                row["activation_intent"]
            ),
            decision_actor=row["decision_actor"],
            interaction_channel=row["interaction_channel"],
            transport_actor=row["transport_actor"],
            command_invocation_id=row["command_invocation_id"],
            approved_at=row["approved_at"],
            content_hash=row["content_hash"],
        )
        receipt.validate()
        return receipt

    def _validate_confirmation(
        self,
        command: "ConfirmTradePlanVersion",
        challenge: PlanConfirmationChallenge,
        draft: TradePlanDraft,
    ) -> None:
        try:
            approved = datetime.fromisoformat(command.approved_at)
            issued = datetime.fromisoformat(challenge.issued_at)
            expires = (
                datetime.fromisoformat(challenge.expires_at)
                if challenge.expires_at is not None
                else None
            )
        except ValueError as error:
            raise PlanValidationError(
                "PLAN_CONFIRMATION_TIME_INVALID"
            ) from error
        if challenge.status != "issued":
            raise PlanValidationError("PLAN_CHALLENGE_NOT_ISSUED")
        if expires is not None and approved > expires:
            with self._connection:
                self._insert_challenge_expiry(
                    challenge.challenge_id
                )
            raise PlanValidationError("PLAN_CHALLENGE_EXPIRED")
        if (
            draft.status != "open"
            or draft.revision != challenge.expected_revision
            or draft.content_hash != challenge.expected_draft_hash
            or draft.proposed_graph.version.graph_seal_hash
            != challenge.expected_graph_seal_hash
            or command.expected_revision
            != challenge.expected_revision
            or command.expected_draft_hash
            != challenge.expected_draft_hash
            or command.expected_diff_hash
            != challenge.canonical_diff.content_hash
            or command.activation_intent
            is not challenge.activation_intent
            or command.actor.decision_actor
            != challenge.decision_actor
            or command.actor.interaction_channel
            != challenge.interaction_channel
            or command.actor.transport_actor
            != challenge.transport_actor
            or approved.tzinfo is None
            or approved < issued
        ):
            raise PlanValidationError(
                "PLAN_CONFIRMATION_CHALLENGE_MISMATCH"
            )

    def _activate_confirmed_version(
        self,
        graph: TradePlanGraph,
        receipt: UserApprovalReceipt,
        command: "ConfirmTradePlanVersion",
    ) -> ActiveTradePlan:
        plan_id = graph.version.plan_id
        plan_version_id = graph.version.plan_version_id
        now = command.approved_at
        current = self._connection.execute(
            "SELECT activation_id FROM plan_activation "
            "WHERE plan_id=? AND ended_at IS NULL",
            (plan_id,),
        ).fetchone()
        if current is not None:
            ended_event_id = (
                "application_event_"
                + canonical_hash(
                    {
                        "event_type": "PlanActivationEnded",
                        "activation_id": current["activation_id"],
                        "next_plan_version_id": plan_version_id,
                    }
                )[:24]
            )
            self._insert_event(
                ended_event_id,
                "PlanActivationEnded",
                "PlanActivation",
                current["activation_id"],
                {
                    "next_plan_version_id": plan_version_id,
                    "reason": "superseded_by_new_version",
                },
                now,
            )
            self._connection.execute(
                "UPDATE plan_activation SET ended_event_id=?,"
                "ended_at=?,end_reason=? WHERE activation_id=? "
                "AND ended_at IS NULL",
                (
                    ended_event_id,
                    now,
                    "superseded_by_new_version",
                    current["activation_id"],
                ),
            )
        master = self._master_row(plan_id)
        from_status = master["lifecycle_status"]
        changed = self._connection.execute(
            "UPDATE trade_plan_master SET lifecycle_status='active',"
            "transition_seq=transition_seq+1 "
            "WHERE plan_id=? AND lifecycle_status<>'ended' "
            "AND legacy_read_only=0",
            (plan_id,),
        ).rowcount
        if changed != 1:
            raise PlanValidationError("PLAN_MASTER_NOT_ACTIVATABLE")
        master = self._master_row(plan_id)
        activation_id = (
            "plan_activation_"
            + canonical_hash(
                {
                    "plan_id": plan_id,
                    "plan_version_id": plan_version_id,
                    "invocation_id": command.invocation_id,
                }
            )[:24]
        )
        event = self._activated_event(
            graph, receipt, activation_id, now
        )
        self._insert_event(
            event.event_id,
            "PlanActivated",
            "TradePlanMaster",
            plan_id,
            {
                "plan_version_id": plan_version_id,
                "activation_id": activation_id,
                "approval_receipt_id": receipt.approval_receipt_id,
            },
            now,
        )
        self._connection.execute(
            "INSERT INTO plan_activation VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                activation_id,
                plan_id,
                plan_version_id,
                event.event_id,
                now,
                None,
                None,
                None,
                receipt.approval_receipt_id,
                command.invocation_id,
            ),
        )
        transition_hash = canonical_hash(
            {
                "plan_id": plan_id,
                "transition_seq": master["transition_seq"],
                "from_status": from_status,
                "to_status": "active",
                "plan_version_id": plan_version_id,
                "command_invocation_id": command.invocation_id,
            }
        )
        self._connection.execute(
            "INSERT INTO trade_plan_transition "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                f"trade_plan_transition_{transition_hash[:24]}",
                plan_id,
                master["transition_seq"],
                from_status,
                "active",
                plan_version_id,
                "version_confirmed_and_activated",
                command.invocation_id,
                now,
                transition_hash,
            ),
        )
        return self._activation_result(
            command.invocation_id, graph
        )

    def _activation_result(
        self, invocation_id: str, graph: TradePlanGraph
    ) -> ActiveTradePlan:
        row = self._connection.execute(
            "SELECT * FROM plan_activation "
            "WHERE command_invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("PLAN_ACTIVATION_NOT_FOUND")
        activation = PlanActivation(
            activation_id=row["activation_id"],
            plan_id=row["plan_id"],
            plan_version_id=row["plan_version_id"],
            activated_event_id=row["activated_event_id"],
            activated_at=row["activated_at"],
            ended_event_id=row["ended_event_id"],
            ended_at=row["ended_at"],
            end_reason=row["end_reason"],
            user_approval_receipt_id=row[
                "user_approval_receipt_id"
            ],
            command_invocation_id=row["command_invocation_id"],
        )
        return ActiveTradePlan(
            self.get_master(graph.version.plan_id),
            activation,
            graph.version,
        )

    @staticmethod
    def _confirmed_event(
        graph: TradePlanGraph,
        receipt: UserApprovalReceipt,
        occurred_at: str,
    ) -> PlanVersionConfirmed:
        event_id = "application_event_" + canonical_hash(
            {
                "event_type": "PlanVersionConfirmed",
                "plan_version_id": graph.version.plan_version_id,
                "approval_receipt_id": receipt.approval_receipt_id,
            }
        )[:24]
        return PlanVersionConfirmed(
            event_id,
            graph.version.plan_id,
            graph.version.plan_version_id,
            receipt.approval_receipt_id,
            occurred_at,
        )

    @staticmethod
    def _activated_event(
        graph: TradePlanGraph,
        receipt: UserApprovalReceipt,
        activation_id: str,
        occurred_at: str,
    ) -> PlanActivated:
        event_id = "application_event_" + canonical_hash(
            {
                "event_type": "PlanActivated",
                "plan_version_id": graph.version.plan_version_id,
                "approval_receipt_id": receipt.approval_receipt_id,
                "activation_id": activation_id,
            }
        )[:24]
        return PlanActivated(
            event_id,
            graph.version.plan_id,
            graph.version.plan_version_id,
            activation_id,
            receipt.approval_receipt_id,
            occurred_at,
        )

    @staticmethod
    def _rejected_event(
        draft_id: str,
        plan_id: str,
        revision: int,
        occurred_at: str,
    ) -> PlanDraftRejected:
        event_id = "application_event_" + canonical_hash(
            {
                "event_type": "PlanDraftRejected",
                "draft_id": draft_id,
                "revision": revision,
            }
        )[:24]
        return PlanDraftRejected(
            event_id,
            draft_id,
            plan_id,
            revision,
            occurred_at,
        )

    def _command_receipt(
        self, invocation_id: str, request_hash: str
    ) -> sqlite3.Row | None:
        row = self._connection.execute(
            "SELECT * FROM application_command_receipt "
            "WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is not None and row["request_hash"] != request_hash:
            raise PlanValidationError("INVOCATION_CONFLICT")
        return row

    def _insert_command_receipt(
        self,
        *,
        invocation_id: str,
        command_name: str,
        request_hash: str,
        result_type: str,
        aggregate_id: str,
        revision_or_version_id: str,
        actor,
        created_at: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO application_command_receipt VALUES("
            "?,?,?,?,?,?,?,?,?,?,?)",
            (
                invocation_id,
                command_name,
                request_hash,
                result_type,
                aggregate_id,
                revision_or_version_id,
                "succeeded",
                actor.decision_actor,
                actor.interaction_channel,
                actor.transport_actor,
                created_at,
            ),
        )

    def _insert_challenge_expiry(
        self, challenge_id: str
    ) -> None:
        self._connection.execute(
            "UPDATE plan_confirmation_challenge SET status='expired' "
            "WHERE challenge_id=? AND status='issued'",
            (challenge_id,),
        )

    def _validate_seal_authority(self, graph: TradePlanGraph) -> None:
        version = graph.version
        master = self._master_row(version.plan_id)
        if (
            master["legacy_read_only"]
            or master["strategy_version_id"] != version.strategy_version_id
        ):
            raise PlanValidationError("PLAN_STRATEGY_OWNERSHIP_CONFLICT")
        snapshot = self._connection.execute(
            "SELECT account_id FROM account_snapshot_version "
            "WHERE account_snapshot_version_id=?",
            (version.account_snapshot_version_id,),
        ).fetchone()
        if snapshot is None or snapshot["account_id"] != master["account_id"]:
            raise PlanValidationError("PLAN_ACCOUNT_SNAPSHOT_INVALID")
        receipt = self._approval_receipt(
            version.user_approval_receipt_id
        )
        if (
            receipt["plan_id"] != version.plan_id
            or receipt["approved_graph_seal_hash"]
            != version.graph_seal_hash
        ):
            raise PlanValidationError("PLAN_CONFIRMATION_AUTHORITY_INVALID")
        latest = self._connection.execute(
            "SELECT plan_version_id,version_no FROM trade_plan_version "
            "WHERE plan_id=? ORDER BY version_no DESC LIMIT 1",
            (version.plan_id,),
        ).fetchone()
        if latest is None:
            if version.version_no != 1 or version.supersedes_version_id is not None:
                raise PlanValidationError("PLAN_VERSION_SEQUENCE_INVALID")
        elif (
            version.version_no != latest["version_no"] + 1
            or version.supersedes_version_id != latest["plan_version_id"]
        ):
            raise PlanValidationError("PLAN_VERSION_SEQUENCE_INVALID")

    def _insert_version(self, version: TradePlanVersion) -> None:
        self._connection.execute(
            "INSERT INTO trade_plan_version "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version.plan_version_id,
                version.plan_id,
                version.version_no,
                version.supersedes_version_id,
                version.strategy_version_id,
                version.investment_thesis_version_id,
                version.account_snapshot_version_id,
                version.data_snapshot_id,
                version.horizon_start,
                version.horizon_end,
                version.review_by,
                version.risk_policy_version_id,
                version.metric_catalog_version,
                version.evaluator_policy_version,
                version.conflict_policy_version,
                version.ast_version,
                json.dumps(
                    version.content,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                version.content_hash,
                version.graph_seal_hash,
                0,
                version.confirmed_at,
                version.user_approval_receipt_id,
                0,
            ),
        )

    def _insert_graph_children(self, graph: TradePlanGraph) -> None:
        plan_version_id = graph.version.plan_version_id
        for sleeve in graph.sleeves:
            if isinstance(sleeve, GridSleeve):
                constraint = sleeve.constraint
                self._connection.execute(
                    "INSERT INTO grid_constraint "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        constraint.grid_constraint_id,
                        plan_version_id,
                        str(constraint.lower_price),
                        str(constraint.upper_price),
                        constraint.level_count,
                        str(constraint.quantity_per_level),
                        str(constraint.total_quantity_budget),
                        constraint.price_basis,
                        constraint.trigger_mode,
                        constraint.cooldown_trading_sessions,
                        str(constraint.lot_size),
                        constraint.generated_levels_hash,
                        constraint.content_hash,
                    ),
                )
            record = sleeve.canonical_content
            self._connection.execute(
                "INSERT INTO trade_plan_sleeve VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_version_id,
                    sleeve.sleeve_id,
                    sleeve.kind.value,
                    record["quantity_budget_state"],
                    record["quantity_budget_value"],
                    record["core_floor_state"],
                    record["core_floor_value"],
                    record["max_notional_state"],
                    record["max_notional_value"],
                    record["max_loss_state"],
                    record["max_loss_value"],
                    record["grid_constraint_id"],
                    sleeve.content_hash,
                ),
            )
        for position, rule in enumerate(graph.rules):
            self._connection.execute(
                "INSERT INTO trade_plan_rule "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_version_id,
                    position,
                    rule.rule_id,
                    rule.rule_class.value,
                    rule.rule_kind,
                    rule.priority.value,
                    rule.scope.value,
                    rule.sleeve_id,
                    rule.effect,
                    rule.applies_to,
                    json.dumps(
                        candidate_to_dict(rule.candidate_intent),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        rule.input_applicability,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    rule.ast_version,
                    json.dumps(
                        ast_to_dict(rule.condition),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    rule.content_hash,
                ),
            )
        for position, reference in enumerate(graph.evidence_references):
            self._connection.execute(
                "INSERT INTO trade_plan_evidence_reference("
                "plan_version_id,ref_order,ref_type,ref_id,"
                "resolution_status,reference_json,content_hash"
                ") VALUES(?,?,?,?,?,?,?)",
                (
                    plan_version_id,
                    position,
                    reference["ref_type"],
                    reference["ref_id"],
                    reference["resolution_status"],
                    self._json(reference),
                    reference["content_hash"],
                ),
            )
        for evidence in graph.adjusted_price_evidence:
            self._connection.execute(
                "INSERT INTO trade_plan_adjusted_price_evidence "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_version_id,
                    evidence["rule_id"],
                    json.dumps(evidence["condition_path"]),
                    evidence["data_snapshot_id"],
                    evidence["factor_set_id"],
                    evidence["adjusted_price_decimal"],
                    evidence["canonical_unadjusted_price_decimal"],
                    evidence["factor_decimal"],
                    evidence["algorithm_version"],
                    evidence["content_hash"],
                ),
            )

    def _insert_event(
        self,
        event_id: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> None:
        content_hash = canonical_hash(
            {
                "event_type": event_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "payload": payload,
                "occurred_at": occurred_at,
            }
        )
        self._connection.execute(
            "INSERT INTO application_event VALUES(?,?,?,?,?,?,?)",
            (
                event_id,
                event_type,
                aggregate_type,
                aggregate_id,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                occurred_at,
                content_hash,
            ),
        )

    def _approval_receipt(self, receipt_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM user_approval_receipt "
            "WHERE user_approval_receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("USER_APPROVAL_RECEIPT_NOT_FOUND")
        return row

    def _master_row(self, plan_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM trade_plan_master WHERE plan_id=?",
            (plan_id,),
        ).fetchone()
        if row is None:
            raise PlanValidationError("PLAN_MASTER_NOT_FOUND")
        return row

    @staticmethod
    def _decode_sleeve(row: sqlite3.Row) -> CoreSleeve | GridSleeve:
        common = {
            "sleeve_id": row["sleeve_id"],
            "quantity_budget": (
                Decimal(row["quantity_budget_value"])
                if row["quantity_budget_state"] == "known"
                else None
            ),
            "core_floor": CoreFloor(Decimal(row["core_floor_value"])),
            "max_notional": (
                Decimal(row["max_notional_value"])
                if row["max_notional_state"] == "known"
                else None
            ),
            "max_loss": (
                Decimal(row["max_loss_value"])
                if row["max_loss_state"] == "known"
                else None
            ),
        }
        if row["sleeve_kind"] == "core":
            sleeve = CoreSleeve(**common)
        elif row["sleeve_kind"] == "grid":
            sleeve = GridSleeve(
                **common,
                constraint=GridConstraint(
                    grid_constraint_id=row["grid_constraint_id"],
                    lower_price=Decimal(row["lower_price"]),
                    upper_price=Decimal(row["upper_price"]),
                    level_count=row["level_count"],
                    quantity_per_level=Decimal(
                        row["quantity_per_level"]
                    ),
                    total_quantity_budget=Decimal(
                        row["total_quantity_budget"]
                    ),
                    price_basis=row["price_basis"],
                    trigger_mode=row["trigger_mode"],
                    cooldown_trading_sessions=row[
                        "cooldown_trading_sessions"
                    ],
                    lot_size=Decimal(row["lot_size"]),
                ),
            )
        else:
            raise PlanValidationError("LEGACY_SLEEVE_READ_ONLY")
        if sleeve.content_hash != row["content_hash"]:
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
        if (
            isinstance(sleeve, GridSleeve)
            and sleeve.constraint.content_hash
            != row["grid_content_hash"]
        ):
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
        if (
            isinstance(sleeve, GridSleeve)
            and sleeve.constraint.generated_levels_hash
            != row["generated_levels_hash"]
        ):
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
        return sleeve

    @staticmethod
    def _decode_rule(row: sqlite3.Row) -> TradePlanRule:
        candidate_payload = (
            json.loads(row["candidate_intent_json"])
            if row["candidate_intent_json"] is not None
            else None
        )
        rule = TradePlanRule(
            rule_id=row["rule_id"],
            rule_class=RuleClass(row["rule_class"]),
            rule_kind=row["rule_kind"],
            priority=RulePriority(row["priority"]),
            scope=RuleScope(row["scope"]),
            sleeve_id=row["sleeve_id"],
            effect=row["effect"],
            applies_to=row["applies_to"],
            candidate_intent=candidate_from_dict(candidate_payload),
            input_applicability=tuple(
                json.loads(row["input_applicability_json"])
            ),
            condition=ast_from_dict(
                json.loads(row["condition_json"])
            ),
            content_hash=row["content_hash"],
            ast_version=row["ast_version"],
        )
        rule.validate()
        return rule

    @staticmethod
    def _decode_reference(row: sqlite3.Row) -> Mapping[str, object]:
        try:
            reference = json.loads(row["reference_json"])
        except (json.JSONDecodeError, TypeError) as error:
            raise PlanValidationError(
                "PLAN_GRAPH_CHILD_INVALID"
            ) from error
        if (
            not isinstance(reference, dict)
            or reference.get("ref_type") != row["ref_type"]
            or reference.get("ref_id") != row["ref_id"]
            or reference.get("resolution_status")
            != row["resolution_status"]
            or reference.get("content_hash") != row["content_hash"]
            or canonical_hash(
                {
                    key: value
                    for key, value in reference.items()
                    if key != "content_hash"
                }
            )
            != row["content_hash"]
        ):
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
        return reference

    @staticmethod
    def _decode_adjusted(row: sqlite3.Row) -> Mapping[str, object]:
        return {
            "rule_id": row["rule_id"],
            "condition_path": tuple(json.loads(row["condition_path"])),
            "data_snapshot_id": row["data_snapshot_id"],
            "factor_set_id": row["factor_set_id"],
            "adjusted_price_decimal": row["adjusted_price_decimal"],
            "canonical_unadjusted_price_decimal": row[
                "canonical_unadjusted_price_decimal"
            ],
            "factor_decimal": row["factor_decimal"],
            "algorithm_version": row["algorithm_version"],
            "content_hash": row["content_hash"],
        }

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _encode_draft_graph(
        cls, graph: TradePlanDraftGraph
    ) -> Mapping[str, object]:
        version = graph.version
        return {
            "schema_version": graph.schema_version,
            "version": {
                "schema_version": version.schema_version,
                "plan_version_id": version.plan_version_id,
                "plan_id": version.plan_id,
                "version_no": version.version_no,
                "supersedes_version_id": (
                    version.supersedes_version_id
                ),
                "strategy_version_id": version.strategy_version_id,
                "investment_thesis_version_id": (
                    version.investment_thesis_version_id
                ),
                "account_snapshot_version_id": (
                    version.account_snapshot_version_id
                ),
                "data_snapshot_id": version.data_snapshot_id,
                "horizon_start": version.horizon_start,
                "horizon_end": version.horizon_end,
                "review_by": version.review_by,
                "risk_policy_version_id": (
                    version.risk_policy_version_id
                ),
                "metric_catalog_version": (
                    version.metric_catalog_version
                ),
                "evaluator_policy_version": (
                    version.evaluator_policy_version
                ),
                "conflict_policy_version": (
                    version.conflict_policy_version
                ),
                "ast_version": version.ast_version,
                "content": version.content,
                "content_hash": version.content_hash,
                "graph_seal_hash": version.graph_seal_hash,
            },
            "sleeves": tuple(
                {
                    **sleeve.canonical_content,
                    "grid_constraint": (
                        sleeve.constraint.canonical_content
                        if isinstance(sleeve, GridSleeve)
                        else None
                    ),
                }
                for sleeve in graph.sleeves
            ),
            "rules": tuple(
                {
                    "rule_id": rule.rule_id,
                    "rule_class": rule.rule_class.value,
                    "rule_kind": rule.rule_kind,
                    "priority": rule.priority.value,
                    "scope": rule.scope.value,
                    "sleeve_id": rule.sleeve_id,
                    "effect": rule.effect,
                    "applies_to": rule.applies_to,
                    "candidate_intent": candidate_to_dict(
                        rule.candidate_intent
                    ),
                    "input_applicability": rule.input_applicability,
                    "condition": ast_to_dict(rule.condition),
                    "content_hash": rule.content_hash,
                    "ast_version": rule.ast_version,
                }
                for rule in graph.rules
            ),
            "evidence_references": graph.evidence_references,
            "adjusted_price_evidence": (
                graph.adjusted_price_evidence
            ),
        }

    @classmethod
    def _decode_draft_graph(
        cls, payload: Mapping[str, object]
    ) -> TradePlanDraftGraph:
        raw_version = payload["version"]
        if (
            payload.get("schema_version") != "TradePlanDraftGraph@1"
            or not isinstance(raw_version, Mapping)
            or raw_version.get("schema_version")
            != "ProposedTradePlanVersion@1"
            or "confirmed_at" in raw_version
            or "user_approval_receipt_id" in raw_version
        ):
            raise PlanValidationError("PLAN_DRAFT_GRAPH_INVALID")
        version = ProposedTradePlanVersion(
            schema_version=str(raw_version["schema_version"]),
            plan_version_id=str(raw_version["plan_version_id"]),
            plan_id=str(raw_version["plan_id"]),
            version_no=int(raw_version["version_no"]),
            supersedes_version_id=(
                str(raw_version["supersedes_version_id"])
                if raw_version.get("supersedes_version_id")
                is not None
                else None
            ),
            strategy_version_id=str(
                raw_version["strategy_version_id"]
            ),
            investment_thesis_version_id=(
                str(raw_version["investment_thesis_version_id"])
                if raw_version.get("investment_thesis_version_id")
                is not None
                else None
            ),
            account_snapshot_version_id=str(
                raw_version["account_snapshot_version_id"]
            ),
            data_snapshot_id=str(raw_version["data_snapshot_id"]),
            horizon_start=str(raw_version["horizon_start"]),
            horizon_end=str(raw_version["horizon_end"]),
            review_by=str(raw_version["review_by"]),
            risk_policy_version_id=(
                str(raw_version["risk_policy_version_id"])
                if raw_version.get("risk_policy_version_id")
                is not None
                else None
            ),
            metric_catalog_version=str(
                raw_version["metric_catalog_version"]
            ),
            evaluator_policy_version=str(
                raw_version["evaluator_policy_version"]
            ),
            conflict_policy_version=str(
                raw_version["conflict_policy_version"]
            ),
            ast_version=str(raw_version["ast_version"]),
            content=raw_version["content"],
            content_hash=str(raw_version["content_hash"]),
            graph_seal_hash=str(raw_version["graph_seal_hash"]),
        )
        sleeves = []
        for raw in payload.get("sleeves", ()):
            if not isinstance(raw, Mapping):
                raise PlanValidationError(
                    "PLAN_DRAFT_GRAPH_INVALID"
                )

            def decimal_value(
                state_key: str, value_key: str
            ) -> Decimal | None:
                return (
                    Decimal(str(raw[value_key]))
                    if raw[state_key] == "known"
                    else None
                )

            common = {
                "sleeve_id": str(raw["sleeve_id"]),
                "quantity_budget": decimal_value(
                    "quantity_budget_state",
                    "quantity_budget_value",
                ),
                "core_floor": CoreFloor(
                    Decimal(str(raw["core_floor_value"]))
                ),
                "max_notional": decimal_value(
                    "max_notional_state", "max_notional_value"
                ),
                "max_loss": decimal_value(
                    "max_loss_state", "max_loss_value"
                ),
            }
            if raw["sleeve_kind"] == "core":
                sleeves.append(CoreSleeve(**common))
            elif raw["sleeve_kind"] == "grid":
                grid = raw["grid_constraint"]
                if not isinstance(grid, Mapping):
                    raise PlanValidationError(
                        "PLAN_DRAFT_GRAPH_INVALID"
                    )
                sleeves.append(
                    GridSleeve(
                        **common,
                        constraint=GridConstraint(
                            grid_constraint_id=str(
                                grid["grid_constraint_id"]
                            ),
                            lower_price=Decimal(
                                str(grid["lower_price"])
                            ),
                            upper_price=Decimal(
                                str(grid["upper_price"])
                            ),
                            level_count=int(grid["level_count"]),
                            quantity_per_level=Decimal(
                                str(grid["quantity_per_level"])
                            ),
                            total_quantity_budget=Decimal(
                                str(
                                    grid[
                                        "total_quantity_budget"
                                    ]
                                )
                            ),
                            price_basis=str(grid["price_basis"]),
                            trigger_mode=str(grid["trigger_mode"]),
                            cooldown_trading_sessions=int(
                                grid[
                                    "cooldown_trading_sessions"
                                ]
                            ),
                            lot_size=Decimal(
                                str(grid["lot_size"])
                            ),
                        ),
                    )
                )
            else:
                raise PlanValidationError(
                    "PLAN_DRAFT_GRAPH_INVALID"
                )
        rules = tuple(
            TradePlanRule(
                rule_id=str(raw["rule_id"]),
                rule_class=RuleClass(str(raw["rule_class"])),
                rule_kind=str(raw["rule_kind"]),
                priority=RulePriority(str(raw["priority"])),
                scope=RuleScope(str(raw["scope"])),
                sleeve_id=(
                    str(raw["sleeve_id"])
                    if raw.get("sleeve_id") is not None
                    else None
                ),
                effect=str(raw["effect"]),
                applies_to=str(raw["applies_to"]),
                candidate_intent=candidate_from_dict(
                    raw.get("candidate_intent")
                ),
                input_applicability=tuple(
                    raw.get("input_applicability", ())
                ),
                condition=ast_from_dict(raw["condition"]),
                content_hash=str(raw["content_hash"]),
                ast_version=str(raw["ast_version"]),
            )
            for raw in payload.get("rules", ())
        )
        graph = TradePlanDraftGraph(
            version=version,
            sleeves=tuple(sleeves),
            rules=rules,
            evidence_references=tuple(
                payload.get("evidence_references", ())
            ),
            adjusted_price_evidence=tuple(
                payload.get("adjusted_price_evidence", ())
            ),
            schema_version=str(payload["schema_version"]),
        )
        graph.validate()
        return graph


__all__ = ["SQLiteTradePlanRepository"]
