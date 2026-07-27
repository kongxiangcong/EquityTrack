from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from trading_platform.identity import canonical_hash


class PlanValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TradePlanMasterId:
    account_id: str
    security_id: str
    value: str

    @classmethod
    def derive(
        cls,
        account_id: str,
        security_id: str,
        identity_seed: str = "initial",
    ) -> "TradePlanMasterId":
        if not account_id or not security_id or not identity_seed:
            raise PlanValidationError("PLAN_OWNERSHIP_REQUIRED")
        digest = canonical_hash(
            {
                "schema_version": "TradePlanMasterId@1",
                "account_id": account_id,
                "security_id": security_id,
                "identity_seed": identity_seed,
            }
        )
        return cls(
            account_id=account_id,
            security_id=security_id,
            value=f"trade_plan_master_{digest[:24]}",
        )


@dataclass(frozen=True)
class TradePlanMaster:
    plan_id: TradePlanMasterId
    strategy_version_id: str
    lifecycle_status: str
    transition_seq: int
    created_at: str
    schema_version: str = "TradePlanMaster@1"

    def validate(self) -> None:
        if (
            self.schema_version != "TradePlanMaster@1"
            or not self.plan_id.account_id
            or not self.plan_id.security_id
            or not self.plan_id.value
            or not self.strategy_version_id
            or self.lifecycle_status not in {"inactive", "active", "ended"}
            or self.transition_seq < 0
            or not self.created_at
        ):
            raise PlanValidationError("PLAN_MASTER_INVALID")


@dataclass(frozen=True)
class TradePlanDraft:
    draft_id: str
    plan_id: str | None
    account_id: str
    security_id: str
    strategy_version_id: str
    based_on_version_id: str | None
    revision: int
    status: str
    parameters: Mapping[str, object]
    content: Mapping[str, object]
    content_hash: str
    created_at: str
    updated_at: str
    decision_actor: str
    interaction_channel: str
    transport_actor: str
    schema_version: str = "TradePlanDraft@1"

    def validate(self) -> None:
        if (
            self.schema_version != "TradePlanDraft@1"
            or not self.draft_id
            or not self.account_id
            or not self.security_id
            or not self.strategy_version_id
            or self.revision < 1
            or self.status not in {"open", "rejected", "confirmed"}
            or not self.decision_actor
            or not self.interaction_channel
            or not self.transport_actor
            or self.content_hash
            != canonical_hash(
                {
                    "account_id": self.account_id,
                    "security_id": self.security_id,
                    "strategy_version_id": self.strategy_version_id,
                    "based_on_version_id": self.based_on_version_id,
                    "parameters": self.parameters,
                    "content": self.content,
                }
            )
        ):
            raise PlanValidationError("PLAN_DRAFT_INVALID")


@dataclass(frozen=True)
class PlanGraphSeal:
    graph_seal_hash: str
    version_content_hash: str
    sleeve_hashes: tuple[str, ...]
    rule_hashes: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    schema_version: str = "PlanGraphSeal@1"

    @classmethod
    def build(
        cls,
        *,
        version_content_hash: str,
        sleeve_hashes: tuple[str, ...],
        rule_hashes: tuple[str, ...],
        evidence_hashes: tuple[str, ...],
    ) -> "PlanGraphSeal":
        canonical_sleeves = tuple(sorted(sleeve_hashes))
        canonical_rules = tuple(rule_hashes)
        canonical_evidence = tuple(evidence_hashes)
        identity = {
            "schema_version": "PlanGraphSeal@1",
            "version_content_hash": version_content_hash,
            "sleeve_hashes": canonical_sleeves,
            "rule_hashes": canonical_rules,
            "evidence_hashes": canonical_evidence,
        }
        return cls(
            graph_seal_hash=canonical_hash(identity),
            version_content_hash=version_content_hash,
            sleeve_hashes=canonical_sleeves,
            rule_hashes=canonical_rules,
            evidence_hashes=canonical_evidence,
        )


@dataclass(frozen=True)
class TradePlanVersion:
    plan_version_id: str
    plan_id: str
    version_no: int
    supersedes_version_id: str | None
    strategy_version_id: str
    investment_thesis_version_id: str | None
    account_snapshot_version_id: str
    data_snapshot_id: str
    horizon_start: str
    horizon_end: str
    review_by: str
    risk_policy_version_id: str | None
    metric_catalog_version: str
    evaluator_policy_version: str
    conflict_policy_version: str
    ast_version: str
    content: Mapping[str, object]
    content_hash: str
    graph_seal_hash: str
    confirmed_at: str
    user_approval_receipt_id: str
    legacy_read_only: bool = False
    schema_version: str = "TradePlanVersion@1"

    def validate(self) -> None:
        try:
            start = date.fromisoformat(self.horizon_start)
            review = date.fromisoformat(self.review_by)
            end = date.fromisoformat(self.horizon_end)
        except ValueError as error:
            raise PlanValidationError("PLAN_HORIZON_INVALID") from error
        if (
            self.schema_version != "TradePlanVersion@1"
            or not self.plan_version_id
            or not self.plan_id
            or self.version_no < 1
            or not self.strategy_version_id
            or not self.account_snapshot_version_id
            or not self.data_snapshot_id
            or not start <= review <= end
            or self.conflict_policy_version != "trade-plan-conflict@1"
            or self.ast_version != "plan-rule-ast@2"
            or self.content_hash != canonical_hash(self.content)
            or not self.graph_seal_hash
            or not self.confirmed_at
            or not self.user_approval_receipt_id
            or self.legacy_read_only
        ):
            raise PlanValidationError("PLAN_VERSION_INVALID")


