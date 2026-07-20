from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from trading_platform.domain.workflow import (
    ImmutableArtifactDraft,
    ResearchArtifactView,
    forecast_structure_identity,
    simulation_fallback_matches_valuation,
)
from trading_platform.identity import canonical_hash


class ArtifactLineageError(ValueError):
    """Stable, redacted failure for an invalid frozen artifact graph."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def artifact_member_role(artifact_kind: str) -> str:
    try:
        return {
            "DataSnapshot": "data_snapshot",
            "Forecast": "forecast",
            "Valuation": "valuation",
            "Simulation": "simulation",
            "MarketDataSnapshot": "market_data_snapshot",
            "MarketPathSimulation": "market_path_simulation",
            "ForecastReview": "forecast_review",
        }[artifact_kind]
    except KeyError as exc:
        raise ArtifactLineageError(
            "RESEARCH_ARTIFACT_KIND_INVALID", "Artifact kind has no manifest role."
        ) from exc


@dataclass(frozen=True)
class ArtifactSubmission:
    research_run_id: str
    workflow_run_id: str | None
    data_snapshot_id: str
    code_identity: str
    drafts: tuple[ImmutableArtifactDraft, ...]
    market_data_snapshot_id: str | None = None
    artifact_mode: str = "bundle"
    parent_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewSnapshotEvidence:
    data_snapshot_id: str
    scope_id: str
    snapshot_purpose: str
    freshness_status: str
    quality_status: str
    as_of_at: str


@dataclass(frozen=True)
class ReviewFactEvidence:
    normalized_version_id: str
    content_hash: str
    source_identity: str
    source_authority: str
    attempt_status: str
    quality_status: str
    retrieved_at: str
    attempt_retrieved_at: str
    published_at: str | None
    available_at: str


@dataclass(frozen=True)
class MarketCalibrationEvidence:
    snapshot: Mapping[str, object] | None
    members: tuple[Mapping[str, object], ...]
    calendar_rows: tuple[Mapping[str, object], ...]
    snapshot_calendar_rows: tuple[Mapping[str, object], ...]
    next_calendar_rows: tuple[Mapping[str, object], ...]
    known_open_rows: tuple[Mapping[str, object], ...]
    series_rows: tuple[Mapping[str, object], ...]
    snapshot_series_rows: tuple[Mapping[str, object], ...]
    starting_row: Mapping[str, object] | None


@dataclass(frozen=True)
class FrozenLineageEvidence:
    research_run_id: str
    workflow_run_id: str | None
    platform_security_id: str
    subject_aliases: frozenset[str]
    research_snapshot_id: str
    model_data_snapshot_identity: str
    original_cutoff_date: str
    engine_code_identity: str
    parent_artifacts: tuple[ResearchArtifactView, ...] = ()
    review_snapshot: ReviewSnapshotEvidence | None = None
    review_facts: tuple[ReviewFactEvidence, ...] = ()
    market_calibration: MarketCalibrationEvidence | None = None


@dataclass(frozen=True)
class ValidatedArtifactEnvelope:
    draft: ImmutableArtifactDraft
    record_id: str
    dependency_record_ids: tuple[str, ...]
    artifact_id: str
    object_sha256: str
    payload: bytes


@dataclass(frozen=True)
class ValidatedArtifactCommit:
    model_data_snapshot_identity: str
    platform_security_id: str
    envelopes: tuple[ValidatedArtifactEnvelope, ...]

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(item.record_id for item in self.envelopes)


class ArtifactLineage:
    """Validate an immutable research artifact graph without persistence or I/O."""

    @classmethod
    def validate(
        cls,
        submission: ArtifactSubmission,
        evidence: FrozenLineageEvidence,
    ) -> ValidatedArtifactCommit:
        cls._validate_parent_identity(submission, evidence)
        drafts = submission.drafts
        if not drafts:
            cls._fail(
                "RESEARCH_ARTIFACT_GRAPH_EMPTY",
                "Artifact submission must contain at least one immutable draft.",
            )
        if any(not isinstance(draft, ImmutableArtifactDraft) for draft in drafts):
            cls._fail(
                "RESEARCH_ARTIFACT_BUNDLE_TYPE_INVALID",
                "Artifact submission must contain typed immutable drafts.",
            )
        kinds = tuple(draft.artifact_kind for draft in drafts)
        if len(kinds) != len(set(kinds)):
            cls._fail(
                "RESEARCH_ARTIFACT_KIND_DUPLICATE",
                "Artifact kinds must be unique within one submission.",
            )
        if submission.artifact_mode == "forecast_review":
            return cls._validate_forecast_review(submission, evidence)
        try:
            model_snapshot_identity = cls._validate_typed_graph(
                drafts,
                subject_aliases=evidence.subject_aliases,
                market_data_snapshot_id=submission.market_data_snapshot_id,
                market_calibration=evidence.market_calibration,
            )
        except ValueError as error:
            cls._fail(str(error), "Typed artifact graph lineage is invalid.")
        if model_snapshot_identity != evidence.model_data_snapshot_identity:
            cls._fail(
                "RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH",
                "Model snapshot identity does not match frozen evidence.",
            )
        seen: set[str] = set()
        for draft in drafts:
            if not set(draft.dependency_kinds).issubset(seen):
                cls._fail(
                    "RESEARCH_ARTIFACT_DEPENDENCY_ORDER_INVALID",
                    "Artifact dependencies must precede their consumers.",
                )
            seen.add(draft.artifact_kind)
            if draft.as_of != evidence.original_cutoff_date:
                cls._fail(
                    "RESEARCH_ARTIFACT_AS_OF_MISMATCH",
                    "Artifact as-of does not match the frozen research cutoff.",
                )

        by_kind = {draft.artifact_kind: draft for draft in drafts}
        snapshot = by_kind.get("DataSnapshot")
        if snapshot is None:
            cls._fail(
                "RESEARCH_ARTIFACT_DATA_SNAPSHOT_MISSING",
                "A typed DataSnapshot artifact is required.",
            )
        subjects = {draft.subject_id for draft in drafts}
        if len(subjects) != 1:
            cls._fail(
                "RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH",
                "All artifacts must share one frozen subject.",
            )
        subject_id = next(iter(subjects))
        if (
            subject_id not in evidence.subject_aliases
            or snapshot.source_identity != evidence.model_data_snapshot_identity
            or snapshot.payload.get("snapshot_id")
            != evidence.model_data_snapshot_identity
            or snapshot.payload.get("security_id") != subject_id
            or snapshot.payload.get("as_of") != snapshot.as_of
        ):
            cls._fail(
                "RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH",
                "The model snapshot and subject do not match frozen evidence.",
            )

        record_by_kind = {
            draft.artifact_kind: (
                "research_artifact_"
                + canonical_hash(
                    {
                        "run": submission.research_run_id,
                        "snapshot": submission.data_snapshot_id,
                        "draft": draft.content_hash,
                        "code": submission.code_identity,
                    }
                )[:24]
            )
            for draft in drafts
        }
        envelopes = []
        for draft in drafts:
            record_id = record_by_kind[draft.artifact_kind]
            dependency_ids = tuple(
                sorted(record_by_kind[kind] for kind in draft.dependency_kinds)
            )
            envelope = {
                "envelope_schema": "ResearchArtifactEnvelope@1",
                "artifact_record_id": record_id,
                "artifact_kind": draft.artifact_kind,
                "artifact_schema_version": draft.schema_version,
                "research_run_id": submission.research_run_id,
                "data_snapshot_id": submission.data_snapshot_id,
                "model_data_snapshot_identity": evidence.model_data_snapshot_identity,
                "platform_security_id": evidence.platform_security_id,
                "subject_id": draft.subject_id,
                "as_of": draft.as_of,
                "source_identity": draft.source_identity,
                "model_identity": draft.model_identity,
                "formula_identities": list(draft.formula_identities),
                "code_identity": submission.code_identity,
                "policy_identity": draft.policy_identity,
                "status": draft.status,
                "dependency_record_ids": list(dependency_ids),
                "summary": draft.summary,
                "payload": draft.payload,
            }
            payload = json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            object_sha256 = hashlib.sha256(payload).hexdigest()
            artifact_id = "artifact_" + canonical_hash(
                {
                    "sha256": object_sha256,
                    "media": "application/json",
                    "schema": draft.schema_version,
                }
            )[:24]
            envelopes.append(
                ValidatedArtifactEnvelope(
                    draft=draft,
                    record_id=record_id,
                    dependency_record_ids=dependency_ids,
                    artifact_id=artifact_id,
                    object_sha256=object_sha256,
                    payload=payload,
                )
            )
        return ValidatedArtifactCommit(
            model_data_snapshot_identity=evidence.model_data_snapshot_identity,
            platform_security_id=evidence.platform_security_id,
            envelopes=tuple(envelopes),
        )

    @classmethod
    def _validate_forecast_review(
        cls,
        submission: ArtifactSubmission,
        evidence: FrozenLineageEvidence,
    ) -> ValidatedArtifactCommit:
        if len(submission.drafts) != 1:
            cls._fail("FORECAST_REVIEW_DRAFT_INVALID", "One review draft is required.")
        draft = submission.drafts[0]
        parents = evidence.parent_artifacts
        if (
            draft.artifact_kind != "ForecastReview"
            or draft.dependency_kinds != ("Forecast", "Valuation", "Simulation")
            or tuple(item.artifact_kind for item in parents)
            != ("Forecast", "Valuation", "Simulation")
            or tuple(item.artifact_record_id for item in parents)
            != submission.parent_record_ids
            or len({item.research_run_id for item in parents}) != 1
            or len({item.data_snapshot_id for item in parents}) != 1
            or len({item.code_identity for item in parents}) != 1
            or len({item.platform_security_id for item in parents}) != 1
            or len({item.subject_id for item in parents}) != 1
            or draft.subject_id != parents[0].subject_id
        ):
            cls._fail(
                "FORECAST_REVIEW_PARENT_LINEAGE_INVALID",
                "Review parents do not form the required frozen graph.",
            )
        if not submission.code_identity.strip():
            cls._fail(
                "FORECAST_REVIEW_CODE_IDENTITY_INVALID",
                "Review code identity must be non-empty.",
            )
        if submission.data_snapshot_id in {item.data_snapshot_id for item in parents}:
            cls._fail(
                "FORECAST_REVIEW_EVIDENCE_SNAPSHOT_NOT_SEPARATE",
                "Review evidence must use a snapshot separate from its parents.",
            )
        cls._validate_review_evidence(draft, evidence)
        record_id = "research_artifact_" + canonical_hash(
            {
                "run": submission.research_run_id,
                "snapshot": submission.data_snapshot_id,
                "draft": draft.content_hash,
                "code": submission.code_identity,
            }
        )[:24]
        dependency_ids = tuple(sorted(submission.parent_record_ids))
        envelope = {
            "envelope_schema": "ResearchArtifactEnvelope@1",
            "artifact_record_id": record_id,
            "artifact_kind": draft.artifact_kind,
            "artifact_schema_version": draft.schema_version,
            "research_run_id": submission.research_run_id,
            "data_snapshot_id": submission.data_snapshot_id,
            "model_data_snapshot_identity": evidence.model_data_snapshot_identity,
            "platform_security_id": evidence.platform_security_id,
            "subject_id": draft.subject_id,
            "as_of": draft.as_of,
            "source_identity": draft.source_identity,
            "model_identity": draft.model_identity,
            "formula_identities": list(draft.formula_identities),
            "code_identity": submission.code_identity,
            "policy_identity": draft.policy_identity,
            "status": draft.status,
            "dependency_record_ids": list(dependency_ids),
            "summary": draft.summary,
            "payload": draft.payload,
        }
        payload = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        object_sha256 = hashlib.sha256(payload).hexdigest()
        artifact_id = "artifact_" + canonical_hash(
            {"sha256": object_sha256, "media": "application/json", "schema": draft.schema_version}
        )[:24]
        return ValidatedArtifactCommit(
            evidence.model_data_snapshot_identity,
            evidence.platform_security_id,
            (ValidatedArtifactEnvelope(draft, record_id, dependency_ids, artifact_id, object_sha256, payload),),
        )

    @classmethod
    def _validate_review_evidence(
        cls,
        draft: ImmutableArtifactDraft,
        evidence: FrozenLineageEvidence,
    ) -> None:
        snapshot = evidence.review_snapshot
        payload = draft.payload
        actual = payload.get("actual_evidence")
        if snapshot is None or not isinstance(actual, list) or not actual:
            cls._fail(
                "FORECAST_REVIEW_EVIDENCE_SNAPSHOT_INVALID",
                "Review snapshot or actual evidence is missing.",
            )
        try:
            reviewed_at = datetime.fromisoformat(
                str(payload.get("reviewed_at")).replace("Z", "+00:00")
            )
            snapshot_cutoff = datetime.fromisoformat(
                snapshot.as_of_at.replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            cls._fail(
                "FORECAST_REVIEW_EVIDENCE_SNAPSHOT_INVALID",
                "Review timestamps are invalid.",
            )
        if (
            snapshot.data_snapshot_id != payload.get("review_data_snapshot_id")
            or snapshot.scope_id != evidence.platform_security_id
            or snapshot.snapshot_purpose not in {"research", "workflow"}
            or snapshot.freshness_status != "valid"
            or snapshot.quality_status == "blocking"
            or snapshot_cutoff > reviewed_at
        ):
            cls._fail(
                "FORECAST_REVIEW_EVIDENCE_SNAPSHOT_INVALID",
                "Review snapshot is not valid frozen evidence.",
            )
        rows = {item.normalized_version_id: item for item in evidence.review_facts}
        if len(rows) != len(actual):
            cls._fail(
                "FORECAST_REVIEW_EVIDENCE_LINEAGE_INVALID",
                "Review evidence members are incomplete.",
            )
        for item in actual:
            if not isinstance(item, Mapping):
                cls._fail(
                    "FORECAST_REVIEW_EVIDENCE_SNAPSHOT_INVALID",
                    "Review evidence entries must be mappings.",
                )
            row = rows.get(str(item.get("normalized_version_id")))
            absent = item.get("comparability_status") in {
                "missing",
                "delayed_disclosure",
            }
            if row is None:
                cls._fail(
                    "FORECAST_REVIEW_EVIDENCE_LINEAGE_INVALID",
                    "A review evidence member is missing.",
                )
            try:
                available_at = datetime.fromisoformat(
                    row.available_at.replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                cls._fail(
                    "FORECAST_REVIEW_EVIDENCE_LINEAGE_INVALID",
                    "Review evidence availability is invalid.",
                )
            if (
                row.content_hash != item.get("semantic_content_hash")
                or row.source_identity != item.get("source_id")
                or row.source_authority != "official"
                or row.attempt_status != "complete"
                or row.quality_status in {"quarantine", "blocking"}
                or row.retrieved_at != item.get("retrieved_at")
                or row.attempt_retrieved_at != item.get("retrieved_at")
                or (not absent and row.published_at != item.get("published_at"))
                or (not absent and row.available_at != item.get("available_at"))
                or available_at > snapshot_cutoff
            ):
                cls._fail(
                    "FORECAST_REVIEW_EVIDENCE_LINEAGE_INVALID",
                    "Review evidence provenance does not match frozen rows.",
                )

    @staticmethod
    def _validate_typed_graph(

        drafts: tuple[ImmutableArtifactDraft, ...],
        *,
        subject_aliases: frozenset[str],
        market_data_snapshot_id: str | None,
        market_calibration: MarketCalibrationEvidence | None,
    ) -> str:
        by_kind = {draft.artifact_kind: draft for draft in drafts}
        data_snapshot = by_kind.get("DataSnapshot")
        if data_snapshot is None:
            raise ValueError("RESEARCH_ARTIFACT_DATA_SNAPSHOT_MISSING")
        model_snapshot_identity = data_snapshot.source_identity
        snapshot_payload = data_snapshot.payload
        subjects = {draft.subject_id for draft in drafts}
        if len(subjects) != 1:
            raise ValueError("RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH")
        subject_id = next(iter(subjects))
        if (
            subject_id not in subject_aliases
            or snapshot_payload.get("snapshot_id") != model_snapshot_identity
            or snapshot_payload.get("security_id") != subject_id
            or snapshot_payload.get("as_of") != data_snapshot.as_of
        ):
            raise ValueError("RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH")

        forecast = by_kind.get("Forecast")
        if forecast is not None:
            forecast_payload = forecast.payload
            if not ArtifactLineage._forecast_payload_matches(
                forecast_payload,
                graph_identity=forecast.source_identity,
                subject_id=subject_id,
                model_snapshot_identity=model_snapshot_identity,
                as_of=forecast.as_of,
            ):
                raise ValueError("RESEARCH_ARTIFACT_FORECAST_LINEAGE_MISMATCH")
            forecast_structure = forecast_structure_identity(forecast_payload)
        else:
            forecast_structure = None

        valuation = by_kind.get("Valuation")
        if valuation is not None:
            if forecast is None:
                raise ValueError("RESEARCH_ARTIFACT_FORECAST_MISSING")
            payload = valuation.payload
            scenarios = payload.get("scenarios")
            if not isinstance(scenarios, list) or not scenarios:
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
            scenario_graphs = [
                scenario.get("forecast_graph")
                for scenario in scenarios
                if isinstance(scenario, Mapping)
            ]
            if len(scenario_graphs) != len(scenarios) or any(
                not isinstance(graph, Mapping)
                or not ArtifactLineage._forecast_payload_matches(
                    graph,
                    graph_identity=str(graph.get("graph_id", "")),
                    subject_id=subject_id,
                    model_snapshot_identity=model_snapshot_identity,
                    as_of=valuation.as_of,
                )
                for graph in scenario_graphs
            ):
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
            scenario_structures = {
                forecast_structure_identity(graph) for graph in scenario_graphs
            }
            if scenario_structures != {forecast_structure}:
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
            source_value = {
                "forecast_graph_identity": forecast.source_identity,
                "forecast_structure_identity": forecast_structure,
                "forecast_graph_ids": [graph["graph_id"] for graph in scenario_graphs],
                "model_data_snapshot_identity": model_snapshot_identity,
            }
            expected_source = "deterministic-scenario-set:" + hashlib.sha256(
                json.dumps(
                    source_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if (
                valuation.source_identity != expected_source
                or valuation.summary.get("forecast_graph_identity")
                != forecast.source_identity
                or valuation.summary.get("forecast_structure_identity")
                != forecast_structure
                or valuation.summary.get("model_data_snapshot_identity")
                != model_snapshot_identity
            ):
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_LINEAGE_MISMATCH")
        simulation = by_kind.get("Simulation")
        if simulation is not None:
            if valuation is None:
                raise ValueError("RESEARCH_ARTIFACT_VALUATION_MISSING")
            payload = simulation.payload
            fallback = payload.get("deterministic_fallback")
            source_value = {
                "simulation_id": payload.get("simulation_id"),
                "valuation_input_fingerprint": valuation.content_hash,
                "simulation_model_identity": payload.get("model_identity"),
                "simulation_policy_identity": payload.get("policy_identity"),
                "assumptions": payload.get("assumptions"),
                "dependency_model": payload.get("dependency_model"),
                "valuation_model": payload.get("valuation_model"),
                "deterministic_fallback": fallback,
                "tail_threshold": payload.get("tail_threshold"),
                "budget": payload.get("budget"),
            }
            expected_source = "valuation-simulation:" + hashlib.sha256(
                json.dumps(
                    source_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if (
                payload.get("security_id") != subject_id
                or payload.get("as_of") != simulation.as_of
                or payload.get("valuation_source_identity")
                != valuation.source_identity
                or simulation.summary.get("valuation_source_identity")
                != valuation.source_identity
                or simulation.summary.get("valuation_input_fingerprint")
                != valuation.content_hash
                or payload.get("simulation_id")
                != simulation.summary.get("simulation_id")
                or not isinstance(fallback, Mapping)
                or not simulation_fallback_matches_valuation(
                    fallback,
                    valuation.payload,
                )
                or simulation.source_identity != expected_source
            ):
                raise ValueError("RESEARCH_ARTIFACT_SIMULATION_LINEAGE_MISMATCH")
        market_data = by_kind.get("MarketDataSnapshot")
        if market_data is not None:
            payload = market_data.payload
            expected_source = "market-data-snapshot:" + hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if (
                payload.get("as_of") != market_data.as_of
                or payload.get("snapshot_id")
                != market_data.summary.get("snapshot_id")
                or payload.get("market") != market_data.summary.get("market")
                or payload.get("market_timezone")
                != market_data.summary.get("market_timezone")
                or payload.get("series_identity")
                != market_data.summary.get("series_identity")
                or payload.get("trading_calendar_identity")
                != market_data.summary.get("trading_calendar_identity")
                or len(payload.get("observations", ()))
                != market_data.summary.get("observation_count")
                or market_data.source_identity != expected_source
            ):
                raise ValueError(
                    "RESEARCH_ARTIFACT_MARKET_DATA_LINEAGE_MISMATCH"
                )
            ArtifactLineage._validate_market_calibration(
                payload,
                subject_aliases=subject_aliases,
                market_data_snapshot_id=market_data_snapshot_id,
                market_path=by_kind.get("MarketPathSimulation"),
                evidence=market_calibration,
            )
        market_path = by_kind.get("MarketPathSimulation")
        if market_path is not None:
            from equity_research import MarketPathEngine

            if simulation is None or market_data is None:
                raise ValueError(
                    "RESEARCH_ARTIFACT_MARKET_PATH_PARENT_MISSING"
                )
            payload = market_path.payload
            fallback = simulation.payload.get("deterministic_fallback")
            constraints = payload.get("constraints")
            budget = payload.get("budget")
            if not isinstance(constraints, Mapping) or not isinstance(
                budget,
                Mapping,
            ):
                raise ValueError(
                    "RESEARCH_ARTIFACT_MARKET_PATH_LINEAGE_MISMATCH"
                )
            lag = constraints.get("minimum_execution_lag_sessions")
            horizon = budget.get("horizon_sessions")
            if not isinstance(lag, int) or not isinstance(horizon, int):
                raise ValueError(
                    "RESEARCH_ARTIFACT_MARKET_PATH_LINEAGE_MISMATCH"
                )
            source_value = {
                "simulation_id": payload.get("simulation_id"),
                "as_of_at": payload.get("as_of_at"),
                "valuation_simulation_input_fingerprint": simulation.content_hash,
                "market_data_snapshot_identity": market_data.source_identity,
                "market_data_input_fingerprint": market_data.content_hash,
                "market_path_model_identity": payload.get("model_identity"),
                "market_path_policy_identity": payload.get("policy_identity"),
                "price_unit": payload.get("price_unit"),
                "currency": payload.get("currency"),
                "calibration": payload.get("calibration"),
                "constraints": payload.get("constraints"),
                "budget": payload.get("budget"),
                "starting_price": payload.get("starting_price"),
                "starting_price_session": payload.get(
                    "starting_price_session"
                ),
                "starting_price_member_id": payload.get(
                    "starting_price_member_id"
                ),
                "starting_price_available_at": payload.get(
                    "starting_price_available_at"
                ),
                "starting_price_evidence_refs": payload.get(
                    "starting_price_evidence_refs"
                ),
                "current_market_state": payload.get("current_market_state"),
                "current_state_available_at": payload.get(
                    "current_state_available_at"
                ),
                "current_state_evidence_refs": payload.get(
                    "current_state_evidence_refs"
                ),
                "price_thresholds": payload.get("price_thresholds"),
                "tail_return_threshold": payload.get(
                    "tail_return_threshold"
                ),
            }
            expected_source = "market-path-simulation:" + hashlib.sha256(
                json.dumps(
                    source_value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if (
                payload.get("security_id") != subject_id
                or payload.get("as_of") != market_path.as_of
                or payload.get("valuation_simulation_source_identity")
                != simulation.source_identity
                or market_path.summary.get(
                    "valuation_simulation_source_identity"
                )
                != simulation.source_identity
                or market_path.summary.get(
                    "valuation_simulation_input_fingerprint"
                )
                != simulation.content_hash
                or payload.get("calibration") != market_data.payload
                or market_path.summary.get("market_data_snapshot_identity")
                != market_data.source_identity
                or market_path.summary.get("market_data_input_fingerprint")
                != market_data.content_hash
                or payload.get("interpretation")
                != market_path.summary.get("interpretation")
                or payload.get("interpretation")
                != MarketPathEngine.INTERPRETATION
                or not isinstance(fallback, Mapping)
                or payload.get("currency") != fallback.get("currency")
                or payload.get("horizon_return_basis")
                != "net_of_declared_round_trip_transaction_costs"
                or payload.get("execution_period")
                != f"T+{lag} trading sessions"
                or payload.get("terminal_period")
                != f"T+{lag + horizon} trading sessions"
                or payload.get("risk_horizon_period")
                != (
                    f"T+{lag} through T+{lag + horizon} trading sessions"
                )
                or market_path.source_identity != expected_source
            ):
                raise ValueError("RESEARCH_ARTIFACT_MARKET_PATH_LINEAGE_MISMATCH")
        return model_snapshot_identity


    @staticmethod
    def _validate_market_calibration(

        payload: Mapping[str, object],
        *,
        subject_aliases: frozenset[str],
        market_data_snapshot_id: str | None,
        market_path: ImmutableArtifactDraft | None,
        evidence: MarketCalibrationEvidence | None,
    ) -> None:
        if (
            market_data_snapshot_id is None
            or payload.get("platform_snapshot_id")
            != market_data_snapshot_id
            or market_path is None
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_SNAPSHOT_UNBOUND"
            )
        if evidence is None:
            raise ValueError("RESEARCH_ARTIFACT_MARKET_DATA_SNAPSHOT_INVALID")
        snapshot = evidence.snapshot
        if (
            snapshot is None
            or snapshot["scope_id"] not in subject_aliases
            or snapshot["snapshot_purpose"] not in {"workflow", "market"}
            or snapshot["freshness_status"] != "valid"
            or snapshot["quality_status"] == "blocking"
            or snapshot["market_timezone"] != payload.get("market_timezone")
            or snapshot["calendar_version"]
            != payload.get("trading_calendar_identity")
            or snapshot["effective_session_date"]
            != market_path.payload.get("starting_price_session")
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_SNAPSHOT_INVALID"
            )
        try:
            snapshot_cutoff = datetime.fromisoformat(
                str(snapshot["as_of_at"]).replace("Z", "+00:00")
            )
            result_cutoff = datetime.fromisoformat(
                str(market_path.payload.get("as_of_at")).replace(
                    "Z",
                    "+00:00",
                )
            )
        except (TypeError, ValueError):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_SNAPSHOT_INVALID"
            ) from None
        if (
            snapshot_cutoff.tzinfo is None
            or result_cutoff.tzinfo is None
            or snapshot_cutoff > result_cutoff
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_SNAPSHOT_INVALID"
            )
        calendar_ids = tuple(payload.get("calendar_member_ids", ()))
        next_calendar_id = payload.get(
            "next_session_calendar_member_id"
        )
        series_ids = tuple(payload.get("series_member_ids", ()))
        adjustment_ids = tuple(payload.get("adjustment_member_ids", ()))
        corporate_action_ids = tuple(
            payload.get("corporate_action_member_ids", ())
        )
        member_ids = (
            *calendar_ids,
            next_calendar_id,
            *series_ids,
            *adjustment_ids,
            *corporate_action_ids,
        )
        if (
            not calendar_ids
            or not series_ids
            or not isinstance(next_calendar_id, str)
            or not next_calendar_id
            or len(member_ids) != len(set(member_ids))
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_MEMBER_INVALID"
            )
        rows = evidence.members
        if len(rows) != len(member_ids):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_MEMBER_INVALID"
            )
        by_id = {row["normalized_version_id"]: row for row in rows}
        try:
            if any(
                row["quality_status"] not in {"pass", "warning"}
                or not row["source_identity"]
                or not row["source_authority"]
                or datetime.fromisoformat(
                    str(row["available_at"]).replace("Z", "+00:00")
                )
                > snapshot_cutoff
                for row in rows
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_MEMBER_INVALID"
            ) from None
        if (
            any(by_id[item]["dataset"] != "trade_cal" for item in calendar_ids)
            or by_id[next_calendar_id]["dataset"] != "trade_cal"
            or any(by_id[item]["dataset"] != "daily" for item in series_ids)
            or any(
                by_id[item]["dataset"] != "adj_factor"
                for item in adjustment_ids
            )
            or any(
                by_id[item]["dataset"] != "corporate_action"
                for item in corporate_action_ids
            )
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_DATA_MEMBER_ROLE_INVALID"
            )
        calendar_rows = evidence.calendar_rows
        trading_sessions = tuple(payload.get("trading_sessions", ()))
        snapshot_calendar_rows = evidence.snapshot_calendar_rows
        if (
            len(calendar_rows) != len(calendar_ids)
            or {row["normalized_version_id"] for row in calendar_rows}
            != set(calendar_ids)
            or any(
                row["market"] != payload.get("market")
                or row["is_open"] != 1
                or row["calendar_version"]
                != payload.get("trading_calendar_identity")
                for row in calendar_rows
            )
            or tuple(
                sorted(row["session_date"] for row in calendar_rows)
            )
            != trading_sessions
            or {
                row["normalized_version_id"]
                for row in snapshot_calendar_rows
            }
            != set(calendar_ids)
            or tuple(
                sorted(row["session_date"] for row in snapshot_calendar_rows)
            )
            != trading_sessions
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_CALENDAR_INVALID"
            )
        next_calendar_rows = evidence.next_calendar_rows
        if (
            len(next_calendar_rows) != 1
            or next_calendar_rows[0]["normalized_version_id"]
            != next_calendar_id
            or next_calendar_rows[0]["session_date"]
            != payload.get("next_session_date")
            or next_calendar_rows[0]["session_date"]
            != market_path.payload.get("starting_price_session")
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_CALENDAR_ADJACENCY_INVALID"
            )
        known_open_rows = evidence.known_open_rows
        try:
            known_open_sessions = {
                row["session_date"]
                for row in known_open_rows
                if datetime.fromisoformat(
                    str(row["available_at"]).replace("Z", "+00:00")
                )
                <= snapshot_cutoff
            }
        except (TypeError, ValueError):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_CALENDAR_ADJACENCY_INVALID"
            ) from None
        if known_open_sessions != {
            market_path.payload.get("starting_price_session")
        }:
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_CALENDAR_ADJACENCY_INVALID"
            )
        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise ValueError("RESEARCH_ARTIFACT_MARKET_SERIES_INVALID")
        observation_by_session = {
            item.get("session_date"): item
            for item in observations
            if isinstance(item, Mapping)
        }
        series_rows = evidence.series_rows
        snapshot_series_rows = evidence.snapshot_series_rows
        try:
            series_valid = (
                len(series_rows) == len(series_ids)
                and {
                    row["normalized_version_id"] for row in series_rows
                }
                == set(series_ids)
                and {
                    row["session_date"] for row in series_rows
                }
                == set(trading_sessions)
                and {
                    row["normalized_version_id"]
                    for row in snapshot_series_rows
                }
                == set(series_ids)
                and {
                    row["session_date"] for row in snapshot_series_rows
                }
                == set(trading_sessions)
                and all(
                    row["security_id"] in subject_aliases
                    and row["market_timezone"]
                    == payload.get("market_timezone")
                    and row["adjustment_mode"] == "none"
                    and row["currency"]
                    == market_path.payload.get("currency")
                    and Decimal(row["close_decimal"])
                    == Decimal(
                        str(
                            observation_by_session[row["session_date"]][
                                "unadjusted_close"
                            ]
                        )
                    )
                    and datetime.fromisoformat(
                        str(
                            observation_by_session[row["session_date"]][
                                "close_available_at"
                            ]
                        ).replace("Z", "+00:00")
                    )
                    == datetime.fromisoformat(
                        str(
                            by_id[row["normalized_version_id"]][
                                "available_at"
                            ]
                        ).replace("Z", "+00:00")
                    )
                    and datetime.fromisoformat(
                        str(
                            observation_by_session[row["session_date"]][
                                "factor_available_at"
                            ]
                        ).replace("Z", "+00:00")
                    )
                    == datetime.fromisoformat(
                        str(
                            by_id[row["normalized_version_id"]][
                                "available_at"
                            ]
                        ).replace("Z", "+00:00")
                    )
                    and datetime.fromisoformat(
                        str(
                            observation_by_session[row["session_date"]][
                                "retrieved_at"
                            ]
                        ).replace("Z", "+00:00")
                    )
                    == datetime.fromisoformat(
                        str(
                            by_id[row["normalized_version_id"]][
                                "retrieved_at"
                            ]
                        ).replace("Z", "+00:00")
                    )
                    for row in series_rows
                )
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            series_valid = False
        if not series_valid:
            raise ValueError("RESEARCH_ARTIFACT_MARKET_SERIES_INVALID")
        starting_member_id = market_path.payload.get(
            "starting_price_member_id"
        )
        starting_row = evidence.starting_row
        try:
            starting_valid = (
                starting_row is not None
                and starting_row["dataset"] == "daily"
                and starting_row["quality_status"] in {"pass", "warning"}
                and bool(starting_row["source_identity"])
                and bool(starting_row["source_authority"])
                and starting_row["security_id"] in subject_aliases
                and starting_row["session_date"]
                == market_path.payload.get("starting_price_session")
                and starting_row["session_date"]
                <= market_path.payload.get("as_of")
                and starting_row["market_timezone"]
                == payload.get("market_timezone")
                and starting_row["adjustment_mode"] == "none"
                and starting_row["currency"]
                == market_path.payload.get("currency")
                and Decimal(starting_row["close_decimal"])
                == Decimal(str(market_path.payload.get("starting_price")))
                and datetime.fromisoformat(
                    str(starting_row["available_at"]).replace(
                        "Z",
                        "+00:00",
                    )
                )
                <= snapshot_cutoff
                and datetime.fromisoformat(
                    str(
                        market_path.payload.get(
                            "starting_price_available_at"
                        )
                    ).replace("Z", "+00:00")
                )
                == datetime.fromisoformat(
                    str(starting_row["available_at"]).replace(
                        "Z",
                        "+00:00",
                    )
                )
                and starting_member_id
                in market_path.payload.get(
                    "starting_price_evidence_refs",
                    (),
                )
            )
        except (InvalidOperation, TypeError, ValueError):
            starting_valid = False
        if not starting_valid:
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_STARTING_PRICE_INVALID"
            )
        state_model_identity = payload.get("state_model_identity")
        if state_model_identity != "one_session_return_sign@1":
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_STATE_LINEAGE_INVALID"
            )

        def state(current: Decimal, previous: Decimal) -> str:
            if current > previous:
                return "risk_on"
            if current < previous:
                return "risk_off"
            return "flat"

        try:
            adjusted = tuple(
                Decimal(str(item["unadjusted_close"]))
                * Decimal(str(item["adjustment_factor"]))
                for item in observations
            )
            for index, item in enumerate(observations):
                expected = (
                    "warmup"
                    if index == 0
                    else state(adjusted[index], adjusted[index - 1])
                )
                required_refs = {series_ids[index]}
                required_available = datetime.fromisoformat(
                    str(by_id[series_ids[index]]["available_at"]).replace(
                        "Z",
                        "+00:00",
                    )
                )
                if index:
                    required_refs.add(series_ids[index - 1])
                    required_available = max(
                        required_available,
                        datetime.fromisoformat(
                            str(
                                by_id[series_ids[index - 1]][
                                    "available_at"
                                ]
                            ).replace("Z", "+00:00")
                        ),
                    )
                state_available = datetime.fromisoformat(
                    str(item["state_available_at"]).replace("Z", "+00:00")
                )
                if (
                    item.get("market_state") != expected
                    or not required_refs.issubset(
                        item.get("evidence_refs", ())
                    )
                    or state_available < required_available
                    or state_available > snapshot_cutoff
                ):
                    raise ValueError
            starting_price = Decimal(
                str(market_path.payload.get("starting_price"))
            )
            expected_current = state(starting_price, adjusted[-1])
            current_refs = {
                starting_member_id,
                series_ids[-1],
                state_model_identity,
            }
            current_available = datetime.fromisoformat(
                str(
                    market_path.payload.get("current_state_available_at")
                ).replace("Z", "+00:00")
            )
            if (
                market_path.payload.get("current_market_state")
                != expected_current
                or not current_refs.issubset(
                    market_path.payload.get(
                        "current_state_evidence_refs",
                        (),
                    )
                )
                or current_available
                < max(
                    datetime.fromisoformat(
                        str(starting_row["available_at"]).replace(
                            "Z",
                            "+00:00",
                        )
                    ),
                    datetime.fromisoformat(
                        str(by_id[series_ids[-1]]["available_at"]).replace(
                            "Z",
                            "+00:00",
                        )
                    ),
                )
                or current_available > snapshot_cutoff
            ):
                raise ValueError
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_STATE_LINEAGE_INVALID"
            ) from None
        factors = {
            str(item.get("adjustment_factor"))
            for item in observations
            if isinstance(item, Mapping)
        }
        actions = {
            str(item.get("corporate_action_identity"))
            for item in observations
            if isinstance(item, Mapping)
            and item.get("corporate_action_identity")
        }
        if (
            factors != {"1"}
            or actions
            or adjustment_ids
            or corporate_action_ids
        ):
            raise ValueError(
                "RESEARCH_ARTIFACT_MARKET_ACTION_LINEAGE_INVALID"
            )


    @staticmethod
    def _forecast_payload_matches(
        payload: Mapping[str, object],
        *,
        graph_identity: str,
        subject_id: str,
        model_snapshot_identity: str,
        as_of: str,
    ) -> bool:
        nodes = payload.get("nodes")
        return (
            payload.get("graph_id") == graph_identity
            and payload.get("security_id") == subject_id
            and payload.get("data_snapshot_id") == model_snapshot_identity
            and isinstance(nodes, list)
            and bool(nodes)
            and all(
                isinstance(node, Mapping)
                and isinstance(node.get("quantity"), Mapping)
                and node["quantity"].get("as_of") == as_of
                for node in nodes
            )
        )


    @classmethod
    def _validate_parent_identity(
        cls,
        submission: ArtifactSubmission,
        evidence: FrozenLineageEvidence,
    ) -> None:
        if (
            submission.research_run_id != evidence.research_run_id
            or submission.workflow_run_id != evidence.workflow_run_id
            or submission.data_snapshot_id != evidence.research_snapshot_id
            or submission.code_identity != evidence.engine_code_identity
        ):
            cls._fail(
                "RESEARCH_ARTIFACT_PARENT_IDENTITY_MISMATCH",
                "Artifact submission does not match its frozen parent identities.",
            )

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise ArtifactLineageError(code, message)
