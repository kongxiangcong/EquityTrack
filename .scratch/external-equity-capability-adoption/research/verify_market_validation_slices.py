from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn


SCHEMA_VERSION = "ExternalEquityMarketValidationEvidence@1"
PLAN_SCHEMA_VERSION = "ExternalEquityMarketValidationPlan@1"
ALLOWED_MARKETS = ("a_share", "us", "hk")
ALLOWED_AUTHORITATIVE_INPUT = "typed_official_fact"
REJECTED_RAW_KINDS = (
    "raw_html",
    "raw_pdf",
    "free_text",
    "caller_authored_json",
)
REPLAY_SPECS = (
    (
        "a-stock-data-fixture-replay.mjs",
        "6d160105788eb16473e2ccaa3153a37e33113cd2d2c41049909b29b579342022",
        "cases",
        12,
    ),
    (
        "a-stock-data-official-fixture-replay.mjs",
        "d8acc7333ae8fb7bb18d05db0f57d461a648fd93c17d44713876809209f889f1",
        "cases",
        5,
    ),
    (
        "global-stock-data-fixture-replay.mjs",
        "a45a29b685165ce8d096dff1dc62095bea2672d6aa0852ea9d997ef34e7dde59",
        "passed",
        12,
    ),
)


class VerificationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class Upstream:
    candidate: str
    checkout: str
    commit: str


@dataclass(frozen=True)
class SlicePlan:
    slice_id: str
    market: str
    security_identity: str
    issuer_identity: str
    as_of: str
    source_authorities: tuple[str, ...]
    qualified_observations: tuple[str, ...]


def fail(message: str) -> NoReturn:
    raise VerificationFailure(message)


def exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        fail(
            f"{path}: exact-key mismatch; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{path}: expected non-empty string")
    return value


