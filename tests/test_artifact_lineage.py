from dataclasses import replace

import pytest

from trading_platform.domain.artifact_lineage import (
    ArtifactLineage,
    ArtifactLineageError,
    ArtifactSubmission,
    FrozenLineageEvidence,
)
from trading_platform.domain.workflow import ImmutableArtifactDraft
from equity_research.forecast import ForecastEngine
from equity_research.scenario_valuation import ScenarioValuationEngine
from test_scenario_valuation import scenario_request


def _submission() -> tuple[ArtifactSubmission, FrozenLineageEvidence]:
    request = scenario_request()
    snapshot = request.base_forecast_request.data_snapshot
    draft = ImmutableArtifactDraft.from_data_snapshot(
        snapshot,
        model_identity="worked-model@1",
        policy_identity="worked-policy@1",
    )
    submission = ArtifactSubmission(
        research_run_id="research_worked",
        workflow_run_id="workflow_worked",
        data_snapshot_id="platform_snapshot_worked",
        code_identity="code-worked",
        drafts=(draft,),
    )
    evidence = FrozenLineageEvidence(
        research_run_id="research_worked",
        workflow_run_id="workflow_worked",
        platform_security_id="security_worked",
        subject_aliases=frozenset({"security_worked", snapshot.security_id}),
        research_snapshot_id="platform_snapshot_worked",
        model_data_snapshot_identity=snapshot.snapshot_id,
        original_cutoff_date=request.base_forecast_request.as_of,
        engine_code_identity="code-worked",
    )
    return submission, evidence


def test_artifact_lineage_validates_a_frozen_typed_graph_without_sqlite() -> None:
    submission, evidence = _submission()

    commit = ArtifactLineage.validate(submission, evidence)

    assert commit.model_data_snapshot_identity == "ds_2025fy"
    assert commit.record_ids == (
        "research_artifact_8ead9f3a6907141391882e94",
    )
    assert commit.envelopes[0].draft.artifact_kind == "DataSnapshot"
    assert commit.envelopes[0].dependency_record_ids == ()


def test_artifact_lineage_rejects_an_empty_graph_without_sqlite() -> None:
    submission, evidence = _submission()

    with pytest.raises(ArtifactLineageError) as error:
        ArtifactLineage.validate(replace(submission, drafts=()), evidence)

    assert error.value.code == "RESEARCH_ARTIFACT_GRAPH_EMPTY"


def test_artifact_lineage_fails_closed_on_parent_identity_or_subject_tamper() -> None:
    submission, evidence = _submission()

    with pytest.raises(ArtifactLineageError) as parent_error:
        ArtifactLineage.validate(
            submission,
            replace(evidence, engine_code_identity="other-code"),
        )
    assert parent_error.value.code == "RESEARCH_ARTIFACT_PARENT_IDENTITY_MISMATCH"

    with pytest.raises(ArtifactLineageError) as subject_error:
        ArtifactLineage.validate(
            submission,
            replace(evidence, subject_aliases=frozenset({"security_worked"})),
        )
    assert subject_error.value.code == "RESEARCH_ARTIFACT_SUBJECT_LINEAGE_MISMATCH"


def test_artifact_lineage_validates_roles_edges_and_exact_replay_without_sqlite() -> None:
    request = scenario_request()
    graph = ForecastEngine().build(request.base_forecast_request)
    valuation = ScenarioValuationEngine().run(request)
    drafts = (
        ImmutableArtifactDraft.from_data_snapshot(
            request.base_forecast_request.data_snapshot,
            model_identity="worked-model@1",
            policy_identity="worked-policy@1",
        ),
        ImmutableArtifactDraft.from_forecast_graph(
            graph,
            model_identity="worked-model@1",
            policy_identity="worked-policy@1",
        ),
        ImmutableArtifactDraft.from_scenario_valuation(
            valuation,
            forecast_graph=graph,
            model_identity="worked-model@1",
            policy_identity="worked-policy@1",
        ),
    )
    base_submission, evidence = _submission()
    submission = replace(base_submission, drafts=drafts)

    first = ArtifactLineage.validate(submission, evidence)
    replay = ArtifactLineage.validate(submission, evidence)

    assert replay == first
    assert tuple(item.draft.artifact_kind for item in first.envelopes) == (
        "DataSnapshot",
        "Forecast",
        "Valuation",
    )
    assert first.envelopes[-1].dependency_record_ids == (
        first.envelopes[1].record_id,
    )
    with pytest.raises(ArtifactLineageError) as order_error:
        ArtifactLineage.validate(
            replace(submission, drafts=(drafts[0], drafts[2], drafts[1])),
            evidence,
        )
    assert order_error.value.code == "RESEARCH_ARTIFACT_DEPENDENCY_ORDER_INVALID"
