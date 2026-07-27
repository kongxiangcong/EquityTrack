from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import Enum
from typing import Mapping

from trading_platform.domain.conflicts import ConflictResolution
from trading_platform.domain.rules import RuleEvaluation

class MarketError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ComponentStatus(str, Enum):
    COMPLETE = "complete"
    LIMITED = "limited"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"


class SnapshotStatus(str, Enum):
    COMPLETE = "complete"
    LIMITED = "limited"
    BLOCKED = "blocked"


class EvaluationStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"


class Completeness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class ReasonCode(str, Enum):
    COMPONENT_COMPUTED = "COMPONENT_COMPUTED"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    INPUT_MISSING = "INPUT_MISSING"
    INPUT_STALE = "INPUT_STALE"
    INPUT_CONFLICTED = "INPUT_CONFLICTED"
    QUALITY_BLOCKING = "QUALITY_BLOCKING"
    UNSUPPORTED = "UNSUPPORTED_IN_FIRST_SLICE"
    MARKET_CONSTRAINT_MISSING = "MARKET_CONSTRAINT_INPUT_MISSING"
    SECURITY_SUSPENDED = "SECURITY_SUSPENDED"
    CONDITION_TRUE = "CONDITION_TRUE"
    CONDITION_FALSE = "CONDITION_FALSE"
    RULE_NOT_APPLICABLE = "RULE_NOT_APPLICABLE"


@dataclass(frozen=True)
class MarketBar:
    security_id: str
    session_date: str
    close: Decimal
    amount: Decimal | None
    normalized_version_id: str


@dataclass(frozen=True)
class UniverseMember:
    security_id: str
    listed_from: str
    delisted_after: str | None
    source_ref: str


@dataclass(frozen=True)
class SecurityMarketConstraint:
    security_id: str
    session_date: str
    suspended: bool
    limit_up: Decimal
    limit_down: Decimal
    corporate_action_conflict: bool
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class MarketComponentView:
    component_id: str
    status: ComponentStatus
    classification: str | None
    values: tuple[tuple[str, str], ...]
    reason_code: ReasonCode
    coverage_expected: int
    coverage_eligible: int
    coverage_excluded: int
    coverage_missing: int
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class MarketSnapshotView:
    market_snapshot_id: str
    security_id: str
    market_scope_id: str
    requested_date: str
    effective_session_date: str
    data_snapshot_id: str
    market_universe_version_id: str
    market_model_version: str
    freshness_policy_version: str
    code_identity_hash: str
    input_fingerprint: str
    status: SnapshotStatus
    components: tuple[MarketComponentView, ...]


@dataclass(frozen=True)
class PlanEvaluationView:
    plan_evaluation_id: str
    plan_version_id: str
    market_snapshot_id: str
    evaluator_version: str
    evaluation_policy_version: str
    status: EvaluationStatus
    completeness: Completeness
    rule_results: tuple[RuleEvaluation, ...]
    resolution: ConflictResolution
    evaluation_hash: str


