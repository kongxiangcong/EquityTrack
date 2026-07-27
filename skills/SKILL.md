---
name: equity-researcher
description: Operate the local personal research platform and generate evidence-constrained equity research. Use for platform bootstrap, doctor, migration, sync, manual portfolio review, serving, tests, backup, restore, workflow resume/history, or company research and valuation requests. Never provide personalized trading instructions.
---

# Personal Research Platform

## Platform operations route

For initialization, maintenance, recovery, or local service requests, use the single deterministic control plane below. Do not assemble ad-hoc SQLite, archive, or server commands and do not load prompts into the business runtime.

```powershell
python -m trading_platform.cli bootstrap --data-root <root>
python -m trading_platform.cli health --data-root <root>
python -m trading_platform.cli doctor --data-root <root>
python -m trading_platform.cli migrate --data-root <root>
python -m trading_platform.cli sync --data-root <root> --job-file <job.json>
python -m trading_platform.cli research --data-root <root> --request-file <request.json>
python -m trading_platform.cli provider-qualify --data-root <root> --job-file <job.json>
python -m trading_platform.cli acceptance --data-root <root> --fixture-manifest <manifest.json> --live-qualification-artifact-id <artifact_id>
python -m trading_platform.cli serve --data-root <root> --web-root <web/dist> --account-id <id> --security-id <id>
python -m trading_platform.cli test --repo-root <repo>
python -m trading_platform.cli inventory --repo-root <repo>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
python -m trading_platform.cli switch-restored-root --restored-root <validated-new-root> --pointer-file <active-root.json>
python -m trading_platform.cli resume --data-root <root> --workflow-run-id <id> --owner-token <token>
python -m trading_platform.cli history --data-root <root> --workflow-run-id <id>
python -m trading_platform.cli archive --data-root <root> --kind manifest --id <id>
```

All formal business mutations use one serialized route:

```powershell
python -m trading_platform.cli application-command --data-root <root> --envelope-file <command.json>
```

`command.json` must be exactly `ApplicationCommandEnvelope@1`. The application,
not Skill or CLI, validates the versioned payload, computes the canonical
request hash, enforces capability, invokes the named task, and emits
`ApplicationCommandResult@1` or a typed failure.
Skill is the interaction channel, not the decision actor. A Skill request transported by Codex therefore
uses `interaction_channel = skill` and `transport_actor = agent:codex`; it may
use `decision_actor = user:<id>` only after the user explicitly confirms that
exact command. CLI is also only an adapter and never upgrades actor capability.

The finite mutation contracts are:

```text
account_snapshot.create_draft@1     CreateAccountSnapshotDraft@1
account_snapshot.update_draft@1     UpdateAccountSnapshotDraft@1
account_snapshot.confirm@1          ConfirmAccountSnapshot@1
trade_plan.create_draft@1           CreateTradePlanDraft@1
trade_plan.revise_draft@1           ReviseTradePlanDraft@1
trade_plan.reject_draft@1           RejectTradePlanDraft@1
trade_plan.issue_confirmation_challenge@1
                                     IssuePlanConfirmationChallenge@1
trade_plan.confirm@1                ConfirmTradePlanDraft@1
manual_portfolio_review.run@1       RunManualPortfolioReview@1
decision_task.defer@1               DeferDecisionTask@1
decision_task.resolve@1             ResolveDecisionTask@1
execution_record.declare@1          DeclareExecutionRecord@1
execution_record.correct@1          CorrectExecutionRecord@1
discipline_review.confirm@1         ConfirmDisciplineReview@1
plan_impact_assessment.create@1     CreatePlanImpactAssessment@1
plan_change_proposal.create@1       CreatePlanChangeProposal@1
plan_change_proposal.accept@1       AcceptPlanChangeProposal@1
plan_change_proposal.reject@1       RejectPlanChangeProposal@1
```

The registry is closed. Commands whose owning ticket has not landed fail
closed with `COMMAND_NOT_AVAILABLE`; their presence here reserves the canonical
name and payload contract and does not claim the capability is implemented.
Agents may create or revise drafts. Account confirmation, plan confirmation,
task disposition, execution truth, and review confirmation require the user as
decision actor. Plan confirmation additionally requires the unexpired,
unconsumed challenge ID in `approval.challenge_id`. Never use arbitrary Shell,
SQL, filesystem paths, provider destinations, credentials, or ad-hoc SQLite
access as an application-command payload.

`manual_portfolio_review.run@1` is the only public portfolio-review workflow.
Its `RunManualPortfolioReview@1` payload supplies `account_id`, `requested_at`,
an explicit `selected_complete_session`,
`first_window_start_exclusive` for the first review, and the current `code_identity` and
`config_identity`. The application proves the selected complete A-share
session, derives the confirmed snapshot and estimated state, and chooses the
last successful cutoff; the caller must not supply holdings, outcomes,
manifest IDs, task IDs, or a truth hash. Reviews are manual and may span
multiple sessions. Sync and research only produce evidence and never trigger a
review.

