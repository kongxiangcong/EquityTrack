from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .locking import DataRootWriterLock, PersistenceError


def _migration_digest(path: Path) -> str:
    canonical_bytes = path.read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def _legacy_rule_to_ast_v2(payload: object):
    from trading_platform.domain.rules import RuleAstV2

    if not isinstance(payload, dict):
        raise ValueError("legacy condition must be an object")
    node = payload.get("node_kind")
    if node in {"all", "any", "not"}:
        return RuleAstV2(
            node=node,
            children=tuple(
                _legacy_rule_to_ast_v2(child)
                for child in payload.get("children", ())
            ),
        )
    if (
        node != "leaf"
        or payload.get("applicability")
        != "current_complete_session"
    ):
        raise ValueError("legacy condition is not finite")
    operand_id = payload.get("metric_ref")
    if operand_id not in {
        "security.close_unadjusted",
        "security.status",
        "market.trend",
        "account.total_quantity",
        "account.cash",
        "account.nav",
    }:
        raise ValueError("legacy operand is not finite")
    constant = payload.get("constant")
    if not isinstance(constant, dict):
        raise ValueError("legacy constant missing")
    kind = constant.get("constant_type")
    raw = constant.get("value")
    if kind == "decimal":
        expected: object = Decimal(str(raw))
    elif kind == "bool":
        if str(raw).lower() not in {"true", "false"}:
            raise ValueError("legacy boolean invalid")
        expected = str(raw).lower() == "true"
    elif kind == "enum":
        expected = str(raw)
    else:
        raise ValueError("legacy constant is not finite")
    return RuleAstV2(
        node="comparison",
        operand_id=str(operand_id),
        operator=str(payload.get("operator")),
        expected=expected,
    )


