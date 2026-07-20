from __future__ import annotations

from typing import Mapping

from equity_research import ForecastReviewEngine, ForecastReviewRequest
from trading_platform.application.workflow_ledger import (
    ForecastReviewCommit,
    ManifestQuery,
    ResearchArtifactQuery,
    ResearchPayloadQuery,
    WorkflowHistoryQuery,
    WorkflowLedgerPort,
)
from trading_platform.domain.workflow import (
    ArtifactManifestView,
    ImmutableArtifactDraft,
    ResearchArtifactView,
    WorkflowHistory,
)


class WorkflowInspection:
    def __init__(self, ledger: WorkflowLedgerPort) -> None:
        self._ledger = ledger

    def inspect(self, workflow_run_id: str) -> WorkflowHistory:
        return self._ledger.load(WorkflowHistoryQuery(workflow_run_id))


class ResearchArchive:
    def __init__(self, ledger: WorkflowLedgerPort) -> None:
        self._ledger = ledger

    def manifest(self, manifest_id: str) -> ArtifactManifestView:
        return self._ledger.load(ManifestQuery(manifest_id))

    def artifact(self, artifact_record_id: str) -> ResearchArtifactView:
        return self._ledger.load(ResearchArtifactQuery(artifact_record_id))

    def source_payload(self, research_run_id: str) -> Mapping[str, object]:
        return self._ledger.load(ResearchPayloadQuery(research_run_id))


class ForecastReview:
    def __init__(self, ledger: WorkflowLedgerPort, code_identity: str) -> None:
        self._ledger = ledger
        self._code_identity = code_identity

    def review(self, request: ForecastReviewRequest) -> ResearchArtifactView:
        forecast = self._ledger.load(
            ResearchArtifactQuery(request.forecast_artifact_record_id)
        )
        valuation = self._ledger.load(
            ResearchArtifactQuery(request.valuation_artifact_record_id)
        )
        simulation = self._ledger.load(
            ResearchArtifactQuery(request.simulation_artifact_record_id)
        )
        draft = ImmutableArtifactDraft.from_forecast_review(
            ForecastReviewEngine().run(request),
            forecast_artifact=forecast,
            valuation_artifact=valuation,
            simulation_artifact=simulation,
        )
        record_id = self._ledger.commit_artifacts(
            ForecastReviewCommit(
                draft=draft,
                parent_record_ids=(
                    forecast.artifact_record_id,
                    valuation.artifact_record_id,
                    simulation.artifact_record_id,
                ),
                code_identity=self._code_identity,
            )
        )
        return self._ledger.load(ResearchArtifactQuery(record_id))
