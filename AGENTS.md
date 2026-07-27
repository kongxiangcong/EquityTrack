# Project-wide Agent Rules

These rules apply to the entire repository. The financial and research rules
apply especially to `skills/` and the `equity-researcher` skill.

## Long-Term Project Baseline

- `docs/prompts/trading_platform_codex_prompt_optimized.md` is the authoritative long-term task statement, scope boundary, and acceptance baseline for this repository.
- Read that file before auditing, designing, planning, or implementing the personal research and trading-strategy platform. Do not weaken, bypass, or silently reinterpret its non-negotiable constraints.
- Current platform work must evolve from the existing equity-research MVP through verified reuse seams; do not copy it into a parallel system or replace it with a big-bang rewrite.
- Wayfinder work for the first vertical-slice Spec is tracked under `.scratch/trading-platform-first-vertical-slice-spec/`. Wayfinder sessions plan and resolve decisions one ticket at a time; they do not authorize large-scale platform implementation.
- Product and UI work is design-driven. Follow the authoritative prompt's product/interaction principles: show only decision-relevant information by default, use progressive disclosure for process/provenance data, help the user understand changes and uncertainty without replacing their judgment, and apply an Apple-inspired clarity/deference/depth/consistency style without weakening accessibility or the financial-output boundary.

## Repository-wide Engineering Policy

### One Canonical Path

- `AGENTS.md` is the sole project-wide Agent rule source. Do not create a second `agent.md`, nested replacement rule set, or conflicting operating guide.
- `skills/SKILL.md` is the sole active Codex/Skill control-plane entry. Platform maintenance uses `python -m trading_platform.cli`; formal application use crosses the named task interfaces in `trading_platform.application` and the typed domain contracts behind them.
- Every capability has one canonical command path, one application path, one persistence path, and one presentation model. Do not add a second CLI, script wrapper, renderer, schema, database access route, or direct-call shortcut for the same behavior.
- README, Skill instructions, examples, tests, and runtime code must name the same current path. Update or delete stale instructions in the same change that replaces an interface.

### No Glue, Bypass, or Compatibility Code

- **Glue code is forbidden.** Do not add a module, class, function, facade method, or script whose only job is to forward arguments, rename fields, repackage a result, mirror another interface, or choose between old and new implementations.
- A module must own meaningful behavior behind a small interface: domain invariants, a transaction, lifecycle/state transitions, security or rights enforcement, deterministic calculation, retry/failure semantics, or protocol translation at a real external seam. The composition root may wire implementations, but it must not become a second business workflow.
- **Bypass code is forbidden.** CLI, Web, scripts, tests, and adapters must not reach around the canonical application interface to call persistence internals, issue ad-hoc SQL, write artifact files directly, invoke private research functions, or duplicate domain decisions.
- **Compatibility code is forbidden.** Do not add or extend shims, aliases, dual-read/dual-write paths, legacy key readers, fallback-to-old-implementation branches, version-dispatch wrappers, deprecated entrypoints, or parallel old/new renderers.
- Replace callers and persisted data with an explicit, versioned, one-way migration, then delete the superseded runtime path in the same unit of work. A migration is not permission to retain runtime compatibility. If safe deletion is blocked by missing facts or data, stop and record the blocker; do not hide it behind a compatibility layer.
- Domain degradation and provider fallback are allowed only when they are part of the current typed contract, evidence-constrained, fail-closed, and tested. They must never route execution into a retired implementation.

### Deep Modules and Dependency Direction

- Prefer deep modules: a small task-level interface that hides substantial implementation and gives callers leverage. Apply the deletion test: if deleting a module merely moves the same calls into its callers, the module is shallow and should not exist.
- Task-level interfaces must not mirror every method of each backing object. Add an application task operation only when it represents a complete user/application task and owns cross-module policy or orchestration.
- Introduce a port only at a real seam with justified production and test adapters. Do not create speculative interfaces or one-implementation abstractions.
- Keep dependencies pointing inward: CLI/Web/provider/filesystem adapters -> application interface -> domain modules. Persistence implements domain/application ports. Domain code must not import CLI, Web, concrete persistence, or presentation code.
- Treat `equity_research` deterministic calculations as implementation behind the platform research task, not as an alternative application entry. Narrow its public exports to contracts genuinely required across the seam.
- Split a large module only along cohesive domain behavior and move the behavior completely. Do not reduce file size by creating pass-through files. When new work touches an oversized multi-responsibility module, first identify and extract a complete deep module, then delete the old implementation and obsolete tests.
- Tests and callers cross the same public interface. After replacement tests cover the new interface, delete tests that exercise retired private seams; do not layer old and new test suites indefinitely.

### Mandatory Cleanup with Every Change

