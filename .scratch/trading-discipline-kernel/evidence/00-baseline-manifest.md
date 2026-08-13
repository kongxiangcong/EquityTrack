# Ticket 00 implementation baseline manifest

Captured: `2026-07-27 Asia/Shanghai`  
Baseline commit: `8aa69c9826a11133c39425ff6214052e387c747c`  
Branch: `codex/trading-discipline-kernel`  
Repository schema ceiling: `14`  
Baseline status: `passed_with_recorded_limits`

## Dirty ownership

The pre-claim worktree was clean immediately after the reviewed documentation
baseline commit and branch creation. Startup dirty-path allowlist: empty.

Ticket 00 then changed only:

- `.scratch/trading-discipline-kernel/issues/00-authority-baseline-and-branch-cleanup.md`
- `.scratch/trading-discipline-kernel/evidence/00-baseline-manifest.md`

Ticket 00 did not merge, stage, commit, push, reset, clean, or alter application
behavior. Pre-baseline generated/raw/local-secret material was reviewed before
the ticket, removed from the worktree, and quarantined outside the repository.

## Authority hashes

SHA-256:

| Path | SHA-256 |
|---|---|
| `AGENTS.md` | `340945526CCA9DF9C4936D38A8BE9DE6A328AF800A91E312F15E13842AF9C6B1` |
| `docs/prompts/trading_platform_codex_prompt_optimized.md` | `93C5E619BF3A543E785FC16B823B9FA7CCF1832DB1EEF61FB0CF4F741048A9E3` |
| `CONTEXT.md` | `16C588C664F8ED0B87EC0823D92043885922DD8A70961313C8FD4DCEDF971DEE` |
| `skills/SKILL.md` | `9847E5D93E39935AACB5E4C8CE2F4DA1B2FCF70AE5DD8A8CCA9E6EEAA11B1170` |
| `trading-discipline-kernel-spec.md` | `4B0726DA4B59E3BA4E396DDD9C15C4ECD9C9DDF521F2E44E7F211F717BFB02A5` |
| `map.md` | `EBD7BABA5CDEF4929DAFD3D2A66DB36587FB2CC47510B6CEFAA278465A04E139` |
| `migration-plan.md` | `1FC70EFC68F02AFC4E031F3DF1F99E16501C9B0F929F37E99C073666FEFCF09D` |
| `acceptance-matrix.md` | `810958EDE11476ED2E060173443D76E2D799BED383592B6007A4B416ACF1DA02` |
| `open-risk-register.md` | `F683F3BCBE707D28C8D3AFCFEAD4897F61C40D0256257016AEF3A2611147A1A4` |

The committed Wayfinder directory tree object is
`eb606ff02dbb34cc07e2d3344c1dc7aae757e5db`. Its committed issue blobs are
recorded by `git ls-tree -r 8aa69c9 .scratch/trading-discipline-kernel`.

## Canonical public symbol inventory

| Symbol | Location | Baseline role | Owner |
|---|---|---|---:|
| `open_daily_research_cycle` | `application/bootstrap.py:174` | public daily research/portfolio-shaped route to retire | 09 |
| `open_decision_workspace` | `application/bootstrap.py:247` | unversioned workspace opener to replace | 14 |
| `open_trade_plan` | `application/bootstrap.py:271` | current plan application opener | 04, 07 |
| `open_market` | `application/bootstrap.py:314` | current market/evaluation opener | 06, 09 |
| `open_account` | `application/bootstrap.py:324` | current opening-account opener | 01 |
| `DecisionWorkspace` | `application/web_tasks.py:25` | unversioned presentation protocol | 14 |
| `PlanConfirmation` | `application/web_tasks.py:39` | old confirmation protocol | 07 |
| `LocalChartWorkspaceServer.start` | `web_server.py:51` | production Web adapter | 15 |
| nested `Handler.do_GET` | `web_server.py:55` | unversioned routes including `/api/workspace` | 15 |
| nested `Handler.do_POST` | `web_server.py:118` | Web-specific mutation routes | 08, 15 |
| `LocalChartWorkspaceServer.close` | `web_server.py:257` | server lifecycle | 15 |
| `MigrationRunner.validate` | `persistence/migration.py:29` | migration ledger/hash validation | 01, 03, 09 |
| `MigrationRunner.migrate` | `persistence/migration.py:45` | public migration transaction entry | 01, 03, 09 |
| `MigrationRunner._migrate_locked` | `persistence/migration.py:52` | ordered execution/rollback implementation | 01, 03, 09 |

