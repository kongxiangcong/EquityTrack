# Target architecture: named tasks over deterministic domain modules

## Application boundary

The platform CLI is the sole maintenance and formal research entry. Static
composition constructs exactly the named task required by a command and owns
its lifetime; it does not expose a root, task bag, string lookup, or persistence
object.

```text
CLI adapter
  -> Health / DataSynchronization / DailyResearchCycle
  -> ResearchWorkflow / WorkflowInspection / ResearchArchive / ForecastReview
  -> Watchlist / Account / Market / Maintenance
  -> domain modules
  -> persistence adapters
```

`DailyResearchCycle` alone owns the daily sync → optional research → optional
market evaluation → doctor sequence. `ProviderQualificationService` alone owns
the live qualification sequence. Watchlist identity, invocation replay, and
transaction rules are implemented by the canonical SQLite Watchlist task;
`PlatformStore` does not forward them.

The Web adapter temporarily retains a Web-only `ApplicationFacade` for chart,
annotation, workspace-update authorization, and plan-confirmation routes. It
contains no CLI, research, data, watchlist, account, market, health, or
maintenance operation and is removed by the following Web cutover.

## Research and presentation

```text
ResearchWorkflow.handle(StartResearchWorkflow(request))
  -> frozen ResearchProjection and DataSnapshot
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
