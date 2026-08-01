from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest

from trading_platform.application.risk_policies import (
    ConfirmPortfolioRiskPolicy,
    GetPortfolioRiskPolicy,
    PortfolioRiskPolicies,
)
from trading_platform.domain.risk_policies import (
    PortfolioRiskLimits,
    PortfolioRiskPolicyError,
)
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.risk_policies import (
    SQLitePortfolioRiskPolicyRepository,
)


ROOT = Path(__file__).resolve().parents[2]


def _limits() -> PortfolioRiskLimits:
    return PortfolioRiskLimits(
        single_security_exposure=Decimal("0.15"),
        industry_exposure=Decimal("0.30"),
        gross_exposure=Decimal("0.90"),
        minimum_cash=Decimal("0.10"),
        single_plan_loss=Decimal("0.005"),
        aggregate_active_plan_loss=Decimal("0.02"),
        drawdown_review=Decimal("0.08"),
        drawdown_freeze=Decimal("0.12"),
        plan_daily_liquidity=Decimal("0.05"),
        position_daily_liquidity=Decimal("0.50"),
    )


def _ready_policy_tasks(
    tmp_path: Path,
) -> tuple[PlatformStore, PortfolioRiskPolicies]:
    store = PlatformStore(tmp_path / "data", ROOT / "migrations")
    store.migrate()
    store.connection.execute(
        "INSERT INTO account VALUES(?,?,?,?,?)",
        (
            "account_local",
            "local",
            "CNY",
            "2026-07-30T00:00:00+08:00",
            "risk-policy-fixture",
        ),
    )
    store.connection.commit()
    repository = SQLitePortfolioRiskPolicyRepository(
        store.connection,
        store.writer_lock,
    )
    return store, PortfolioRiskPolicies(repository)


def _confirmation() -> ConfirmPortfolioRiskPolicy:
    return ConfirmPortfolioRiskPolicy(
        invocation_id="risk-policy:confirm:1",
        account_id="account_local",
        currency="CNY",
        limits=_limits(),
        decision_actor_type="user",
        decision_actor_id="local-user",
        interaction_channel="skill",
        transport_actor_type="agent",
        transport_actor_id="codex",
    )


def test_user_confirmation_creates_version_one_readable_by_exact_or_latest(
    tmp_path: Path,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)
    version = policies.confirm(_confirmation())

    assert version.account_id == "account_local"
    assert version.version_no == 1
    assert version.currency == "CNY"
    assert version.confirmed_by == "user:local-user"
    assert len(version.content_hash) == 64
    assert len(version.identity_hash) == 64
    assert policies.get(
        GetPortfolioRiskPolicy(
            portfolio_risk_policy_version_id=(
                version.portfolio_risk_policy_version_id
            )
        )
    ) == version
    assert policies.get(
        GetPortfolioRiskPolicy(account_id="account_local")
    ) == version
    store.close()


def test_confirmation_requires_the_user_decision_capability(
    tmp_path: Path,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)

    with pytest.raises(PortfolioRiskPolicyError) as failure:
        policies.confirm(
            replace(
                _confirmation(),
                decision_actor_type="agent",
                decision_actor_id="codex",
            )
        )

    assert failure.value.code == "USER_CONFIRMATION_CAPABILITY_REQUIRED"
    with pytest.raises(PortfolioRiskPolicyError) as missing:
        policies.get(
            GetPortfolioRiskPolicy(account_id="account_local")
        )
    assert missing.value.code == "RISK_POLICY_NOT_FOUND"
    store.close()


@pytest.mark.parametrize(
    ("field_name", "value", "expected_code"),
    (
        (
            "single_security_exposure",
            None,
            "RISK_POLICY_THRESHOLD_UNKNOWN",
        ),
        (
            "single_plan_loss",
            Decimal("-0.001"),
            "RISK_POLICY_THRESHOLD_INVALID",
        ),
        (
            "drawdown_freeze",
            0.12,
            "RISK_POLICY_THRESHOLD_INVALID",
        ),
    ),
)
def test_unknown_or_inexact_thresholds_fail_closed(
    tmp_path: Path,
    field_name: str,
    value: object,
    expected_code: str,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)
    command = replace(
        _confirmation(),
        limits=replace(_limits(), **{field_name: value}),
    )

    with pytest.raises(PortfolioRiskPolicyError) as failure:
        policies.confirm(command)

    assert failure.value.code == expected_code
    assert failure.value.field == field_name
    store.close()


def test_incoherent_threshold_relationships_fail_closed(
    tmp_path: Path,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)
    command = replace(
        _confirmation(),
        limits=replace(
            _limits(),
            gross_exposure=Decimal("0.95"),
        ),
    )

    with pytest.raises(PortfolioRiskPolicyError) as failure:
        policies.confirm(command)

    assert failure.value.code == (
        "RISK_POLICY_THRESHOLD_RELATION_INVALID"
    )
    store.close()


def test_same_invocation_replays_and_conflicting_reuse_is_rejected(
    tmp_path: Path,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)
    command = _confirmation()

    first = policies.confirm(command)
    replay = policies.confirm(command)

    assert replay == first
    with pytest.raises(PortfolioRiskPolicyError) as failure:
        policies.confirm(
            replace(
                command,
                limits=replace(
                    command.limits,
                    minimum_cash=Decimal("0.09"),
                ),
            )
        )
    assert failure.value.code == "COMMAND_INVOCATION_CONFLICT"
    assert policies.get(
        GetPortfolioRiskPolicy(account_id="account_local")
    ).version_no == 1
    store.close()


def test_new_confirmation_chains_versions_without_moving_exact_reads(
    tmp_path: Path,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)
    first = policies.confirm(_confirmation())
    second = policies.confirm(
        replace(
            _confirmation(),
            invocation_id="risk-policy:confirm:2",
            limits=replace(
                _limits(),
                single_security_exposure=Decimal("0.14"),
            ),
        )
    )

    assert second.version_no == 2
    assert second.previous_portfolio_risk_policy_version_id == (
        first.portfolio_risk_policy_version_id
    )
    assert policies.get(
        GetPortfolioRiskPolicy(account_id="account_local")
    ) == second
    assert policies.get(
        GetPortfolioRiskPolicy(
            portfolio_risk_policy_version_id=(
                first.portfolio_risk_policy_version_id
            )
        )
    ) == first
    store.close()


def test_persisted_policy_versions_are_immutable(
    tmp_path: Path,
) -> None:
    store, policies = _ready_policy_tasks(tmp_path)
    version = policies.confirm(_confirmation())

    with pytest.raises(
        sqlite3.IntegrityError,
        match="PORTFOLIO_RISK_POLICY_IMMUTABLE",
    ):
        store.connection.execute(
            "UPDATE portfolio_risk_policy_version "
            "SET minimum_cash='0.20' "
            "WHERE portfolio_risk_policy_version_id=?",
            (version.portfolio_risk_policy_version_id,),
        )
    store.connection.rollback()
    with pytest.raises(
        sqlite3.IntegrityError,
        match="PORTFOLIO_RISK_POLICY_IMMUTABLE",
    ):
        store.connection.execute(
            "DELETE FROM portfolio_risk_policy_version "
            "WHERE portfolio_risk_policy_version_id=?",
            (version.portfolio_risk_policy_version_id,),
        )
    store.connection.rollback()
    store.close()