Source SHA-256:

- `application/bootstrap.py`:
  `66448652F7CA49246CF46555A9F5AFBF1A93A4C0210E8B4F2271C3B63C08BDA4`
- `application/web_tasks.py`:
  `0E2705E3FA3C3EADA3EA7F43986E8A4862FA15C682AD06967D2B38BDE9F64E8E`
- `web_server.py`:
  `2F4989326F92E38D48E179FC7F48A0ED00B1E58784713364020BBD578B28B04A`
- `persistence/migration.py`:
  `771956DACE0BC04C0EB8FA46B065B6215D88B427182A71546FA4E1D8A5DC9F44`

## Migration inventory and release cohorts

Committed migrations 0001–0014 are the complete baseline. SHA-256:

```text
0001 B8CBF0D323C21AB89D7D0E6F60372CA7A00B0A58751519CC03001AE53406ADFD
0002 9D2C4ABE94EAB54138D549DFD50668A5B50382069E0FFEA8A4FD2FA7192B289B
0003 47DA39EF4959A33F9657E3CED50CBC86E9B76DCC4ED00113CBCBA3FA8FDA4919
0004 038AF0966F962FA1EE1B93587492D9298AE0D6A575EF66EB2314C33EA8366AA7
0005 C4902A84175B17D732E9EFF3DFEC1E952C286BAFB3A5CCFB3D78248D1317DE09
0006 041BBBF4A3C41F172C431253D7061310965007C139579496A505ECC6F0D296B4
0007 E5C9C76AC52792183F3564BE0A6DC03DBCF389D3D7D4F22147F225B26F202AC7
0008 75D20EAE9E31ECBB2C30E85F91EFCADD1CA1BF02E81B696045EA276510E049BF
0009 82B526FCA7B522575F657A22D99216ADE5C7C6094071EDD739CF147A4DCE4FD5
0010 6F054EBFB69A9975D63CC2EACFAB6E940578D71ACE318884D96D68119B7E1812
0011 9605D4FD571B11CDAE69365DADF1C5776B440B6446A92AD5D4524C1642F99492
0012 87E58F6A077B7B01123ECB83A2BE58392A23E980777BF8FA19476B0F29180753
0013 AB26675FFC77EA33C2FB341565920E020455711BB766F31FF1E6B3A970C5AD05
0014 2F66D6D7858562C098F5852178227A8A3A2BFEA22BF53143406BB2AE89AB00AF
```

Future files were absent at baseline:

| Migration | Cohort | Owner tickets | First-application rule |
|---|---|---|---|
| `0015_account_snapshot_version.sql` | A | 01–02 | may apply only with final account snapshot/estimate cohort |
| `0016_strategy_plan_model_b.sql` | B | 03–07 | must remain unapplied until the entire cohort is byte-final |
| `0017_manual_review_journal.sql` | C | 09–13 | must remain unapplied until the entire cohort is byte-final |

A disposable bootstrap root reached schema `14`; `doctor` passed with SQLite
`3.50.4`, Python `3.14.0`, provider status `not_configured`, and warning
`SENSITIVE_BACKUP_ENCRYPTION_NOT_VERIFIED`. No user production root was selected
or mutated. Two existing historical output roots inspected during baseline were
at schema `11`; they are not treated as active truth.

## Web asset inventory

