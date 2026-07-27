# 08 — Shared Skill and CLI command adapters

**Status:** ready-for-agent  
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
