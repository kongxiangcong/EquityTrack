# Project-wide Agent Rules

These rules apply to the entire repository.

## Authority and current state

- `docs/decision-core.md` is the sole product, architecture, scope, and acceptance baseline for the Decision Core.
- The Decision Core is **design confirmed, not implemented**. Do not describe its target records, operations, or Modules as live runtime facts.
- The user will invoke `to-spec` and `to-issue` manually. Do not generate a Spec, issues, or implementation merely because the design document exists.
- `CONTEXT.md` is the sole domain glossary. `docs/adr/` records only hard-to-reverse decisions and their reasons.
- `skills/SKILL.md` remains the sole current Codex/Skill entry. Until a future atomic cutover, it describes the existing runtime rather than the target design.

## Request routing

- For a current supported user task, read `skills/SKILL.md` and the matching `skills/tasks/` document first, then use its canonical application path.
- For Decision Core design, `to-spec`, `to-issue`, or future implementation work, read `docs/decision-core.md`, `CONTEXT.md`, and relevant ADRs before exploring code.
- Platform maintenance uses `python -m trading_platform.cli`. CLI, tests, adapters, and future presentation cross the same application Interface; they do not reach persistence or private research functions directly.

## Deep Modules and canonical paths

- Use the Module, Interface, Seam, Adapter, Depth, Leverage, and Locality vocabulary from the repository `codebase-design` skill.
- A Module earns its existence by hiding substantial invariants, calculation, transaction, lifecycle, persistence, recovery, or real protocol translation behind a small Interface. Apply the deletion test to shallow forwarding Modules.
- Every capability has one application path, one persistence path, and one presentation model. Do not add a second CLI, schema, renderer, direct SQL route, or script wrapper for the same behavior.
- Introduce a port only at a real seam with justified production and test Adapters. Do not create speculative extension points.
- Dependencies point inward: external Adapters -> application Interface -> domain Modules. Persistence implements inward-facing ports; domain code does not import concrete persistence, CLI, Web, or presentation code.

## AI, Python, and user authority

**AI proposes meaning and judgment; Python verifies facts, computes numbers, enforces constraints, and stores truth; the user confirms accounts, plans, and actual execution.**

- Skill instructions own evidence interpretation, investment theses, counterarguments, falsifiers, uncertainty, and review judgment.
- Python owns fact processing, accounting, valuation formulas, risk limits, plan-rule evaluation, validation, idempotency, transactions, SQLite, migration, and recovery.
- Python does not assemble investment opinions through hard-coded prompts, workflow graphs, scoring trees, or narrative templates. Business runtime code does not call an LLM.
- AI does not invent financial data, calculate authoritative valuation or account results, set risk limits, or assert plan triggers.
- Account facts, final TradePlan confirmation, and actual ExecutionRecord declarations require the user's explicit decision.

## Replacement and cleanup

- Replace an owned seam in place. New implementation, one-way data migration, caller switch, tests and docs, and deletion of the superseded path form one change unit.
- Do not add compatibility shims, aliases, dual-read or dual-write paths, feature flags, fallback-to-old branches, version dispatchers, parallel packages, or placeholder Interfaces.
- Preserve irreplaceable business facts through explicit migration. Delete superseded code, schemas, exports, fixtures, tests, docs, generated assets, and dependencies after cutover.
- Git history is the archive for source and docs. Temporary migration code remains only through the verified rollback window described in ADR-0008.

## Evidence and data

- Current Decision Core development uses synthetic fixtures only. Do not access or modify `E:\trading-data\kong`, configure a real provider, or request credentials without a later explicit user task.
- An EvidenceItem records a value and `source_id`, or a `missing_reason`. EvidenceSet has no global pass/fail gate; missing data degrades only its direct consumer.
- Never fabricate financial data, market data, consensus data, citations, or source metadata. Every critical number has a source_id or is missing.
- Official disclosure remains primary for critical financial facts. Structured providers are auxiliary evidence and retain their true gateway identity.
- Credentials stay in the approved local credential seam and never appear in source, Git, chat, artifacts, or logs.

## Financial output

- Do not provide personalized investment advice or tell the user to buy, sell, hold, add, reduce, or avoid a security.
- Default output contains no BUY/HOLD/SELL, 买入/卖出/持有, target-price conclusion, or house rating language.
- Use research language: valuation view, risk-reward summary, data quality, key uncertainties, and what would change the view.
- Valuation is explicit and deterministic. Use `skills/valuation/valuation-method-router.md` and the relevant method rules; method-critical missing inputs produce an insufficient ValuationAssessment, not invented numbers.

## Current scope exclusions

- No DSH integration, Vibe-Trading, Qlib, factor mining, general backtesting, strategy marketplace, portfolio optimization, broker orders, automatic execution, or runtime LLM.
- Do not create packages, tables, ports, config, tests, or placeholders for excluded capabilities. A future user request requires independent design and evidence before introducing a seam.

## Verification and Git discipline

- Tests and callers cross the same public Interface. Once replacement Interface tests exist, delete tests that exercise retired private seams.
- Stable operations return typed results and a small stable failure set. Preserve redacted diagnostics at the failing substep; do not collapse every cause into one message.
- Report exact commands, pass/fail/skip/timeout counts, external checks not run, and generated artifacts. Fixture success is never live-provider success.
- Inspect `git status`, the final diff, and superseded-symbol searches before completion. Preserve unrelated user work; stage explicit paths only.
- Never reset, clean, restore, stash, rebase, amend, push, or overwrite user changes without explicit scope.

## Repository process references

- Issues and Specs: `docs/agents/issue-tracker.md`
- Triage labels: `docs/agents/triage-labels.md`
- Domain docs: `docs/agents/domain.md`
