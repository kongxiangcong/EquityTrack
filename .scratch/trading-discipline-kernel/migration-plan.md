# Trading discipline kernel migration plan

Status: implementation-ready  
Applies to: migrations `0015`–`0017`  
Rollback model: restore-first; no runtime compatibility path

## 1. Migration policy

The cutover is one-way. Each migration is immutable after it has been applied to any persistent database. Runtime code, tests, Skill instructions, CLI commands, Web routes, and read models switch to the new contract in the same release cohort that enables the migration. The old runtime path is deleted; a down migration, dual read, dual write, fallback reader, compatibility alias, or old/new feature flag is forbidden.

Before every migration:

1. create an application backup with the canonical maintenance command;
2. verify that the backup is readable;
3. run the migration-specific preflight against the source database;
4. stop if required identities, ownership, active-plan mapping, or invariant evidence is missing;
5. record the source schema version, source database hash, backup artifact, preflight result, mapping artifact hash, and target schema version.

Rollback means stopping the upgraded application and restoring the verified pre-migration backup with the prior application release. It never means writing migrated rows back into the retired schema.

## 2. Release cohorts

| Cohort | Migration | Owning tickets | Activation rule |
|---|---|---|---|
| A | `0015_account_snapshot_version.sql` | 01–02 | Account snapshot graph and estimated state ship together; old account-opening current-state reads are removed |
| B | `0016_strategy_plan_model_b.sql` | 03–07 | The migration contains the final StrategyVersion, Model B, sleeve, AST@2, authoring, challenge, receipt, and activation schema before first application |
| C | `0017_manual_review_journal.sql` | 09–13 | The migration contains the final review, task, action, execution, discipline review, impact, and proposal schema before first application |
| D | no schema migration | 08, 14–16 | Shared adapters, versioned reads, production Web, and acceptance switch onto cohorts A–C |

Tickets inside cohorts B and C may be implemented separately in source control, but the migration file is not applied to a persistent development or production root until the whole cohort schema and its migration tests are complete. A later ticket must not edit an already-applied migration.

## 3. Migration 0015 — AccountSnapshotVersion

Target file: `migrations/0015_account_snapshot_version.sql`

Target tables:

- `account_snapshot_draft`
- `account_snapshot_draft_position`
- `account_snapshot_version`
- `account_snapshot_position`
- `account_snapshot_transition`
- `account_snapshot_projection_checkpoint`

Preflight symbol: `trading_platform.persistence.migration.MigrationRunner._preflight_account_snapshot_0015`

Preflight must verify:

- every source account has a stable account identity and currency;
- every migrated position has a canonical security identity and non-negative total quantity;
- as-of, timezone, and complete-session semantics are explicit;
- unknown available quantity, cash, cost, market value, NAV, and fees are represented as unknown, not zero;
- every legacy opening graph has the existing explicit account-initialization confirmation provenance required to preserve it as confirmed truth;
- any legacy row that lacks required identity, quantity, or confirmation provenance blocks the migration rather than becoming a draft.

Transform:

1. Preserve old import/opening artifacts as source evidence.
2. Convert each confirmed `portfolio_snapshot` opening graph into a confirmed `AccountSnapshotVersion` with `source_kind=legacy_broker_opening_import`.
3. Preserve missing timestamp precision as `as_of_precision=date` and `session_semantics=legacy_unknown`; never invent a close timestamp.
4. Rewrite exact `plan_account_snapshot_reference` rows to the new snapshot version identity.
5. Build the current projection strictly from the latest confirmed version.
6. Persist transition and migration provenance, including the source row identity and migration manifest hash.

A broker current export received after cutover follows the ordinary product contract and creates only an `AccountSnapshotDraft`; this does not change the explicit one-time treatment of already-confirmed legacy opening truth.

Cutover deletes application reads that treat `account_opening_position` or broker history as current truth. Broker history remains evidence/reconciliation input only.

## 4. Migration 0016 — StrategyVersion and Model B plan graph

Target file: `migrations/0016_strategy_plan_model_b.sql`

Target tables and constraints:

- `investment_thesis_version`
- `strategy_definition`
- `strategy_version`
- `strategy_parameter_contract`
- `trade_plan_master`
- `trade_plan_draft`
- `trade_plan_version`
- `trade_plan_sleeve`
- `trade_plan_rule`
- `plan_confirmation_challenge`
- `user_approval_receipt`
- `plan_activation`
- partial unique index for one active master plan per `(account_id, security_id)`
- immutable foreign-key graph from activation to confirmed version, receipt, and challenge

