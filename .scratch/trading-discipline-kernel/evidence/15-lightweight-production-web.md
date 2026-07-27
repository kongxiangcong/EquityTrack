# Ticket 15 — Lightweight production Web evidence

## Result

- Status: passed
- Acceptance: `TDK-AC-031`, `TDK-AC-032`
- Migration: none

## Implemented contract

- Primary navigation is exactly `总览`, `组合`, `复核`, and `研究`.
- The home page renders only the five `PortfolioWorkspaceView@1` decision
  groups: account state, unresolved tasks, material changes, active-plan
  summaries, and discipline exceptions.
- Confirmed and estimated account facts are labeled separately. Known,
  unknown, not-applicable, unable, and unverified states remain explicit;
  unknown values render as unknown and are never coerced to zero.
- Holding, review, and persisted-research pages consume their versioned
  application DTOs. Read-only plan detail and AccountSnapshot editor are
  dialogs; diagnostic/lineage/canonical-diff content begins collapsed.
- AccountSnapshot create/update/confirm posts
  `ApplicationCommandEnvelope@1` to the existing dispatcher. HTTP policy admits
  only `user:local-user`, `interaction_channel=web`,
  `transport_actor=adapter:web-local`, and `account_snapshot.*`. Agent
  confirmation and every non-account Web mutation fail closed.
- The server has six finite versioned GET routes, one finite shared-command
  POST route, strict local host/origin/CSRF/content-type/body-size checks,
  CSP/nosniff/referrer/opener headers, and no arbitrary query or direct SQLite
  surface.

## One-way replacement

- Removed `/api/workspace`, `/api/chart-series`, `/api/annotations`,
  `/api/update-authorizations`, public `daily`, and all production callers.
  Only explicit absence assertions and acceptance allowlists retain those
  strings.
- Deleted the old chart/research workspace DOM, annotation and authorization
  interactions, hard-coded single-security shell, retired renderer modules,
  private-seam tests, old hashed bundles, and copied KLineCharts licenses.
- Removed `klinecharts@10.0.0` from `package.json`, lockfile, runtime bundle,
  notices, and `node_modules`; the production browser runtime has no
  third-party dependency.
- CLI, README, and Skill now use `serve --account-id ... --security-id ...`;
  `--snapshot-id` is deleted.

## Production build evidence

```text
npm test
3 passed

npm run build
vite v7.0.6
4 modules transformed
dist/index.html                         6.90 kB
dist/assets/index-DFnvsgPV.css          3.89 kB
dist/assets/index-B09eXuhg.js          12.49 kB
```

Tracked production asset SHA-256:

```text
web/dist/index.html
1A313C20978AC3419BC5C183E7B4525F819C9BB04AA75262D824DB9132C7D674
web/dist/assets/index-B09eXuhg.js
A33928D8C05E0DE36BEB8B160AA419A383D0B1C514036EEC80ADE9A2000A88A9
web/dist/assets/index-DFnvsgPV.css
60236898C394A3BDE45451377123E2F6BC1B5E1A21078628C632475B9607F5BC
```

## Production CDP evidence

Command:

```text
python scripts/verify_issue05_browser.py --evidence-file .scratch/trading-discipline-kernel/evidence/15-browser-cdp.json
passed
```

The verifier launched a clean headless Chrome 150 profile against `web/dist`
and a synthetic temporary data root. It proved:

- exactly four primary navigation items and five home groups;
- no external browser resources;
- explicit unknown rendering, skip link, focusable main, one H1, and labeled
  dialogs;
- all six retired routes return 404;
- CSP, nosniff, no-referrer, and same-origin opener headers;
- plan diagnostics remain collapsed behind read-only detail;
- AccountSnapshot draft save, deterministic validation, explicit user
  confirmation, immutable v2 projection, and restart reconstruction;
- responsive 620 px layout and reduced-motion media behavior;
- zero console errors and zero network failures;
- screenshot capture for all four primary pages.

The first CDP runs correctly failed on three issues and were not counted:
asynchronous plan detail was checked before rendering, account confirmation
waited on an ambiguous status substring, and intentional 404 probes polluted
browser console evidence. After correction, visual inspection found a fourth
issue: the review renderer used retired field aliases and displayed
`undefined`. The renderer and CDP assertion were corrected, the production
bundle rebuilt, and all evidence regenerated.

Final browser evidence SHA-256:

```text
C0BC9541EBAA307D91FC74120FC045C94335712F7C47B47636AF4A886F2D7276
```

`AcceptanceEvidenceService.validate_browser_evidence(...)` returned passed and
verified all four PNG files against the hashes embedded in that JSON.

## Python verification

Focused production Web gate:

```text
python -m pytest -q tests/platform/test_production_web.py tests/platform/test_secure_workspace.py tests/platform/test_web_application_tasks.py tests/platform/test_versioned_read_models.py tests/platform/test_runtime_skeleton.py tests/platform/test_chart_annotations.py tests/platform/test_acceptance_evidence.py::test_browser_evidence_must_prove_real_cdp_journey tests/platform/test_operations_backup_restore.py::test_windows_cli_backup_restore_doctor_serve_history_and_secret_redaction
49 passed in 58.53s
```

Wider public-interface regression, excluding the final full canonical
acceptance command reserved for Ticket 16:

```text
python -m pytest -q tests/platform/test_account_snapshots.py tests/platform/test_action_log.py tests/platform/test_application_command_envelope.py tests/platform/test_discipline_reviews.py tests/platform/test_estimated_account_state.py tests/platform/test_execution_records.py tests/platform/test_manual_portfolio_review.py tests/platform/test_plan_change_proposals.py tests/platform/test_plan_confirmation.py tests/platform/test_plan_impact_assessments.py tests/platform/test_research_workflow.py tests/platform/test_trade_plan_model_b.py tests/platform/test_trade_plan_sleeves.py tests/platform/test_versioned_read_models.py tests/platform/test_web_application_tasks.py tests/platform/test_secure_workspace.py tests/platform/test_production_web.py tests/platform/test_chart_annotations.py tests/platform/test_workspace_persistence.py tests/platform/test_runtime_skeleton.py tests/platform/test_acceptance_evidence.py -k 'not acceptance_cli_executes_fixed_suites_and_freezes_evidence'
125 passed, 1 deselected in 93.10s
```

`python -m compileall -q src scripts/verify_issue05_browser.py` also passed.

## Mechanical self-audit

- Application DTO/codec, SQLite read projection, HTTP security/protocol
  adapter, browser rendering, and shared command dispatcher remain separate;
  no Web-specific business task or direct persistence access was added.
- Production mutation crosses the same envelope and named AccountSnapshot
  tasks as Skill/CLI. Plan confirmation, task disposition, execution entry,
  and discipline-review confirmation are absent from Web.
- Source/dist searches found no active retired route, caller, bundle import,
  `DecisionWorkspace`, KLineCharts dependency, compatibility alias, dual read,
  fallback, feature flag, dormant branch, `TODO`, or `FIXME`.
- Ticket 00 files remain untracked/unstaged and outside this evidence unit.
