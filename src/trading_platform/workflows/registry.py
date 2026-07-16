from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeDefinition:
    node_id: str
    version: str
    input_schema: str
    output_schema: str
    preconditions: tuple[str, ...]
    required: bool
    cache_policy: str
    retry_policy: str
    failure_codes: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    version: str
    nodes: tuple[NodeDefinition, ...]


RESEARCH_WORKFLOW = WorkflowDefinition(
    "run_or_reuse_research",
    "2",
    (
        NodeDefinition("freeze_research_projection", "1", "ResearchProjection@1", "ResearchSnapshotRef@1", ("security_exists", "projection_cutoff_legal", "field_semantics_complete"), True, "content_addressed", "new_attempt_same_run", ("RESEARCH_PROJECTION_INVALID", "SNAPSHOT_PURPOSE_COLLISION", "WORKFLOW_SNAPSHOT_INVALID")),
        NodeDefinition("run_or_link_research", "2", "ResearchSnapshotRef@1", "ResearchArtifactSetRef@1", ("research_snapshot_frozen",), True, "research_and_artifact_fingerprints", "new_attempt_same_run", ("RESEARCH_ENGINE_FAILED", "RESEARCH_ARTIFACT_PERSISTENCE_FAILED")),
        NodeDefinition("publish_run_manifest", "2", "ResearchArtifactSetRef@1", "ArtifactManifestRef@1", ("research_artifacts_committed",), True, "none", "new_attempt_same_run", ("MANIFEST_PUBLICATION_FAILED",)),
    ),
)
