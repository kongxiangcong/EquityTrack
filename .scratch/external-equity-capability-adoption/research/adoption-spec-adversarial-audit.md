# Adoption Spec adversarial audit

## Audit identity

- Ticket: `11-adversarially-audit-adoption-spec`
- Fixed comparison: `git diff --no-index -- /dev/null .scratch/external-equity-capability-adoption/spec.md`
- Repository base: `7171489 fix: close issue 14 release proof gaps`
- Governing Goal Prompt SHA-256: `CA1148516E14C148AC247123081CE7A2237863A725192779B3B9C7241FBEE41D`
- Initial audited Spec SHA-256: `F2A51F40A45C7E19656B602D66E3192DA3058E73922D9D5B90FAEDFC1798E0A1`
- Review method: independent Standards and Spec reviews, followed by eight adversarial-domain lenses. The Spec is a new planning asset, so there is no commit range that could faithfully represent the comparison.

## Independent review findings and closure

| Finding | Severity | Closure in corrected Spec |
|---|---|---|
| Decision cells used out-of-enum states and evidence-only ideas as adapt-code | blocker | Section 4 now uses only the four allowed decisions; qualification state is separate |
| I02-I04 were horizontal layers, not complete vertical slices | blocker | Sections 17-18 merge 0013 into the A-source slice and give every production issue caller/schema/persistence/presentation/test/doc/deletion ownership |
| I06 deferred cleanup/release without an owning feature | blocker | Removed; cleanup closes in its owning issue and final proof is a Goal gate |
| Large modified files had no mandatory deepening deliverable | blocker | I04 names three responsibility audits and behavior-owning extractions; forwarding files and mirror ports are forbidden |
| Six portfolio-discipline planning tickets were not backwritten | blocker | I05 owns the exact six open tickets and forbids reopening resolved history |
| Canonical presentation omitted PDF | blocker | I04 and final gates require a View@2-derived PDF projection and render verification |
| SourcePolicy had no declared compliant fallback semantics | blocker | Section 8.3 defines no-fallback/qualified-equivalent, attempt recording, substitution status and critical-official no-fallback |
| Mandatory phase full verification was reduced to narrow tests | blocker | Section 20 runs the canonical verifier at each material production/migration/presentation gate |
| Acceptance trusted a caller-authored live JSON file | blocker | Sections 16.1 and 21.2 require a ledger/object/command-receipt-bound qualification artifact id and delete the file option |
| Adapter failure/time/market-semantics matrix was incomplete | blocker | Section 20.2 makes every case required or explicitly typed not-applicable |
| Migrations 0013/0014 did not determine one schema | blocker | Section 16 fixes table names, columns, keys, FKs, checks, triggers, backfill mapping and failure gates |
| I05 risked shotgun surgery | major | Corrected I04 first deepens each owner around a complete behavior while retaining one atomic caller/schema cutover |
| Repeated string identities and date boundaries risk primitive obsession | major | Typed QueryPolicy/SourcePolicy/Plan identities and existing typed temporal boundaries are required at public seams |

No material scope creep was found. PDF and portfolio planning backwrite are explicit Goal requirements, not optional expansion.

## Eight-lens adversarial failure cases

### Financial and valuation

1. An aggregator supplies a target price or consensus field without official critical facts. Expected: it cannot enter a ready snapshot; research returns `data_insufficient_memo`, never a rating or target.
2. Diluted shares, pension deficit or option dilution is missing. Expected: formal per-share output fails closed and market/value bases become `not_comparable`.

### Data time and point-in-time

1. A filing has `published_at` but no evidenced `available_at`. Expected: availability is unknown/blocking; publication time is not copied.
2. An amended SEC fact becomes available after the cutoff. Expected: the earlier snapshot cannot see it; the later version has distinct amendment, availability and supersession identity.

### Quantitative validity

1. Vibe reports Walk-Forward metrics without fold identities or a frozen universe. Expected: the rejected runtime cannot create a result.
2. A strategy-return Monte Carlo is presented as company valuation uncertainty. Expected: schema/identity mismatch; no artifact lineage or DecisionView entry.

### Portfolio risk

1. Research or valuation completes. Expected: account, TradePlan, PlanEvaluation, authorization and order tables are byte-for-byte unchanged.
2. A position/account value is unknown. Expected: it remains unknown, is not coerced to zero and cannot authorize a portfolio action.

### Software operations

1. An 0012 root contains mixed placeholder policy identities or an active old workflow. Expected: migration fails before cutover and the verified backup remains restorable.
2. A production provider times out. Expected: every attempt is recorded; only a prequalified equivalent declared in SourcePolicy may substitute, and critical official facts do not fall back to an aggregator.

### Security, license and rights

1. Endpoint code is Apache/MIT but data terms forbid local storage. Expected: rights admission fails; no raw object, normalized fact or snapshot member is persisted.
2. A claimed PDF is oversized, wrong-MIME or malicious. Expected: quarantine and typed diagnostic; no semantic fact extraction or authority upgrade.

### Workflow and recovery

1. A queued/running Request@1 exists during 0014. Expected: migration fails; it is not resumed through a compatibility reader.
2. A new caller submits Request@1 bytes/free mappings. Expected: admission rejects them; only Request@2 snapshot references plus plan are accepted.

### Hindsight and upgrade drift

1. A pinned upstream changes schema or terms on a later commit. Expected: the existing pin remains authoritative until full requalification; there is no automatic-main upgrade.
2. A correction is known at retrieval time but was unavailable at the requested cutoff. Expected: PIT selection excludes it and records later evidence without rewriting history.

## Replacement-gate audit

There are zero `adopt-external` rows, so no external runtime is represented as already adopted. Each `adapt-code` row is assigned to the existing `DataProvider` port, which has production adapters and deterministic `FixtureProvider`. CNINFO/SZSE and SEC each have a complete vertical slice, exact deletion targets, controlled live receipt and public sync-to-snapshot acceptance. No new StrategyValidation port is created because there is no qualified production adapter; unavailable is a capability state, not a fake result artifact.

## Result

All review blockers are corrected in the implementation-level Spec. Remaining items are explicit implementation preconditions owned by I01-I05; they are not unresolved Wayfinder decisions. Audit result: **pass for Wayfinder closure and handoff to `/to-spec`, then `/to-tickets`; production implementation has not started.**
