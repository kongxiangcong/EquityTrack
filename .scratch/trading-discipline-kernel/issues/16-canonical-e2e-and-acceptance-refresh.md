# 16 — Canonical E2E and acceptance refresh

**Status:** resolved
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

## Claim record

- External seams: one synthetic fixture manifest, one canonical acceptance
  command/report, public named application tasks, canonical maintenance
  backup/restore, six read-model queries, and production CDP evidence.
- Deep-module ownership: the E2E fixture owns only fixed synthetic inputs and
  expected identities; application/domain/persistence modules retain all
  behavior; acceptance owns suite execution, exact status accounting,
  evidence hashing, and fail-closed completion judgment.
- Old paths to replace: the 51-row pre-kernel acceptance ledger/suite list,
  browser evidence assumptions tied to the retired chart workspace, partial
  current-product completion language, and any tests/docs that still treat old
  commands, AST@1, `user_fixture_input`, opening rows, or prototype routes as
  active authority.
- Superseded artifacts to delete: every runtime/test/doc/dependency hit named
  by the Ticket 00 retirement inventory that is not a migration-only legacy
  input, explicit absence assertion, or immutable historical evidence;
  obsolete acceptance artifacts and stale fixed counts are regenerated rather
  than retained.

## Answer

The canonical two-security fixture, 20-step E2E, restart/replay identity proof,
distinct-root backup/restore reconstruction, migration hash ledger,
architecture import graph, exact status-semantics evidence, production CDP,
and all 35 TDK criteria are frozen under
[`evidence/acceptance/`](../evidence/acceptance/). The canonical manifest is
`acceptance-7ce3c3637c07a34dbc80dc53bff0b75442aeb488550ebd4cc3877c0320c19968.json`;
it reports `35/35` criteria and `168/168` suite tests passed, with no failures,
skips, xfails, or timeouts. Live provider qualification is explicitly
`not_applicable` to the synthetic offline kernel gate and is not represented
as a passed external check.

The implementation and verification narrative is recorded in
[`evidence/16-canonical-e2e-and-acceptance-refresh.md`](../evidence/16-canonical-e2e-and-acceptance-refresh.md).
