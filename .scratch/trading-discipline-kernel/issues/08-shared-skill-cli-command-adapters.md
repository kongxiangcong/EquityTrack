# 08 — Shared Skill and CLI command adapters

**Status:** resolved
**Type:** task  
**Mode:** AFK  
**Blocked by:** 07

## Scope

Implement one `ApplicationCommandEnvelope@1` codec and dispatcher used by Skill, CLI, and later Web. Expose complete task-level application operations, enforce the capability matrix centrally, and keep Skill as interaction channel rather than decision actor.

## Exact files and symbols

- Add `src/trading_platform/application/command_envelope.py::{ApplicationCommandEnvelopeV1,DecisionActor,InteractionChannel,TransportActor,ApprovalCapability}`.
- Add `src/trading_platform/application/commands.py::{ApplicationCommandDispatcher,ApplicationCommandResult,ApplicationCommandFailure}`.
- Update `src/trading_platform/application/bootstrap.py::open_application_commands`.
- Update `src/trading_platform/cli.py` to decode/encode the shared envelope through the dispatcher.
- Update `skills/SKILL.md` with the canonical account, plan, challenge, review, task, execution, and discipline-review task contracts.
- Update `src/trading_platform/application/__init__.py` public exports.

## Migration

No schema change. Persisted command idempotency and receipt fields use the already-final 0015–0017 schemas. This ticket cannot alter an applied cohort migration.

## Tests

- Add `tests/platform/test_application_command_envelope.py` and `tests/platform/test_skill_contract.py`.
- Update `tests/platform/test_cli_application_tasks.py`, `tests/platform/test_runtime_skeleton.py`, and `tests/platform/test_secure_workspace.py`.
- Cover typed decoding, actor/channel/transport separation, capability denial, redaction, idempotency, stable failure codes, and identical behavior across Skill and CLI.

## Dependency

Requires 07. Ticket 09 uses the dispatcher; ticket 15 may expose only corresponding commands.

## Acceptance gate

TDK-AC-018 and TDK-AC-034 pass. Each state-changing operation has one application command and one envelope; Skill and CLI neither duplicate domain decisions nor reach persistence directly.

## Out of scope

New Web pages, arbitrary Shell/SQL/filesystem tools, generic command buses, scheduler integration, or provider keys in payloads.

## One-way cutover

Replace stale Skill/CLI instructions and direct task invocations in the same change. Delete superseded commands instead of retaining aliases or wrapper forwarders.

## Claim record

- External seams: one serialized `ApplicationCommandEnvelope@1`, one typed
  result/failure schema, CLI stdin/file decoding, and the active Skill
  command contract.
- Deep-module ownership: `command_envelope.py` owns finite envelope identity
  and actor/channel/transport capability facts; `commands.py` owns command
  selection, central authorization, dispatch, result normalization, and
  redaction; named application tasks retain all business behavior.
- Old paths to replace: CLI operation-specific mutation decoding and direct
  task invocation, Skill examples that name retired commands, and any
  channel-local actor or capability decision.
- Superseded artifacts to delete: duplicate account/plan command codecs,
  direct adapter-to-persistence instructions, generic command routing,
  arbitrary tool payloads, and legacy result/failure shapes.

## Resolution evidence

- Added the finite `ApplicationCommandEnvelope@1` decoder, actor/channel/
  transport types, central capability matrix, typed result/failure contracts,
  and the `open_application_commands` composition seam.
- Replaced CLI-local watchlist/market mutation codecs and commands with the
  single `application-command --envelope-file` route. Removed the retired byte
  decoders and their public exports; retained only nested typed provider-job
  value translation.
- Skill now names the closed 16-command trading-discipline registry, explicit
  user capability rules, plan challenge requirement, and fail-closed
  `COMMAND_NOT_AVAILABLE` behavior for commands owned by later tickets.
- Account and plan dispatcher results now expose the exact request hash stored
  in `application_command_receipt`; plan persistence uses the same canonical
  application-command identity instead of a repository-local hash recipe.
- Focused gate: 55 passed in 38.64 seconds across envelope, Skill, CLI,
  runtime/security, account, plan confirmation, Model B, and market regression
  suites. The dedicated envelope suite also passed 6 tests in 2.30 seconds,
  including account replay/receipt equality and plan
  create/challenge/confirm/activation through the dispatcher.
- Migration 0016 remained unchanged at SHA-256
  `732FAC8AB6DBE393E8B62595D57730247A8929F5EE271CCE380C28E0FF58AA62`.
  See `evidence/08-shared-command-envelope.md`.