`decision_task.defer@1` and `decision_task.resolve@1` are the only user
task-disposition mutations. Both require `decision_actor = user:<id>` with an
explicitly confirmed command. Defer supplies `decision_task_id`,
`defer_target_type`, optional `defer_target_value`, and `occurred_at`; valid
targets are a specific date/session, the next manual review, or an exact
evidence trigger. Resolve supplies `decision_task_id`, `disposition`, `reason`,
and `occurred_at`. `skipped`, `overridden`, and `not_applicable` resolve
directly. `executed` fails closed until the same transaction contains the
required execution record. System workflow transitions may only reopen the
same persistent task when its typed condition fires, or supersede it when the
plan/condition is invalidated; they never create a user disposition.

`execution_record.declare@1` is the only command that resolves a task as
`executed`. Its `DeclareExecutionRecord@1` payload supplies
`decision_task_id`, `reason`, `effective_at`, `effective_session`,
`intent_type`, positive decimal `quantity`, explicit price and fee
state/value pairs, `currency`, and `confirmed_at`.
`execution_record.correct@1` supplies the original execution ID and the full
corrected record; it appends linked action/execution facts and never edits the
original. Both require an explicitly confirmed user decision actor. Unknown
price or fee remains unknown, makes dependent cash projection unknown, and is
never inferred. A user declaration is always
`user_declared_unverified` unless a future typed broker reconciliation record
proves another state; absence of broker evidence never means “not executed”.
The application atomically commits the action log, execution, task transition,
and receipt.

`DisciplineReviewVersion@1` is the only formal behavior-review contract.
Create its draft through the named application task using a `weekly` (default
presentation) or `custom` period whose start and end are proven complete
Asia/Shanghai A-share sessions. A period is not tied to Friday and no
scheduler starts it. The application derives task/action/execution/plan/
snapshot refs and overridden, skipped, deferred, unrecorded, and unverified
evidence; callers cannot classify behavior or supply a score.
`discipline_review.confirm@1` supplies `discipline_review_id`,
`expected_revision`, and `confirmed_at`, and requires an explicitly confirmed
user decision actor. Confirmation appends an immutable version. Monthly views
aggregate confirmed versions and do not create another workflow or table.

`plan_impact_assessment.create@1` lets an Agent author a typed finding only
against one immutable manual-review item, its frozen manifest, and one
ReviewRule from the referenced plan version. An unable rule remains
`unable_to_determine` with explicit uncertainty; the caller cannot upgrade it
to a determined finding. `plan_change_proposal.create@1` stores a finite
canonical content-replacement patch against that exact active plan version.
Only a user may call `plan_change_proposal.accept@1` or
`plan_change_proposal.reject@1`. Acceptance creates or revises an ordinary
open `TradePlanDraft`; it cannot issue or consume a confirmation challenge and
cannot activate a plan. The existing trade-plan challenge and user
confirmation commands remain mandatory.

Formal reads use the same six immutable application DTOs for Skill and Web:
`PortfolioWorkspaceView@1`, `HoldingWorkspaceView@1`,
`TradePlanDetailView@1`, `ReviewWorkspaceView@1`,
`ResearchIndexView@1`, and `AccountSnapshotEditorView@1`. Use
`open_read_models(...)` and the single `encode_read_model(...)` codec; adapters
must not rebuild or rename fields. Every DTO carries exact source IDs,
`generated_at`, a deterministic projection ID, and a content hash. The
portfolio home contract has exactly five summary groups: account state,
unresolved tasks, material changes, active-plan summaries, and discipline
exceptions. Unknown, unable, and unverified remain explicit. Full manifest,
policy, model, hash, and log detail is never promoted onto the home view.

The production local Web exposes those DTOs through six explicit versioned
read routes and has exactly four primary destinations: `总览`, `组合`, `复核`,
and `研究`. AccountSnapshot editing posts the same
`ApplicationCommandEnvelope@1` to the shared dispatcher and always identifies
an explicit local user; plan detail is read-only. Plan confirmation, task
disposition, execution entry, and discipline-review confirmation remain
Skill-first. `/api/workspace`, public `daily`, chart annotation routes, and
update-authorization routes are retired and have no aliases or fallbacks.

Only `ProviderJob@2` is accepted. Its provider block contains only `provider_id`, `adapter_version`, and `credential_env`; the production composition owns the fixed approved destination and transport. Immutable `QueryPolicy@1` owns typed dataset queries and `SourcePolicy@1` owns source authority, rights, freshness, completeness, retry, fallback, and failure disposition. There is no caller-supplied endpoint, provider class selector, or implicit fallback order. The Tushare-compatible market-data role uses `credential_env = TUSHARE_TOKEN`; the token value must remain in the process environment or an approved credential adapter. The statically composed CNINFO/SZSE official-filing roles use `credential_env = not_applicable` and must not read a credential. Official filing jobs persist verified document evidence and PIT metadata only; without a separately qualified semantic extractor they do not create financial facts. `provider-qualify` runs the same raw, normalization, quality, PIT, and persistence path as `sync`, persists a `ProviderQualificationReceipt@1` through the data root's authoritative object/artifact/command-receipt path, and returns its artifact ID. Acceptance resolves only that ID and rejects caller-authored qualification files.