@dataclass(frozen=True)
class TradePlanGraph:
    version: TradePlanVersion
    sleeves: tuple[Mapping[str, object], ...]
    rules: tuple[Mapping[str, object], ...]
    evidence_references: tuple[Mapping[str, object], ...]
    adjusted_price_evidence: tuple[Mapping[str, object], ...] = ()
    schema_version: str = "TradePlanGraph@1"

    def validate(self) -> None:
        self.version.validate()
        if self.schema_version != "TradePlanGraph@1":
            raise PlanValidationError("PLAN_GRAPH_INVALID")
        sleeve_hashes = _child_hashes(self.sleeves, "sleeve_id")
        rule_hashes = _child_hashes(
            self.rules, "rule_id", sequence_sensitive=True
        )
        evidence_hashes = _child_hashes(
            self.evidence_references,
            "ref_id",
            sequence_sensitive=True,
        ) + _child_hashes(
            self.adjusted_price_evidence,
            "content_hash",
            sequence_sensitive=True,
        )
        expected = PlanGraphSeal.build(
            version_content_hash=self.version.content_hash,
            sleeve_hashes=sleeve_hashes,
            rule_hashes=rule_hashes,
            evidence_hashes=evidence_hashes,
        )
        if self.version.graph_seal_hash != expected.graph_seal_hash:
            raise PlanValidationError("PLAN_GRAPH_SEAL_MISMATCH")


@dataclass(frozen=True)
class PlanActivation:
    activation_id: str
    plan_id: str
    plan_version_id: str
    activated_event_id: str
    activated_at: str
    user_approval_receipt_id: str
    command_invocation_id: str
    ended_event_id: str | None = None
    ended_at: str | None = None
    end_reason: str | None = None
    schema_version: str = "PlanActivation@1"


@dataclass(frozen=True)
class ActiveTradePlan:
    master: TradePlanMaster
    activation: PlanActivation | None
    version: TradePlanVersion | None


def build_plan_version(
    *,
    plan_version_id: str,
    plan_id: str,
    version_no: int,
    supersedes_version_id: str | None,
    strategy_version_id: str,
    investment_thesis_version_id: str | None,
    account_snapshot_version_id: str,
    data_snapshot_id: str,
    horizon_start: str,
    horizon_end: str,
    review_by: str,
    risk_policy_version_id: str | None,
    metric_catalog_version: str,
    evaluator_policy_version: str,
    content: Mapping[str, object],
    sleeves: tuple[Mapping[str, object], ...],
    rules: tuple[Mapping[str, object], ...],
    evidence_references: tuple[Mapping[str, object], ...],
    adjusted_price_evidence: tuple[Mapping[str, object], ...],
    confirmed_at: str,
    user_approval_receipt_id: str,
) -> TradePlanGraph:
    content_hash = canonical_hash(content)
    seal = PlanGraphSeal.build(
        version_content_hash=content_hash,
        sleeve_hashes=_child_hashes(sleeves, "sleeve_id"),
        rule_hashes=_child_hashes(
            rules, "rule_id", sequence_sensitive=True
        ),
        evidence_hashes=_child_hashes(
            evidence_references, "ref_id", sequence_sensitive=True
        )
        + _child_hashes(
            adjusted_price_evidence,
            "content_hash",
            sequence_sensitive=True,
        ),
    )
    version = TradePlanVersion(
        plan_version_id=plan_version_id,
        plan_id=plan_id,
        version_no=version_no,
        supersedes_version_id=supersedes_version_id,
        strategy_version_id=strategy_version_id,
        investment_thesis_version_id=investment_thesis_version_id,
        account_snapshot_version_id=account_snapshot_version_id,
        data_snapshot_id=data_snapshot_id,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        review_by=review_by,
        risk_policy_version_id=risk_policy_version_id,
        metric_catalog_version=metric_catalog_version,
        evaluator_policy_version=evaluator_policy_version,
        conflict_policy_version="trade-plan-conflict@1",
        ast_version="plan-rule-ast@2",
        content=content,
        content_hash=content_hash,
        graph_seal_hash=seal.graph_seal_hash,
        confirmed_at=confirmed_at,
        user_approval_receipt_id=user_approval_receipt_id,
    )
    graph = TradePlanGraph(
        version=version,
        sleeves=sleeves,
        rules=rules,
        evidence_references=evidence_references,
        adjusted_price_evidence=adjusted_price_evidence,
    )
    graph.validate()
    return graph


def _child_hashes(
    children: tuple[Mapping[str, object], ...],
    identity_key: str,
    *,
    sequence_sensitive: bool = False,
) -> tuple[str, ...]:
    identities: set[str] = set()
    hashes: list[str] = []
    for child in children:
        identity = child.get(identity_key)
        content_hash = child.get("content_hash")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in identities
            or not isinstance(content_hash, str)
            or content_hash != canonical_hash(
                {
                    key: value
                    for key, value in child.items()
                    if key != "content_hash"
                }
            )
        ):
            raise PlanValidationError("PLAN_GRAPH_CHILD_INVALID")
        identities.add(identity)
        hashes.append(content_hash)
    return tuple(hashes if sequence_sensitive else sorted(hashes))


__all__ = [
    "ActiveTradePlan",
    "PlanActivation",
    "PlanGraphSeal",
    "PlanValidationError",
    "TradePlanDraft",
    "TradePlanGraph",
    "TradePlanMaster",
    "TradePlanMasterId",
    "TradePlanVersion",
    "build_plan_version",
]