Preflight symbol: `trading_platform.persistence.migration.MigrationRunner._preflight_strategy_plan_0016`

Preflight must:

- inventory every legacy plan and its lifecycle state;
- classify every legacy plan as `legacy_unsleeved`;
- reject the migration when an active legacy plan lacks an explicit, user-approved mapping to `core` or `grid`;
- reject multiple active candidates for one account/security;
- verify that every mapped plan has an account owner and canonical security identity;
- verify that plan content and child rows can be sealed without late mutation;
- hash the mapping artifact and include the hash in the migration manifest.

Transform:

1. Install the two built-in immutable strategy versions.
2. Create one master identity per account/security.
3. Preserve unmapped historical plans as read-only `legacy_unsleeved`.
4. Apply only explicit mappings to active legacy plans.
5. Move plan content into immutable versions and sleeves.
6. Create activation rows only from valid confirmed versions and preserved confirmation evidence.
7. Seal the whole version graph and enforce active uniqueness in storage.

The former `trade_plan` content discriminator `user_fixture_input`, singular latest-plan lookup, and old confirmation path are removed from runtime use in the same cohort.

## 5. Migration 0017 — Manual review and decision journal

Target file: `migrations/0017_manual_review_journal.sql`

Target tables:

- `manual_portfolio_review_run`
- `manual_portfolio_review_item`
- `manual_portfolio_review_checkpoint`
- `manual_portfolio_review_manifest`
- `decision_task`
- `decision_task_transition`
- `action_log_entry`
- `execution_record`
- `discipline_review_version`
- `plan_impact_assessment`
- `plan_change_proposal`

Preflight symbol: `trading_platform.persistence.migration.MigrationRunner._preflight_manual_review_0017`

Preflight must verify:

- any legacy evaluation/run identity can be retained without pretending it was a successful manual review;
- no current row would be inferred as a user execution;
- task identities can be generated deterministically from review, plan version, rule, candidate intent, and evidence window;
- the first selected cutoff is explicit when no successful checkpoint exists.

Transform:

1. Preserve legacy evaluations as diagnostic history, not `DecisionTask` or execution truth.
2. Start the successful-review checkpoint only from completed `manual_portfolio_review@1` runs.
3. Create no tasks for historical `NO_CHANGE` results.
4. Create no execution records from broker evidence.
5. Install immutable task transitions, actions, executions, reviews, assessments, and proposals.

The old public daily portfolio entry is removed. Daily research may remain an internal evidence producer, but it cannot be the public portfolio-review workflow.

## 6. Cutover sequence

1. Freeze writes and record the source application/schema version.
2. Produce and verify a backup.
3. Run all three preflights in dry-run mode and export their canonical, hash-addressed manifests.
4. Resolve every blocking record; rerun until preflight is clean.
5. Apply 0015 and verify snapshot projections.
6. Apply 0016 and verify ownership, graph seals, legacy preservation, and active uniqueness.
7. Apply 0017 and verify checkpoint, task, and journal invariants.
8. Start the new application release.
9. Run restart/replay/idempotency smoke tests.
10. Compare versioned Web and Skill reads for identical projection IDs and content hashes.
11. Run the synthetic canonical E2E.
12. Mark the cutover accepted only after backup/restore reconstruction succeeds in a separate temporary root.

## 7. Correction policy

Confirmed history is immutable. Corrections create new versions or compensating records:

- account error → new confirmed `AccountSnapshotVersion`;
- execution error → correcting/reversing `ExecutionRecord` linked to the original;
- action annotation error → new immutable `ActionLogEntry` referencing the superseded entry;
- plan error → new draft, confirmation challenge, receipt, version, and activation;
- review error → new `DisciplineReviewVersion`;
- evidence correction → new evidence version and, if material, a new assessment/proposal.

No correction updates a prior confirmed version in place.

## 8. Migration acceptance

The migration is accepted only when:

- preflight failure is fail-closed and leaves the source database unchanged;
- an active legacy plan without explicit sleeve mapping blocks 0016;
- migrated historical plans remain byte-for-byte reconstructable as read-only history;
- unknown numeric fields remain unknown;
- active master uniqueness is enforced by the database;
- backup/restore recreates the complete authority chain;
- rerunning migration/replay does not duplicate versions, tasks, activations, or executions;
- searches find no active old command, route, SQL read, schema alias, compatibility branch, or stale Skill instruction.
