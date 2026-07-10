from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .output_policy import normalize_action_language


POLICY_IDENTIFIER_KEYS = {
    "source_id",
    "source_ids",
    "input_source_ids",
    "evidence_id",
    "evidence_ids",
    "field_name",
    "subject_id",
    "semantic_role",
    "derived_from",
    "basis_sources",
    "url_or_api",
    "run_id",
    "ticker",
    "period",
    "currency",
    "unit",
    "path",
    "code",
    "method_id",
    "capability_id",
    "role",
    "status",
    "profile",
}


def _sanitize_output_payload(value: Any, *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            item_key: _sanitize_output_payload(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_output_payload(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_output_payload(item, key=key) for item in value]
    if isinstance(value, str) and key not in POLICY_IDENTIFIER_KEYS:
        return normalize_action_language(value)[0]
    return value


@dataclass(frozen=True)
class ResearchRequest:
    """Everything needed for one deterministic research assessment.

    File and network I/O live in adapters (the CLI is one).  Keeping mappings
    here makes the core directly testable and prevents the renderer from
    refetching or silently changing financial data.
    """

    manifest: Mapping[str, Any]
    as_of_date: str
    estimates: Mapping[str, Any] | None = None
    context: Mapping[str, Any] | None = None
    profile: str = "standard"
    render_html: bool = True


@dataclass(frozen=True)
class IntegrityIssue:
    severity: str
    code: str
    message: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    tier: str
    publisher: str
    title: str
    url_or_api: str
    retrieved_at: str
    available_at: str
    official: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    subject_id: str
    semantic_role: str
    field_name: str
    period: str
    value: Any
    unit: str
    currency: str
    source_id: str
    source_tier: str
    publisher: str
    title: str
    url_or_api: str
    retrieved_at: str
    extraction_method: str
    confidence: str
    official: bool
    estimated: bool
    derived_from: tuple[str, ...] = ()
    basis_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["derived_from"] = list(self.derived_from)
        payload["basis_sources"] = list(self.basis_sources)
        return payload


@dataclass(frozen=True)
class CapabilityResult:
    capability_id: str
    label: str
    status: str
    required_fields: tuple[str, ...]
    sourced_fields: tuple[str, ...]
    estimated_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    optional_gaps: tuple[str, ...]
    context_gaps: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "required_fields",
            "sourced_fields",
            "estimated_fields",
            "missing_fields",
            "optional_gaps",
            "context_gaps",
            "evidence_ids",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True)
class MethodResult:
    method_id: str
    label: str
    status: str
    role: str
    explanation: str
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "label": self.label,
            "status": self.status,
            "role": self.role,
            "explanation": self.explanation,
            "missing_fields": list(self.missing_fields),
            "evidence_ids": list(self.evidence_ids),
            "assumptions": dict(self.assumptions),
            "metrics": dict(self.metrics),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class ResearchRun:
    schema_version: int
    run_id: str
    status: str
    as_of_date: str
    profile: str
    company: Mapping[str, Any]
    sources: tuple[SourceRecord, ...]
    evidence: tuple[EvidenceItem, ...]
    declared_missing: tuple[Mapping[str, Any], ...]
    integrity_issues: tuple[IntegrityIssue, ...]
    capabilities: Mapping[str, CapabilityResult]
    methods: Mapping[str, MethodResult]
    permissions: Mapping[str, bool]
    summary: Mapping[str, Any]
    conditional_plan: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[str, ...]
    html: str = ""

    def to_dict(self, *, include_html: bool = False) -> dict[str, Any]:
        method_payload = {key: value.to_dict() for key, value in self.methods.items()}
        if not self.permissions.get("research_report", False):
            for method in method_payload.values():
                method["metrics"] = {}
                method["assumptions"] = {}
        elif not self.permissions.get("formal_per_share_valuation", False):
            for method in method_payload.values():
                metrics = method["metrics"]
                for key in list(metrics):
                    if "per_share" in key or key == "sensitivity":
                        metrics.pop(key)
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status,
            "as_of_date": self.as_of_date,
            "profile": self.profile,
            "company": dict(self.company),
            "sources": [source.to_dict() for source in self.sources],
            "evidence": [item.to_dict() for item in self.evidence],
            "declared_missing": [dict(item) for item in self.declared_missing],
            "integrity_issues": [issue.to_dict() for issue in self.integrity_issues],
            "capabilities": {
                key: value.to_dict() for key, value in self.capabilities.items()
            },
            "methods": method_payload,
            "permissions": dict(self.permissions),
            "summary": dict(self.summary),
            "conditional_plan": [dict(item) for item in self.conditional_plan],
            "diagnostics": list(self.diagnostics),
        }
        if include_html:
            payload["html"] = self.html
        return _sanitize_output_payload(payload)
