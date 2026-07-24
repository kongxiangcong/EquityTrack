# Personal Research and Trading Strategy Platform

This repository is a local-first, deterministic research and decision-support
platform. It preserves immutable evidence, point-in-time data, workflow history,
Forecast and Scenario Valuation artifacts, and a canonical
`ResearchDecisionView@2`. It does not place orders or provide personalized
investment instructions.

## Canonical control plane

Codex and maintainers use one cross-platform entry:

```powershell
python -m trading_platform.cli bootstrap --data-root <root>
python -m trading_platform.cli health --data-root <root>
python -m trading_platform.cli doctor --data-root <root>
python -m trading_platform.cli migrate --data-root <root>
python -m trading_platform.cli sync --data-root <root> --job-file <job.json>
python -m trading_platform.cli daily --data-root <root> --job-file <job.json>
python -m trading_platform.cli research --data-root <root> --request-file <request.json>
python -m trading_platform.cli history --data-root <root> --workflow-run-id <id>
python -m trading_platform.cli archive --data-root <root> --kind manifest --id <id>
python -m trading_platform.cli provider-qualify --data-root <root> --job-file <job.json>
python -m trading_platform.cli serve --data-root <root> --web-root web/dist --security-id <id> --snapshot-id <id>
python -m trading_platform.cli backup --data-root <root> --archive <outside-root.zip>
python -m trading_platform.cli restore --archive <backup.zip> --target-root <new-root>
python -m trading_platform.cli test --repo-root .
```

Every command emits one JSON envelope. Failures retain a typed code and only
redacted diagnostics. Credentials remain in the configured environment scope;
they are never written to jobs, artifacts, backups, or Git.

## Research path

New research always follows the platform workflow:

```text
Frozen DataSnapshot
  -> ForecastGraphIdentity@2
  -> Scenario Valuation
  -> optional Simulation / Market Path
  -> ResearchDecisionView@2
  -> persisted JSON and decision-first HTML
  -> reconciled XLSX adapter
```

`ResearchWorkflow.handle` owns lifecycle policy. `WorkflowInspection`,
`ResearchArchive`, and `ForecastReview` are separate named tasks. Presentation
loads the persisted DecisionView bytes and does not recompute research or
valuation semantics.

## Data and financial boundaries

- Official disclosures are authoritative for critical financial facts.
- Tushare-compatible structured data is an aggregator, not official disclosure.
- Every critical number resolves to source identity or is explicitly missing.
- Missing gates produce a typed data-insufficient result, never fabricated data.
- Default outputs use research language and contain no buy/sell/hold instruction,
  target-price conclusion, or house rating.

## Repository map

```text
src/equity_research/       deterministic evidence, Forecast, and valuation domain
src/trading_platform/      application tasks, workflows, persistence, CLI, and Web
migrations/                one-way local schema migrations
skills/SKILL.md            sole Codex/Skill operating entry
tests/                     domain, application, adapter, and acceptance suites
web/                       local decision workspace
```

Architecture and operating constraints are defined by
`docs/prompts/trading_platform_codex_prompt_optimized.md` and `AGENTS.md`.
