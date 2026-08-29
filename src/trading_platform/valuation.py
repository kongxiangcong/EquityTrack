from __future__ import annotations

from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from statistics import median
from typing import Any, Mapping

from trading_platform.evidence import EvidenceSet
from trading_platform.identifiers import identity
from trading_platform.result import FrozenFields


DCF_DISABLED = {
    "financial": "ordinary DCF is disabled for financial institutions",
    "pipeline_biopharma": "pipeline biopharma routes to rNPV",
    "cyclical_resource": "cyclical and resource valuation requires a mid-cycle method",
}


@dataclass(frozen=True)
class ValuationAssessment:
    valuation_assessment_id: str
    investment_case_id: str
    evidence_set_id: str
    as_of: str
    method: str
    company_archetype: str
    status: str
    result: FrozenFields | None
    scenarios: FrozenFields
    sensitivity: tuple[FrozenFields, ...]
    missing_inputs: tuple[str, ...] = ()
    disabled_reason: str | None = None
    disabled_conclusion: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "valuation_assessment_id": self.valuation_assessment_id,
            "investment_case_id": self.investment_case_id,
            "evidence_set_id": self.evidence_set_id,
            "as_of": self.as_of,
            "method": self.method,
            "company_archetype": self.company_archetype,
            "status": self.status,
            "result": self.result.as_dict() if self.result is not None else None,
            "scenarios": self.scenarios.as_dict(),
            "sensitivity": [point.as_dict() for point in self.sensitivity],
            **(
                {
                    "missing_inputs": list(self.missing_inputs),
                    "disabled_reason": self.disabled_reason,
                    "disabled_conclusion": self.disabled_conclusion,
                }
                if self.status == "insufficient"
                else {}
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValuationAssessment":
        result = value.get("result")
        return cls(
            valuation_assessment_id=str(value["valuation_assessment_id"]),
            investment_case_id=str(value["investment_case_id"]), evidence_set_id=str(value["evidence_set_id"]),
            as_of=str(value["as_of"]), method=str(value["method"]), company_archetype=str(value["company_archetype"]),
            status=str(value["status"]), result=FrozenFields.from_mapping(result) if isinstance(result, Mapping) else None,
            scenarios=FrozenFields.from_mapping(value.get("scenarios", {})),
            sensitivity=tuple(FrozenFields.from_mapping(point) for point in value.get("sensitivity", [])),
            missing_inputs=tuple(str(item) for item in value.get("missing_inputs", [])),
            disabled_reason=str(value["disabled_reason"]) if value.get("disabled_reason") is not None else None,
            disabled_conclusion=str(value["disabled_conclusion"]) if value.get("disabled_conclusion") is not None else None,
        )


def assess(
    investment_case_id: str,
    evidence: EvidenceSet,
    method: str,
    archetype: str,
    *,
    scenarios: Mapping[str, Mapping[str, Any]] | None = None,
    peers: list[Mapping[str, Any]] | None = None,
    comparable_currency: str | None = None,
    accounting_basis: str | None = None,
) -> ValuationAssessment:
    base: dict[str, Any] = {
        "investment_case_id": investment_case_id,
        "evidence_set_id": evidence.evidence_set_id,
        "as_of": evidence.as_of,
        "method": method,
        "company_archetype": archetype,
    }
    if method == "dcf" and archetype in DCF_DISABLED:
        return _insufficient(base, disabled_reason=DCF_DISABLED[archetype], disabled_conclusion="dcf_valuation")
    if method == "comparables":
        missing_contract = [
            name
            for name, value in (
                ("comparable_currency", comparable_currency),
                ("accounting_basis", accounting_basis),
            )
            if not value
        ]
        if missing_contract:
            return _insufficient(
                base,
                missing_inputs=missing_contract,
                disabled_conclusion="comparable_valuation",
            )
        usable: list[tuple[str, Decimal]] = []
        rejected: list[dict[str, str]] = []
        for peer in peers or []:
            peer_id = str(peer.get("peer_id", ""))
            reason = _peer_rejection(peer, str(comparable_currency), str(accounting_basis))
            if reason is not None:
                rejected.append({"peer_id": peer_id, "reason": reason})
                continue
            usable.append((peer_id, _decimal(peer["multiple"])))
        if len(usable) < 3:
            return _insufficient(
                base,
                missing_inputs=["at_least_three_usable_peers"],
                disabled_reason=f"{len(usable)} peers passed source, currency, and accounting-basis checks",
                disabled_conclusion="comparable_valuation",
            )
        multiples = [value for _, value in usable]
        return _completed(
            base,
            {
                "usable_peer_count": len(usable),
                "peer_ids": [peer_id for peer_id, _ in usable],
                "median_multiple": _text(Decimal(str(median(multiples)))),
                "currency": comparable_currency,
                "accounting_basis": accounting_basis,
                "rejected_peers": rejected,
            },
        )
    if method != "dcf":
        return _insufficient(base, disabled_reason=f"unsupported method for {archetype}", disabled_conclusion="method_valuation")

    values = {item.name: item.value for item in evidence.items if item.missing_reason is None}
    required = ["free_cash_flow", "net_debt", "diluted_shares", "wacc", "terminal_growth"]
    missing = [name for name in required if name not in values]
    if missing:
        conclusion = "per_share_valuation" if "diluted_shares" in missing else "dcf_valuation"
        return _insufficient(base, missing_inputs=missing, disabled_conclusion=conclusion)
    fcf, fcf_currency = _money(values["free_cash_flow"])
    debt, debt_currency = _money(values["net_debt"])
    if fcf_currency != debt_currency:
        return _insufficient(base, disabled_reason="DCF equity bridge currencies do not match", disabled_conclusion="dcf_valuation")
    shares = _amount(values["diluted_shares"])
    wacc = _decimal(values["wacc"])
    growth = _decimal(values["terminal_growth"])
    if shares <= 0:
        return _insufficient(base, disabled_reason="diluted shares must be positive", disabled_conclusion="per_share_valuation")
    if wacc <= growth:
        return _insufficient(base, disabled_reason="WACC must be greater than terminal growth", disabled_conclusion="dcf_valuation")
    result = _dcf(fcf, debt, shares, wacc, growth, fcf_currency)
    scenario_results: dict[str, Any] = {}
    if scenarios is not None:
        if set(scenarios) != {"stress", "base", "improvement"}:
            raise ValueError("scenarios must be stress, base, and improvement")
        for name in ("stress", "base", "improvement"):
            scenario_wacc = _decimal(scenarios[name]["wacc"])
            scenario_growth = _decimal(scenarios[name]["growth"])
            if scenario_wacc <= scenario_growth:
                raise ValueError("every scenario requires WACC greater than growth")
            scenario_results[name] = _dcf(fcf, debt, shares, scenario_wacc, scenario_growth, fcf_currency)
    return _completed(
        base,
        result,
        scenarios=scenario_results,
        sensitivity=_sensitivity(fcf, debt, shares, wacc, growth, fcf_currency),
    )


def _dcf(fcf: Decimal, debt: Decimal, shares: Decimal, wacc: Decimal, growth: Decimal, currency: str) -> dict[str, Any]:
    enterprise = fcf * (Decimal("1") + growth) / (wacc - growth)
    equity = enterprise - debt
    per_share = equity / shares
    return {
        "enterprise_value": _text(enterprise),
        "equity_value": _text(equity),
        "per_share_value": _text(per_share),
        "currency": currency,
        "wacc": _text(wacc),
        "terminal_growth": _text(growth),
    }


def _completed(
    base: dict[str, Any],
    result: dict[str, Any],
    *,
    scenarios: dict[str, Any] | None = None,
    sensitivity: list[dict[str, Any]] | None = None,
) -> ValuationAssessment:
    payload = {**base, "status": "completed", "result": result, "scenarios": scenarios or {}, "sensitivity": sensitivity or []}
    return ValuationAssessment(
        valuation_assessment_id=identity("valuation", payload),
        investment_case_id=str(base["investment_case_id"]),
        evidence_set_id=str(base["evidence_set_id"]),
        as_of=str(base["as_of"]),
        method=str(base["method"]),
        company_archetype=str(base["company_archetype"]),
        status="completed",
        result=FrozenFields.from_mapping(result),
        scenarios=FrozenFields.from_mapping(scenarios or {}),
        sensitivity=tuple(FrozenFields.from_mapping(point) for point in sensitivity or []),
    )


def _insufficient(base: dict[str, Any], *, missing_inputs: list[str] | None = None, disabled_reason: str | None = None, disabled_conclusion: str) -> ValuationAssessment:
    payload = {
        **base,
        "status": "insufficient",
        "missing_inputs": missing_inputs or [],
        "disabled_reason": disabled_reason,
        "disabled_conclusion": disabled_conclusion,
        "result": None,
        "scenarios": {},
        "sensitivity": [],
    }
    return ValuationAssessment(
        valuation_assessment_id=identity("valuation", payload),
        investment_case_id=str(base["investment_case_id"]),
        evidence_set_id=str(base["evidence_set_id"]),
        as_of=str(base["as_of"]),
        method=str(base["method"]),
        company_archetype=str(base["company_archetype"]),
        status="insufficient",
        result=None,
        scenarios=FrozenFields.from_mapping({}),
        sensitivity=(),
        missing_inputs=tuple(missing_inputs or []),
        disabled_reason=disabled_reason,
        disabled_conclusion=disabled_conclusion,
    )


def _money(value: object) -> tuple[Decimal, str]:
    if not isinstance(value, Mapping) or not value.get("currency"):
        raise ValueError("money requires amount and currency")
    return _amount(value), str(value["currency"])


def _sensitivity(
    fcf: Decimal,
    debt: Decimal,
    shares: Decimal,
    wacc: Decimal,
    growth: Decimal,
    currency: str,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for wacc_delta in (Decimal("-0.01"), Decimal("0"), Decimal("0.01")):
        for growth_delta in (Decimal("-0.005"), Decimal("0"), Decimal("0.005")):
            stressed_wacc = wacc + wacc_delta
            stressed_growth = growth + growth_delta
            if stressed_wacc <= stressed_growth:
                continue
            value = _dcf(fcf, debt, shares, stressed_wacc, stressed_growth, currency)
            points.append(
                {
                    "wacc": _text(stressed_wacc),
                    "terminal_growth": _text(stressed_growth),
                    "per_share_value": value["per_share_value"],
                }
            )
    return points


def _peer_rejection(
    peer: Mapping[str, Any], currency: str, accounting_basis: str
) -> str | None:
    if not peer.get("peer_id") or not peer.get("source_id"):
        return "missing peer identity or source_id"
    if peer.get("currency") != currency:
        return "currency mismatch"
    if peer.get("accounting_basis") != accounting_basis:
        return "accounting basis mismatch"
    try:
        if _decimal(peer.get("multiple")) <= 0:
            return "multiple must be positive"
    except ValueError:
        return "multiple is invalid"
    return None


def _amount(value: object) -> Decimal:
    return _decimal(value["amount"] if isinstance(value, Mapping) else value)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid valuation decimal") from error


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")