def compute_components(
    security_id: str,
    benchmark_id: str,
    universe_members: tuple[UniverseMember, ...],
    bars: tuple[MarketBar, ...],
    effective_session: str,
    freshness: str,
    quality: str,
    constraints: Mapping[str, SecurityMarketConstraint],
) -> tuple[SnapshotStatus, tuple[MarketComponentView, ...]]:
    grouped: dict[str, list[MarketBar]] = {
        identity: []
        for identity in (
            {item.security_id for item in universe_members}
            | {security_id, benchmark_id}
        )
    }
    for bar in bars:
        if bar.security_id in grouped:
            grouped[bar.security_id].append(bar)
    for series in grouped.values():
        series.sort(key=lambda item: item.session_date)
    expected = len(universe_members)
    benchmark_sessions = [item.session_date for item in grouped.get(benchmark_id, [])]
    twenty_session_cutoff = (
        benchmark_sessions[-20] if len(benchmark_sessions) >= 20 else None
    )
    exclusions: list[tuple[str, str]] = []
    exclusion_evidence: list[str] = []
    eligible_ids: list[str] = []
    for member in universe_members:
        series = grouped[member.security_id]
        if member.listed_from > effective_session:
            exclusions.append((member.security_id, "NOT_LISTED_AT_CUTOFF"))
        elif (
            member.delisted_after is not None
            and member.delisted_after <= effective_session
        ):
            exclusions.append((member.security_id, "DELISTED_AT_CUTOFF"))
        elif (
            member.security_id in constraints
            and constraints[member.security_id].suspended
        ):
            exclusions.append((member.security_id, "SUSPENDED_AT_CUTOFF"))
            exclusion_evidence.extend(constraints[member.security_id].evidence_refs)
        elif (
            twenty_session_cutoff
            and member.listed_from > twenty_session_cutoff
            and len(series) < 20
        ):
            exclusions.append((member.security_id, "INSUFFICIENT_LISTING_HISTORY"))
        elif member.security_id in constraints:
            eligible_ids.append(member.security_id)
    eligible = {identity: grouped[identity] for identity in eligible_ids}
    excluded = len(exclusions)
    exclusion_refs = tuple(
        f"{identity}:{reason}" for identity, reason in sorted(exclusions)
    ) + tuple(sorted(set(exclusion_evidence)))
    missing_series = sum(not series for series in eligible.values())
    components = [
        _trend(grouped.get(benchmark_id, []), expected),
        _breadth(eligible, expected, excluded, exclusion_refs),
        _liquidity(eligible, expected, excluded, exclusion_refs),
        _volatility(grouped.get(benchmark_id, []), expected),
        _price_context(
            grouped.get(security_id, []),
            effective_session,
            expected,
            constraints.get(security_id),
        ),
    ]
    if freshness != "valid":
        components.append(
            MarketComponentView(
                "data.freshness",
                ComponentStatus.BLOCKED,
                None,
                (("freshness", freshness),),
                (
                    ReasonCode.INPUT_STALE
                    if freshness == "stale"
                    else ReasonCode.INPUT_MISSING
                ),
                expected,
                0,
                excluded,
                expected - excluded,
                exclusion_refs,
            )
        )
    if quality == "blocking":
        components.append(
            MarketComponentView(
                "data.quality",
                ComponentStatus.BLOCKED,
                None,
                (),
                ReasonCode.QUALITY_BLOCKING,
                expected,
                0,
                excluded,
                expected - excluded,
                exclusion_refs,
            )
        )
    for component_id in (
        "market.macro",
        "market.funds",
        "market.news",
        "market.sentiment",
        "market.crowding",
        "market.industry_rotation",
    ):
        components.append(
            MarketComponentView(
                component_id,
                ComponentStatus.UNSUPPORTED,
                None,
                (),
                ReasonCode.UNSUPPORTED,
                expected,
                0,
                excluded,
                expected - excluded,
                exclusion_refs,
            )
        )
    if freshness != "valid" or quality == "blocking" or missing_series:
        status = SnapshotStatus.BLOCKED
    elif any(
        item.component_id == "security.price_context" and item.status == "blocked"
        for item in components
    ):
        status = SnapshotStatus.BLOCKED
    elif any(item.status == "blocked" for item in components):
        status = SnapshotStatus.LIMITED
    elif any(item.status == "unsupported" for item in components):
        status = SnapshotStatus.LIMITED
    else:
        status = SnapshotStatus.COMPLETE
    return status, tuple(components)


