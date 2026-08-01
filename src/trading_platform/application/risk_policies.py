from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_platform.domain.risk_policies import (
    PortfolioRiskLimits,
    PortfolioRiskPolicyContent,
    PortfolioRiskPolicyError,
    PortfolioRiskPolicyService,
    PortfolioRiskPolicyVersion,
)


@dataclass(frozen=True)
class ConfirmPortfolioRiskPolicy:
    invocation_id: str
    account_id: str
    currency: str
    limits: PortfolioRiskLimits
    decision_actor_type: str
    decision_actor_id: str
    interaction_channel: str
    transport_actor_type: str
    transport_actor_id: str


@dataclass(frozen=True)
class GetPortfolioRiskPolicy:
    account_id: str | None = None
    portfolio_risk_policy_version_id: str | None = None


class PortfolioRiskPolicyRepository(Protocol):
    def confirm(
        self,
        command: ConfirmPortfolioRiskPolicy,
        content: PortfolioRiskPolicyContent,
    ) -> PortfolioRiskPolicyVersion: ...

    def get(
        self,
        query: GetPortfolioRiskPolicy,
    ) -> PortfolioRiskPolicyVersion: ...


class PortfolioRiskPolicies:
    """Confirms and reads exact account risk-policy versions."""

    def __init__(self, repository: PortfolioRiskPolicyRepository) -> None:
        self._repository = repository
        self._service = PortfolioRiskPolicyService()

    def confirm(
        self,
        command: ConfirmPortfolioRiskPolicy,
    ) -> PortfolioRiskPolicyVersion:
        if not command.invocation_id:
            raise PortfolioRiskPolicyError(
                "COMMAND_INVOCATION_ID_REQUIRED"
            )
        if (
            command.decision_actor_type != "user"
            or not command.decision_actor_id
        ):
            raise PortfolioRiskPolicyError(
                "USER_CONFIRMATION_CAPABILITY_REQUIRED"
            )
        if (
            command.interaction_channel not in {"skill", "cli", "web"}
            or command.transport_actor_type
            not in {"user", "agent", "adapter"}
            or not command.transport_actor_id
        ):
            raise PortfolioRiskPolicyError("COMMAND_ACTOR_METADATA_INVALID")
        content = self._service.prepare(
            command.account_id,
            command.currency,
            command.limits,
        )
        return self._repository.confirm(command, content)

    def get(
        self,
        query: GetPortfolioRiskPolicy,
    ) -> PortfolioRiskPolicyVersion:
        if (
            sum(
                value is not None
                for value in (
                    query.account_id,
                    query.portfolio_risk_policy_version_id,
                )
            )
            != 1
        ):
            raise PortfolioRiskPolicyError(
                "RISK_POLICY_QUERY_IDENTITY_REQUIRED"
            )
        return self._repository.get(query)


__all__ = [
    "ConfirmPortfolioRiskPolicy",
    "GetPortfolioRiskPolicy",
    "PortfolioRiskPolicies",
    "PortfolioRiskPolicyRepository",
]
