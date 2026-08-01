from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import sqlite3

from trading_platform.application.risk_policies import (
    ConfirmPortfolioRiskPolicy,
    GetPortfolioRiskPolicy,
)
from trading_platform.domain.risk_policies import (
    PortfolioRiskLimits,
    PortfolioRiskPolicyContent,
    PortfolioRiskPolicyError,
    PortfolioRiskPolicyService,
    PortfolioRiskPolicyVersion,
)
from trading_platform.identity import canonical_hash

from .locking import DataRootWriterLock


_COMMAND_NAME = "portfolio_risk_policy.confirm@1"


class SQLitePortfolioRiskPolicyRepository:
    """Owns atomic policy versioning, replay, and SQLite conversion."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        writer_lock: DataRootWriterLock,
    ) -> None:
        self._connection = connection
        self._writer_lock = writer_lock
        self._service = PortfolioRiskPolicyService()

    def confirm(
        self,
        command: ConfirmPortfolioRiskPolicy,
        content: PortfolioRiskPolicyContent,
    ) -> PortfolioRiskPolicyVersion:
        request_hash = canonical_hash(command)
        replay = self._receipt(command.invocation_id, request_hash)
        if replay is not None:
            return self._exact(replay["revision_or_version_id"])

        with self._writer_lock.acquire(
            f"portfolio-risk-policy:{content.account_id}"
        ):
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                replay = self._receipt(
                    command.invocation_id,
                    request_hash,
                )
                if replay is not None:
                    self._connection.rollback()
                    return self._exact(
                        replay["revision_or_version_id"]
                    )
                self._assert_account(content)
                prior = self._latest(content.account_id)
                version = self._service.create_version(
                    content,
                    version_no=(
                        1 if prior is None else prior.version_no + 1
                    ),
                    previous_version_id=(
                        None
                        if prior is None
                        else prior.portfolio_risk_policy_version_id
                    ),
                    confirmed_by=f"user:{command.decision_actor_id}",
                    confirmed_at=datetime.now(timezone.utc).isoformat(),
                )
                self._insert(version, command.invocation_id)
                self._insert_event(version)
                self._insert_receipt(
                    command=command,
                    request_hash=request_hash,
                    version=version,
                )
                self._connection.commit()
                return version
            except Exception:
                self._connection.rollback()
                raise

    def get(
        self,
        query: GetPortfolioRiskPolicy,
    ) -> PortfolioRiskPolicyVersion:
        if query.portfolio_risk_policy_version_id is not None:
            return self._exact(
                query.portfolio_risk_policy_version_id
            )
        assert query.account_id is not None
        version = self._latest(query.account_id)
        if version is None:
            raise PortfolioRiskPolicyError("RISK_POLICY_NOT_FOUND")
        return version

    def _assert_account(
        self,
        content: PortfolioRiskPolicyContent,
    ) -> None:
        row = self._connection.execute(
            "SELECT base_currency FROM account WHERE account_id=?",
            (content.account_id,),
        ).fetchone()
        if row is None:
            raise PortfolioRiskPolicyError("RISK_POLICY_ACCOUNT_NOT_FOUND")
        if row["base_currency"] != content.currency:
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_ACCOUNT_CURRENCY_MISMATCH"
            )

    def _insert(
        self,
        version: PortfolioRiskPolicyVersion,
        invocation_id: str,
    ) -> None:
        limits = version.limits
        render = self._service.render_decimal
        self._connection.execute(
            "INSERT INTO portfolio_risk_policy_version VALUES("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version.portfolio_risk_policy_version_id,
                version.account_id,
                version.version_no,
                version.schema_version,
                version.currency,
                version.previous_portfolio_risk_policy_version_id,
                render(self._known(limits.single_security_exposure)),
                render(self._known(limits.industry_exposure)),
                render(self._known(limits.gross_exposure)),
                render(self._known(limits.minimum_cash)),
                render(self._known(limits.single_plan_loss)),
                render(
                    self._known(limits.aggregate_active_plan_loss)
                ),
                render(self._known(limits.drawdown_review)),
                render(self._known(limits.drawdown_freeze)),
                render(self._known(limits.plan_daily_liquidity)),
                render(
                    self._known(limits.position_daily_liquidity)
                ),
                version.confirmed_by,
                version.confirmed_at,
                version.content_hash,
                version.identity_hash,
                invocation_id,
            ),
        )

    def _insert_event(
        self,
        version: PortfolioRiskPolicyVersion,
    ) -> None:
        payload = {
            "account_id": version.account_id,
            "portfolio_risk_policy_version_id": (
                version.portfolio_risk_policy_version_id
            ),
            "version_no": version.version_no,
            "content_hash": version.content_hash,
        }
        event_hash = canonical_hash(payload)
        self._connection.execute(
            "INSERT INTO application_event VALUES(?,?,?,?,?,?,?)",
            (
                "application_event_" + event_hash[:24],
                "PortfolioRiskPolicyConfirmed",
                "PortfolioRiskPolicyVersion",
                version.portfolio_risk_policy_version_id,
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                version.confirmed_at,
                event_hash,
            ),
        )

    def _insert_receipt(
        self,
        *,
        command: ConfirmPortfolioRiskPolicy,
        request_hash: str,
        version: PortfolioRiskPolicyVersion,
    ) -> None:
        self._connection.execute(
            "INSERT INTO application_command_receipt VALUES("
            "?,?,?,?,?,?,?,?,?,?,?)",
            (
                command.invocation_id,
                _COMMAND_NAME,
                request_hash,
                "PortfolioRiskPolicyVersion",
                version.account_id,
                version.portfolio_risk_policy_version_id,
                "succeeded",
                version.confirmed_by,
                command.interaction_channel,
                (
                    f"{command.transport_actor_type}:"
                    f"{command.transport_actor_id}"
                ),
                version.confirmed_at,
            ),
        )

    def _receipt(
        self,
        invocation_id: str,
        request_hash: str,
    ) -> sqlite3.Row | None:
        row = self._connection.execute(
            "SELECT * FROM application_command_receipt "
            "WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if row is not None and (
            row["command_name"] != _COMMAND_NAME
            or row["request_hash"] != request_hash
        ):
            raise PortfolioRiskPolicyError(
                "COMMAND_INVOCATION_CONFLICT"
            )
        return row

    def _latest(
        self,
        account_id: str,
    ) -> PortfolioRiskPolicyVersion | None:
        row = self._connection.execute(
            "SELECT * FROM portfolio_risk_policy_version "
            "WHERE account_id=? ORDER BY version_no DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        return None if row is None else self._load(row)

    def _exact(
        self,
        version_id: str,
    ) -> PortfolioRiskPolicyVersion:
        row = self._connection.execute(
            "SELECT * FROM portfolio_risk_policy_version "
            "WHERE portfolio_risk_policy_version_id=?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise PortfolioRiskPolicyError("RISK_POLICY_NOT_FOUND")
        return self._load(row)

    def _load(
        self,
        row: sqlite3.Row,
    ) -> PortfolioRiskPolicyVersion:
        try:
            limits = PortfolioRiskLimits(
                single_security_exposure=Decimal(
                    row["single_security_exposure"]
                ),
                industry_exposure=Decimal(row["industry_exposure"]),
                gross_exposure=Decimal(row["gross_exposure"]),
                minimum_cash=Decimal(row["minimum_cash"]),
                single_plan_loss=Decimal(row["single_plan_loss"]),
                aggregate_active_plan_loss=Decimal(
                    row["aggregate_active_plan_loss"]
                ),
                drawdown_review=Decimal(row["drawdown_review"]),
                drawdown_freeze=Decimal(row["drawdown_freeze"]),
                plan_daily_liquidity=Decimal(
                    row["plan_daily_liquidity"]
                ),
                position_daily_liquidity=Decimal(
                    row["position_daily_liquidity"]
                ),
            )
        except (InvalidOperation, TypeError) as error:
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_INTEGRITY_INVALID"
            ) from error
        return self._service.verify(
            PortfolioRiskPolicyVersion(
                portfolio_risk_policy_version_id=(
                    row["portfolio_risk_policy_version_id"]
                ),
                account_id=row["account_id"],
                version_no=row["version_no"],
                currency=row["currency"],
                limits=limits,
                previous_portfolio_risk_policy_version_id=(
                    row[
                        "previous_portfolio_risk_policy_version_id"
                    ]
                ),
                confirmed_by=row["confirmed_by"],
                confirmed_at=row["confirmed_at"],
                content_hash=row["content_hash"],
                identity_hash=row["identity_hash"],
                schema_version=row["schema_version"],
            )
        )

    @staticmethod
    def _known(value: Decimal | None) -> Decimal:
        if value is None:
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_INTEGRITY_INVALID"
            )
        return value


__all__ = ["SQLitePortfolioRiskPolicyRepository"]