def _trend(series: list[MarketBar], expected: int) -> MarketComponentView:
    if len(series) < 65:
        return _blocked("market.trend", expected, ReasonCode.INPUT_MISSING)
    closes = [item.close for item in series]
    sma20, sma60 = sum(closes[-20:]) / 20, sum(closes[-60:]) / 60
    prior_sma20 = sum(closes[-25:-5]) / 20
    current = closes[-1]
    classification = (
        "up"
        if current > sma20 and current > sma60 and sma20 > prior_sma20
        else (
            "down"
            if current < sma20 and current < sma60 and sma20 < prior_sma20
            else "mixed"
        )
    )
    return MarketComponentView(
        "market.trend",
        ComponentStatus.COMPLETE,
        classification,
        (
            ("close", str(current)),
            ("sma20", str(sma20)),
            ("sma60", str(sma60)),
            ("sma20_5d_prior", str(prior_sma20)),
        ),
        ReasonCode.COMPONENT_COMPUTED,
        1,
        1,
        0,
        0,
        tuple(item.normalized_version_id for item in series[-60:]),
    )


def _breadth(
    grouped: Mapping[str, list[MarketBar]],
    expected: int,
    excluded: int,
    exclusion_refs: tuple[str, ...],
) -> MarketComponentView:
    eligible = [series for series in grouped.values() if len(series) >= 20]
    missing = expected - excluded - len(eligible)
    if missing:
        return MarketComponentView(
            "market.breadth",
            ComponentStatus.BLOCKED,
            None,
            (),
            ReasonCode.COVERAGE_INCOMPLETE,
            expected,
            len(eligible),
            excluded,
            missing,
            exclusion_refs,
        )
    rising = sum(series[-1].close > series[-2].close for series in eligible)
    above = sum(
        series[-1].close > sum(item.close for item in series[-20:]) / 20
        for series in eligible
    )
    rising_ratio, above_ratio = Decimal(rising) / len(eligible), Decimal(above) / len(
        eligible
    )
    classification = (
        "broad"
        if rising_ratio >= Decimal("0.6") and above_ratio >= Decimal("0.6")
        else (
            "narrow"
            if rising_ratio <= Decimal("0.4") and above_ratio <= Decimal("0.4")
            else "mixed"
        )
    )
    return MarketComponentView(
        "market.breadth",
        ComponentStatus.COMPLETE,
        classification,
        (("rising_ratio", str(rising_ratio)), ("above_sma20_ratio", str(above_ratio))),
        ReasonCode.COMPONENT_COMPUTED,
        expected,
        len(eligible),
        excluded,
        0,
        exclusion_refs + tuple(series[-1].normalized_version_id for series in eligible),
    )


def _liquidity(
    grouped: Mapping[str, list[MarketBar]],
    expected: int,
    excluded: int,
    exclusion_refs: tuple[str, ...],
) -> MarketComponentView:
    sample_count = min(
        252, min((len(series) for series in grouped.values()), default=0) - 1
    )
    if sample_count < 120:
        return _blocked("market.liquidity", expected, ReasonCode.INPUT_MISSING)
    totals: list[Decimal] = []
    for offset in range(sample_count + 1):
        values = [
            series[-sample_count - 1 + offset].amount for series in grouped.values()
        ]
        if any(value is None for value in values):
            missing = sum(value is None for value in values)
            return MarketComponentView(
                "market.liquidity",
                ComponentStatus.BLOCKED,
                None,
                (),
                ReasonCode.COVERAGE_INCOMPLETE,
                expected,
                len(grouped) - missing,
                excluded,
                missing,
                exclusion_refs,
            )
        totals.append(sum((value for value in values if value is not None), Decimal(0)))
    percentile = _percentile(totals[-1], totals[:-1])
    classification = (
        "ample"
        if percentile >= Decimal("0.7")
        else "thin" if percentile <= Decimal("0.3") else "normal"
    )
    return MarketComponentView(
        "market.liquidity",
        ComponentStatus.COMPLETE,
        classification,
        (
            ("total_amount", str(totals[-1])),
            ("historical_percentile", str(percentile)),
            ("sample_count", str(sample_count)),
        ),
        ReasonCode.COMPONENT_COMPUTED,
        expected,
        len(grouped),
        excluded,
        0,
        exclusion_refs
        + tuple(series[-1].normalized_version_id for series in grouped.values()),
    )


