from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from trading_platform.domain.strategies import (
    StrategyContractError,
    StrategyDefinition,
    StrategyParameterContract,
    StrategyVersion,
    builtin_strategy_versions,
)
from trading_platform.identity import canonical_hash

from .locking import PersistenceError


class SQLiteStrategyRepository:
    """Owns immutable SQLite-to-domain conversion for the strategy registry."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def all_versions(self) -> tuple[StrategyVersion, ...]:
        rows = tuple(
            self._connection.execute(
                "SELECT v.*,d.display_name,d.purpose,d.market_scope,"
                "d.authoring_mode FROM strategy_version v "
                "JOIN strategy_definition d USING(strategy_id) "
                "ORDER BY v.strategy_key,v.version_no"
            )
        )
        versions = tuple(self._load(row) for row in rows)
        try:
            for version in versions:
                version.validate_integrity()
        except StrategyContractError as error:
            raise PersistenceError(
                "STRATEGY_REGISTRY_CORRUPT",
                "A persisted strategy version failed its immutable hash.",
            ) from error
        return versions

    def _load(self, row: sqlite3.Row) -> StrategyVersion:
        contracts = tuple(
            StrategyParameterContract(
                parameter_key=item["parameter_key"],
                value_type=item["value_type"],
                required=bool(item["required"]),
                enum_values=tuple(json.loads(item["enum_values_json"])),
                minimum=item["minimum_value"],
                maximum=item["maximum_value"],
                item_type=item["item_type"],
                unknown_policy=item["unknown_policy"],
            )
            for item in self._connection.execute(
                "SELECT * FROM strategy_parameter_contract "
                "WHERE strategy_version_id=? ORDER BY parameter_order",
                (row["strategy_version_id"],),
            )
        )
        return StrategyVersion(
            strategy_definition=StrategyDefinition(
                strategy_id=row["strategy_id"],
                strategy_key=row["strategy_key"],
                display_name=row["display_name"],
                purpose=row["purpose"],
                market_scope=row["market_scope"],
                authoring_mode=row["authoring_mode"],
            ),
            strategy_version_id=row["strategy_version_id"],
            version_no=row["version_no"],
            status=row["status"],
            sleeve_contract=tuple(
                json.loads(row["sleeve_contract_json"])
            ),
            parameter_contracts=contracts,
            rule_templates=tuple(json.loads(row["rule_templates_json"])),
            conflict_policy_version=row["conflict_policy_version"],
            ast_version=row["ast_version"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            schema_version=row["schema_version"],
            publicly_selectable=bool(row["publicly_selectable"]),
        )


def install_builtin_strategy_versions(connection: sqlite3.Connection) -> None:
    """Install or verify the exact built-ins inside the caller's transaction."""
    for version in builtin_strategy_versions():
        definition = version.strategy_definition
        definition_values = (
            definition.strategy_id,
            definition.strategy_key,
            definition.display_name,
            definition.purpose,
            definition.market_scope,
            definition.authoring_mode,
            version.created_at,
        )
        _insert_or_verify(
            connection,
            "strategy_definition",
            "strategy_id",
            definition.strategy_id,
            (
                "INSERT INTO strategy_definition VALUES(?,?,?,?,?,?,?)"
            ),
            definition_values,
        )
        version_values = (
            version.strategy_version_id,
            definition.strategy_id,
            version.strategy_key,
            version.version_no,
            version.schema_version,
            version.status,
            json.dumps(
                version.sleeve_contract,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            json.dumps(
                version.rule_templates,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            version.conflict_policy_version,
            version.ast_version,
            version.content_hash,
            version.created_at,
            int(version.publicly_selectable),
        )
        _insert_or_verify(
            connection,
            "strategy_version",
            "strategy_version_id",
            version.strategy_version_id,
            "INSERT INTO strategy_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            version_values,
        )
        for position, contract in enumerate(version.parameter_contracts):
            values = (
                version.strategy_version_id,
                position,
                contract.parameter_key,
                contract.value_type,
                int(contract.required),
                json.dumps(
                    contract.enum_values,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                contract.minimum,
                contract.maximum,
                contract.item_type,
                contract.unknown_policy,
                canonical_hash(asdict(contract)),
            )
            _insert_or_verify(
                connection,
                "strategy_parameter_contract",
                "strategy_version_id=? AND parameter_order",
                (version.strategy_version_id, position),
                "INSERT INTO strategy_parameter_contract "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )


def _insert_or_verify(
    connection: sqlite3.Connection,
    table: str,
    identity_expression: str,
    identity_value: object,
    statement: str,
    values: tuple[object, ...],
) -> None:
    if isinstance(identity_value, tuple):
        clause = identity_expression + "=?"
        parameters = identity_value
    else:
        clause = identity_expression + "=?"
        parameters = (identity_value,)
    row = connection.execute(
        f"SELECT * FROM {table} WHERE {clause}", parameters
    ).fetchone()
    if row is None:
        try:
            connection.execute(statement, values)
        except sqlite3.IntegrityError as error:
            raise PersistenceError(
                "STRATEGY_REGISTRY_INSTALL_FAILED",
                "Built-in strategy registry installation violated storage.",
            ) from error
        return
    if tuple(row) != values:
        raise PersistenceError(
            "STRATEGY_REGISTRY_HASH_DRIFT",
            "A built-in strategy identity already has different content.",
        )


__all__ = [
    "SQLiteStrategyRepository",
    "install_builtin_strategy_versions",
]
