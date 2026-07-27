# Ticket 07 — Plan authoring and confirmation evidence

Date: `2026-07-27 Asia/Shanghai`
Branch: `codex/trading-discipline-kernel`
Parent: `a4592802df517fbfa9c9276c0710a6c6720b39fb`

## Canonical authoring path

- `TradePlanTasks` is the only plan mutation entry. It accepts create,
  revise, reject, issue-challenge, and confirm-version named commands with
  separate decision actor, interaction channel, and transport actor fields.
- Creating a draft establishes the Model-B master identity and persists the
  complete proposed graph. Revisions require the exact current revision,
  reseal the complete draft identity, recompute the canonical graph diff,
  and supersede every issued challenge.
- Draft identity binds version identity, ownership, account/data snapshots,
  horizon, review date, policy versions, content, sleeves, rules, evidence,
  and graph seal. Confirmation cannot change any of these after challenge
  issuance.
- Reject requires a user decision actor, cancels issued challenges, freezes
  the draft, and emits `PlanDraftRejected`. It does not affect the active
  slot.

## Approval and atomic confirmation

- `PlanConfirmationChallenge@1` binds one revision, draft hash, graph seal,
  canonical diff hash, and exactly one `confirm_only` or
  `confirm_and_activate` intent. Status transitions are storage-guarded from
  `issued` to one terminal status.
- `UserApprovalReceipt@1` requires `decision_actor=user:*`, preserves the
  interaction and transport identities, binds the approved draft/diff/graph,
  and is unique by challenge and command invocation.
- Agent confirmation, stale revision/hash/diff/intent, expired challenge,
  superseded challenge, consumed challenge, and same-invocation/different
  request all fail with stable typed codes.
- `confirm_and_activate` inserts the receipt, consumes the challenge, seals
  the full graph, emits `PlanVersionConfirmed`, emits `PlanActivated`, updates
  the active slot, and writes the command receipt in one SQLite transaction.
  Injected failure at the second event rolls all of those writes back.
- `confirm_only` writes the confirmed version and first event while preserving
  the existing active slot. Replaying an older confirmation after a newer
  activation returns its original graph, receipt, and historical activation
  rather than substituting the current version.

## One-way replacement

- Caller-seeded approval SQL, `CreateTradePlanMaster`,
  `SealTradePlanGraph`, `ActivateTradePlanVersion`, repository
  `seal_version`/`activate_version`, and old activation-intent values are
  deleted.
- Market, sleeve, graph immutability, and active-uniqueness tests now author
  and confirm through the same public named tasks as production callers.
- No plan-ID-only confirmation, implicit activation, reusable challenge,
  actor inference, compatibility alias, dual path, or Web confirmation facade
  remains.

## Cohort-B migration gate

- Migration 0016 now contains the final Strategy/Model-B/sleeve/AST@2/draft/
  challenge/receipt/activation schema and guarded transitions.
- Explicitly mapped historical approvals are converted to current canonical
  diff, challenge, receipt, graph-seal, actor/channel/transport, and content
  hashes. The selected receipt binds the exact open legacy activation version
  or the latest version when no open activation exists.
- Fresh, populated, mapped, unmappable, rollback, and replay migration tests
  pass. Both persistent repository roots remain at schema 11, so 0016 has not
  been applied to a persistent root and remains eligible for cohort-B
  immutability.
- Final pre-commit SHA-256:
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`.

## Verification

Terminal focused gate:

```text
python -m pytest tests/platform/test_plan_confirmation.py tests/platform/test_trade_plan_model_b.py tests/platform/test_trade_plan_sleeves.py tests/platform/test_market_evaluation.py tests/platform/test_migration_0015_0017.py tests/platform/test_runtime_skeleton.py tests/platform/test_cli_application_tasks.py tests/platform/test_web_application_tasks.py tests/platform/test_provider_qualification.py -q
61 passed in 31.81s

python -m compileall -q src/trading_platform
exit 0
```

Cohort-B persistent-root check:

```text
outputs/live-tushare-qualification-20260714/data/platform.sqlite3  schema=11
outputs/ui-smoke-20260714/data/platform.sqlite3                   schema=11
```

Intermediate failures were retained as failures and corrected before the
terminal run: draft INSERT placeholder count, a nested concurrency command
tuple, active-uniqueness error classification, forbidden-symbol naming,
owning-adapter registration, and one owning-adapter query typo. None is
counted as passing evidence.

## Mechanical audit

- Approval invariants live in `domain/approvals.py`; the plan aggregate owns
  draft/graph/event identity; the application module owns the five complete
  named tasks; the SQLite plan adapter owns the entire atomic transaction,
  replay receipts, constraints, and exact JSON/decimal protocol conversion.
- The persistence interface is deep: callers provide one typed command and
  do not coordinate draft rows, challenges, receipts, events, graph children,
  activations, or transitions. No forwarding-only module or one-class-per-file
  fragmentation was introduced.
- Runtime searches found no retired direct-seal/direct-activate command,
  caller-seeded receipt helper, old activation-intent value, plan-ID-only
  confirmation, compatibility/fallback/dual path, `TODO`, or `FIXME`.
- `git diff --check` passed for the Ticket-07 scope. Ticket-00's three
  deliberately dirty authority paths remain excluded and unstaged.

## Acceptance mapping

| Acceptance | Current evidence |
|---|---|
| `TDK-AC-010` | the confirmed graph test rejects version, sleeve, rule, and late evidence mutation |
| `TDK-AC-015` | the exact confirmation test covers Agent denial and stale revision/hash/diff/intent, expiry, supersession, and consumption |
| `TDK-AC-016` | the exact atomic test proves one receipt and both explicit events, plus full rollback under injected failure |
| `TDK-AC-017` | the exact confirm-only/reject test preserves the prior active slot |
| `TDK-AC-026` | a newer activation ends but never rewrites the old graph/activation, and replay remains historical |

Ticket 16 owns final canonical cross-ticket acceptance.
