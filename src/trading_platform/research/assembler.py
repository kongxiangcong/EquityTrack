from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from dataclasses import asdict
from typing import Any, Mapping

from equity_research import LegacyResearchContextAdapter, ResearchRequest

from trading_platform.domain.workflow import ResearchProjection


class ProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_mapping_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SnapshotToResearchRequestAssembler:
    POLICY_VERSION = "research_input_policy@1"

    def assemble(self, projection: ResearchProjection) -> ResearchRequest:
        self._validate(projection)
        frozen = json.loads(json.dumps({"manifest": projection.manifest, "estimates": projection.estimates, "context": projection.context}, ensure_ascii=False, allow_nan=False))
        migration = LegacyResearchContextAdapter.adapt(frozen["context"])
        return ResearchRequest(
            manifest=frozen["manifest"],
            estimates=frozen["estimates"],
            context=None,
            research_inputs=migration.inputs,
            as_of_date=projection.as_of_date,
            profile=projection.profile,
            render_html=True,
        )

    def fingerprint(self, projection: ResearchProjection) -> str:
        self._validate(projection)
        migration = LegacyResearchContextAdapter.adapt(projection.context)
        return canonical_mapping_hash({
            "policy_version": self.POLICY_VERSION,
            "manifest": projection.manifest,
            "estimates": projection.estimates,
            "research_inputs": migration.inputs.identity_payload(),
            "as_of_date": projection.as_of_date,
            "profile": projection.profile,
            "field_semantics": [asdict(item) for item in projection.field_semantics],
            "diluted_share_identity": projection.diluted_share_identity,
            "net_debt_bridge_identity": projection.net_debt_bridge_identity,
        })

    def _validate(self, projection: ResearchProjection) -> None:
        manifest = projection.manifest
        sources = manifest.get("sources") if isinstance(manifest, Mapping) else None
        if not isinstance(sources, list) or not sources:
            raise ProjectionError("RESEARCH_SOURCES_MISSING", "Frozen projection requires source records.")
        declared = {(item.source_id, item.field_name, item.period): item for item in projection.field_semantics}
        observed: set[tuple[str, str, str]] = set()
        field_names: set[str] = set()
        for source in sources:
            if not isinstance(source, Mapping):
                raise ProjectionError("RESEARCH_SOURCE_INVALID", "Source record must be an object.")
            source_id = str(source.get("source_id", ""))
            authority = str(source.get("tier", ""))
            report_date = str(source.get("report_date", ""))
            retrieved_at = str(source.get("retrieved_at", ""))
            available_at = str(source.get("available_at", retrieved_at))
            availability_basis = "publisher_timestamp" if source.get("available_at") else "conservative_retrieval_time"
            if not report_date or not retrieved_at or not available_at or report_date > projection.as_of_date or self._instant(available_at) > datetime.combine(date.fromisoformat(projection.as_of_date), time.max, timezone.utc):
                raise ProjectionError("SOURCE_NOT_AVAILABLE_AS_OF", f"Source {source_id} is not cutoff-legal.")
            for field in source.get("extracted_fields", []):
                if not isinstance(field, Mapping):
                    raise ProjectionError("RESEARCH_FIELD_INVALID", "Extracted field must be an object.")
                key = (source_id, str(field.get("field_name", "")), str(field.get("period", "")))
                semantics = declared.get(key)
                if semantics is None:
                    raise ProjectionError("RESEARCH_FIELD_SEMANTICS_MISSING", f"Missing frozen semantics for {key}.")
                expected = {
                    "source_authority": authority,
                    "unit": str(field.get("unit", "")),
                    "currency": str(field.get("currency", "")),
                    "scale": str(field.get("scale", "1")),
                    "statement_scope": str(field.get("statement_scope", "consolidated")),
                    "restatement_status": str(field.get("restatement_status", "as_reported")),
                    "published_at": str(source.get("published_at", report_date)),
                    "available_at": available_at,
                    "retrieved_at": retrieved_at,
                    "supersedes_identity": source.get("supersedes_identity"),
                    "availability_basis": availability_basis,
                }
                for name, value in expected.items():
                    if getattr(semantics, name) != value:
                        raise ProjectionError("RESEARCH_SEMANTICS_MISMATCH", f"{name} mismatch for {key}.")
                observed.add(key)
                field_names.add(key[1])
        if observed != set(declared):
            raise ProjectionError("RESEARCH_SEMANTICS_EXTRA", "Projection contains semantics not present in the frozen manifest.")
        if "diluted_shares" in field_names:
            if not self._identity_resolves(
                projection.diluted_share_identity,
                observed,
                ("diluted_shares",),
            ):
                raise ProjectionError(
                    "DILUTED_SHARE_IDENTITY_MISSING",
                    "A present diluted-share field requires an exact frozen identity.",
                )
        elif projection.diluted_share_identity:
            raise ProjectionError(
                "DILUTED_SHARE_IDENTITY_MISSING",
                "Diluted-share identity cannot resolve when the frozen field is absent.",
            )
        elif not self._declares_missing(manifest, "diluted_shares"):
            raise ProjectionError(
                "DILUTED_SHARE_GAP_UNDECLARED",
                "An absent diluted-share field must be declared in missing_critical_data.",
            )
        net_debt_fields = {"cash", "debt"}
        if net_debt_fields.issubset(field_names):
            if not self._identity_resolves(
                projection.net_debt_bridge_identity,
                observed,
                ("cash", "debt"),
            ):
                raise ProjectionError(
                    "NET_DEBT_BRIDGE_IDENTITY_MISSING",
                    "Present cash and debt fields require an exact frozen identity.",
                )
        elif projection.net_debt_bridge_identity:
            raise ProjectionError(
                "NET_DEBT_BRIDGE_IDENTITY_MISSING",
                "Net-debt identity cannot resolve when a frozen bridge field is absent.",
            )
        else:
            undeclared = tuple(
                field_name
                for field_name in sorted(net_debt_fields - field_names)
                if not self._declares_missing(manifest, field_name)
            )
            if undeclared:
                raise ProjectionError(
                    "NET_DEBT_GAP_UNDECLARED",
                    "Absent net-debt fields must be declared in missing_critical_data: "
                    + ", ".join(undeclared),
                )

    @staticmethod
    def _instant(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    @staticmethod
    def _identity_resolves(identity: str, observed: set[tuple[str, str, str]], fields: tuple[str, ...]) -> bool:
        parts = identity.split(":")
        if len(parts) != 3:
            return False
        source_id, joined_fields, period = parts
        return tuple(joined_fields.split("+")) == fields and all((source_id, field, period) in observed for field in fields)

    @staticmethod
    def _declares_missing(manifest: Mapping[str, Any], field_name: str) -> bool:
        missing = manifest.get("missing_critical_data", [])
        return isinstance(missing, list) and any(
            isinstance(item, Mapping)
            and str(item.get("field_name", "")) == field_name
            for item in missing
        )