Every command emits one JSON envelope and a typed error on failure. Credentials come only from the environment named by an explicit job configuration; never put credential values in job files, command lines, logs, database fields, backups, or artifacts. Backup archives are immutable and restore only into a new data root after full validation.

For company research requests, use the typed platform route below.

# Equity Research

Use one formal workflow for every new run:

```text
Frozen DataSnapshot
  -> Forecast Graph
  -> Scenario Valuation
  -> optional Monte Carlo / Market Path Simulation
  -> ResearchDecisionView@2
  -> canonical JSON + decision-first HTML + reconciled XLSX
```

The formal CLI invokes the named lifecycle task:

```python
ResearchWorkflow.handle(StartResearchWorkflow(request)) -> ResearchWorkflowResult
```

`WorkflowInspection`, `ResearchArchive`, and `ForecastReview` are separate
query/task seams. New execution uses typed request and artifact contracts; no
formal renderer reads source narrative magic keys or reconstructs valuation
semantics.

Python owns identity and date checks, evidence resolution, capability
readiness, method routing, calculations, simulation, immutable artifact
identity, reconciliation, permissions, and rendering.

## 1. Lock the request

Before collecting data, record:

- target company, ticker, listing venue, and market;
- `as_of_date`;
- reporting and trading currencies;
- accounting standard and latest reported period;
- requested depth and output language.

Use the same workflow for concise and deep research. Depth changes the amount of evidence and narrative, not the execution architecture or safety rules.

Completion criterion: the target identity and as-of boundary are unambiguous.

## 2. Build the Evidence Ledger

Use `references/source-manifest.md` as the manifest contract.

Prioritize:

1. exchange filings and official disclosures;
2. company investor-relations materials;
3. timestamped market-data terminals or APIs;
4. reputable news and secondary research for events and cross-checking.

Every critical number must resolve to a canonical evidence item. Keep estimates separate. An estimate may support a limited scenario but cannot upgrade official coverage.

If a field is unavailable, record it as missing and continue with unaffected capabilities. Do not use a single source-status flag to stop the whole run.

Completion criterion: every accepted fact has source identity, subject, period, unit, currency, availability date, and extraction metadata.

## 3. Route valuation methods

Read `valuation/valuation-method-router.md` before valuation. Read `valuation/dcf-and-sensitivity.md` only when DCF is selected or explicitly requested.

Apply method-specific gates:

- ordinary FCFF/WACC DCF requires an explicit forecast case, auditable WACC components, `WACC > g`, and a complete equity bridge;
- financial firms use P/B–ROE/COE, DDM, residual-income, or excess-return framing;
- pre-revenue biopharma uses rNPV/SOTP and cash-runway analysis;
- cyclical and resource companies use mid-cycle, SOTP, or NAV framing;
- peer conclusions require at least three comparable, source-compatible companies.

A disabled method limits only that method. It does not erase valid company research.

Completion criterion: every candidate method is `ready`, `limited`, `caution`, `blocked`, or `disabled`, with an evidence-backed reason.

## 4. Build typed Forecast and Valuation artifacts

Represent the company story as Event -> Driver -> Forecast Financial ->
Valuation transmission. Build stress, base, and improvement scenarios from
explicit driver conditions; do not create arbitrary percentage bands.

Route each scenario through every applicable method, including industry
specializations. Use Monte Carlo only after a frozen dependency model,
distributions, constraints, and valuation model exist. Keep simulated intrinsic
value and simulated market price paths as separate artifacts.

Completion criterion: typed Forecast and Valuation artifacts reconcile their
facts, formulas, diluted shares, equity bridges, identities, and source refs.

## 5. Build the decision-first view

`ResearchDecisionView@2` is the sole formal presentation model. It must expose:

- the future story and what would change it;
- key Drivers and scenario financials;
- method applicability and conditional value ranges;
- optional valuation distributions and market paths;
- value-market divergence without action language;
- a complete audit appendix with artifact, source, parameter, formula, model,
  policy, and code identities.

Formal JSON and HTML must serialize this exact view. XLSX must import the same
view, recompute every bridge step with formulas, and fail when canonical values
are hardcoded or links are broken.

## Financial boundary

- Provide educational company research, not personalized investment instructions.
- Use `valuation_view`, `risk_reward_summary`, `data_quality_grade`, `key_uncertainties`, and `what_would_change_the_view`.
- Do not publish a formal per-share valuation when its selected method or critical official inputs are blocked.
- Integrity errors fail closed to an audit memo and remove professional synthesis.
- A `completed_with_limits` run is a valid outcome when useful research is complete but some dimensions or methods remain limited.

## On-demand references

- Source schema and evidence rules: `references/source-manifest.md`
- Valuation routing: `valuation/valuation-method-router.md`
- Industry method matrix: `valuation/industry-valuation-matrix.md`
- Conditional DCF rules: `valuation/dcf-and-sensitivity.md`