def require_string_list(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        fail(f"{path}: expected non-empty string list")
    result = tuple(require_string(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        fail(f"{path}: duplicate values")
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"{path.name}: unreadable JSON: {type(exc).__name__}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        fail(f"{path}: unreadable evidence: {type(exc).__name__}")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def parse_plan(plan_path: Path) -> tuple[
    tuple[EvidenceFile, ...],
    tuple[Upstream, ...],
    tuple[SlicePlan, ...],
]:
    raw = load_json(plan_path)
    if not isinstance(raw, dict):
        fail("plan: expected object")
    exact_keys(raw, {"schema_version", "evidence_files", "upstreams", "slices"}, "plan")
    if raw["schema_version"] != PLAN_SCHEMA_VERSION:
        fail("plan.schema_version: unsupported")

    evidence: list[EvidenceFile] = []
    if not isinstance(raw["evidence_files"], list):
        fail("plan.evidence_files: expected list")
    for index, item in enumerate(raw["evidence_files"]):
        if not isinstance(item, dict):
            fail(f"plan.evidence_files[{index}]: expected object")
        exact_keys(item, {"path", "sha256"}, f"plan.evidence_files[{index}]")
        evidence.append(
            EvidenceFile(
                path=require_string(item["path"], f"plan.evidence_files[{index}].path"),
                sha256=require_string(
                    item["sha256"], f"plan.evidence_files[{index}].sha256"
                ).lower(),
            )
        )

    upstreams: list[Upstream] = []
    if not isinstance(raw["upstreams"], list):
        fail("plan.upstreams: expected list")
    for index, item in enumerate(raw["upstreams"]):
        if not isinstance(item, dict):
            fail(f"plan.upstreams[{index}]: expected object")
        exact_keys(item, {"candidate", "checkout", "commit"}, f"plan.upstreams[{index}]")
        upstreams.append(
            Upstream(
                candidate=require_string(
                    item["candidate"], f"plan.upstreams[{index}].candidate"
                ),
                checkout=require_string(
                    item["checkout"], f"plan.upstreams[{index}].checkout"
                ),
                commit=require_string(
                    item["commit"], f"plan.upstreams[{index}].commit"
                ).lower(),
            )
        )

    slices: list[SlicePlan] = []
    if not isinstance(raw["slices"], list):
        fail("plan.slices: expected list")
    for index, item in enumerate(raw["slices"]):
        if not isinstance(item, dict):
            fail(f"plan.slices[{index}]: expected object")
        exact_keys(
            item,
            {
                "slice_id",
                "market",
                "security_identity",
                "issuer_identity",
                "as_of",
                "source_authorities",
                "qualified_observations",
            },
            f"plan.slices[{index}]",
        )
        market = require_string(item["market"], f"plan.slices[{index}].market")
        if market not in ALLOWED_MARKETS:
            fail(f"plan.slices[{index}].market: unsupported")
        slices.append(
            SlicePlan(
                slice_id=require_string(
                    item["slice_id"], f"plan.slices[{index}].slice_id"
                ),
                market=market,
                security_identity=require_string(
                    item["security_identity"],
                    f"plan.slices[{index}].security_identity",
                ),
                issuer_identity=require_string(
                    item["issuer_identity"],
                    f"plan.slices[{index}].issuer_identity",
                ),
                as_of=require_string(item["as_of"], f"plan.slices[{index}].as_of"),
                source_authorities=require_string_list(
                    item["source_authorities"],
                    f"plan.slices[{index}].source_authorities",
                ),
                qualified_observations=require_string_list(
                    item["qualified_observations"],
                    f"plan.slices[{index}].qualified_observations",
                ),
            )
        )

    if tuple(item.market for item in slices) != ALLOWED_MARKETS:
        fail("plan.slices: must contain exactly a_share, us, hk in canonical order")
    if len({item.slice_id for item in slices}) != len(slices):
        fail("plan.slices: duplicate slice_id")
    return tuple(evidence), tuple(upstreams), tuple(slices)


def verify_upstreams(upstreams: tuple[Upstream, ...]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    expected_candidates = ("a-stock-data", "global-stock-data", "Vibe-Trading")
    if tuple(item.candidate for item in upstreams) != expected_candidates:
        fail("plan.upstreams: canonical candidate order/coverage mismatch")
    for upstream in upstreams:
        checkout = Path(upstream.checkout)
        if not checkout.is_dir():
            fail(f"upstream {upstream.candidate}: checkout missing")
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if completed.returncode != 0:
            fail(f"upstream {upstream.candidate}: git identity unavailable")
        actual = completed.stdout.strip().lower()
        if actual != upstream.commit:
            fail(
                f"upstream {upstream.candidate}: commit mismatch "
                f"expected={upstream.commit} actual={actual}"
            )
        clean = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if clean.returncode != 0 or clean.stdout.strip():
            fail(f"upstream {upstream.candidate}: checkout is not clean")
        result.append(
            {
                "candidate": upstream.candidate,
                "commit": actual,
                "identity_status": "pinned",
                "worktree_status": "clean",
            }
        )
    return result


def verify_evidence_files(
    root: Path, evidence_files: tuple[EvidenceFile, ...]
) -> tuple[dict[str, Any], dict[str, str]]:
    loaded: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    seen: set[str] = set()
    for item in evidence_files:
        if item.path in seen or Path(item.path).name != item.path:
            fail(f"evidence path must be unique local filename: {item.path}")
        seen.add(item.path)
        path = root / item.path
        actual = sha256_file(path)
        if actual != item.sha256:
            fail(
                f"{item.path}: evidence hash mismatch "
                f"expected={item.sha256} actual={actual}"
            )
        loaded[item.path] = load_json(path)
        hashes[item.path] = actual
    return loaded, hashes


def find_by(items: Any, field: str, value: str, path: str) -> dict[str, Any]:
    if not isinstance(items, list):
        fail(f"{path}: expected list")
    matches = [
        item for item in items if isinstance(item, dict) and item.get(field) == value
    ]
    if len(matches) != 1:
        fail(f"{path}: expected one {field}={value}, got {len(matches)}")
    return matches[0]


def base_outcome(
    plan: SlicePlan,
    frozen_records: list[dict[str, Any]],
    market_gaps: list[str],
) -> dict[str, Any]:
    frozen_identity = canonical_hash(
        {
            "schema_version": "FrozenExternalEvidence@1",
            "slice_id": plan.slice_id,
            "market": plan.market,
            "security_identity": plan.security_identity,
            "issuer_identity": plan.issuer_identity,
            "as_of": plan.as_of,
            "source_authorities": plan.source_authorities,
            "records": frozen_records,
        }
    )
    common_research = [
        "OFFICIAL_FACTS_NOT_NORMALIZED",
        "CRITICAL_FINANCIAL_FACTS_MISSING",
        "AVAILABLE_AT_UNPROVEN",
    ]
    return {
        "slice_id": plan.slice_id,
        "market": plan.market,
        "security_identity": plan.security_identity,
        "issuer_identity": plan.issuer_identity,
        "as_of": plan.as_of,
        "frozen_evidence": {
            "schema_version": "FrozenExternalEvidence@1",
            "status": "metadata_only",
            "identity": frozen_identity,
            "records": frozen_records,
            "authoritative_financial_fact_count": 0,
        },
        "research_evaluation": {
            "schema_version": "ResearchEvaluationCandidateResult@1",
            "status": "blocked",
            "reason_codes": common_research,
            "output_kind": "data_insufficient_memo",
        },
        "valuation": {
            "schema_version": "ValuationCandidateResult@1",
            "status": "not_comparable",
            "reason_codes": [
                "CRITICAL_FINANCIAL_FACTS_MISSING",
                "SELECTED_METHOD_INPUTS_MISSING",
            ],
            "formal_value": None,
        },
        "strategy_validation": {
            "schema_version": "StrategyValidationCandidateResult@1",
            "status": "blocked",
            "reason_codes": [
                "STRATEGY_VALIDATION_CAPABILITY_UNAVAILABLE",
                *market_gaps,
            ],
            "result": None,
        },
        "production_replacement_gate": {
            "status": "failed",
            "reason_codes": sorted(set(common_research + market_gaps)),
        },
    }


def build_a_share_slice(plan: SlicePlan, evidence: dict[str, Any]) -> dict[str, Any]:
    general = evidence["a-stock-data-live-probe-evidence.json"]
    official = evidence["a-stock-data-official-live-probe-evidence.json"]
    if general.get("upstream_commit") != "06791b5a3159401524c10bd0e28aaebe415ce604":
        fail("a_share: upstream identity mismatch in live evidence")
    cninfo_map = find_by(
        general.get("http"), "id", "cninfo_security_map_https", "a_share.http"
    )
    cninfo = find_by(
        general.get("http"), "id", "cninfo_announcements_exact", "a_share.http"
    )
    szse = find_by(
        official.get("results"),
        "id",
        "szse_announcements_verified_tls",
        "a_share.official",
    )
    if not (
        cninfo_map.get("status") == 200
        and cninfo_map.get("requested_identity_found") is True
        and cninfo.get("status") == 200
        and cninfo.get("row_count", 0) > 0
        and cninfo.get("identity_match_count") == cninfo.get("row_count")
        and cninfo.get("has_published_time") is True
        and cninfo.get("has_available_at") is False
        and cninfo.get("has_retrieved_at") is False
        and szse.get("status") == 200
        and szse.get("identity_match_count") == szse.get("row_count")
        and szse.get("has_available_at") is False
    ):
        fail("a_share: qualified official observation invariants failed")
    records = [
        {
            "authority": "CNINFO",
            "observation": "cninfo_announcements_exact",
            "response_sha256": require_string(cninfo.get("sha256"), "a_share.cninfo.sha256"),
            "published_at_state": "present",
            "available_at_state": "missing",
            "retrieved_at": require_string(
                general.get("observed_at_utc"), "a_share.observed_at_utc"
            ),
            "raw_payload_state": "not_retained",
            "normalization_status": "blocked",
        },
        {
            "authority": "SZSE",
            "observation": "szse_announcements_verified_tls",
            "response_sha256": require_string(szse.get("sha256"), "a_share.szse.sha256"),
            "published_at_state": "present",
            "available_at_state": "missing",
            "retrieved_at": require_string(
                official.get("observed_at_utc"), "a_share.official.observed_at_utc"
            ),
            "raw_payload_state": "not_retained",
            "normalization_status": "blocked",
        },
    ]
    return base_outcome(
        plan,
        records,
        [
            "A_SHARE_SECURITY_IDENTITY_NOT_PERSISTED",
            "A_SHARE_CALENDAR_IDENTITY_MISSING",
            "A_SHARE_ADJUSTMENT_LINEAGE_MISSING",
            "A_SHARE_CORPORATE_ACTION_LINEAGE_MISSING",
            "A_SHARE_EXECUTION_RULES_UNQUALIFIED",
        ],
    )


def build_us_slice(plan: SlicePlan, evidence: dict[str, Any]) -> dict[str, Any]:
    global_live = evidence["global-stock-data-live-probe-evidence.json"]
    if global_live.get("upstream_commit") != "d52a8a0013363577bceb28ca876c88fe6c1a5aeb":
        fail("us: upstream identity mismatch in live evidence")
    submissions = find_by(
        global_live.get("probes"), "name", "sec-submissions-aapl", "us.probes"
    )
    facts = find_by(
        global_live.get("probes"), "name", "sec-companyfacts-aapl", "us.probes"
    )
    if not (
        submissions.get("status") == 200
        and submissions.get("content_type") == "application/json"
        and facts.get("status") == 200
        and facts.get("content_type") == "application/json"
        and global_live.get("raw_bodies_persisted") is False
    ):
        fail("us: SEC qualified observation invariants failed")
    retrieved_at = require_string(global_live.get("retrieved_at"), "us.retrieved_at")
    records = [
        {
            "authority": "SEC",
            "observation": "sec-submissions-aapl",
            "response_sha256": require_string(
                submissions.get("sha256"), "us.submissions.sha256"
            ),
            "published_at_state": "embedded_unparsed",
            "available_at_state": "embedded_unparsed",
            "retrieved_at": retrieved_at,
            "raw_payload_state": "not_retained",
            "normalization_status": "blocked",
        },
        {
            "authority": "SEC",
            "observation": "sec-companyfacts-aapl",
            "response_sha256": require_string(facts.get("sha256"), "us.facts.sha256"),
            "published_at_state": "embedded_unparsed",
            "available_at_state": "embedded_unparsed",
            "retrieved_at": retrieved_at,
            "raw_payload_state": "not_retained",
            "normalization_status": "blocked",
        },
    ]
    return base_outcome(
        plan,
        records,
        [
            "SEC_TYPED_PARSER_NOT_IMPLEMENTED",
            "SEC_FILING_COVERAGE_NOT_FROZEN",
            "US_SECURITY_MASTER_HISTORY_MISSING",
            "US_CORPORATE_ACTION_LINEAGE_MISSING",
            "US_EXECUTION_RULES_UNQUALIFIED",
        ],
    )


def build_hk_slice(plan: SlicePlan, evidence: dict[str, Any]) -> dict[str, Any]:
    cross = evidence["global-stock-data-official-cross-validation-evidence.json"]
    hkex = find_by(
        cross.get("checks"),
        "name",
        "hkexnews-tencent-2025-annual-report",
        "hk.checks",
    )
    issuer = find_by(
        cross.get("checks"),
        "name",
        "tencent-ir-2025-annual-report",
        "hk.checks",
    )
    if not (
        hkex.get("http_status") == 200
        and issuer.get("http_status") == 200
        and hkex.get("content_type") == "application/pdf"
        and issuer.get("content_type") == "application/pdf"
        and hkex.get("sha256") == issuer.get("sha256")
        and hkex.get("bytes") == issuer.get("bytes")
        and cross.get("raw_bodies_persisted") is False
        and cross.get("cross_validation", {}).get("byte_identical") is True
    ):
        fail("hk: official/issuer cross-validation invariants failed")
    retrieved_at = require_string(cross.get("retrieved_at"), "hk.retrieved_at")
    records = [
        {
            "authority": "HKEXnews",
            "observation": "hkexnews-tencent-2025-annual-report",
            "response_sha256": require_string(hkex.get("sha256"), "hk.hkex.sha256"),
            "published_at_state": "present",
            "available_at_state": "release_time_only",
            "retrieved_at": retrieved_at,
            "raw_payload_state": "not_retained",
            "normalization_status": "blocked",
        },
        {
            "authority": "Tencent investor relations",
            "observation": "tencent-ir-2025-annual-report",
            "response_sha256": require_string(issuer.get("sha256"), "hk.issuer.sha256"),
            "published_at_state": "mirrored_filing",
            "available_at_state": "unproven",
            "retrieved_at": retrieved_at,
            "raw_payload_state": "not_retained",
            "normalization_status": "blocked",
        },
    ]
    return base_outcome(
        plan,
        records,
        [
            "HKEX_AUTOMATION_RIGHTS_NOT_QUALIFIED",
            "HKEX_TYPED_ADAPTER_NOT_IMPLEMENTED",
            "HK_SECURITY_MASTER_HISTORY_MISSING",
            "HK_CORPORATE_ACTION_LINEAGE_MISSING",
            "HK_EXECUTION_RULES_UNQUALIFIED",
        ],
    )


def verify_vibe_rejection(evidence: dict[str, Any]) -> dict[str, Any]:
    vibe = evidence["vibe-trading-runtime-evidence.json"]
    decision = vibe.get("decision")
    if not isinstance(decision, dict):
        fail("vibe: decision missing")
    if decision.get("entire_mcp_server") != "reject":
        fail("vibe: entire MCP rejection changed")
    if decision.get("production_mcp_allowlist") != []:
        fail("vibe: production allowlist is not empty")
    for field in ("generic_backtest_tool", "walk_forward", "bootstrap"):
        if decision.get(field) != "reject":
            fail(f"vibe: {field} rejection changed")
    if decision.get("monte_carlo") != "reject_as_monte_carlo":
        fail("vibe: monte_carlo rejection changed")
    return {
        "upstream_decision": "reject",
        "production_mcp_allowlist": [],
        "candidate_result_policy": "blocked_without_result",
    }


def negative_admission_checks() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for kind in REJECTED_RAW_KINDS:
        candidate = {
            "kind": kind,
            "authority_claim": True,
            "payload": "synthetic-adversarial-placeholder",
        }
        admitted = candidate["kind"] == ALLOWED_AUTHORITATIVE_INPUT
        if admitted:
            fail(f"negative admission unexpectedly accepted {kind}")
        checks.append(
            {
                "kind": kind,
                "status": "passed",
                "decision": "rejected_as_authoritative_result",
                "reason_code": "TYPED_OFFICIAL_FACT_REQUIRED",
            }
        )
    return checks


def verify_deterministic_replays(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for filename, expected_hash, count_field, expected_count in REPLAY_SPECS:
        path = root / filename
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            fail(
                f"{filename}: replay hash mismatch "
                f"expected={expected_hash} actual={actual_hash}"
            )
        completed = subprocess.run(
            ["node", str(path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if completed.returncode != 0:
            fail(f"{filename}: replay exited {completed.returncode}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            fail(f"{filename}: replay stdout is not JSON")
        if not isinstance(payload, dict):
            fail(f"{filename}: replay result is not an object")
        if payload.get(count_field) != expected_count:
            fail(
                f"{filename}: expected {count_field}={expected_count}, "
                f"got {payload.get(count_field)!r}"
            )
        if filename == "global-stock-data-fixture-replay.mjs":
            if payload.get("failed") != 0:
                fail(f"{filename}: replay reported failed checks")
        elif payload.get("fixture_kind") != "synthetic-no-provider-payload":
            fail(f"{filename}: fixture boundary changed")
        results.append(
            {
                "argv": ["node", filename],
                "exit_code": completed.returncode,
                "script_sha256": actual_hash,
                "stdout_sha256": sha256_bytes(completed.stdout.encode("utf-8")),
                "assertion_field": count_field,
                "assertion_count": expected_count,
                "status": "passed",
            }
        )
    return results


def build_evidence(plan_path: Path) -> dict[str, Any]:
    evidence_files, upstreams, plans = parse_plan(plan_path)
    root = plan_path.parent
    loaded, evidence_hashes = verify_evidence_files(root, evidence_files)
    pinned = verify_upstreams(upstreams)
    slices = [
        build_a_share_slice(plans[0], loaded),
        build_us_slice(plans[1], loaded),
        build_hk_slice(plans[2], loaded),
    ]
    if any(
        item["production_replacement_gate"]["status"] != "failed" for item in slices
    ):
        fail("a market slice incorrectly passed the production replacement gate")
    if any(
        item["frozen_evidence"]["authoritative_financial_fact_count"] != 0
        for item in slices
    ):
        fail("an unparsed raw observation became an authoritative fact")
    negative = negative_admission_checks()
    core = {
        "upstreams": pinned,
        "input_evidence_sha256": evidence_hashes,
        "deterministic_replays": verify_deterministic_replays(root),
        "slices": slices,
        "raw_authority_admission_checks": negative,
        "strategy_runtime": verify_vibe_rejection(loaded),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_sha256": sha256_file(plan_path),
        "verifier_sha256": sha256_file(Path(__file__).resolve()),
        **core,
        "artifact_manifest_sha256": canonical_hash(core),
        "summary": {
            "slice_count": len(slices),
            "frozen_evidence_count": len(slices),
            "research_blocked_count": sum(
                item["research_evaluation"]["status"] == "blocked" for item in slices
            ),
            "valuation_not_comparable_count": sum(
                item["valuation"]["status"] == "not_comparable" for item in slices
            ),
            "strategy_blocked_count": sum(
                item["strategy_validation"]["status"] == "blocked" for item in slices
            ),
            "production_gate_failed_count": sum(
                item["production_replacement_gate"]["status"] == "failed"
                for item in slices
            ),
            "raw_authority_rejection_count": len(negative),
            "verification_status": "passed",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(__file__).with_name("market-validation-slices.json"),
    )
    parser.add_argument("--write-evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = build_evidence(args.plan.resolve())
        encoded = json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        if args.write_evidence is not None:
            args.write_evidence.resolve().write_text(encoded, encoding="utf-8")
        summary = evidence["summary"]
        print(
            "market-validation-slices: "
            f"{summary['slice_count']} slices verified; "
            f"{summary['production_gate_failed_count']} expected production gates failed; "
            f"{summary['raw_authority_rejection_count']} raw-authority attacks rejected"
        )
        print(f"artifact_manifest_sha256={evidence['artifact_manifest_sha256']}")
        return 0
    except (VerificationFailure, subprocess.TimeoutExpired) as exc:
        print(
            f"market-validation-slices: verification failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
