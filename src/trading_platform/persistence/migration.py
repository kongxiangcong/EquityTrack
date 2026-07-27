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
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
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
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rebuilds_parent_tables = (
                path.name
                in {
                    "0013_source_policy_official_evidence.sql",
                    "0014_research_evaluation.sql",
                    "0015_account_snapshot_version.sql",
                    "0016_strategy_plan_model_b.sql",
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
                    else:
                        self._preflight_strategy_plan_0016()
                statements = self._statements(path.read_text(encoding="utf-8"))
                for statement_number, statement in enumerate(statements, start=1):
                    self.connection.execute(statement)
                    if fail_after_statement == statement_number:
                        raise PersistenceError("MIGRATION_INJECTED_FAILURE", "Injected inside migration transaction.")
                if path.name == "0016_strategy_plan_model_b.sql":
                    from .strategies import install_builtin_strategy_versions

                    install_builtin_strategy_versions(self.connection)
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
                                        else "STRATEGY_PLAN_HISTORY_UNMIGRATABLE"
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

    def _preflight_strategy_plan_0016(self) -> None:
        from trading_platform.domain.plans import (
            CoreFloor,
            CoreSleeve,
            GridConstraint,
            GridSleeve,
            PlanValidationError,
            validate_sleeve_contract,
            validate_sleeve_quantities,
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
            except (
                PlanValidationError,
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
                or any(scope not in kinds for scope in rule_scopes.values())
            ):
                block("A legacy rule lacks one explicit sleeve scope.")
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