def _volatility(series: list[MarketBar], expected: int) -> MarketComponentView:
    if len(series) < 141:
        return _blocked("market.volatility", expected, ReasonCode.INPUT_MISSING)
    closes = [item.close for item in series]
    observations = [
        _annualized_volatility(closes[index - 20 : index + 1])
        for index in range(20, len(closes))
    ]
    prior = observations[-253:-1]
    percentile = _percentile(observations[-1], prior)
    classification = (
        "high"
        if percentile >= Decimal("0.8")
        else "low" if percentile <= Decimal("0.2") else "normal"
    )
    return MarketComponentView(
        "market.volatility",
        ComponentStatus.COMPLETE,
        classification,
        (
            ("annualized_volatility", str(observations[-1])),
            ("historical_percentile", str(percentile)),
            ("sample_count", str(len(prior))),
        ),
        ReasonCode.COMPONENT_COMPUTED,
        1,
        1,
        0,
        0,
        tuple(item.normalized_version_id for item in series[-273:]),
    )


def _price_context(
    series: list[MarketBar],
    effective_session: str,
    expected: int,
    constraint: SecurityMarketConstraint | None,
) -> MarketComponentView:
    if constraint is None or constraint.session_date != effective_session:
        return MarketComponentView(
            "security.price_context",
            ComponentStatus.BLOCKED,
            None,
            (),
            ReasonCode.MARKET_CONSTRAINT_MISSING,
            1,
            0,
            0,
            1,
            (),
        )
    if constraint.corporate_action_conflict:
        return MarketComponentView(
            "security.price_context",
            ComponentStatus.BLOCKED,
            None,
            (),
            ReasonCode.INPUT_CONFLICTED,
            1,
            0,
            0,
            1,
            constraint.evidence_refs,
        )
    if constraint.suspended:
        return MarketComponentView(
            "security.price_context",
            ComponentStatus.LIMITED,
            "suspended",
            (
                ("suspended", "true"),
                ("limit_state", "none"),
                ("corporate_action_conflict", "false"),
            ),
            ReasonCode.SECURITY_SUSPENDED,
            1,
            1,
            0,
            0,
            constraint.evidence_refs,
        )
    if len(series) < 60 or series[-1].session_date != effective_session:
        return _blocked("security.price_context", 1, ReasonCode.INPUT_MISSING)
    closes = [item.close for item in series]
    change = closes[-1] / closes[-2] - 1
    limit_state = (
        "up"
        if closes[-1] == constraint.limit_up
        else "down" if closes[-1] == constraint.limit_down else "none"
    )
    return MarketComponentView(
        "security.price_context",
        ComponentStatus.COMPLETE,
        "available",
        (
            ("close", str(closes[-1])),
            ("previous_close", str(closes[-2])),
            ("daily_change", str(change)),
            ("sma20", str(sum(closes[-20:]) / 20)),
            ("sma60", str(sum(closes[-60:]) / 60)),
            ("suspended", str(constraint.suspended).lower()),
            ("limit_state", limit_state),
            ("corporate_action_conflict", "false"),
        ),
        ReasonCode.COMPONENT_COMPUTED,
        1,
        1,
        0,
        0,
        (series[-1].normalized_version_id,) + constraint.evidence_refs,
    )


def _annualized_volatility(closes: list[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        returns = [
            context.ln(closes[index] / closes[index - 1])
            for index in range(1, len(closes))
        ]
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / len(returns)
        return context.sqrt(variance) * context.sqrt(Decimal(252))


def _percentile(value: Decimal, history: list[Decimal]) -> Decimal:
    return Decimal(sum(item <= value for item in history)) / len(history)


def _blocked(
    component_id: str, expected: int, reason: ReasonCode
) -> MarketComponentView:
    return MarketComponentView(
        component_id,
        ComponentStatus.BLOCKED,
        None,
        (),
        reason,
        expected,
        0,
        0,
        expected,
        (),
    )
