from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import Enum
from typing import Mapping

from trading_platform.domain.plans import PlanCondition, PlanDraftContent, PlanRule


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


class EvaluationOutcome(str, Enum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    UNABLE = "unable_to_determine"


class Completeness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class RuleResult(str, Enum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    UNABLE = "unable_to_determine"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


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
class RuleEvaluationView:
    rule_id: str
    result: RuleResult
    reason_code: ReasonCode
    operands: tuple[tuple[str, str], ...]
    effect: str
    applies_to: str
    observed_at: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class PlanEvaluationView:
    plan_evaluation_id: str
    plan_version_id: str
    market_snapshot_id: str
    evaluator_version: str
    evaluation_policy_version: str
    status: EvaluationStatus
    outcome: EvaluationOutcome | None
    completeness: Completeness
    rule_results: tuple[RuleEvaluationView, ...]


def compute_components(security_id: str, benchmark_id: str, universe_members: tuple[UniverseMember, ...], bars: tuple[MarketBar, ...], effective_session: str, freshness: str, quality: str, constraints: Mapping[str, SecurityMarketConstraint]) -> tuple[SnapshotStatus, tuple[MarketComponentView, ...]]:
    grouped: dict[str, list[MarketBar]] = {identity: [] for identity in ({item.security_id for item in universe_members} | {security_id, benchmark_id})}
    for bar in bars:
        if bar.security_id in grouped:
            grouped[bar.security_id].append(bar)
    for series in grouped.values():
        series.sort(key=lambda item: item.session_date)
    expected = len(universe_members)
    benchmark_sessions = [item.session_date for item in grouped.get(benchmark_id, [])]
    twenty_session_cutoff = benchmark_sessions[-20] if len(benchmark_sessions) >= 20 else None
    exclusions: list[tuple[str, str]] = []
    exclusion_evidence: list[str] = []
    eligible_ids: list[str] = []
    for member in universe_members:
        series = grouped[member.security_id]
        if member.listed_from > effective_session:
            exclusions.append((member.security_id, "NOT_LISTED_AT_CUTOFF"))
        elif member.delisted_after is not None and member.delisted_after <= effective_session:
            exclusions.append((member.security_id, "DELISTED_AT_CUTOFF"))
        elif member.security_id in constraints and constraints[member.security_id].suspended:
            exclusions.append((member.security_id, "SUSPENDED_AT_CUTOFF"))
            exclusion_evidence.extend(constraints[member.security_id].evidence_refs)
        elif twenty_session_cutoff and member.listed_from > twenty_session_cutoff and len(series) < 20:
            exclusions.append((member.security_id, "INSUFFICIENT_LISTING_HISTORY"))
        elif member.security_id in constraints:
            eligible_ids.append(member.security_id)
    eligible = {identity: grouped[identity] for identity in eligible_ids}
    excluded = len(exclusions)
    exclusion_refs = tuple(f"{identity}:{reason}" for identity, reason in sorted(exclusions)) + tuple(sorted(set(exclusion_evidence)))
    missing_series = sum(not series for series in eligible.values())
    components = [
        _trend(grouped.get(benchmark_id, []), expected),
        _breadth(eligible, expected, excluded, exclusion_refs),
        _liquidity(eligible, expected, excluded, exclusion_refs),
        _volatility(grouped.get(benchmark_id, []), expected),
        _price_context(grouped.get(security_id, []), effective_session, expected, constraints.get(security_id)),
    ]
    if freshness != "valid":
        components.append(MarketComponentView("data.freshness", ComponentStatus.BLOCKED, None, (("freshness", freshness),), ReasonCode.INPUT_STALE if freshness == "stale" else ReasonCode.INPUT_MISSING, expected, 0, excluded, expected - excluded, exclusion_refs))
    if quality == "blocking":
        components.append(MarketComponentView("data.quality", ComponentStatus.BLOCKED, None, (), ReasonCode.QUALITY_BLOCKING, expected, 0, excluded, expected - excluded, exclusion_refs))
    for component_id in ("market.macro", "market.funds", "market.news", "market.sentiment", "market.crowding", "market.industry_rotation"):
        components.append(MarketComponentView(component_id, ComponentStatus.UNSUPPORTED, None, (), ReasonCode.UNSUPPORTED, expected, 0, excluded, expected - excluded, exclusion_refs))
    if freshness != "valid" or quality == "blocking" or missing_series:
        status = SnapshotStatus.BLOCKED
    elif any(item.component_id == "security.price_context" and item.status == "blocked" for item in components):
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
    classification = "up" if current > sma20 and current > sma60 and sma20 > prior_sma20 else "down" if current < sma20 and current < sma60 and sma20 < prior_sma20 else "mixed"
    return MarketComponentView("market.trend", ComponentStatus.COMPLETE, classification, (("close", str(current)), ("sma20", str(sma20)), ("sma60", str(sma60)), ("sma20_5d_prior", str(prior_sma20))), ReasonCode.COMPONENT_COMPUTED, 1, 1, 0, 0, tuple(item.normalized_version_id for item in series[-60:]))


def _breadth(grouped: Mapping[str, list[MarketBar]], expected: int, excluded: int, exclusion_refs: tuple[str, ...]) -> MarketComponentView:
    eligible = [series for series in grouped.values() if len(series) >= 20]
    missing = expected - excluded - len(eligible)
    if missing:
        return MarketComponentView("market.breadth", ComponentStatus.BLOCKED, None, (), ReasonCode.COVERAGE_INCOMPLETE, expected, len(eligible), excluded, missing, exclusion_refs)
    rising = sum(series[-1].close > series[-2].close for series in eligible)
    above = sum(series[-1].close > sum(item.close for item in series[-20:]) / 20 for series in eligible)
    rising_ratio, above_ratio = Decimal(rising) / len(eligible), Decimal(above) / len(eligible)
    classification = "broad" if rising_ratio >= Decimal("0.6") and above_ratio >= Decimal("0.6") else "narrow" if rising_ratio <= Decimal("0.4") and above_ratio <= Decimal("0.4") else "mixed"
    return MarketComponentView("market.breadth", ComponentStatus.COMPLETE, classification, (("rising_ratio", str(rising_ratio)), ("above_sma20_ratio", str(above_ratio))), ReasonCode.COMPONENT_COMPUTED, expected, len(eligible), excluded, 0, exclusion_refs + tuple(series[-1].normalized_version_id for series in eligible))


def _liquidity(grouped: Mapping[str, list[MarketBar]], expected: int, excluded: int, exclusion_refs: tuple[str, ...]) -> MarketComponentView:
    sample_count = min(252, min((len(series) for series in grouped.values()), default=0) - 1)
    if sample_count < 120:
        return _blocked("market.liquidity", expected, ReasonCode.INPUT_MISSING)
    totals: list[Decimal] = []
    for offset in range(sample_count + 1):
        values = [series[-sample_count - 1 + offset].amount for series in grouped.values()]
        if any(value is None for value in values):
            missing = sum(value is None for value in values)
            return MarketComponentView("market.liquidity", ComponentStatus.BLOCKED, None, (), ReasonCode.COVERAGE_INCOMPLETE, expected, len(grouped) - missing, excluded, missing, exclusion_refs)
        totals.append(sum((value for value in values if value is not None), Decimal(0)))
    percentile = _percentile(totals[-1], totals[:-1])
    classification = "ample" if percentile >= Decimal("0.7") else "thin" if percentile <= Decimal("0.3") else "normal"
    return MarketComponentView("market.liquidity", ComponentStatus.COMPLETE, classification, (("total_amount", str(totals[-1])), ("historical_percentile", str(percentile)), ("sample_count", str(sample_count))), ReasonCode.COMPONENT_COMPUTED, expected, len(grouped), excluded, 0, exclusion_refs + tuple(series[-1].normalized_version_id for series in grouped.values()))


def _volatility(series: list[MarketBar], expected: int) -> MarketComponentView:
    if len(series) < 141:
        return _blocked("market.volatility", expected, ReasonCode.INPUT_MISSING)
    closes = [item.close for item in series]
    observations = [_annualized_volatility(closes[index - 20:index + 1]) for index in range(20, len(closes))]
    prior = observations[-253:-1]
    percentile = _percentile(observations[-1], prior)
    classification = "high" if percentile >= Decimal("0.8") else "low" if percentile <= Decimal("0.2") else "normal"
    return MarketComponentView("market.volatility", ComponentStatus.COMPLETE, classification, (("annualized_volatility", str(observations[-1])), ("historical_percentile", str(percentile)), ("sample_count", str(len(prior)))), ReasonCode.COMPONENT_COMPUTED, 1, 1, 0, 0, tuple(item.normalized_version_id for item in series[-273:]))


def _price_context(series: list[MarketBar], effective_session: str, expected: int, constraint: SecurityMarketConstraint | None) -> MarketComponentView:
    if constraint is None or constraint.session_date != effective_session:
        return MarketComponentView("security.price_context", ComponentStatus.BLOCKED, None, (), ReasonCode.MARKET_CONSTRAINT_MISSING, 1, 0, 0, 1, ())
    if constraint.corporate_action_conflict:
        return MarketComponentView("security.price_context", ComponentStatus.BLOCKED, None, (), ReasonCode.INPUT_CONFLICTED, 1, 0, 0, 1, constraint.evidence_refs)
    if constraint.suspended:
        return MarketComponentView("security.price_context", ComponentStatus.LIMITED, "suspended", (("suspended", "true"), ("limit_state", "none"), ("corporate_action_conflict", "false")), ReasonCode.SECURITY_SUSPENDED, 1, 1, 0, 0, constraint.evidence_refs)
    if len(series) < 60 or series[-1].session_date != effective_session:
        return _blocked("security.price_context", 1, ReasonCode.INPUT_MISSING)
    closes = [item.close for item in series]
    change = closes[-1] / closes[-2] - 1
    limit_state = "up" if closes[-1] == constraint.limit_up else "down" if closes[-1] == constraint.limit_down else "none"
    return MarketComponentView("security.price_context", ComponentStatus.COMPLETE, "available", (("close", str(closes[-1])), ("previous_close", str(closes[-2])), ("daily_change", str(change)), ("sma20", str(sum(closes[-20:]) / 20)), ("sma60", str(sum(closes[-60:]) / 60)), ("suspended", str(constraint.suspended).lower()), ("limit_state", limit_state), ("corporate_action_conflict", "false")), ReasonCode.COMPONENT_COMPUTED, 1, 1, 0, 0, (series[-1].normalized_version_id,) + constraint.evidence_refs)


def _annualized_volatility(closes: list[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        returns = [context.ln(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / len(returns)
        return context.sqrt(variance) * context.sqrt(Decimal(252))


def _percentile(value: Decimal, history: list[Decimal]) -> Decimal:
    return Decimal(sum(item <= value for item in history)) / len(history)


def _blocked(component_id: str, expected: int, reason: ReasonCode) -> MarketComponentView:
    return MarketComponentView(component_id, ComponentStatus.BLOCKED, None, (), reason, expected, 0, 0, expected, ())


def evaluate_rules(content: PlanDraftContent, market: MarketSnapshotView) -> tuple[EvaluationStatus, EvaluationOutcome | None, Completeness, tuple[RuleEvaluationView, ...]]:
    if market.status == "blocked":
        blocker = next((component for component in market.components if component.status == "blocked"), None)
        reason = blocker.reason_code if blocker else ReasonCode.QUALITY_BLOCKING
        blocked = tuple(RuleEvaluationView(rule.rule_id, RuleResult.BLOCKED, reason, (), rule.effect, rule.applies_to, market.effective_session_date, blocker.evidence_refs if blocker else ()) for rule in content.rules)
        return EvaluationStatus.BLOCKED, None, Completeness.PARTIAL, blocked
    components = {item.component_id: item for item in market.components}
    results = tuple(_evaluate_rule(rule, components, market.effective_session_date) for rule in content.rules)
    if any(item.result is RuleResult.BLOCKED for item in results):
        return EvaluationStatus.BLOCKED, None, Completeness.PARTIAL, results
    outcome = EvaluationOutcome.TRIGGERED if any(item.result is RuleResult.TRIGGERED for item in results) else EvaluationOutcome.UNABLE if any(item.result is RuleResult.UNABLE for item in results) else EvaluationOutcome.NOT_TRIGGERED
    completeness = Completeness.PARTIAL if market.status is not SnapshotStatus.COMPLETE or any(item.result in {RuleResult.UNABLE, RuleResult.NOT_APPLICABLE} for item in results) else Completeness.COMPLETE
    return EvaluationStatus.COMPLETED, outcome, completeness, results


def _evaluate_rule(rule: PlanRule, components: Mapping[str, MarketComponentView], observed_at: str) -> RuleEvaluationView:
    state, operands, evidence, propagated_reason = _evaluate_condition(rule.condition, components)
    result = {"true": RuleResult.TRIGGERED, "false": RuleResult.NOT_TRIGGERED, "unknown": RuleResult.UNABLE, "blocked": RuleResult.BLOCKED, "not_applicable": RuleResult.NOT_APPLICABLE}[state]
    reason = propagated_reason or {"true": ReasonCode.CONDITION_TRUE, "false": ReasonCode.CONDITION_FALSE, "unknown": ReasonCode.INPUT_MISSING, "blocked": ReasonCode.QUALITY_BLOCKING, "not_applicable": ReasonCode.RULE_NOT_APPLICABLE}[state]
    return RuleEvaluationView(rule.rule_id, result, reason, operands, rule.effect, rule.applies_to, observed_at, evidence)


def _evaluate_condition(condition: PlanCondition, components: Mapping[str, MarketComponentView]) -> tuple[str, tuple[tuple[str, str], ...], tuple[str, ...], ReasonCode | None]:
    if condition.node_kind != "leaf":
        children = [_evaluate_condition(item, components) for item in condition.children]
        states = [item[0] for item in children]
        if condition.node_kind == "not":
            state = "false" if states[0] == "true" else "true" if states[0] == "false" else states[0]
        elif "blocked" in states:
            state = "blocked"
        elif condition.node_kind == "all":
            state = "false" if "false" in states else "unknown" if "unknown" in states else "not_applicable" if "not_applicable" in states else "true"
        else:
            state = "true" if "true" in states else "unknown" if "unknown" in states else "not_applicable" if "not_applicable" in states else "false"
        propagated = next((child[3] for child in children if child[0] in {"blocked", "unknown"} and child[3] is not None), None)
        return state, tuple(item for child in children for item in child[1]), tuple(item for child in children for item in child[2]), propagated
    if condition.metric_ref in {"position.quantity", "portfolio.net_asset_value"}:
        return "not_applicable", (("metric_ref", condition.metric_ref),), (), ReasonCode.RULE_NOT_APPLICABLE
    component_id = "security.price_context" if condition.metric_ref.startswith("security.") else condition.metric_ref
    component = components.get(component_id)
    if component is None or component.status in {"blocked", "unsupported"}:
        state = "blocked" if component and component.status == "blocked" else "unknown"
        return state, (("metric_ref", condition.metric_ref),), component.evidence_refs if component else (), component.reason_code if component else ReasonCode.INPUT_MISSING
    values = dict(component.values)
    if condition.metric_ref in {"security.close_unadjusted", "security.close_adjusted"}:
        actual = values.get("close")
    elif condition.metric_ref == "security.suspended":
        actual = values.get("suspended")
    elif condition.metric_ref == "security.limit_state":
        actual = values.get("limit_state")
    else:
        actual = component.classification
    if actual is None or condition.constant is None:
        return "unknown", (("metric_ref", condition.metric_ref),), component.evidence_refs, ReasonCode.INPUT_MISSING
    if condition.constant.constant_type == "decimal":
        left, right = Decimal(actual), Decimal(condition.constant.value)
        if condition.operator == "between" and condition.constant.secondary_value is not None:
            matched = right <= left <= Decimal(condition.constant.secondary_value)
        elif condition.operator in {"crosses_above", "crosses_below"} and component_id == "security.price_context" and values.get("previous_close") is not None:
            previous = Decimal(values["previous_close"])
            matched = previous <= right < left if condition.operator == "crosses_above" else previous >= right > left
        else:
            matched = {"eq": left == right, "ne": left != right, "lt": left < right, "lte": left <= right, "gt": left > right, "gte": left >= right}.get(condition.operator)
    else:
        if condition.operator == "changed_to":
            previous = values.get("previous_classification")
            matched = None if previous is None else previous != condition.constant.value and actual == condition.constant.value
        else:
            matched = actual == condition.constant.value if condition.operator == "eq" else actual != condition.constant.value
    if matched is None:
        return "unknown", (("metric_ref", condition.metric_ref), ("actual", actual)), component.evidence_refs, ReasonCode.INPUT_MISSING
    operands = [("metric_ref", condition.metric_ref), ("actual", actual), ("expected", condition.constant.value), ("unit", condition.constant.unit or "enum")]
    if condition.constant.secondary_value is not None:
        operands.append(("expected_upper", condition.constant.secondary_value))
    return "true" if matched else "false", tuple(operands), component.evidence_refs, None
