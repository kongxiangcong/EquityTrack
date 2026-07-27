from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

from trading_platform.domain.plans import (
    ActiveTradePlan,
    CoreFloor,
    CoreSleeve,
    GridSleeve,
    PlanActivation,
    PlanValidationError,
    TradePlanGraph,
    TradePlanMaster,
    TradePlanMasterId,
    TradePlanRule,
    TradePlanVersion,
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteTradePlanRepository:
    """Owns atomic Model B graph sealing, activation, and exact reconstruction."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock

    def create_master(self, master: TradePlanMaster) -> TradePlanMaster:
        master.validate()
        values = (
            master.plan_id.value,
            master.plan_id.account_id,
            master.plan_id.security_id,
            master.strategy_version_id,
            master.lifecycle_status,
            master.transition_seq,
            master.created_at,
            0,
        )
        with self._writer_lock.acquire(
            f"trade-plan-master:{master.plan_id.value}"
        ):
            existing = self._connection.execute(
                "SELECT * FROM trade_plan_master WHERE plan_id=?",
                (master.plan_id.value,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise PlanValidationError("PLAN_MASTER_IDENTITY_CONFLICT")
                return master
            try:
                with self._connection:
                    self._connection.execute(
                        "INSERT INTO trade_plan_master VALUES(?,?,?,?,?,?,?,?)",
                        values,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanValidationError("PLAN_MASTER_STORAGE_CONFLICT") from error
        return self.get_master(master.plan_id.value)

    def seal_version(self, graph: TradePlanGraph) -> TradePlanGraph:
        graph.validate()
        version = graph.version
        with self._writer_lock.acquire(
            f"trade-plan-version:{version.plan_id}"
        ):
            existing = self._connection.execute(
                "SELECT graph_seal_hash FROM trade_plan_version "
                "WHERE plan_version_id=?",
                (version.plan_version_id,),
            ).fetchone()
            if existing is not None:
                if existing["graph_seal_hash"] != version.graph_seal_hash:
                    raise PlanValidationError(
                        "PLAN_VERSION_IDENTITY_CONFLICT"
                    )
                return self.get_graph(version.plan_version_id)
            self._validate_seal_authority(graph)
            try:
                with self._connection:
                    self._insert_version(version)
                    self._insert_graph_children(graph)
                    changed = self._connection.execute(
                        "UPDATE trade_plan_version SET graph_sealed=1 "
                        "WHERE plan_version_id=? AND graph_sealed=0",
                        (version.plan_version_id,),
                    ).rowcount
                    if changed != 1:
                        raise PlanValidationError(
                            "PLAN_GRAPH_SEAL_CONFLICT"
                        )
                    self._connection.execute(
                        "UPDATE trade_plan_draft "
                        "SET status='confirmed',updated_at=? "
                        "WHERE draft_id=("
                        "SELECT draft_id FROM user_approval_receipt "
                        "WHERE user_approval_receipt_id=?"
                        ") AND status='open'",
                        (_now(), version.user_approval_receipt_id),
                    )
            except sqlite3.IntegrityError as error:
                raise PlanValidationError(
                    "PLAN_GRAPH_STORAGE_CONFLICT"
                ) from error
        return self.get_graph(version.plan_version_id)

    def activate_version(
        self,
        *,
        plan_id: str,
        plan_version_id: str,
        user_approval_receipt_id: str,
        command_invocation_id: str,
    ) -> ActiveTradePlan:
        if not command_invocation_id:
            raise PlanValidationError("COMMAND_INVOCATION_ID_REQUIRED")
        with self._writer_lock.acquire(
            f"trade-plan-activation:{plan_id}"
        ):
            replay = self._connection.execute(
                "SELECT plan_id FROM plan_activation "
                "WHERE command_invocation_id=?",
                (command_invocation_id,),
            ).fetchone()
            if replay is not None:
                if replay["plan_id"] != plan_id:
                    raise PlanValidationError("INVOCATION_CONFLICT")
                return self.get_active_master_by_plan(plan_id)
            version = self.get_version(plan_version_id)
            if version.plan_id != plan_id:
                raise PlanValidationError("PLAN_VERSION_OWNERSHIP_CONFLICT")
            receipt = self._approval_receipt(user_approval_receipt_id)
            if (
                receipt["plan_id"] != plan_id
                or receipt["expected_content_hash"] != version.content_hash
                or receipt["activation_intent"] != "confirm_and_enable"
                or user_approval_receipt_id
                != version.user_approval_receipt_id
            ):
                raise PlanValidationError("PLAN_ACTIVATION_AUTHORITY_INVALID")
            now = _now()
            event_id = (
                "application_event_"
                + canonical_hash(
                    {
                        "event_type": "PlanActivated",
                        "plan_id": plan_id,
                        "plan_version_id": plan_version_id,
                        "command_invocation_id": command_invocation_id,
                    }
                )[:24]
            )
            activation_id = (
                "plan_activation_"
                + canonical_hash(
                    {
                        "plan_id": plan_id,
                        "plan_version_id": plan_version_id,
                        "command_invocation_id": command_invocation_id,
                    }
                )[:24]
            )
            try:
                with self._connection:
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
                            "UPDATE plan_activation "
                            "SET ended_event_id=?,ended_at=?,end_reason=? "
                            "WHERE activation_id=? AND ended_at IS NULL",
                            (
                                ended_event_id,
                                now,
                                "superseded_by_new_version",
                                current["activation_id"],
                            ),
                        )
                    self._connection.execute(
                        "UPDATE trade_plan_master "
                        "SET lifecycle_status='active',transition_seq=transition_seq+1 "
                        "WHERE plan_id=? AND lifecycle_status<>'ended' "
                        "AND legacy_read_only=0",
                        (plan_id,),
                    )
                    master = self._master_row(plan_id)
                    if master["lifecycle_status"] != "active":
                        raise PlanValidationError("PLAN_MASTER_NOT_ACTIVATABLE")
                    self._insert_event(
                        event_id,
                        "PlanActivated",
                        "TradePlanMaster",
                        plan_id,
                        {"plan_version_id": plan_version_id},
                        now,
                    )
                    self._connection.execute(
                        "INSERT INTO plan_activation "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            activation_id,
                            plan_id,
                            plan_version_id,
                            event_id,
                            now,
                            None,
                            None,
                            None,
                            user_approval_receipt_id,
                            command_invocation_id,
                        ),
                    )
                    transition_seq = master["transition_seq"]
                    transition_hash = canonical_hash(
                        {
                            "plan_id": plan_id,
                            "transition_seq": transition_seq,
                            "to_status": "active",
                            "plan_version_id": plan_version_id,
                            "command_invocation_id": command_invocation_id,
                        }
                    )
                    self._connection.execute(
                        "INSERT INTO trade_plan_transition "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            f"trade_plan_transition_{transition_hash[:24]}",
                            plan_id,
                            transition_seq,
                            "inactive" if transition_seq == 1 else "active",
                            "active",
                            plan_version_id,
                            "version_activated",
                            command_invocation_id,
                            now,
                            transition_hash,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                if "trade_plan_master.account_id" in str(error):
                    raise PlanValidationError(
                        "ACTIVE_MASTER_OWNERSHIP_CONFLICT"
                    ) from error
                raise PlanValidationError(
                    "PLAN_ACTIVATION_STORAGE_CONFLICT"
                ) from error
        return self.get_active_master_by_plan(plan_id)

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
            or receipt["expected_content_hash"] != version.content_hash
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
                "INSERT INTO trade_plan_evidence_reference "
                "VALUES(?,?,?,?,?,?)",
                (
                    plan_version_id,
                    position,
                    reference["ref_type"],
                    reference["ref_id"],
                    reference["resolution_status"],
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
        return {
            "ref_type": row["ref_type"],
            "ref_id": row["ref_id"],
            "resolution_status": row["resolution_status"],
            "content_hash": row["content_hash"],
        }

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


__all__ = ["SQLiteTradePlanRepository"]
