from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from decimal import Decimal
import re

from trading_platform.identity import canonical_hash


RISK_POLICY_SCHEMA_VERSION = "PortfolioRiskPolicy@1"


class PortfolioRiskPolicyError(RuntimeError):
    def __init__(self, code: str, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(code if field is None else f"{code}:{field}")


@dataclass(frozen=True)
class PortfolioRiskLimits:
    single_security_exposure: Decimal | None
    industry_exposure: Decimal | None
    gross_exposure: Decimal | None
    minimum_cash: Decimal | None
    single_plan_loss: Decimal | None
    aggregate_active_plan_loss: Decimal | None
    drawdown_review: Decimal | None
    drawdown_freeze: Decimal | None
    plan_daily_liquidity: Decimal | None
    position_daily_liquidity: Decimal | None


@dataclass(frozen=True)
class PortfolioRiskPolicyContent:
    account_id: str
    currency: str
    limits: PortfolioRiskLimits
    schema_version: str
    content_hash: str


@dataclass(frozen=True)
class PortfolioRiskPolicyVersion:
    portfolio_risk_policy_version_id: str
    account_id: str
    version_no: int
    currency: str
    limits: PortfolioRiskLimits
    previous_portfolio_risk_policy_version_id: str | None
    confirmed_by: str
    confirmed_at: str
    content_hash: str
    identity_hash: str
    schema_version: str = RISK_POLICY_SCHEMA_VERSION


class PortfolioRiskPolicyService:
    """Owns exact threshold semantics and immutable version identity."""

    _ACCOUNT_ID = re.compile(r"account_[a-z0-9][a-z0-9_-]{1,63}")
    _LIMIT_FIELDS = tuple(field.name for field in fields(PortfolioRiskLimits))
    _ALLOW_ZERO = frozenset({"minimum_cash"})

    def prepare(
        self,
        account_id: str,
        currency: str,
        limits: PortfolioRiskLimits,
    ) -> PortfolioRiskPolicyContent:
        if not self._ACCOUNT_ID.fullmatch(account_id):
            raise PortfolioRiskPolicyError("RISK_POLICY_ACCOUNT_ID_INVALID")
        normalized_currency = currency.upper()
        if normalized_currency != "CNY":
            raise PortfolioRiskPolicyError("RISK_POLICY_CURRENCY_UNSUPPORTED")

        normalized: dict[str, Decimal] = {}
        for field_name in self._LIMIT_FIELDS:
            value = getattr(limits, field_name)
            if value is None:
                raise PortfolioRiskPolicyError(
                    "RISK_POLICY_THRESHOLD_UNKNOWN",
                    field_name,
                )
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value > Decimal(1)
                or (
                    value < Decimal(0)
                    if field_name in self._ALLOW_ZERO
                    else value <= Decimal(0)
                )
            ):
                raise PortfolioRiskPolicyError(
                    "RISK_POLICY_THRESHOLD_INVALID",
                    field_name,
                )
            normalized[field_name] = self._normalize_decimal(value)

        self._require_limit_sequence(
            normalized["single_security_exposure"]
            <= normalized["industry_exposure"]
            <= normalized["gross_exposure"],
            "single_security_exposure<=industry_exposure<=gross_exposure",
        )
        self._require_limit_sequence(
            normalized["gross_exposure"] + normalized["minimum_cash"]
            <= Decimal(1),
            "gross_exposure+minimum_cash<=1",
        )
        self._require_limit_sequence(
            normalized["single_plan_loss"]
            <= normalized["aggregate_active_plan_loss"]
            <= normalized["drawdown_review"]
            < normalized["drawdown_freeze"],
            (
                "single_plan_loss<=aggregate_active_plan_loss"
                "<=drawdown_review<drawdown_freeze"
            ),
        )
        self._require_limit_sequence(
            normalized["plan_daily_liquidity"]
            <= normalized["position_daily_liquidity"],
            "plan_daily_liquidity<=position_daily_liquidity",
        )

        prepared_limits = PortfolioRiskLimits(**normalized)
        content = {
            "schema_version": RISK_POLICY_SCHEMA_VERSION,
            "account_id": account_id,
            "currency": normalized_currency,
            "limits": prepared_limits,
        }
        return PortfolioRiskPolicyContent(
            account_id=account_id,
            currency=normalized_currency,
            limits=prepared_limits,
            schema_version=RISK_POLICY_SCHEMA_VERSION,
            content_hash=canonical_hash(content),
        )

    def create_version(
        self,
        content: PortfolioRiskPolicyContent,
        *,
        version_no: int,
        previous_version_id: str | None,
        confirmed_by: str,
        confirmed_at: str,
    ) -> PortfolioRiskPolicyVersion:
        if version_no < 1:
            raise PortfolioRiskPolicyError("RISK_POLICY_VERSION_INVALID")
        if (version_no == 1) != (previous_version_id is None):
            raise PortfolioRiskPolicyError("RISK_POLICY_PREDECESSOR_INVALID")
        if not confirmed_by.startswith("user:") or len(confirmed_by) == len("user:"):
            raise PortfolioRiskPolicyError(
                "USER_CONFIRMATION_CAPABILITY_REQUIRED"
            )
        try:
            confirmation_instant = datetime.fromisoformat(confirmed_at)
        except ValueError as error:
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_CONFIRMED_AT_INVALID"
            ) from error
        if (
            confirmation_instant.tzinfo is None
            or confirmation_instant.utcoffset() is None
        ):
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_CONFIRMED_AT_OFFSET_REQUIRED"
            )

        identity = {
            "schema_version": content.schema_version,
            "account_id": content.account_id,
            "version_no": version_no,
            "previous_version_id": previous_version_id,
            "content_hash": content.content_hash,
        }
        identity_hash = canonical_hash(identity)
        return PortfolioRiskPolicyVersion(
            portfolio_risk_policy_version_id=(
                "portfolio_risk_policy_version_" + identity_hash[:24]
            ),
            account_id=content.account_id,
            version_no=version_no,
            currency=content.currency,
            limits=content.limits,
            previous_portfolio_risk_policy_version_id=previous_version_id,
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at,
            content_hash=content.content_hash,
            identity_hash=identity_hash,
            schema_version=content.schema_version,
        )

    def verify(
        self,
        version: PortfolioRiskPolicyVersion,
    ) -> PortfolioRiskPolicyVersion:
        try:
            content = self.prepare(
                version.account_id,
                version.currency,
                version.limits,
            )
            expected = self.create_version(
                content,
                version_no=version.version_no,
                previous_version_id=(
                    version.previous_portfolio_risk_policy_version_id
                ),
                confirmed_by=version.confirmed_by,
                confirmed_at=version.confirmed_at,
            )
        except PortfolioRiskPolicyError as error:
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_INTEGRITY_INVALID"
            ) from error
        if expected != version:
            raise PortfolioRiskPolicyError("RISK_POLICY_INTEGRITY_INVALID")
        return version

    @staticmethod
    def render_decimal(value: Decimal) -> str:
        rendered = format(value.normalize(), "f")
        return "0" if rendered == "-0" else rendered

    @classmethod
    def _normalize_decimal(cls, value: Decimal) -> Decimal:
        return Decimal(cls.render_decimal(value))

    @staticmethod
    def _require_limit_sequence(condition: bool, relation: str) -> None:
        if not condition:
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_THRESHOLD_RELATION_INVALID",
                relation,
            )


__all__ = [
    "PortfolioRiskLimits",
    "PortfolioRiskPolicyContent",
    "PortfolioRiskPolicyError",
    "PortfolioRiskPolicyService",
    "PortfolioRiskPolicyVersion",
    "RISK_POLICY_SCHEMA_VERSION",
]
