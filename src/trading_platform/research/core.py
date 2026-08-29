from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from trading_platform.evidence import EvidenceSet
from trading_platform.identifiers import identity


REQUIRED_FIELDS = ("thesis", "counterargument", "drivers", "risks", "falsifiers", "uncertainties")
FORBIDDEN_FIELDS = {"valuation", "target_price", "rating", "action", "trade", "order"}


@dataclass(frozen=True)
class InvestmentCase:
    investment_case_id: str
    security_id: str
    as_of: str
    evidence_set_id: str
    thesis: str
    counterargument: str
    drivers: tuple[str, ...]
    risks: tuple[str, ...]
    falsifiers: tuple[str, ...]
    uncertainties: tuple[str, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "investment_case_id": self.investment_case_id,
            "security_id": self.security_id,
            "as_of": self.as_of,
            "evidence_set_id": self.evidence_set_id,
            "thesis": self.thesis,
            "counterargument": self.counterargument,
            "drivers": list(self.drivers),
            "risks": list(self.risks),
            "falsifiers": list(self.falsifiers),
            "uncertainties": list(self.uncertainties),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvestmentCase":
        return cls(
            investment_case_id=str(value["investment_case_id"]), security_id=str(value["security_id"]),
            as_of=str(value["as_of"]), evidence_set_id=str(value["evidence_set_id"]),
            thesis=str(value["thesis"]), counterargument=str(value["counterargument"]),
            drivers=tuple(str(item) for item in value["drivers"]), risks=tuple(str(item) for item in value["risks"]),
            falsifiers=tuple(str(item) for item in value["falsifiers"]), uncertainties=tuple(str(item) for item in value["uncertainties"]),
            limitations=tuple(str(item) for item in value["limitations"]),
        )


def validate_candidate(
    security_id: str,
    as_of: str,
    evidence: EvidenceSet,
    candidate: Mapping[str, Any],
) -> InvestmentCase:
    if evidence.as_of != as_of:
        raise ValueError("InvestmentCase and EvidenceSet as_of must match")
    if not security_id or any(not candidate.get(field) for field in REQUIRED_FIELDS):
        raise ValueError("InvestmentCase candidate is incomplete")
    if not isinstance(candidate["thesis"], str) or not isinstance(candidate["counterargument"], str):
        raise ValueError("InvestmentCase thesis and counterargument must be text")
    list_fields = ("drivers", "risks", "falsifiers", "uncertainties")
    if any(
        not isinstance(candidate[field], list)
        or any(not isinstance(item, str) or not item.strip() for item in candidate[field])
        for field in list_fields
    ):
        raise ValueError("InvestmentCase list fields must contain non-empty text")
    if FORBIDDEN_FIELDS.intersection(candidate):
        raise ValueError("InvestmentCase cannot contain valuation or trading content")
    limitations = [
        f"{item.name}: {item.missing_reason}"
        for item in evidence.items
        if item.missing_reason is not None
    ]
    result: dict[str, Any] = {
        "security_id": security_id,
        "as_of": as_of,
        "evidence_set_id": evidence.evidence_set_id,
        "thesis": candidate["thesis"],
        "counterargument": candidate["counterargument"],
        **{field: [str(item) for item in candidate[field]] for field in list_fields},
        "limitations": limitations,
    }
    case_id = identity("case", result)
    return InvestmentCase(
        investment_case_id=case_id,
        security_id=security_id,
        as_of=as_of,
        evidence_set_id=evidence.evidence_set_id,
        thesis=str(candidate["thesis"]),
        counterargument=str(candidate["counterargument"]),
        drivers=tuple(result["drivers"]),
        risks=tuple(result["risks"]),
        falsifiers=tuple(result["falsifiers"]),
        uncertainties=tuple(result["uncertainties"]),
        limitations=tuple(limitations),
    )