| Path | SHA-256 |
|---|---|
| `web/index.html` | `6D33354E2A835BC60A8520A430EDFF4FBAE0B3C665D592F144D7FA6D453A29F9` |
| `web/src/app.js` | `D73FA8CE165DFE18190662B1A2F8AF17B7F8AAFE002B7D0DFEF0B9819E3048C3` |
| `web/src/styles.css` | `D7C2EF57A4989E6ECF88A0E59018BB941001C715851E8DF0E2D2C0B2FD86F667` |
| `web/dist/index.html` | `6D453ECA3385DC11D212A39B9A818AD11163D197125DFFC1C9354F120ED10C31` |

Baseline `web/dist/` contained six files and 288,704 bytes. The source and
production HTML hashes differ, so ticket 15 must rebuild and verify the
production tree rather than copying an old prototype bundle.

## Removal inventory

Searches prove these current paths exist and therefore remain explicitly open
until their owner ticket replaces and deletes them:

- `/api/workspace`: `web/src/app.js`, `web_server.py`, account/Web/operations
  tests.
- `user_fixture_input`: plan domain validation, browser fixture, doctor,
  persistence hydration, Web text, and plan/Web tests.
- AST@1: `domain/plans.py` default/parser/evaluator branches and fixtures.
- singular `get_active_for_security`: `plans.py`, persistence repository, market
  and plan tests.
- public `open_daily_research_cycle`: application exports, bootstrap, CLI and
  Skill `daily` instruction.
- unversioned `DecisionWorkspace` and old `PlanConfirmation`.
- prototype/build references in historical planning and old Web bundles.

Direct SQLite ownership outside `persistence/` was found in
`acceptance.py`, `account.py`, `chart.py`, `cli.py`, `operations.py`,
`data/repository.py`, `data/service.py`, and the bootstrap database composition.
Owner tickets must distinguish legitimate external protocol/maintenance
translation from application/domain bypass; this inventory is not permission
to add a second repository or facade.

## Focused public-interface baseline tests

Final successful coverage:

| Suite | Result | Duration |
|---|---:|---:|
| `test_account_opening.py` | 12 passed | 14.29s |
| `test_account_history_import.py` | 3 passed | 3.95s |
| `test_account_workspace_plans.py` | 3 passed | 10.54s |
| `test_trade_plans.py` | 8 passed | 16.42s |
| `test_market_evaluation.py` | 4 passed | 17.17s |
| `test_web_application_tasks.py` | 3 passed | 3.81s |
| `test_secure_workspace.py` | 11 passed | 25.45s |
| `test_operations_backup_restore.py` | 24 passed | 117.10s split execution |
| `test_workflow_ledger_recovery.py` | 3 passed | 9.47s |
| `test_acceptance_evidence.py` | 5 passed, 1 deselected | 3.40s |
| `test_runtime_skeleton.py` | 9 passed | 10.86s |

Total final coverage: `85 passed`, `1 deselected`, `0 failed`, `0 skipped`,
`0 final timeouts`. The deselected acceptance test is marked
`release_acceptance` by the repository default and is not claimed as passed.

Recorded timeout attempts, retained as diagnostics rather than converted to
passes:

1. the initial five-suite account/plan/market command timed out at 59.1s;
2. the initial six-suite Web/operations/recovery command timed out at 59.1s;
3. the whole operations file timed out at 59.1s;
4. three progressively smaller operations groups timed out at about 59.0–59.1s;
5. the first individual migration-matrix attempt timed out at 57.2s.

Every node from those attempts was subsequently rerun to a terminal passing
result; the slow migration-matrix node passed alone in 52.84s. Supporting
pre-baseline cleanup verification also passed `14` tests
(`test_project_verification.py`, `test_runtime_skeleton.py`, and the dependency
lock/Skill routing node).

## Ticket 00 gate

- Baseline commit, branch, clean pre-claim ownership and hashes: recorded.
- Canonical public symbols and direct SQLite callers: recorded.
- Existing migration ceiling and future cohort ownership: recorded.
- Focused suites, durations, deselection and timeout attempts: recorded.
- Old routes/symbols/schemas/assets to replace: recorded.
- No domain/application/persistence/Skill/CLI/Web behavior changed.
- No user account data or external provider facts were used.
