# Ticket 08 shared command-envelope evidence

## Public seam

- Serialized input: `ApplicationCommandEnvelope@1`
- Composition: `open_application_commands`
- Finite dispatcher: `ApplicationCommandDispatcher`
- Success: `ApplicationCommandResult@1`
- Failure: `ApplicationCommandFailure@1`
- CLI: `python -m trading_platform.cli application-command --data-root
  <root> --envelope-file <command.json>`

The registry is the locked 16-command trading-discipline set. Account and plan
operations implemented by Tickets 01 and 07 dispatch to their named tasks.
Commands owned by Tickets 09–13 are reserved but return
`COMMAND_NOT_AVAILABLE` until their business module is installed.

## Capability and identity proof

- Decision actor, interaction channel, and transport actor decode independently.
- Agent account/plan confirmation is denied centrally.
- System mutation and first-release Web plan mutation fail closed.
- Skill transport must remain an agent; CLI does not upgrade decision authority.
- Plan confirmation requires the challenge ID in the approval field.
- Account replay and plan confirmation tests compare the dispatcher result hash
  to the exact `application_command_receipt.request_hash`.

## Replace-and-delete proof

- Removed CLI `watchlist-add`, `market-build`, and `market-evaluate` mutation
  routes.
- Removed their byte-oriented external command decoders and public exports.
- Skill names only the shared envelope route for trading-discipline mutation.
- Source scans found no retired CLI command or byte-decoder use under active
  runtime, Skill, or platform tests.
- No migration, schema, provider key, arbitrary Shell/SQL/filesystem tool,
  scheduler, broker, compatibility route, or generic command bus was added.

## Verification

```text
python -m pytest -q \
  tests/platform/test_application_command_envelope.py \
  tests/platform/test_skill_contract.py \
  tests/platform/test_cli_application_tasks.py \
  tests/platform/test_runtime_skeleton.py \
  tests/platform/test_secure_workspace.py \
  tests/platform/test_account_snapshots.py \
  tests/platform/test_plan_confirmation.py \
  tests/platform/test_trade_plan_model_b.py \
  tests/platform/test_market_evaluation.py

55 passed in 38.64s
```

```text
python -m pytest -q tests/platform/test_application_command_envelope.py
6 passed in 2.30s
```

Python compile checks passed. `ruff` was unavailable in the current interpreter,
so it was not reported as a passing gate. Targeted `git diff --check` passed.
Migration `0016_strategy_plan_model_b.sql` stayed unchanged with SHA-256
`732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`.