- Before closing a change, search for superseded symbols, imports, commands, feature flags, schemas, fixtures, tests, documentation, generated assets, and dependencies. Remove all artifacts made obsolete by the change.
- Delete dead, redundant, commented-out, temporary, deprecated, legacy, and unreachable code immediately. Git history is the archive; active source and docs must describe only the current system.
- Do not leave `TODO`, `FIXME`, compatibility notes, or dormant branches as substitutes for cleanup. A genuinely blocked follow-up must be a named tracker item with evidence and an explicit removal target.
- Remove unused dependencies from manifests and lock files, and regenerate third-party notices when dependency scope changes.
- Existing violations are technical debt, not precedent. New work must not copy their shape or increase their surface area.

### Verification and Diagnostics

- Stable commands emit a typed result and typed failure code. Preserve redacted, actionable diagnostics at the failing substep; do not catch broad exceptions and replace all causes with an undifferentiated failure.
- Long-running test and maintenance commands must expose substep progress, suite identity, duration, and the underlying redacted failure evidence while retaining one stable top-level command.
- Verification is proportional to risk and runs through public interfaces. Report the exact commands, passing and failing counts, timeouts, skipped external checks, and any generated artifacts; never convert an incomplete or timed-out run into a pass.
- Before completion, inspect `git status` and the final diff. Preserve unrelated user changes and never treat a dirty working tree as permission to rewrite or clean files outside the task.

## Financial Output Boundary

- Do not provide personalized investment advice.
- Do not tell a user to buy, sell, hold, add, reduce, or avoid a security.
- Default outputs must not contain BUY/HOLD/SELL, 买入/卖出/持有, 可以买, 不能买, target-price conclusion, or house-style rating language.
- Use research-language fields by default: `valuation_view`, `risk_reward_summary`, `data_quality_grade`, `key_uncertainties`, and `what_would_change_the_view`.
- Rating language is allowed only when `user_requested_rating = true`, all data gates pass, and the output includes a non-investment-advice boundary.

## Data Rules

- Do not fabricate financial data, market data, consensus data, citations, or source metadata.
- Use Tushare as the primary structured market-data provider for security master, trading calendar, OHLCV, adjustment factors, market cross-sections, and financial/disclosure indexes when configured and entitled. Use Kimi Datasource only as an auxiliary Codex/Skill control-plane source for discovery, candidate data, and cross-checking; do not make Kimi a business-runtime dependency.
- Before using Tushare, read `.scratch/trading-platform-first-vertical-slice-spec/research/kimi-experiments/tushare_usage.md` and the companion `tushare-vs-kimi-datasource.md`, then use only the approved environment-backed connection seam documented there. Do not require the user to paste or reconfigure a token for that gateway. Do not put or echo credential values or private endpoint parameters in source, Git, user-facing output, artifacts, or logs.
- The Tushare-compatible gateway documented there is not an official `tushare.pro` host. Preserve the actual gateway identity in provenance and do not treat it as an official disclosure authority.
- Official disclosure is primary for critical financial data:
  - A-share: CNINFO, SSE/SZSE/BSE announcements, company IR reports.
  - HK: HKEXnews and company IR reports.
  - US: SEC EDGAR/XBRL and company IR reports.
- iFind, Yahoo, and other terminals are optional secondary sources for structuring, market data, or cross-checking. They cannot be the sole authority for critical financial statements.
- Every critical number must be in `source_manifest` with `source_id`, or explicitly marked `missing`.
- Missing official source for critical financial data means no valuation conclusion, target price, or rating.

## Valuation Rules

- Do not default to DCF for L2.
- Run `valuation/valuation-method-router.md` before valuation.
- Run `valuation/dcf-and-sensitivity.md` applicability gate before any DCF tab, WACC table, or DCF-derived value.
- Financial firms disable ordinary FCFF/WACC DCF; use P/B x ROE/COE, DDM, residual income, or excess return.
- Pre-revenue or pipeline-driven biopharma should route to rNPV/SOTP and cash runway analysis.
- Cyclical/resource companies require mid-cycle or NAV framing; do not extrapolate peak commodity prices into perpetuity.
- If fewer than 3 usable peers remain after source/currency/accounting checks, comps cannot support a valuation conclusion.

## Degradation Rules

- If critical data, required official sources, selected-method inputs, or required tools/APIs are unavailable, produce `data_insufficient_memo`.
- A data insufficient memo may include research notes, source gaps, disabled-method reasons, and next data requirements.
- A data insufficient memo must not include target price, rating, buy/sell advice, or probability-weighted target.
- Tool/API unavailability must be recorded; never invent data to keep the workflow moving.

## Phase 0 Scope

- Do not implement full `model_validator.py` or `source_manifest_validator.py` as part of Phase 0.
- Do not generate stock reports while patching this skill.
- Keep changes scoped to safety boundaries, source gates, valuation method routing, DCF applicability, source manifest schema, and degradation behavior.

## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage state uses the default Matt Pocock skill label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain documentation layout. See `docs/agents/domain.md`.
