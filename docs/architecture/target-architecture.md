# Target architecture: named tasks over deterministic domain modules

## Application boundary

The platform CLI is the sole maintenance and formal research entry. Static
composition constructs exactly the named task required by a command and owns
its lifetime; it does not expose a root, task bag, string lookup, or persistence
object.

```text
CLI adapter
  -> Health / DataSynchronization / ApplicationCommandDispatcher
  -> ManualPortfolioReview
  -> ResearchWorkflow / WorkflowInspection / ResearchArchive / ForecastReview
  -> Watchlist / Account / Market / Maintenance
  -> domain modules
  -> persistence adapters
```

`ManualPortfolioReview` owns the explicit complete-session portfolio review,
last-successful cutoff, per-holding continuation, and frozen manifest. Data
sync and research remain separate evidence-producing tasks and never schedule
or trigger portfolio review. `ProviderQualificationService` alone owns
the live qualification sequence. Watchlist identity, invocation replay, and
transaction rules are implemented by the canonical SQLite Watchlist task;
`PlatformStore` does not forward them.

The Web adapter receives explicit DecisionWorkspace, ChartWorkspace,
ChartAnnotations, TradePlan, and update-authorization tasks. It projects typed
results and does not receive a root object, container, or facade.

## Research and presentation

```text
ResearchWorkflow.handle(StartResearchWorkflow(request))
  -> immutable ResearchWorkflowRequest@2 with frozen DataSnapshot and ResearchEvaluationPlan
  -> deterministic ResearchEngine
  -> ForecastGraphIdentity@2
  -> ScenarioValuationEngine
  -> optional Simulation and MarketPathSimulation
  -> persisted ResearchDecisionView@2
  -> persisted decision-first HTML
```

`ResearchWorkflow.handle` owns lifecycle, lease, checkpoint, retry,
cancellation, and transition policy. `ResearchExecution.execute` owns selected
node execution and research gates without changing lifecycle state.

The immutable source JSON remains evidence for the deterministic engine run.
Its paired source HTML is an identity-only serialization, not a report. Formal
JSON, HTML, workspace, archive, and XLSX presentation load the persisted
`ResearchDecisionView@2`; renderers do not interpret source narrative fields or
recompute research and valuation semantics.

## Dependency direction

```text
CLI / Web / provider / filesystem adapters
  -> named application tasks
  -> Forecast, valuation, workflow, account, plan, chart, and market domains
  <- persistence implementations
```

Only `application/bootstrap.py` wires concrete production adapters. Application
journey tests cross named task interfaces. Persistence adapter, migration, and
corruption tests alone may use owned database fault seams.

Manual review materializes eligible `DecisionTask@1` identities in the same
SQLite transaction as its frozen items and manifest. Task state is projected
only from append-only `DecisionTaskTransition@1` records. User disposition
crosses the shared application envelope; typed workflow transitions may reopen
the same deferred task or supersede it, but no adapter maintains an in-memory
or broker-derived task state.

`DecisionJournal` is the sole immutable behavior/execution path. Its SQLite
adapter commits the user action, optional user-declared execution, linked task
transition, and application receipt in one transaction. The same adapter
implements the `ExecutionRecordReader` consumed by estimated account state;
corrections replace projection inputs through immutable links and never update
the confirmed account snapshot. Missing broker evidence stays explicitly
unverified.

`DisciplineReviews` derives immutable weekly/custom review versions from those
task and journal authorities. Period boundaries are proven complete
Asia/Shanghai sessions rather than scheduler or Friday assumptions.
Confirmation appends a version and receipt; later drafts never rewrite prior
versions. Monthly reporting is a deterministic aggregation of confirmed
versions, not a second persistence model.

`PlanImpacts` consumes only the immutable manual-review item/manifest and its
referenced ReviewRule. The domain owns evidence-bound assessment identity,
unable-state preservation, the finite canonical content patch, and immutable
proposal revisions. The SQLite adapter owns frozen authority proof,
active-base concurrency, replay, and append-only disposition history.
Accepting a proposal delegates to the existing `TradePlanTasks` draft
operation and stops at an open draft; only the existing canonical diff,
confirmation challenge, and explicit user-confirmation path can change the
active plan.

`ReadModelService` owns six frozen application presentation contracts and one
deterministic codec shared by Skill and Web. `SQLiteReadModelProjection`
rebuilds them from snapshot, estimated-state, plan, review, journal, proposal,
and persisted research authority; no projection table or second truth model
exists. The portfolio home DTO exposes only its five decision-summary groups.
Holding, plan, review, research, and account-editor DTOs keep diagnostics and
provenance behind detail fields while preserving explicit
known/unknown/not-applicable, unable, and unverified states. The unversioned
`DecisionWorkspace` mapping and Python `/api/workspace` route are deleted.

## Data, privacy, and financial boundaries

- Official disclosures are canonical for critical financial facts.
- Structured aggregators retain their real source identity and cannot upgrade
  themselves to official authority.
- Every critical number has source identity or is explicitly missing.
- Immutable artifacts, manifests, Workflow history, and point-in-time identities
  are never rewritten by ordinary runtime paths.
- Credentials and personal account data remain local and are excluded from Git.
- Default research output never contains personalized buy, sell, hold, rating,
  or target-price instructions.
