# 14 — Versioned read models

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 01, 02, 03, 10, 11, 12, 13

## Scope

Implement the six versioned, immutable presentation contracts consumed identically by Web and Skill: portfolio, holding, plan detail, review, research index, and account snapshot editor. Enforce progressive disclosure and explicit unknown/unverified/unable states.

## Exact files and symbols

- Add `src/trading_platform/application/read_models.py::{PortfolioWorkspaceViewV1,HoldingWorkspaceViewV1,TradePlanDetailViewV1,ReviewWorkspaceViewV1,ResearchIndexViewV1,AccountSnapshotEditorViewV1,ReadModelService}`.
- Add `src/trading_platform/persistence/read_models.py::SQLiteReadModelProjection`.
- Replace `src/trading_platform/application/web_tasks.py::DecisionWorkspace`.
- Update `src/trading_platform/application/bootstrap.py::{open_read_models}` and public application exports.
- Define stable codecs in `src/trading_platform/application/read_model_codecs.py`.

## Migration

No new migration. Read models project from 0015–0017 authority tables and existing research evidence. Persistent projection checkpoints, if used, must stay within already-defined cohort schemas and be rebuildable.

## Tests

- Add `tests/platform/test_versioned_read_models.py`.
- Replace workspace assertions in `tests/platform/test_web_application_tasks.py`, `tests/platform/test_account_workspace_plans.py`, and `tests/platform/test_secure_workspace.py`.
- Cover version tags, projection IDs/hashes, home-field allowlist/denylist, progressive disclosure, cross-channel serialization equality, unknown/unverified rendering, and restart rebuild.

## Dependency

Requires 01, 02, 03, 10, 11, 12, and 13. Ticket 15 exposes these views.

## Acceptance gate

TDK-AC-027 passes. `PortfolioWorkspaceView@1` contains only the five allowed summary groups and none of the forbidden diagnostic/provenance fields; Skill and Web receive the same serialized projection.

## Out of scope

HTML/CSS, Web routing, state-changing UI, arbitrary query endpoints, raw provenance wall, or copying domain entities directly into JSON.

## One-way cutover

Delete the unversioned `DecisionWorkspace`/workspace mapping and all callers. Do not retain `/api/workspace` payload compatibility or a second projection builder.

## Claim record

- External seams: six typed read queries on one `ReadModelService`, plus one
  stable application codec used identically by Skill and Web adapters.
- Deep-module ownership: immutable application DTOs own presentation
  allowlists, exact source identities, progressive-disclosure boundaries, and
  content hashes; SQLite projection owns cross-authority reads and explicit
  unknown/unverified/unable conversion; codecs own deterministic external
  serialization only.
- Old paths to replace: unversioned `DecisionWorkspace.build`, the monolithic
  workspace mapping, direct Web `WorkspaceService` reads, and channel-specific
  read serialization.
- Superseded artifacts to delete: `DecisionWorkspace`, `open_decision_workspace`,
  `/api/workspace` payload assumptions and fixtures, raw provenance/home
  diagnostics fields, duplicate Web/Skill projection builders, compatibility
  aliases, and tests tied to the retired mapping.

## Resolution evidence

- Added the six immutable `@1` application DTOs, one `ReadModelService`, one
  SQLite projection adapter, and one deterministic codec shared by external
  adapters.
- Portfolio summary projection is closed to exactly the five specified groups;
  unknown, unable, and unverified states remain explicit in all detailed
  projections.
- Deleted the unversioned Python `DecisionWorkspace`,
  `EstimatedAccountWorkspace`, `WorkspaceService.build`, bootstrap entrypoint,
  backend route, CLI composition, fixtures, and retired payload assertions.
  Ticket 15 owns the already-declared production asset cutover to the six
  versioned Web routes.
- Replaced one stale no-trade-side-effect assertion that still queried retired
  `trade_plan` with the canonical `trade_plan_master` and
  `trade_plan_version` authority tables.
- `TDK-AC-027` and focused Web/Skill equality/restart tests passed; the wider
  current-state public-interface regression passed 101 tests.
- Detailed current evidence:
  `.scratch/trading-discipline-kernel/evidence/14-versioned-read-models.md`.
