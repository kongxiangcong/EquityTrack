# Issue 15 deepening audit

Date: 2026-07-25
Baseline: `3b3e99a`

## `domain.workflow`

Current size: 1,182 lines. The module owns general workflow/node contracts, the
entire `ImmutableArtifactDraft` factory family, research field semantics,
`ResearchProjection`, `ResearchWorkflowRequest`, result/history views, and
artifact views. Its interface forces callers to learn research artifact
canonicalization and lifecycle vocabulary together.

Deepening target: move the complete ResearchEvaluationPlan, Request@2,
research-artifact canonicalization, invariants, fingerprints, and typed
factories into one `domain.research_evaluation` module. The public interface is
the Request@2/plan values plus typed artifact factories. Deleting the module
would move canonicalization, cross-artifact invariants, and identity rules back
into workflow, presentation, and tests, so it passes the deletion test.

## `workflows.research`

Current size: 929 lines. `ResearchWorkflow` owns lifecycle/lease/checkpoint
policy, while `ResearchExecution` in the same file also owns projection
validation, source-manifest/PIT/quality gates, engine invocation, artifact
construction, and publication input preparation. `ResearchRunner` exposes a
fake variation at the external workflow interface even though the production
behavior is local.

Deepening target: a concrete local `ResearchEvaluation.evaluate(request,
frozen_evidence)` interface owns source/PIT/quality, Forecast, valuation,
simulation, artifact factories, and publication permission. Workflow retains
only lifecycle, checkpoint, retry, cancellation, and transition behavior.
Tests cross the evaluation interface or the public workflow seam; retired
private execution tests are deleted.

## `persistence.workflow_ledger`

Current size: 2,551 lines. The adapter owns general workflow transitions and
queries, object publication, projection freeze, research artifact bundle
validation/commit, decision-view materialization, legacy cutover, and final
manifest publication. Research commit logic spans many private methods and
shares transaction details with unrelated lifecycle behavior.

Deepening target: extract a private `ResearchArtifactCommit` implementation
that owns the complete transaction for research records, artifact objects,
typed artifact rows, the single View@2 manifest, references, and checkpoint
success. `WorkflowLedgerPort` remains the sole public persistence interface;
the extracted implementation is an internal seam, not a new port or mirrored
repository. Deleting it would re-spread transaction ordering, identity checks,
rollback, and replay rules into the ledger adapter, so it passes the deletion
test.

## Dependency classification

- Domain canonicalization and ResearchEvaluation are in-process dependencies.
- SQLite/object storage are local-substitutable through the existing
  `PlatformStore` test fixture.
- No new remote or true-external seam is introduced.
- Deterministic PDF is a local projection of persisted View@2 bytes and does
  not become a research or persistence interface.