class MigrationRunner:
    def __init__(self, connection: sqlite3.Connection, data_root: Path, migrations_root: Path, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.data_root = data_root
        self.migrations_root = migrations_root
        self.writer_lock = writer_lock
        self.connection.create_function(
            "canonical_sha256",
            1,
            lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest(),
            deterministic=True,
        )
        self.connection.execute("CREATE TABLE IF NOT EXISTS schema_migration(version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL, app_version TEXT NOT NULL)")
        self.connection.commit()

    def validate(self) -> tuple[list[Path], dict[int, sqlite3.Row]]:
        files = sorted(self.migrations_root.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        applied = {row["version"]: row for row in self.connection.execute("SELECT * FROM schema_migration ORDER BY version")}
        if applied and max(applied) > len(files):
            raise PersistenceError("MIGRATION_FUTURE_VERSION", "Database has an unknown future migration.")
        if sorted(applied) != list(range(1, len(applied) + 1)):
            raise PersistenceError("MIGRATION_HALF_UPGRADED", "Migration ledger is not contiguous.")
        for index, path in enumerate(files, start=1):
            if not path.name.startswith(f"{index:04d}_"):
                raise PersistenceError("MIGRATION_SEQUENCE_INVALID", "Migration sequence is not contiguous.")
            row = applied.get(index)
            digest = _migration_digest(path)
            if row and (row["name"] != path.name or row["sha256"] != digest):
                raise PersistenceError("MIGRATION_HASH_DRIFT", f"Migration {index} differs from its ledger entry.")
        return files, applied

    def migrate(self, fail_after_statement: int | None = None, acquire_lock: bool = True) -> None:
        if acquire_lock:
            with self.writer_lock.acquire("maintenance:migrate"):
                self._migrate_locked(fail_after_statement)
        else:
            self._migrate_locked(fail_after_statement)

    def _migrate_locked(self, fail_after_statement: int | None) -> None:
        files, applied = self.validate()
        pending = [(index, path) for index, path in enumerate(files, start=1) if index not in applied]
        if applied and pending:
            self._backup_and_verify(max(applied))
        for index, path in pending:
            digest = _migration_digest(path)
            rebuilds_parent_tables = (
                path.name
                in {
                    "0013_source_policy_official_evidence.sql",
                    "0014_research_evaluation.sql",
                    "0015_account_snapshot_version.sql",
                    "0016_strategy_plan_model_b.sql",
                    "0022_manual_review_universe_v2.sql",
                    "0025_normalized_version_policy_scope.sql",
                }
            )
            try:
                if rebuilds_parent_tables:
                    self.connection.execute("PRAGMA foreign_keys=OFF")
                    self.connection.execute("PRAGMA legacy_alter_table=ON")
                self.connection.execute("BEGIN IMMEDIATE")
                if rebuilds_parent_tables:
                    if path.name == "0013_source_policy_official_evidence.sql":
                        self._preflight_source_policy_0013()
                    elif path.name == "0014_research_evaluation.sql":
                        self._preflight_research_evaluation_0014()
                    elif path.name == "0015_account_snapshot_version.sql":
                        self._preflight_account_snapshot_0015()
                    elif path.name == "0016_strategy_plan_model_b.sql":
                        self._preflight_strategy_plan_0016()
                    elif path.name == "0025_normalized_version_policy_scope.sql":
                        self._preflight_normalized_version_0025()
                elif path.name == "0017_manual_review_journal.sql":
                    self._preflight_manual_review_0017()
                elif path.name == "0024_trade_plan_evidence_payload.sql":
                    self._preflight_plan_evidence_0024()
                statements = self._statements(path.read_text(encoding="utf-8"))
                for statement_number, statement in enumerate(statements, start=1):
                    self.connection.execute(statement)
                    if fail_after_statement == statement_number:
                        raise PersistenceError("MIGRATION_INJECTED_FAILURE", "Injected inside migration transaction.")
                if path.name == "0016_strategy_plan_model_b.sql":
                    from .strategies import install_builtin_strategy_versions

                    install_builtin_strategy_versions(self.connection)
                if path.name == "0022_manual_review_universe_v2.sql":
                    self._migrate_manual_review_universe_0022()
                    violations = self.connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if violations:
                        raise PersistenceError(
                            "MANUAL_REVIEW_HISTORY_UNMIGRATABLE",
                            "Migration 0022 produced invalid foreign-key lineage.",
                        )
                if rebuilds_parent_tables:
                    violations = self.connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if violations:
                        raise PersistenceError(
                            (
                                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE"
                                if path.name
                                == "0013_source_policy_official_evidence.sql"
                                else (
                                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE"
                                    if path.name == "0014_research_evaluation.sql"
                                    else (
                                        "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE"
                                        if path.name
                                        == "0015_account_snapshot_version.sql"
                                        else (
                                            "NORMALIZED_VERSION_HISTORY_UNMIGRATABLE"
                                            if path.name
                                            == "0025_normalized_version_policy_scope.sql"
                                            else "STRATEGY_PLAN_HISTORY_UNMIGRATABLE"
                                        )
                                    )
                                )
                            ),
                            f"Migration {index:04d} produced invalid foreign-key lineage.",
                        )
                self.connection.execute(
                    "INSERT INTO schema_migration VALUES(?,?,?,?,?)",
                    (index, path.name, digest, datetime.now(timezone.utc).isoformat(), "platform-skeleton@1"),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            finally:
                if rebuilds_parent_tables:
                    self.connection.execute("PRAGMA legacy_alter_table=OFF")
                    self.connection.execute("PRAGMA foreign_keys=ON")

    def _migrate_manual_review_universe_0022(self) -> None:
        from trading_platform.domain.manual_review import (
            ManualPortfolioReviewItem,
            ManualReviewError,
            ReviewOutcome,
        )
        from trading_platform.identity import canonical_hash

        rows = tuple(
            self.connection.execute(
                "SELECT * FROM manual_portfolio_review_item "
                "ORDER BY review_run_id,security_id"
            )
        )
        for row in rows:
            try:
                base = ManualPortfolioReviewItem(
                    review_item_id=row["review_item_id"],
                    review_run_id=row["review_run_id"],
                    account_id=row["account_id"],
                    security_id=row["security_id"],
                    universe_member_identity=(
                        row["universe_member_identity"]
                    ),
                    universe_roles=tuple(
                        json.loads(row["universe_roles_json"])
                    ),
                    account_snapshot_version_id=(
                        row["account_snapshot_version_id"]
                    ),
                    account_snapshot_hash=row["account_snapshot_hash"],
                    estimated_state_hash=row["estimated_state_hash"],
                    active_plan_id=row["active_plan_id"],
                    plan_version_id=row["plan_version_id"],
                    plan_evaluation_id=row["plan_evaluation_id"],
                    evaluation_reason_code=(
                        row["evaluation_reason_code"]
                    ),
                    strategy_version_id=row["strategy_version_id"],
                    sleeve_graph=tuple(
                        json.loads(row["sleeve_graph_json"])
                    ),
                    data_snapshot_ids=tuple(
                        json.loads(row["data_snapshot_ids_json"])
                    ),
                    research_run_ids=tuple(
                        json.loads(row["research_run_ids_json"])
                    ),
                    evidence_ids=tuple(
                        json.loads(row["evidence_ids_json"])
                    ),
                    market_snapshot_ids=tuple(
                        json.loads(row["market_snapshot_ids_json"])
                    ),
                    hard_rule_evaluations=tuple(
                        json.loads(row["hard_rule_evaluations_json"])
                    ),
                    review_rule_routing=tuple(
                        json.loads(row["review_rule_routing_json"])
                    ),
                    conflict_resolution=json.loads(
                        row["conflict_resolution_json"]
                    ),
                    outcome=ReviewOutcome(row["outcome"]),
                    material_changes=tuple(
                        json.loads(row["material_changes_json"])
                    ),
                    unable_reasons=tuple(
                        json.loads(row["unable_reasons_json"])
                    ),
                    blocked_reasons=tuple(
                        json.loads(row["blocked_reasons_json"])
                    ),
                    decision_task_ids=tuple(
                        json.loads(row["decision_task_ids_json"])
                    ),
                    plan_impact_assessment_ids=tuple(
                        json.loads(
                            row["plan_impact_assessment_ids_json"]
                        )
                    ),
                    plan_change_proposal_ids=tuple(
                        json.loads(
                            row["plan_change_proposal_ids_json"]
                        )
                    ),
                    content_hash="",
                    created_at=row["created_at"],
                    schema_version=row["schema_version"],
                )
                identity = {
                    key: value
                    for key, value in base.__dict__.items()
                    if key != "content_hash"
                }
                migrated = ManualPortfolioReviewItem(
                    **{
                        **base.__dict__,
                        "content_hash": canonical_hash(identity),
                    }
                )
                migrated.validate()
            except (
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                ManualReviewError,
            ) as error:
                raise PersistenceError(
                    "MANUAL_REVIEW_HISTORY_UNMIGRATABLE",
                    "A legacy manual review item cannot be rewritten "
                    "to SecurityReviewItem@2.",
                ) from error
            self.connection.execute(
                "UPDATE manual_portfolio_review_item "
                "SET content_hash=? WHERE review_item_id=?",
                (migrated.content_hash, migrated.review_item_id),
            )
            self.connection.execute(
                "UPDATE manual_portfolio_review_checkpoint "
                "SET input_fingerprint=? "
                "WHERE review_run_id=? AND security_id=? "
                "AND stage='review_item'",
                (
                    migrated.content_hash,
                    migrated.review_run_id,
                    migrated.security_id,
                ),
            )
        self.connection.execute(
            "CREATE TRIGGER manual_review_item_no_update "
            "BEFORE UPDATE ON manual_portfolio_review_item "
            "BEGIN SELECT RAISE("
            "ABORT,'MANUAL_REVIEW_ITEM_IMMUTABLE'"
            "); END"
        )
        self.connection.execute(
            "CREATE TRIGGER manual_review_item_no_delete "
            "BEFORE DELETE ON manual_portfolio_review_item "
            "BEGIN SELECT RAISE("
            "ABORT,'MANUAL_REVIEW_ITEM_IMMUTABLE'"
            "); END"
        )

    def _preflight_manual_review_0017(self) -> None:
        def block(message: str) -> None:
            raise PersistenceError(
                "MANUAL_REVIEW_HISTORY_UNMIGRATABLE", message
            )

        reserved = {
            "manual_portfolio_review_run",
            "manual_portfolio_review_item",
            "manual_portfolio_review_checkpoint",
            "manual_portfolio_review_manifest",
            "decision_task",
            "decision_task_transition",
            "action_log_entry",
            "execution_record",
            "discipline_review_version",
            "plan_impact_assessment",
            "plan_change_proposal",
        }
        collision = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            f"AND name IN ({','.join('?' for _ in reserved)}) LIMIT 1",
            tuple(sorted(reserved)),
        ).fetchone()
        if collision is not None:
            block(
                "A reserved cohort-C table already exists without a "
                "migration ledger entry."
            )
        corrupt_workflow = self.connection.execute(
            "SELECT workflow_run_id FROM workflow_run "
            "WHERE workflow_run_id IS NULL OR workflow_id IS NULL "
            "OR status NOT IN "
            "('queued','running','succeeded','succeeded_with_limits',"
            "'failed','cancelled') LIMIT 1"
        ).fetchone()
        if corrupt_workflow is not None:
            block("Legacy workflow identity cannot be retained exactly.")
        corrupt_evaluation = self.connection.execute(
            "SELECT plan_evaluation_id FROM plan_evaluation "
            "WHERE plan_evaluation_id IS NULL OR plan_version_id IS NULL "
            "OR market_snapshot_id IS NULL LIMIT 1"
        ).fetchone()
        if corrupt_evaluation is not None:
            block("Legacy plan evaluation identity is incomplete.")

    def _preflight_strategy_plan_0016(self) -> None:
        from trading_platform.domain.plans import (
            CoreFloor,
            CoreSleeve,
            GridSleeve,
            PlanValidationError,
            TradePlanRule,
            validate_sleeve_contract,
            validate_sleeve_quantities,
        )
        from trading_platform.domain.rules import (
            GridConstraint,
            RuleAstV2,
            RuleClass,
            RuleContractError,
            RulePriority,
            RuleScope,
            ast_to_dict,
        )

        def block(message: str) -> None:
            raise PersistenceError(
                "STRATEGY_PLAN_HISTORY_UNMIGRATABLE", message
            )

        missing_owner = self.connection.execute(
            "SELECT p.plan_id FROM trade_plan p "
            "LEFT JOIN ("
            "SELECT v.plan_id,count(DISTINCT r.account_id) AS account_count "
            "FROM trade_plan_version v "
            "LEFT JOIN plan_account_snapshot_reference r USING(plan_version_id) "
            "GROUP BY v.plan_id"
            ") o USING(plan_id) "
            "WHERE coalesce(o.account_count,0)<>1 LIMIT 1"
        ).fetchone()
        if missing_owner is not None:
            block("A legacy plan lacks one explicit account owner.")

        inconsistent_security = self.connection.execute(
            "SELECT p.plan_id FROM trade_plan p "
            "JOIN trade_plan_version v USING(plan_id) "
            "WHERE p.security_id<>v.security_id LIMIT 1"
        ).fetchone()
        if inconsistent_security is not None:
            block("A legacy plan has inconsistent security ownership.")

        active_plan_ids = {
            row["plan_id"]
            for row in self.connection.execute(
                "SELECT plan_id FROM trade_plan "
                "WHERE lifecycle_status='active'"
            )
        }
        mapping_file = (
            self.data_root
            / "migration-inputs"
            / "0016-legacy-sleeve-mapping.json"
        )
        if mapping_file.is_file():
            raw_mapping = mapping_file.read_bytes()
            try:
                mapping = json.loads(raw_mapping)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise PersistenceError(
                    "STRATEGY_PLAN_HISTORY_UNMIGRATABLE",
                    "The legacy sleeve mapping artifact is invalid JSON.",
                ) from error
            canonical_mapping = json.dumps(
                mapping,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if canonical_mapping != raw_mapping:
                block("The legacy sleeve mapping artifact is not canonical.")
        else:
            mapping = {
                "schema_version": "LegacySleeveMapping@1",
                "approved_by": "not_required:no_active_legacy_plan",
                "approved_at": "2026-07-27T00:00:00+08:00",
                "plans": [],
            }
            raw_mapping = json.dumps(
                mapping,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        if (
            not isinstance(mapping, dict)
            or mapping.get("schema_version") != "LegacySleeveMapping@1"
            or not isinstance(mapping.get("plans"), list)
        ):
            block("The legacy sleeve mapping contract is invalid.")
        approved_by = mapping.get("approved_by")
        approved_at = mapping.get("approved_at")
        try:
            approval_instant = datetime.fromisoformat(str(approved_at))
        except ValueError as error:
            raise PersistenceError(
                "STRATEGY_PLAN_HISTORY_UNMIGRATABLE",
                "The legacy sleeve mapping lacks an approval instant.",
            ) from error
        if (
            active_plan_ids
            and (
                not isinstance(approved_by, str)
                or not approved_by.startswith("user:")
                or approval_instant.tzinfo is None
            )
        ):
            block("The legacy sleeve mapping lacks explicit user approval.")

        parsed_mappings: dict[str, tuple[str, str, str]] = {}
        converted_rules: list[tuple[str, int, str, str]] = []
        converted_versions: list[tuple[str, str, str]] = []
        converted_approvals: list[
            tuple[str, str, str, str, str, str]
        ] = []
        for item in mapping["plans"]:
            if not isinstance(item, dict):
                block("A legacy sleeve mapping entry is invalid.")
            plan_id = item.get("plan_id")
            strategy_version_id = item.get("strategy_version_id")
            sleeves = item.get("sleeves")
            rule_scopes = item.get("rule_scopes")
            if (
                not isinstance(plan_id, str)
                or plan_id in parsed_mappings
                or strategy_version_id
                not in {
                    "strategy_version_trend_hold_break_exit_1",
                    "strategy_version_core_plus_grid_1",
                }
                or not isinstance(sleeves, list)
                or not isinstance(rule_scopes, dict)
            ):
                block("A legacy sleeve mapping entry is invalid.")
            kinds = [sleeve.get("sleeve_kind") for sleeve in sleeves if isinstance(sleeve, dict)]
            if (
                len(kinds) != len(sleeves)
                or kinds.count("core") != 1
                or any(kind not in {"core", "grid"} for kind in kinds)
                or len(kinds) != len(set(kinds))
                or (
                    strategy_version_id
                    == "strategy_version_trend_hold_break_exit_1"
                    and kinds != ["core"]
                )
            ):
                block("A legacy sleeve mapping violates the strategy contract.")
            for sleeve in sleeves:
                for state_key, value_key in (
                    ("quantity_budget_state", "quantity_budget_value"),
                    ("core_floor_state", "core_floor_value"),
                    ("max_notional_state", "max_notional_value"),
                    ("max_loss_state", "max_loss_value"),
                ):
                    state = sleeve.get(state_key)
                    value = sleeve.get(value_key)
                    if state not in {"known", "unknown", "not_applicable"}:
                        block("A legacy sleeve mapping has an invalid value state.")
                    if state == "known":
                        try:
                            number = Decimal(str(value))
                        except (InvalidOperation, TypeError) as error:
                            raise PersistenceError(
                                "STRATEGY_PLAN_HISTORY_UNMIGRATABLE",
                                "A mapped sleeve value is not an exact decimal.",
                            ) from error
                        if not number.is_finite() or number < 0:
                            block("A mapped sleeve value is invalid.")
                    elif value is not None:
                        block("An unknown mapped sleeve value must remain null.")
            try:
                typed_sleeves = []
                for sleeve in sleeves:
                    sleeve_id = sleeve.get("sleeve_id")
                    if not isinstance(sleeve_id, str) or not sleeve_id:
                        block("A mapped sleeve lacks stable identity.")

                    def mapped_decimal(
                        state_key: str, value_key: str
                    ) -> Decimal | None:
                        if sleeve.get(state_key) != "known":
                            return None
                        return Decimal(str(sleeve.get(value_key)))

                    floor = CoreFloor(
                        mapped_decimal(
                            "core_floor_state", "core_floor_value"
                        )
                    )
                    common = {
                        "sleeve_id": sleeve_id,
                        "quantity_budget": mapped_decimal(
                            "quantity_budget_state",
                            "quantity_budget_value",
                        ),
                        "core_floor": floor,
                        "max_notional": mapped_decimal(
                            "max_notional_state", "max_notional_value"
                        ),
                        "max_loss": mapped_decimal(
                            "max_loss_state", "max_loss_value"
                        ),
                    }
                    if sleeve["sleeve_kind"] == "core":
                        if sleeve.get("grid_constraint") is not None:
                            block(
                                "A core sleeve cannot own a grid constraint."
                            )
                        typed_sleeves.append(CoreSleeve(**common))
                    else:
                        grid = sleeve.get("grid_constraint")
                        if not isinstance(grid, dict):
                            block(
                                "A grid sleeve lacks its explicit constraint."
                            )
                        typed_sleeves.append(
                            GridSleeve(
                                **common,
                                constraint=GridConstraint(
                                    grid_constraint_id=grid.get(
                                        "grid_constraint_id"
                                    ),
                                    lower_price=Decimal(
                                        str(grid.get("lower_price"))
                                    ),
                                    upper_price=Decimal(
                                        str(grid.get("upper_price"))
                                    ),
                                    level_count=grid.get("level_count"),
                                    quantity_per_level=Decimal(
                                        str(
                                            grid.get(
                                                "quantity_per_level"
                                            )
                                        )
                                    ),
                                    total_quantity_budget=Decimal(
                                        str(
                                            grid.get(
                                                "total_quantity_budget"
                                            )
                                        )
                                    ),
                                    price_basis=grid.get("price_basis"),
                                    trigger_mode=grid.get("trigger_mode"),
                                    cooldown_trading_sessions=grid.get(
                                        "cooldown_trading_sessions"
                                    ),
                                ),
                            )
                        )
                typed_tuple = tuple(typed_sleeves)
                validate_sleeve_contract(
                    str(strategy_version_id), typed_tuple
                )
                validate_sleeve_quantities(
                    typed_tuple, total_quantity=None
                )
                for raw_sleeve, typed_sleeve in zip(
                    sleeves, typed_tuple, strict=True
                ):
                    raw_sleeve["_migration_content_hash"] = (
                        typed_sleeve.content_hash
                    )
                    if isinstance(typed_sleeve, GridSleeve):
                        raw_sleeve["grid_constraint"][
                            "_migration_content_hash"
                        ] = typed_sleeve.constraint.content_hash
                        raw_sleeve["grid_constraint"][
                            "_migration_lot_size"
                        ] = str(typed_sleeve.constraint.lot_size)
                        raw_sleeve["grid_constraint"][
                            "_migration_levels_hash"
                        ] = typed_sleeve.constraint.generated_levels_hash
            except (
                PlanValidationError,
                RuleContractError,
                InvalidOperation,
                TypeError,
            ) as error:
                block(f"Mapped sleeve contract is invalid: {error}")
            expected_rules = {
                row["rule_id"]
                for row in self.connection.execute(
                    "SELECT rule_id FROM plan_rule WHERE plan_version_id IN ("
                    "SELECT plan_version_id FROM trade_plan_version "
                    "WHERE plan_id=?)",
                    (plan_id,),
                )
            }
            if (
                set(rule_scopes) != expected_rules
                or any(
                    scope
                    not in {
                        sleeve["sleeve_id"] for sleeve in sleeves
                    }
                    for scope in rule_scopes.values()
                )
            ):
                block("A legacy rule lacks one explicit sleeve scope.")
            sleeve_kinds = {
                sleeve["sleeve_id"]: sleeve["sleeve_kind"]
                for sleeve in sleeves
            }
            plan_rule_hashes: dict[str, list[str]] = {}
            for row in self.connection.execute(
                "SELECT r.*,c.condition_json FROM plan_rule r "
                "JOIN plan_rule_condition c "
                "USING(plan_version_id,rule_no) "
                "JOIN trade_plan_version v USING(plan_version_id) "
                "WHERE v.plan_id=? ORDER BY r.rule_no",
                (plan_id,),
            ):
                try:
                    condition = _legacy_rule_to_ast_v2(
                        json.loads(row["condition_json"])
                    )
                    sleeve_id = str(rule_scopes[row["rule_id"]])
                    rule = TradePlanRule.build(
                        rule_id=row["rule_id"],
                        rule_class=RuleClass.HARD,
                        rule_kind=row["rule_kind"],
                        priority=RulePriority.ORDINARY,
                        scope=RuleScope(sleeve_kinds[sleeve_id]),
                        sleeve_id=sleeve_id,
                        effect=row["effect"],
                        applies_to=row["applies_to"],
                        candidate_intent=None,
                        input_applicability=(
                            row["input_applicability"],
                        ),
                        condition=condition,
                    )
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                    RuleContractError,
                    PlanValidationError,
                ) as error:
                    raise PersistenceError(
                        "STRATEGY_PLAN_HISTORY_UNMIGRATABLE",
                        "An active legacy rule is not representable as "
                        "the finite AST@2 contract.",
                    ) from error
                converted_rules.append(
                    (
                        row["plan_version_id"],
                        row["rule_no"],
                        json.dumps(
                            ast_to_dict(condition),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        rule.content_hash,
                    )
                )
                plan_rule_hashes.setdefault(
                    row["plan_version_id"], []
                ).append(rule.content_hash)
            try:
                from trading_platform.domain.approvals import (
                    ActivationIntent,
                    CanonicalPlanDiff,
                    PlanConfirmationChallenge,
                    UserApprovalReceipt,
                )
                from trading_platform.domain.plans import PlanGraphSeal
                from trading_platform.identity import canonical_hash

                plan_versions = tuple(
                    self.connection.execute(
                    "SELECT plan_version_id,content_json "
                    "FROM trade_plan_version WHERE plan_id=? "
                    "ORDER BY version_no",
                    (plan_id,),
                    )
                )
                for version in plan_versions:
                    plan_version_id = version["plan_version_id"]
                    content_hash = canonical_hash(
                        json.loads(version["content_json"])
                    )
                    reference_hashes = tuple(
                        hashlib.sha256(
                            (
                                "0016-legacy-ref:"
                                f"{plan_version_id}:{row['ref_no']}:"
                                f"{row['ref_type']}:{row['ref_id']}"
                            ).encode("utf-8")
                        ).hexdigest()
                        for row in self.connection.execute(
                            "SELECT ref_no,ref_type,ref_id "
                            "FROM plan_version_reference "
                            "WHERE plan_version_id=? ORDER BY ref_no",
                            (plan_version_id,),
                        )
                    )
                    adjusted_hashes = tuple(
                        hashlib.sha256(
                            (
                                "0016-legacy-adjusted:"
                                f"{plan_version_id}:{row['rule_id']}:"
                                f"{row['condition_path']}"
                            ).encode("utf-8")
                        ).hexdigest()
                        for row in self.connection.execute(
                            "SELECT rule_id,condition_path "
                            "FROM plan_adjusted_price_evidence "
                            "WHERE plan_version_id=? "
                            "ORDER BY rule_id,condition_path",
                            (plan_version_id,),
                        )
                    )
                    seal = PlanGraphSeal.build(
                        version_content_hash=content_hash,
                        sleeve_hashes=tuple(
                            sleeve.content_hash
                            for sleeve in typed_tuple
                        ),
                        rule_hashes=tuple(
                            plan_rule_hashes.get(plan_version_id, ())
                        ),
                        evidence_hashes=(
                            reference_hashes + adjusted_hashes
                        ),
                    )
                    converted_versions.append(
                        (
                            plan_version_id,
                            content_hash,
                            seal.graph_seal_hash,
                        )
                    )
                open_activation = self.connection.execute(
                    "SELECT plan_version_id FROM plan_activation "
                    "WHERE plan_id=? AND ended_at IS NULL",
                    (plan_id,),
                ).fetchone()
                latest_version_id = (
                    open_activation["plan_version_id"]
                    if open_activation is not None
                    else plan_versions[-1]["plan_version_id"]
                )
                _, latest_content_hash, latest_graph_hash = next(
                    item
                    for item in converted_versions
                    if item[0] == latest_version_id
                )
                diff = CanonicalPlanDiff.build(
                    based_on_graph_seal_hash=None,
                    proposed_graph_seal_hash=latest_graph_hash,
                    changed_components=(
                        "evidence",
                        "rules",
                        "sleeves",
                        "version",
                    ),
                )
                suffix = hashlib.sha256(
                    str(plan_id).encode("utf-8")
                ).hexdigest()[:24]
                challenge_id = (
                    f"plan_confirmation_challenge_migration_{suffix}"
                )
                receipt_id = (
                    f"user_approval_receipt_migration_{suffix}"
                )
                challenge_prototype = PlanConfirmationChallenge(
                    challenge_id=challenge_id,
                    plan_id=str(plan_id),
                    draft_id=(
                        f"trade_plan_draft_migration_{suffix}"
                    ),
                    expected_revision=1,
                    expected_draft_hash=latest_content_hash,
                    expected_graph_seal_hash=latest_graph_hash,
                    canonical_diff=diff,
                    activation_intent=(
                        ActivationIntent.CONFIRM_AND_ACTIVATE
                    ),
                    decision_actor=str(approved_by),
                    interaction_channel="cli",
                    transport_actor="adapter:migration-0016",
                    issued_at=str(approved_at),
                    expires_at=None,
                    status="consumed",
                    content_hash="",
                )
                challenge_hash = canonical_hash(
                    challenge_prototype.identity_payload()
                )
                receipt_prototype = UserApprovalReceipt(
                    approval_receipt_id=receipt_id,
                    challenge_id=challenge_id,
                    plan_id=str(plan_id),
                    draft_id=(
                        f"trade_plan_draft_migration_{suffix}"
                    ),
                    approved_revision=1,
                    approved_draft_hash=latest_content_hash,
                    approved_graph_seal_hash=latest_graph_hash,
                    approved_diff_hash=diff.content_hash,
                    activation_intent=(
                        ActivationIntent.CONFIRM_AND_ACTIVATE
                    ),
                    decision_actor=str(approved_by),
                    interaction_channel="cli",
                    transport_actor="adapter:migration-0016",
                    command_invocation_id=(
                        f"migration-0016:approve:{plan_id}"
                    ),
                    approved_at=str(approved_at),
                    content_hash="",
                )
                receipt_hash = canonical_hash(
                    receipt_prototype.identity_payload()
                )
                converted_approvals.append(
                    (
                        str(plan_id),
                        latest_version_id,
                        json.dumps(
                            {
                                "schema_version": diff.schema_version,
                                "based_on_graph_seal_hash": (
                                    diff.based_on_graph_seal_hash
                                ),
                                "proposed_graph_seal_hash": (
                                    diff.proposed_graph_seal_hash
                                ),
                                "changed_components": (
                                    diff.changed_components
                                ),
                                "content_hash": diff.content_hash,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        diff.content_hash,
                        challenge_hash,
                        receipt_hash,
                    )
                )
            except (json.JSONDecodeError, TypeError) as error:
                raise PersistenceError(
                    "STRATEGY_PLAN_HISTORY_UNMIGRATABLE",
                    "An active legacy plan does not contain canonical "
                    "JSON content.",
                ) from error
            parsed_mappings[plan_id] = (
                str(strategy_version_id),
                json.dumps(
                    sleeves,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    rule_scopes,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        if set(parsed_mappings) != active_plan_ids:
            block(
                "An active legacy plan lacks an explicit user-approved "
                "LegacySleeveMapping@1 artifact."
            )

        duplicate_active = self.connection.execute(
            "SELECT r.account_id,p.security_id,count(*) "
            "FROM trade_plan p JOIN ("
            "SELECT v.plan_id,min(a.account_id) AS account_id "
            "FROM trade_plan_version v "
            "JOIN plan_account_snapshot_reference a USING(plan_version_id) "
            "GROUP BY v.plan_id"
            ") r USING(plan_id) "
            "WHERE p.lifecycle_status='active' "
            "GROUP BY r.account_id,p.security_id HAVING count(*)>1 LIMIT 1"
        ).fetchone()
        if duplicate_active is not None:
            block("Multiple active legacy plans share one account/security owner.")

        artifact_hash = hashlib.sha256(raw_mapping).hexdigest()
        self.connection.execute(
            "CREATE TEMP TABLE migration_0016_mapping_meta("
            "artifact_hash TEXT NOT NULL,approved_by TEXT NOT NULL,"
            "approved_at TEXT NOT NULL)"
        )
        self.connection.execute(
            "INSERT INTO migration_0016_mapping_meta VALUES(?,?,?)",
            (artifact_hash, str(approved_by), str(approved_at)),
        )
        self.connection.execute(
            "CREATE TEMP TABLE migration_0016_legacy_mapping("
            "plan_id TEXT PRIMARY KEY,strategy_version_id TEXT NOT NULL,"
            "sleeves_json TEXT NOT NULL,rule_scopes_json TEXT NOT NULL)"
        )
        self.connection.executemany(
            "INSERT INTO migration_0016_legacy_mapping VALUES(?,?,?,?)",
            (
                (plan_id, strategy, sleeves, scopes)
                for plan_id, (strategy, sleeves, scopes)
                in parsed_mappings.items()
            ),
        )
        self.connection.execute(
            "CREATE TEMP TABLE migration_0016_rule_conversion("
            "plan_version_id TEXT NOT NULL,rule_no INTEGER NOT NULL,"
            "condition_json TEXT NOT NULL,content_hash TEXT NOT NULL,"
            "PRIMARY KEY(plan_version_id,rule_no))"
        )
        self.connection.executemany(
            "INSERT INTO migration_0016_rule_conversion VALUES(?,?,?,?)",
            converted_rules,
        )
        self.connection.execute(
            "CREATE TEMP TABLE migration_0016_version_conversion("
            "plan_version_id TEXT PRIMARY KEY,content_hash TEXT NOT NULL,"
            "graph_seal_hash TEXT NOT NULL)"
        )
        self.connection.executemany(
            "INSERT INTO migration_0016_version_conversion VALUES(?,?,?)",
            converted_versions,
        )
        self.connection.execute(
            "CREATE TEMP TABLE migration_0016_approval_conversion("
            "plan_id TEXT PRIMARY KEY,"
            "target_plan_version_id TEXT NOT NULL,"
            "diff_json TEXT NOT NULL,"
            "diff_hash TEXT NOT NULL,challenge_hash TEXT NOT NULL,"
            "receipt_hash TEXT NOT NULL)"
        )
        self.connection.executemany(
            "INSERT INTO migration_0016_approval_conversion "
            "VALUES(?,?,?,?,?,?)",
            converted_approvals,
        )

        inconsistent_activation = self.connection.execute(
            "SELECT a.activation_id FROM plan_activation a "
            "JOIN trade_plan p USING(plan_id) "
            "WHERE a.ended_at IS NULL AND p.lifecycle_status<>'active' LIMIT 1"
        ).fetchone()
        if inconsistent_activation is not None:
            block("Legacy lifecycle and open activation disagree.")

        legacy_draft = self.connection.execute(
            "SELECT draft_id FROM trade_plan_draft LIMIT 1"
        ).fetchone()
        if legacy_draft is not None:
            block(
                "A legacy mutable draft cannot be classified as immutable "
                "Model B history."
            )

        incomplete_rule = self.connection.execute(
            "SELECT r.rule_id FROM plan_rule r "
            "LEFT JOIN plan_rule_condition c "
            "USING(plan_version_id,rule_no) "
            "WHERE c.plan_version_id IS NULL LIMIT 1"
        ).fetchone()
        if incomplete_rule is not None:
            block("A legacy plan rule lacks its sealed condition.")

        invalid_version = self.connection.execute(
            "SELECT plan_version_id FROM trade_plan_version "
            "WHERE length(trim(content_hash))=0 OR length(trim(content_json))=0 "
            "LIMIT 1"
        ).fetchone()
        if invalid_version is not None:
            block("A legacy plan version lacks preserved content identity.")

    def _preflight_account_snapshot_0015(self) -> None:
        def block(message: str) -> None:
            raise PersistenceError(
                "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE", message
            )

        invalid_account = self.connection.execute(
            "SELECT p.portfolio_snapshot_id FROM portfolio_snapshot p "
            "LEFT JOIN account a USING(account_id) "
            "WHERE a.account_id IS NULL OR length(trim(a.account_id))=0 "
            "OR length(trim(a.base_currency))<>3 LIMIT 1"
        ).fetchone()
        if invalid_account is not None:
            block("A legacy opening graph lacks stable account identity or currency.")

        missing_graph = self.connection.execute(
            "SELECT p.portfolio_snapshot_id FROM portfolio_snapshot p "
            "LEFT JOIN account_import_batch b "
            "ON b.account_id=p.account_id "
            "AND b.source_snapshot_hash=p.source_snapshot_hash "
            "LEFT JOIN account_cash_opening c USING(account_id) "
            "WHERE b.import_batch_id IS NULL OR c.account_id IS NULL LIMIT 1"
        ).fetchone()
        if missing_graph is not None:
            block("A legacy opening graph is incomplete.")

        legacy_graphs = tuple(
            self.connection.execute(
                "SELECT p.portfolio_snapshot_id,p.account_id,p.as_of_date,"
                "p.source_snapshot_hash,b.confirmed_as_of,b.evidence_json "
                "FROM portfolio_snapshot p "
                "JOIN account_import_batch b "
                "ON b.account_id=p.account_id "
                "AND b.source_snapshot_hash=p.source_snapshot_hash"
            )
        )
        for row in legacy_graphs:
            try:
                evidence = json.loads(row["evidence_json"])
                confirmation = evidence["confirmation"]
                invocation_id = confirmation["invocation_id"]
                confirmed_at = confirmation["confirmed_at"]
                confirmed_as_of = confirmation["confirmed_as_of"]
                confirmed_instant = datetime.fromisoformat(confirmed_at)
                datetime.fromisoformat(f"{row['as_of_date']}T00:00:00")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise PersistenceError(
                    "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE",
                    "A legacy opening graph lacks explicit confirmation provenance.",
                ) from error
            if (
                not invocation_id
                or confirmed_instant.tzinfo is None
                or confirmed_as_of != row["as_of_date"]
                or row["confirmed_as_of"] != row["as_of_date"]
            ):
                block(
                    "A legacy opening graph has inconsistent confirmation provenance."
                )

        positions = tuple(
            self.connection.execute(
                "SELECT p.position_id,p.account_id,p.security_id,"
                "p.quantity_decimal,p.available_decimal,p.frozen_decimal "
                "FROM account_position p "
                "LEFT JOIN security s USING(security_id)"
                " WHERE s.security_id IS NULL OR length(trim(p.security_id))=0 "
                "OR NOT EXISTS(SELECT 1 FROM portfolio_snapshot ps "
                "WHERE ps.account_id=p.account_id)"
            )
        )
        if positions:
            block("A legacy position lacks stable snapshot or security identity.")
        quantities = tuple(
            self.connection.execute(
                "SELECT position_id,quantity_decimal,available_decimal,"
                "frozen_decimal FROM account_position"
            )
        )
        for row in quantities:
            try:
                total = Decimal(row["quantity_decimal"])
                available = Decimal(row["available_decimal"])
                frozen = Decimal(row["frozen_decimal"])
            except (InvalidOperation, TypeError) as error:
                raise PersistenceError(
                    "ACCOUNT_SNAPSHOT_HISTORY_UNMIGRATABLE",
                    "A legacy position quantity is not an exact decimal.",
                ) from error
            if (
                not all(value.is_finite() and value >= 0 for value in (total, available, frozen))
                or available + frozen != total
            ):
                block("A legacy position has an invalid quantity relation.")

        history_reference = self.connection.execute(
            "SELECT plan_version_id FROM plan_account_snapshot_reference "
            "WHERE snapshot_type<>'PortfolioSnapshot' LIMIT 1"
        ).fetchone()
        if history_reference is not None:
            block(
                "A legacy plan references broker history as current account truth."
            )

    def _preflight_source_policy_0013(self) -> None:
        placeholder_policy = self.connection.execute(
            """
            SELECT data_snapshot_id
            FROM data_snapshot
            WHERE query_policy_version NOT LIKE 'query_policy_%'
               OR source_policy_version NOT LIKE 'source_policy_%'
            LIMIT 1
            """
        ).fetchone()
        if placeholder_policy is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy snapshot contains a placeholder policy identity.",
            )

        empty_snapshot = self.connection.execute(
            """
            SELECT s.data_snapshot_id
            FROM data_snapshot s
            LEFT JOIN data_snapshot_member m
              ON m.data_snapshot_id=s.data_snapshot_id
            GROUP BY s.data_snapshot_id
            HAVING count(m.normalized_version_id)=0
            LIMIT 1
            """
        ).fetchone()
        if empty_snapshot is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy data snapshot has no member attempts from which to prove policy identity.",
            )

        ambiguous = self.connection.execute(
            """
            SELECT v.source_attempt_id
            FROM normalized_version v
            JOIN data_snapshot_member m
              ON m.normalized_version_id=v.normalized_version_id
            JOIN data_snapshot s ON s.data_snapshot_id=m.data_snapshot_id
            GROUP BY v.source_attempt_id
            HAVING count(
              DISTINCT s.query_policy_version || char(0)
                || s.source_policy_version
            ) > 1
            LIMIT 1
            """
        ).fetchone()
        if ambiguous is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy provider attempt belongs to snapshots with conflicting policy identities.",
            )

        orphan_attempt = self.connection.execute(
            """
            SELECT p.attempt_id
            FROM provider_attempt p
            LEFT JOIN normalized_version v
              ON v.source_attempt_id=p.attempt_id
            LEFT JOIN data_snapshot_member m
              ON m.normalized_version_id=v.normalized_version_id
            WHERE m.data_snapshot_id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if orphan_attempt is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy provider attempt has no snapshot policy identity.",
            )

        missing_rights = self.connection.execute(
            """
            SELECT p.attempt_id
            FROM provider_attempt p
            LEFT JOIN fixture_rights_profile f
              ON f.fixture_member_id=p.provider_id || ':' || p.dataset
             AND f.source_identity=p.source_identity
            WHERE p.source_authority='fixture'
              AND f.fixture_member_id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if missing_rights is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy fixture provider attempt has no provable rights profile.",
            )

        unproved_source_rights = self.connection.execute(
            """
            SELECT attempt_id
            FROM provider_attempt
            WHERE source_authority<>'fixture'
            LIMIT 1
            """
        ).fetchone()
        if unproved_source_rights is not None:
            raise PersistenceError(
                "SOURCE_POLICY_IDENTITY_UNMIGRATABLE",
                "A legacy non-fixture provider attempt has no persisted rights evidence.",
            )

    def _preflight_normalized_version_0025(self) -> None:
        duplicate = self.connection.execute(
            """
            SELECT v.normalized_record_id,v.content_hash,a.source_policy_identity
            FROM normalized_version v
            JOIN provider_attempt a ON a.attempt_id=v.source_attempt_id
            GROUP BY v.normalized_record_id,v.content_hash,a.source_policy_identity
            HAVING count(*)>1
            LIMIT 1
            """
        ).fetchone()
        if duplicate is not None:
            raise PersistenceError(
                "NORMALIZED_VERSION_HISTORY_UNMIGRATABLE",
                "Duplicate (record, content, policy) normalized versions exist.",
            )

    def _preflight_research_evaluation_0014(self) -> None:
        from .migrations.research_evaluation_0014 import (
            decode_request_v1_for_audit,
        )

        nonterminal = self.connection.execute(
            "SELECT workflow_run_id FROM workflow_run "
            "WHERE workflow_id='research-workflow' "
            "AND status IN ('queued','running') LIMIT 1"
        ).fetchone()
        if nonterminal is not None:
            raise PersistenceError(
                "MIGRATION_WORKFLOW_NOT_TERMINAL",
                "A nonterminal legacy research workflow blocks migration 0014.",
            )
        legacy_requests = tuple(
            self.connection.execute(
                "SELECT w.workflow_run_id,r.request_hash,a.object_sha256,"
                "o.size_bytes,o.relative_path "
                "FROM workflow_run w "
                "JOIN workflow_run_request r USING(workflow_run_id) "
                "JOIN artifact a ON a.artifact_id=r.request_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256 "
                "WHERE w.workflow_id='research-workflow' "
                "AND r.request_schema_version='ResearchWorkflowRequest@1'"
            )
        )
        for row in legacy_requests:
            path = (self.data_root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.data_root.resolve())
                payload = path.read_bytes()
                audit = decode_request_v1_for_audit(payload)
            except (OSError, ValueError) as error:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy Request@1 audit identity is unavailable.",
                ) from error
            digest = hashlib.sha256(payload).hexdigest()
            if (
                len(payload) != row["size_bytes"]
                or digest != row["object_sha256"]
                or digest != row["request_hash"]
            ):
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy Request@1 failed identity verification.",
                )
            projection = self.connection.execute(
                "SELECT security_id FROM research_input_projection "
                "WHERE research_projection_id=?",
                (audit.research_projection_id,),
            ).fetchone()
            if projection is None or projection["security_id"] != audit.security_id:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy Request@1 projection identity does not match history.",
                )
        ambiguous = self.connection.execute(
            "SELECT research_projection_id FROM research_input_projection "
            "GROUP BY projection_hash HAVING count(*)<>1 LIMIT 1"
        ).fetchone()
        if ambiguous is not None:
            raise PersistenceError(
                "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                "Legacy projection identity is not unique.",
            )
        missing_artifact = self.connection.execute(
            "SELECT p.research_projection_id FROM research_input_projection p "
            "LEFT JOIN artifact a ON a.artifact_id=p.projection_artifact_id "
            "LEFT JOIN object_blob o ON o.sha256=a.object_sha256 "
            "WHERE a.artifact_id IS NULL OR o.sha256 IS NULL LIMIT 1"
        ).fetchone()
        if missing_artifact is not None:
            raise PersistenceError(
                "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                "Legacy projection audit artifact is missing.",
            )
        projection_artifacts = tuple(
            self.connection.execute(
                "SELECT p.research_projection_id,p.projection_hash,"
                "a.object_sha256,o.size_bytes,o.relative_path "
                "FROM research_input_projection p "
                "JOIN artifact a ON a.artifact_id=p.projection_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256"
            )
        )
        for row in projection_artifacts:
            path = (self.data_root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.data_root.resolve())
                payload = path.read_bytes()
            except (OSError, ValueError) as error:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy projection audit object is unavailable.",
                ) from error
            digest = hashlib.sha256(payload).hexdigest()
            if (
                len(payload) != row["size_bytes"]
                or digest != row["object_sha256"]
                or digest != row["projection_hash"]
            ):
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy projection audit object failed identity verification.",
                )
        research_artifacts = tuple(
            self.connection.execute(
                "SELECT r.research_run_id,r.engine_schema_version,"
                "a.object_sha256,o.size_bytes,o.relative_path "
                "FROM research_run_record r "
                "JOIN artifact a "
                "ON a.artifact_id=r.canonical_json_artifact_id "
                "JOIN object_blob o ON o.sha256=a.object_sha256"
            )
        )
        for row in research_artifacts:
            path = (self.data_root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.data_root.resolve())
                payload = path.read_bytes()
                decoded = json.loads(payload)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy research artifact is missing or corrupt.",
                ) from error
            if (
                len(payload) != row["size_bytes"]
                or hashlib.sha256(payload).hexdigest()
                != row["object_sha256"]
                or not isinstance(decoded, dict)
                or decoded.get("run_id") != row["research_run_id"]
                or decoded.get("schema_version")
                != row["engine_schema_version"]
            ):
                raise PersistenceError(
                    "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                    "Legacy research artifact failed identity verification.",
                )
        incomplete_view = self.connection.execute(
            "SELECT w.workflow_run_id FROM workflow_run w "
            "LEFT JOIN workflow_run_ref r "
            "ON r.workflow_run_id=w.workflow_run_id "
            "AND r.ref_role='decision_view_manifest' "
            "LEFT JOIN artifact_manifest f "
            "ON f.artifact_manifest_id=r.ref_id "
            "WHERE w.workflow_id='research-workflow' "
            "AND w.status IN ('succeeded','succeeded_with_limits') "
            "GROUP BY w.workflow_run_id "
            "HAVING count(f.artifact_manifest_id)<>1 "
            "OR min(f.manifest_role)<>'workflow_decision_view@1' "
            "OR min(f.member_count)<>2 LIMIT 1"
        ).fetchone()
        if incomplete_view is not None:
            raise PersistenceError(
                "RESEARCH_EVALUATION_HISTORY_UNMIGRATABLE",
                "Legacy successful workflow lacks one complete decision view.",
            )


    def _preflight_plan_evidence_0024(self) -> None:
        from trading_platform.identity import canonical_hash

        rows = tuple(
            self.connection.execute(
                "SELECT evidence.*,version.legacy_read_only,"
                "draft.proposed_graph_json "
                "FROM trade_plan_evidence_reference evidence "
                "JOIN trade_plan_version version USING(plan_version_id) "
                "LEFT JOIN user_approval_receipt receipt "
                "ON receipt.user_approval_receipt_id="
                "version.user_approval_receipt_id "
                "LEFT JOIN trade_plan_draft draft "
                "ON draft.draft_id=receipt.draft_id "
                "ORDER BY evidence.plan_version_id,evidence.ref_order"
            )
        )
        identities: dict[str, set[str]] = {}
        for row in rows:
            if row["legacy_read_only"]:
                continue
            try:
                graph = json.loads(row["proposed_graph_json"])
                version = graph["version"]
                references = graph["evidence_references"]
                reference = references[row["ref_order"]]
                identity = {
                    key: value
                    for key, value in reference.items()
                    if key != "content_hash"
                }
                plan_identities = identities.setdefault(
                    row["plan_version_id"], set()
                )
                if (
                    not isinstance(reference, dict)
                    or version["plan_version_id"]
                    != row["plan_version_id"]
                    or reference["ref_type"] != row["ref_type"]
                    or reference["ref_id"] != row["ref_id"]
                    or reference["resolution_status"]
                    != row["resolution_status"]
                    or reference["content_hash"] != row["content_hash"]
                    or canonical_hash(identity) != row["content_hash"]
                    or reference["ref_id"] in plan_identities
                ):
                    raise ValueError("evidence reference mismatch")
                plan_identities.add(reference["ref_id"])
            except (
                IndexError,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as error:
                raise PersistenceError(
                    "PLAN_EVIDENCE_HISTORY_UNMIGRATABLE",
                    "A confirmed plan evidence reference cannot be "
                    "reconstructed from its approved draft.",
                ) from error


    @staticmethod
    def _statements(script: str) -> tuple[str, ...]:
        statements: list[str] = []
        buffer = ""
        for character in script:
            buffer += character
            if character == ";" and sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                if statement:
                    statements.append(statement)
                buffer = ""
        if buffer.strip():
            if sqlite3.complete_statement(buffer + ";"):
                statements.append(buffer.strip())
            else:
                raise PersistenceError("MIGRATION_SQL_INCOMPLETE", "Migration contains an incomplete SQL statement.")
        return tuple(statements)

    def _backup_and_verify(self, version: int) -> Path:
        final = self.data_root / f"migration-backup-v{version:04d}.sqlite3"
        if final.exists():
            existing = sqlite3.connect(final)
            try:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise PersistenceError("MIGRATION_BACKUP_INVALID", "Existing migration backup failed integrity verification.")
                backed_up_version = existing.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
                if backed_up_version != version:
                    raise PersistenceError("MIGRATION_BACKUP_INVALID", "Existing migration backup has the wrong schema version.")
            except sqlite3.DatabaseError as error:
                raise PersistenceError("MIGRATION_BACKUP_INVALID", "Existing migration backup is unreadable.") from error
            finally:
                existing.close()
            return final
        descriptor, temp_name = tempfile.mkstemp(prefix=".migration-backup-", suffix=".sqlite3", dir=self.data_root)
        os.close(descriptor)
        temp = Path(temp_name)
        target = sqlite3.connect(temp)
        try:
            self.connection.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PersistenceError("MIGRATION_BACKUP_INVALID", "Migration backup failed integrity verification.")
        finally:
            target.close()
        os.replace(temp, final)
        return final
