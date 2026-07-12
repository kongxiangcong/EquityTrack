from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from trading_platform.domain.plans import (
    ActivatePlanVersionCommand,
    ActivePlanView,
    AdjustedPriceEvidence,
    ChangePlanLifecycleCommand,
    ConfirmPlanDraftCommand,
    CreatePlanDraftCommand,
    DiscardPlanDraftCommand,
    PlanCondition,
    PlanConstant,
    PlanDraftContent,
    PlanReference,
    PlanRule,
    TradePlanDraftView,
    TradePlanVersionView,
    UpdatePlanDraftCommand,
    PlanValidationError,
    validate_plan_content,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock


PlanError = PlanValidationError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLitePlanRepository:

    def __init__(
        self, connection: sqlite3.Connection, writer_lock: DataRootWriterLock
    ) -> None:
        self.connection = connection
        self.writer_lock = writer_lock

    def create_draft(self, command: CreatePlanDraftCommand) -> TradePlanDraftView:
        self._validate_content(command.content)
        fingerprint = self._fingerprint("create_plan_draft", command)
        with self.writer_lock.acquire(f"plan-invocation:{command.invocation_id}"):
            replay = self._draft_receipt(
                command.invocation_id, "create_plan_draft", fingerprint
            )
            if replay is not None:
                return replay
            plan_id = command.plan_id
            if plan_id is not None:
                plan = self._plan_row(plan_id)
                if plan["security_id"] != command.content.security_id:
                    raise PlanError("PLAN_SECURITY_CONFLICT")
                if plan["lifecycle_status"] == "ended":
                    plan_id = None
            draft_id = f"plan_draft_{uuid.uuid4().hex}"
            content_json, content_hash = self._serialize(command.content)
            now = _now()
            try:
                with self.connection:
                    self.connection.execute(
                        "INSERT INTO trade_plan_draft VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            draft_id,
                            plan_id,
                            command.content.security_id,
                            command.content.based_on_version_id,
                            1,
                            "open",
                            content_json,
                            content_hash,
                            now,
                            now,
                        ),
                    )
                    self._insert_receipt(
                        command.invocation_id,
                        "create_plan_draft",
                        fingerprint,
                        "TradePlanDraft",
                        draft_id,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanError("PLAN_OPEN_DRAFT_EXISTS") from error
            return self.get_draft(draft_id)

    def update_draft(self, command: UpdatePlanDraftCommand) -> TradePlanDraftView:
        self._validate_content(command.content)
        fingerprint = self._fingerprint("update_plan_draft", command)
        with self.writer_lock.acquire(f"plan-invocation:{command.invocation_id}"):
            replay = self._draft_receipt(
                command.invocation_id, "update_plan_draft", fingerprint
            )
            if replay is not None:
                return replay
            current = self.get_draft(command.draft_id)
            if (
                current.status != "open"
                or current.revision != command.expected_revision
            ):
                raise PlanError("PLAN_DRAFT_REVISION_CONFLICT")
            if (
                current.content.security_id != command.content.security_id
                or current.plan_id != command.plan_id
            ):
                raise PlanError("PLAN_DRAFT_IDENTITY_CONFLICT")
            content_json, content_hash = self._serialize(command.content)
            with self.connection:
                changed = self.connection.execute(
                    "UPDATE trade_plan_draft SET revision=revision+1,content_json=?,content_hash=?,updated_at=? WHERE draft_id=? AND status='open' AND revision=?",
                    (
                        content_json,
                        content_hash,
                        _now(),
                        command.draft_id,
                        command.expected_revision,
                    ),
                ).rowcount
                if changed != 1:
                    raise PlanError("PLAN_DRAFT_REVISION_CONFLICT")
                self._insert_receipt(
                    command.invocation_id,
                    "update_plan_draft",
                    fingerprint,
                    "TradePlanDraft",
                    command.draft_id,
                )
            return self.get_draft(command.draft_id)

    def discard_draft(self, command: DiscardPlanDraftCommand) -> TradePlanDraftView:
        fingerprint = self._fingerprint("discard_plan_draft", command)
        with self.writer_lock.acquire(f"plan-invocation:{command.invocation_id}"):
            replay = self._draft_receipt(
                command.invocation_id, "discard_plan_draft", fingerprint
            )
            if replay is not None:
                return replay
            current = self.get_draft(command.draft_id)
            if (
                current.status != "open"
                or current.revision != command.expected_revision
            ):
                raise PlanError("PLAN_DRAFT_REVISION_CONFLICT")
            with self.connection:
                self.connection.execute(
                    "UPDATE trade_plan_draft SET status='discarded',updated_at=? WHERE draft_id=?",
                    (_now(), command.draft_id),
                )
                self._insert_receipt(
                    command.invocation_id,
                    "discard_plan_draft",
                    fingerprint,
                    "TradePlanDraft",
                    command.draft_id,
                )
            return self.get_draft(command.draft_id)

    def confirm_draft(self, command: ConfirmPlanDraftCommand) -> TradePlanVersionView:
        if command.activation_mode not in {"activate", "inactive"}:
            raise PlanError("PLAN_CONFIRMATION_INVALID")
        fingerprint = self._fingerprint("confirm_plan_draft", command)
        with self.writer_lock.acquire(f"plan-invocation:{command.invocation_id}"):
            replay = self._version_receipt(
                command.invocation_id, "confirm_plan_draft", fingerprint
            )
            if replay is not None:
                return replay
            draft = self.get_draft(command.draft_id)
            if draft.status != "open" or draft.revision != command.expected_revision:
                raise PlanError("PLAN_DRAFT_REVISION_CONFLICT")
            self._validate_content(draft.content)
            plan_id = draft.plan_id
            plan = self._plan_row(plan_id) if plan_id else None
            if plan is not None and plan["lifecycle_status"] == "ended":
                plan = None
                plan_id = None
            if plan is None:
                plan_id = f"trade_plan_{uuid.uuid4().hex}"
                version_no, supersedes = 1, None
            else:
                latest = self.connection.execute(
                    "SELECT * FROM trade_plan_version WHERE plan_id=? ORDER BY version_no DESC LIMIT 1",
                    (plan_id,),
                ).fetchone()
                version_no, supersedes = (
                    latest["version_no"] + 1,
                    latest["plan_version_id"],
                )
                if draft.content.based_on_version_id != supersedes:
                    raise PlanError("PLAN_BASELINE_CONFLICT")
            version_id = f"trade_plan_version_{uuid.uuid4().hex}"
            now = _now()
            try:
                with self.connection:
                    if plan is None:
                        self.connection.execute(
                            "INSERT INTO trade_plan VALUES(?,?,?,?,?)",
                            (plan_id, draft.content.security_id, "inactive", 0, now),
                        )
                    self.connection.execute(
                        "INSERT INTO trade_plan_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            version_id,
                            plan_id,
                            version_no,
                            supersedes,
                            draft.content.security_id,
                            draft.content.based_on_version_id,
                            draft.content.data_snapshot_id,
                            draft.content.horizon_start,
                            draft.content.horizon_end,
                            draft.content.review_by,
                            draft.content.market_gate_policy_version,
                            draft.content.metric_catalog_version,
                            draft.content.evaluator_policy_version,
                            draft.content.user_input_source,
                            self._serialize(draft.content)[0],
                            draft.content_hash,
                            now,
                            command.invocation_id,
                        ),
                    )
                    for index, rule in enumerate(draft.content.rules):
                        condition_json = json.dumps(
                            asdict(rule.condition),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        self.connection.execute(
                            "INSERT INTO plan_rule VALUES(?,?,?,?,?,?,?)",
                            (
                                version_id,
                                index,
                                rule.rule_id,
                                rule.rule_kind,
                                rule.effect,
                                rule.applies_to,
                                rule.input_applicability,
                            ),
                        )
                        self.connection.execute(
                            "INSERT INTO plan_rule_condition VALUES(?,?,?,?,?)",
                            (
                                version_id,
                                index,
                                rule.condition.ast_version,
                                condition_json,
                                canonical_hash(asdict(rule.condition)),
                            ),
                        )
                    for index, reference in enumerate(draft.content.references):
                        self.connection.execute(
                            "INSERT INTO plan_version_reference VALUES(?,?,?,?,?)",
                            (
                                version_id,
                                index,
                                reference.ref_type,
                                reference.ref_id,
                                reference.resolution_status,
                            ),
                        )
                    for evidence in draft.content.adjusted_price_evidence:
                        self.connection.execute(
                            "INSERT INTO plan_adjusted_price_evidence VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                version_id,
                                evidence.rule_id,
                                json.dumps(evidence.condition_path),
                                evidence.data_snapshot_id,
                                evidence.factor_set_id,
                                evidence.adjusted_price_decimal,
                                evidence.canonical_unadjusted_price_decimal,
                                evidence.factor_decimal,
                                evidence.algorithm_version,
                            ),
                        )
                    account_context = self._account_context(draft.content)
                    if account_context:
                        self.connection.execute(
                            "INSERT INTO plan_account_snapshot_reference VALUES(?,?,?,?,?,?,?,?)",
                            (version_id, *account_context),
                        )
                    self.connection.execute(
                        "INSERT INTO plan_risk_constraint VALUES(?,?,?,?,?)",
                        (
                            version_id,
                            draft.content.currency,
                            draft.content.max_planned_notional,
                            draft.content.max_planned_loss,
                            "verified" if account_context else "not_applicable",
                        ),
                    )
                    self.connection.execute(
                        "UPDATE trade_plan_draft SET status='confirmed',plan_id=?,updated_at=? WHERE draft_id=?",
                        (plan_id, now, draft.draft_id),
                    )
                    self._transition(
                        plan_id,
                        version_id,
                        "confirmed",
                        command.invocation_id,
                        now,
                        status="inactive",
                    )
                    if command.activation_mode == "activate":
                        self._activate_locked(
                            plan_id, version_id, command.invocation_id, now
                        )
                    self._insert_receipt(
                        command.invocation_id,
                        "confirm_plan_draft",
                        fingerprint,
                        "TradePlanVersion",
                        version_id,
                    )
            except sqlite3.IntegrityError as error:
                raise PlanError("PLAN_CONFIRMATION_ATOMIC_FAILURE") from error
            return self.get_version(version_id)

    def activate_version(
        self, command: ActivatePlanVersionCommand
    ) -> TradePlanVersionView:
        fingerprint = self._fingerprint("activate_plan_version", command)
        with self.writer_lock.acquire(f"plan-invocation:{command.invocation_id}"):
            replay = self._version_receipt(
                command.invocation_id, "activate_plan_version", fingerprint
            )
            if replay is not None:
                return replay
            plan = self._plan_row(command.plan_id)
            if plan["lifecycle_status"] == "ended":
                raise PlanError("PLAN_ENDED_TERMINAL")
            if plan["transition_seq"] != command.expected_transition_seq:
                raise PlanError("PLAN_TRANSITION_CONFLICT")
            version = self.get_version(command.plan_version_id)
            if version.plan_id != command.plan_id:
                raise PlanError("PLAN_VERSION_CONFLICT")
            with self.connection:
                self._activate_locked(
                    command.plan_id,
                    command.plan_version_id,
                    command.invocation_id,
                    _now(),
                )
                self._insert_receipt(
                    command.invocation_id,
                    "activate_plan_version",
                    fingerprint,
                    "TradePlanVersion",
                    command.plan_version_id,
                )
            return self.get_version(command.plan_version_id)

    def deactivate(self, command: ChangePlanLifecycleCommand) -> ActivePlanView:
        return self._change_lifecycle(command, "inactive", "deactivated")

    def end(self, command: ChangePlanLifecycleCommand) -> ActivePlanView:
        return self._change_lifecycle(command, "ended", command.reason or "user_ended")

    def _change_lifecycle(
        self, command: ChangePlanLifecycleCommand, status: str, reason: str
    ) -> ActivePlanView:
        name = "end_plan" if status == "ended" else "deactivate_plan"
        fingerprint = self._fingerprint(name, command)
        with self.writer_lock.acquire(f"plan-invocation:{command.invocation_id}"):
            receipt = self.connection.execute(
                "SELECT * FROM command_receipt WHERE invocation_id=?",
                (command.invocation_id,),
            ).fetchone()
            if receipt is not None:
                if (
                    receipt["command_name"] != name
                    or receipt["request_hash"] != fingerprint
                ):
                    raise PlanError("INVOCATION_CONFLICT")
                return self.get_lifecycle(command.plan_id)
            plan = self._plan_row(command.plan_id)
            if plan["lifecycle_status"] == "ended":
                raise PlanError("PLAN_ENDED_TERMINAL")
            if plan["transition_seq"] != command.expected_transition_seq:
                raise PlanError("PLAN_TRANSITION_CONFLICT")
            now = _now()
            active = self.connection.execute(
                "SELECT plan_version_id FROM plan_activation WHERE plan_id=? AND ended_at IS NULL",
                (command.plan_id,),
            ).fetchone()
            with self.connection:
                if active:
                    self.connection.execute(
                        "UPDATE plan_activation SET ended_at=? WHERE plan_id=? AND ended_at IS NULL",
                        (now, command.plan_id),
                    )
                self._transition(
                    command.plan_id,
                    active[0] if active else None,
                    reason,
                    command.invocation_id,
                    now,
                    status=status,
                )
                self._insert_receipt(
                    command.invocation_id,
                    name,
                    fingerprint,
                    "TradePlan",
                    command.plan_id,
                )
            return self.get_lifecycle(command.plan_id)

    def get_draft(self, draft_id: str) -> TradePlanDraftView:
        row = self.connection.execute(
            "SELECT * FROM trade_plan_draft WHERE draft_id=?", (draft_id,)
        ).fetchone()
        if row is None:
            raise PlanError("PLAN_DRAFT_NOT_FOUND")
        return TradePlanDraftView(
            row["draft_id"],
            row["plan_id"],
            row["revision"],
            row["status"],
            self._deserialize(row["content_json"]),
            row["content_hash"],
            row["created_at"],
            row["updated_at"],
        )

    def get_version(self, version_id: str) -> TradePlanVersionView:
        row = self.connection.execute(
            "SELECT v.*,p.lifecycle_status FROM trade_plan_version v JOIN trade_plan p USING(plan_id) WHERE plan_version_id=?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise PlanError("PLAN_VERSION_NOT_FOUND")
        active = self.connection.execute(
            "SELECT 1 FROM plan_activation WHERE plan_version_id=? AND ended_at IS NULL",
            (version_id,),
        ).fetchone()
        lifecycle = (
            "active"
            if active
            else (
                row["lifecycle_status"]
                if row["lifecycle_status"] == "ended"
                else "inactive"
            )
        )
        return TradePlanVersionView(
            row["plan_id"],
            row["plan_version_id"],
            row["version_no"],
            row["supersedes_version_id"],
            lifecycle,
            self._deserialize(row["content_json"]),
            row["content_hash"],
            row["confirmed_at"],
            row["confirmation_invocation_id"],
        )

    def get_active_for_security(self, security_id: str) -> ActivePlanView:
        row = self.connection.execute(
            "SELECT * FROM trade_plan WHERE security_id=? AND lifecycle_status!='ended' ORDER BY created_at DESC LIMIT 1",
            (security_id,),
        ).fetchone()
        if row is None:
            raise PlanError("PLAN_NOT_FOUND")
        active = self.connection.execute(
            "SELECT plan_version_id FROM plan_activation WHERE plan_id=? AND ended_at IS NULL",
            (row["plan_id"],),
        ).fetchone()
        return ActivePlanView(
            row["plan_id"],
            row["lifecycle_status"],
            self.get_version(active[0]) if active else None,
        )

    def get_lifecycle(self, plan_id: str) -> ActivePlanView:
        row = self._plan_row(plan_id)
        active = self.connection.execute(
            "SELECT plan_version_id FROM plan_activation WHERE plan_id=? AND ended_at IS NULL",
            (plan_id,),
        ).fetchone()
        return ActivePlanView(
            plan_id,
            row["lifecycle_status"],
            self.get_version(active[0]) if active else None,
        )

    def _activate_locked(
        self, plan_id: str, version_id: str, invocation_id: str, now: str
    ) -> None:
        plan = self._plan_row(plan_id)
        if plan["lifecycle_status"] == "ended":
            raise PlanError("PLAN_ENDED_TERMINAL")
        self.connection.execute(
            "UPDATE plan_activation SET ended_at=? WHERE plan_id=? AND ended_at IS NULL",
            (now, plan_id),
        )
        self.connection.execute(
            "INSERT INTO plan_activation VALUES(?,?,?,?,?,?)",
            (
                f"activation_{uuid.uuid4().hex}",
                plan_id,
                version_id,
                now,
                None,
                invocation_id,
            ),
        )
        self._transition(
            plan_id, version_id, "activated", invocation_id, now, status="active"
        )

    def _transition(
        self,
        plan_id: str,
        version_id: str | None,
        reason: str,
        invocation_id: str,
        now: str,
        status: str,
    ) -> None:
        plan = self._plan_row(plan_id)
        sequence = plan["transition_seq"] + 1
        self.connection.execute(
            "INSERT INTO trade_plan_transition VALUES(?,?,?,?,?,?,?,?)",
            (
                plan_id,
                sequence,
                plan["lifecycle_status"],
                status,
                version_id,
                reason,
                invocation_id,
                now,
            ),
        )
        self.connection.execute(
            "UPDATE trade_plan SET lifecycle_status=?,transition_seq=? WHERE plan_id=?",
            (status, sequence, plan_id),
        )

    def validate_content(self, content: PlanDraftContent) -> None:
        security = self.connection.execute(
            "SELECT currency FROM security WHERE security_id=?", (content.security_id,)
        ).fetchone()
        snapshot = self.connection.execute(
            "SELECT scope_id FROM data_snapshot WHERE data_snapshot_id=?",
            (content.data_snapshot_id,),
        ).fetchone()
        resolved_research_ids = {
            row[0]
            for row in self.connection.execute(
                "SELECT research_run_id FROM research_run_record"
            )
        }
        factor_sets = {
            row[0]: (row[1], row[2], row[3], row[4])
            for row in self.connection.execute(
                "SELECT factor_set_id,data_snapshot_id,mapping_status,source_ref,algorithm_version FROM price_factor_set"
            )
        }
        account_context = self._account_context(content)
        validate_plan_content(
            content,
            security_currency=security[0] if security else None,
            snapshot_scope=snapshot[0] if snapshot else None,
            resolved_research_ids=resolved_research_ids,
            factor_sets=factor_sets,
            account_metrics_supported=(
                account_context is not None
                and json.loads(account_context[5]).get("metrics_supported") is True
            ),
        )

    _validate_content = validate_content

    def _account_context(self, content: PlanDraftContent):
        if content.account_snapshot_id is None:
            return None
        row = self.connection.execute(
            "SELECT 'AccountHistorySnapshot' AS snapshot_type,s.account_history_snapshot_id AS snapshot_id,s.account_id,s.as_of_date AS snapshot_as_of,s.reconciliation_status FROM account_history_snapshot s WHERE s.account_history_snapshot_id=? UNION ALL SELECT 'PortfolioSnapshot',p.portfolio_snapshot_id,p.account_id,p.as_of_date,p.reconciliation_status FROM portfolio_snapshot p WHERE p.portfolio_snapshot_id=?",
            (content.account_snapshot_id, content.account_snapshot_id),
        ).fetchone()
        if row is None or row["reconciliation_status"] == "blocked":
            raise PlanError("PLAN_ACCOUNT_SNAPSHOT_INVALID")
        account = self.connection.execute(
            "SELECT base_currency FROM account WHERE account_id=?", (row["account_id"],)
        ).fetchone()
        if account is None or account[0] != content.currency:
            raise PlanError("PLAN_ACCOUNT_SNAPSHOT_INVALID")
        is_portfolio = row["snapshot_type"] == "PortfolioSnapshot"
        position = (
            self.connection.execute(
                "SELECT p.quantity_decimal,p.available_decimal,p.frozen_decimal,l.cost_price_decimal FROM account_position p JOIN account_position_lot l USING(position_id) WHERE p.account_id=? AND p.security_id=?",
                (row["account_id"], content.security_id),
            ).fetchone()
            if is_portfolio
            else None
        )
        portfolio = (
            self.connection.execute(
                "SELECT total_equity_decimal FROM portfolio_snapshot WHERE portfolio_snapshot_id=?",
                (row["snapshot_id"],),
            ).fetchone()
            if is_portfolio
            else None
        )
        values = {
            "metrics_supported": is_portfolio,
            "position_status": (
                ("position" if position else "not_held") if is_portfolio else "unknown"
            ),
            "position_quantity": (
                (position[0] if position else "0") if is_portfolio else None
            ),
            "position_available": (
                (position[1] if position else "0") if is_portfolio else None
            ),
            "position_frozen": (
                (position[2] if position else "0") if is_portfolio else None
            ),
            "position_cost_basis": position[3] if position else None,
            "portfolio_net_asset_value": portfolio[0] if portfolio else None,
            "currency": content.currency,
        }
        context_json = json.dumps(values, sort_keys=True, separators=(",", ":"))
        context_hash = canonical_hash({"snapshot": dict(row), "values": values})
        return (
            row["snapshot_type"],
            row["snapshot_id"],
            row["account_id"],
            row["snapshot_as_of"],
            row["reconciliation_status"],
            context_json,
            context_hash,
        )

    def get_account_operands(self, plan_version_id: str) -> dict[str, str]:
        row = self.connection.execute(
            "SELECT context_json FROM plan_account_snapshot_reference WHERE plan_version_id=?",
            (plan_version_id,),
        ).fetchone()
        return {} if row is None else json.loads(row[0])

    def _plan_row(self, plan_id: str | None) -> sqlite3.Row:
        row = (
            None
            if plan_id is None
            else self.connection.execute(
                "SELECT * FROM trade_plan WHERE plan_id=?", (plan_id,)
            ).fetchone()
        )
        if row is None:
            raise PlanError("PLAN_NOT_FOUND")
        return row

    @staticmethod
    def _serialize(content: PlanDraftContent) -> tuple[str, str]:
        payload = asdict(content)
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ), canonical_hash(payload)

    @staticmethod
    def _deserialize(value: str) -> PlanDraftContent:
        payload = json.loads(value)

        def condition(item: dict[str, object]) -> PlanCondition:
            constant = (
                PlanConstant(**item["constant"]) if item.get("constant") else None
            )
            children = tuple(condition(child) for child in item.get("children", []))
            return PlanCondition(
                node_kind=item["node_kind"],
                metric_ref=item.get("metric_ref"),
                operator=item.get("operator"),
                constant=constant,
                observation=item.get("observation"),
                children=children,
                ast_version=item.get("ast_version", "plan-condition-ast@1"),
            )

        rules = tuple(
            PlanRule(
                item["rule_id"],
                item["rule_kind"],
                item["effect"],
                item["applies_to"],
                condition(item["condition"]),
                item.get("input_applicability", "applicable"),
            )
            for item in payload.pop("rules")
        )
        evidence = tuple(
            AdjustedPriceEvidence(**item)
            for item in payload.pop("adjusted_price_evidence")
        )
        references = tuple(PlanReference(**item) for item in payload.pop("references"))
        return PlanDraftContent(
            rules=rules,
            references=references,
            adjusted_price_evidence=evidence,
            **payload,
        )

    def _fingerprint(self, name: str, command: PlanCommand) -> str:
        payload = asdict(command)
        payload.pop("invocation_id")
        return canonical_hash({"command": name, "request": payload})

    def _insert_receipt(
        self,
        invocation_id: str,
        name: str,
        fingerprint: str,
        result_type: str,
        result_id: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO command_receipt VALUES(?,?,?,?,?)",
            (invocation_id, name, fingerprint, result_type, result_id),
        )

    def _draft_receipt(
        self, invocation_id: str, name: str, fingerprint: str
    ) -> TradePlanDraftView | None:
        row = self.connection.execute(
            "SELECT * FROM command_receipt WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"] != name
            or row["request_hash"] != fingerprint
            or row["result_type"] != "TradePlanDraft"
        ):
            raise PlanError("INVOCATION_CONFLICT")
        return self.get_draft(row["result_id"])

    def _version_receipt(
        self, invocation_id: str, name: str, fingerprint: str
    ) -> TradePlanVersionView | None:
        row = self.connection.execute(
            "SELECT * FROM command_receipt WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"] != name
            or row["request_hash"] != fingerprint
            or row["result_type"] != "TradePlanVersion"
        ):
            raise PlanError("INVOCATION_CONFLICT")
        return self.get_version(row["result_id"])
