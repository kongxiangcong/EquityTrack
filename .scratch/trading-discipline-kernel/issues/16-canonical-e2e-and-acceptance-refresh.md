# 16 — Canonical E2E and acceptance refresh

**Status:** ready-for-agent  
**Type:** task  
**Mode:** AFK  
**Blocked by:** 15

## Scope

Build the canonical synthetic two-security E2E, execute all 35 acceptance criteria, prove restart/replay/idempotency and backup/restore reconstruction, refresh the live acceptance ledger, and remove every superseded kernel path identified by ticket 00.

## Exact files and symbols

- Add `tests/fixtures/trading_discipline_kernel/account.json`, `evidence/`, `plans/`, and expected manifests for `002897.SZ` and `600183.SH`.
- Add `tests/platform/test_trading_discipline_kernel_e2e.py`.
- Add `tests/platform/test_trading_discipline_kernel_backup_restore.py`.
- Add/complete `tests/platform/test_migration_0015_0017.py`.
- Update `tests/platform/test_acceptance_evidence.py`, `src/trading_platform/acceptance.py::{AcceptanceEvidenceResult,AcceptanceEvidenceService}`, and canonical application/CLI acceptance command output.
- Write generated evidence only under `.scratch/trading-discipline-kernel/evidence/acceptance/`.

## Migration

Exercise clean install, 0014→0017 upgrade, every fail-closed preflight, explicit legacy mapping, repeated startup, and restore to a distinct root. Never edit the bytes of an applied 0015, 0016, or 0017.

## Tests

- Execute every suite and evidence requirement in `acceptance-matrix.md`.
- Run the 20-step fixture from spec section 27.
- Run focused tests before the full acceptance command.
- Record pass/fail/skip/timeout counts, durations, schema/hash manifests, browser artifacts, restart/replay identity sets, backup path, and restored-root reconstruction.
- Search for superseded symbols, `/api/workspace`, AST@1, public daily review, `user_fixture_input`, old schemas, prototype assets, stale docs, unused dependencies, and direct persistence bypasses.

## Dependency

Requires 15 and therefore all preceding tickets.

## Acceptance gate

TDK-AC-001 through TDK-AC-035 all pass, with direct ownership of TDK-AC-028, TDK-AC-029, TDK-AC-032 through TDK-AC-035 and final integration proof for every other row. The fixture proves all 20 requested behaviors, including Agent denial, core-floor protection, multi-session review, task deferral/reappearance, proposal-to-draft only, history preservation, read parity, idempotency, restore, and `unverified` broker evidence.

## Out of scope

User real data, live orders, external broker transactions, automatic scheduler, non-A-share instruments, performance claims, or accepting a timeout/skipped external gate as pass.

## One-way cutover

Delete all superseded runtime code, tests, docs, assets, schemas, flags, dependencies, and commands named by the ticket-00 inventory. Git history is the archive; the active tree contains only the canonical kernel paths.
