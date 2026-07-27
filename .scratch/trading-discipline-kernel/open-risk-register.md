# Trading discipline kernel open-risk register

Status: implementation risk register  
Product decisions: locked; this file does not reopen them

| ID | Risk | Likelihood | Impact | Mitigation and closing evidence | Owner ticket |
|---|---|---:|---:|---|---:|
| R-01 | The working tree contains user-owned, untracked authority and prototype material; implementation could accidentally absorb or overwrite it. | High | High | Ticket 00 records HEAD/status/hash inventory, names protected paths, and proves that only kernel paths are staged. | 00 |
| R-02 | Tickets 03–07 or 09–13 could edit a migration after it has already been applied. | Medium | Critical | Treat 0016 and 0017 as immutable release-cohort schemas; test them in disposable roots until the cohort is complete; record first-application hashes. | 03, 09 |
| R-03 | Active legacy plans may lack account ownership or explicit sleeve mapping. | High | Critical | 0016 preflight fails closed and emits a reviewable mapping manifest; no automatic core/grid guess, disable, or activation. | 04 |
| R-04 | Current market/industry/sector evidence may be missing or not qualified for a selected complete A-share session. | Medium | High | Freeze typed evidence with source/quality/session metadata; degrade affected review rules to unable/unverified without fabricating results. | 09, 13 |
| R-05 | Unknown cash, available quantity, cost, NAV, market value, or fees may be accidentally coerced to zero. | Medium | Critical | Use three-state operands end-to-end; property tests cover persistence, evaluation, read models, and Web rendering. | 01, 02, 06 |
| R-06 | A challenge could become stale after a draft revision or diff normalization change. | Medium | Critical | Bind challenge to draft ID, revision, canonical diff, content hash, activation intent, expiry/consumption state, and idempotent approval receipt. | 07 |
| R-07 | Skill transport attribution could be confused with decision authority. | Medium | Critical | Enforce the capability matrix in the application: `decision_actor=user`, `interaction_channel=skill`, `transport_actor=agent`; denial tests cover agent attempts. | 07, 08 |
| R-08 | EstimatedAccountState may drift indefinitely from broker/current reality. | High | High | Show base snapshot and unverified executions, calculate drift at each new confirmed snapshot, and require correction records rather than mutation. | 02, 11 |
| R-09 | Review replay could duplicate a DecisionTask after restart or evidence refresh. | Medium | High | Deterministic task identity includes plan version, rule, candidate intent, review window, and normalized evidence identity; persistence has unique constraints. | 09, 10, 16 |
| R-10 | Existing production Web and unversioned `/api/workspace` may tempt a dual-route cutover. | High | High | Ticket 15 replaces all callers and removes the route/assets in one change; tests search for stale endpoints and exercise production assets. | 14, 15 |
| R-11 | The synthetic fixture could leak user account data through reused local roots or screenshots. | Low | Critical | Use a dedicated temporary fixture root, fixed synthetic identities, redaction assertions, and artifact scanning. | 16 |
| R-12 | Broker transaction reconciliation is out of scope but schema placeholders could be mistaken for current truth. | Medium | High | Keep evidence verification state explicit; no imported transaction creates an execution or snapshot version; missing evidence reads `unverified`. | 01, 11 |
| R-13 | Graph sealing may cover the plan row but permit late child insertion or mutable links. | Medium | Critical | Seal the full plan version graph in one transaction and deny updates/inserts after confirmation; verify with adversarial SQL/repository tests. | 04, 05, 07 |
| R-14 | A valid rule may still require unavailable quantity/cash operands. | High | Medium | Return per-rule `unable` with typed reasons; do not block unrelated snapshot confirmation or other rules. | 06 |
| R-15 | Backup may be created but not actually restorable with application-level invariants intact. | Medium | Critical | Restore into a distinct root, restart, rebuild all projections, compare chain manifests, then replay idempotently. | 16 |
| R-16 | Existing acceptance counts and documents may be stale relative to live HEAD. | High | Medium | Ticket 00 captures the live baseline; ticket 16 refreshes the canonical acceptance ledger from actual command output and never treats timeout as pass. | 00, 16 |

## Risk closure rule

A risk is closed only when its named evidence is attached to the owning ticket and the relevant acceptance criterion passes. “Implemented”, an old report, a green unrelated suite, or a manually observed happy path is insufficient.

External-data risks may remain accepted degradation only when the resulting state is explicit (`unable`, `unknown`, or `unverified`), no financial fact is fabricated, and no plan or execution authority is inferred.
