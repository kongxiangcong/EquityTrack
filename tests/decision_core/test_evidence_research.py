from __future__ import annotations

import pytest

from trading_platform.application import open_application
from trading_platform.evidence import FixtureEvidenceAdapter, build_evidence_set


AS_OF = "2035-04-18T08:00:00+00:00"


def evidence_set(*, missing: bool = False) -> dict[str, object]:
    items = [
        {"name": "market_price", "value": "17.50", "source_id": "fixture-source-price", "as_of": AS_OF},
        {"name": "free_cash_flow", "missing_reason": "fixture omission", "as_of": AS_OF}
        if missing
        else {"name": "free_cash_flow", "value": "420", "source_id": "fixture-source-fcf", "as_of": AS_OF},
    ]
    return build_evidence_set(AS_OF, items).as_dict()


def candidate() -> dict[str, object]:
    return {
        "thesis": "A falsifiable capacity thesis grounded in fixture evidence.",
        "counterargument": "Capacity could fail to translate into durable economics.",
        "drivers": ["fixture capacity utilization"],
        "risks": ["fixture demand contraction"],
        "falsifiers": ["utilization remains below the stated threshold"],
        "uncertainties": ["future demand is an assumption"],
    }


def test_evidence_requires_exactly_source_or_missing_and_deduplicates() -> None:
    item = {"name": "price", "value": "10", "source_id": "fixture-source-price", "as_of": AS_OF}
    result = build_evidence_set(AS_OF, [item, item])
    assert len(result.items) == 1

    with pytest.raises(ValueError, match="exactly one"):
        build_evidence_set(AS_OF, [{"name": "bad", "value": "1", "source_id": "s", "missing_reason": "also missing", "as_of": AS_OF}])
    with pytest.raises(ValueError, match="as_of"):
        build_evidence_set(AS_OF, [item | {"as_of": "2035-04-17T08:00:00+00:00"}])


def test_fixture_adapter_is_deterministic_and_controls_failure_modes() -> None:
    adapter = FixtureEvidenceAdapter()
    assert adapter.collect("complete", AS_OF).as_dict() == adapter.collect("complete", AS_OF).as_dict()
    assert any(item.missing_reason is not None for item in adapter.collect("missing", AS_OF).items)
    assert adapter.collect("stale", AS_OF).as_of == "2035-04-01T08:00:00+00:00"
    with pytest.raises(ValueError, match="conflicting duplicate"):
        adapter.collect("conflict", AS_OF)
    with pytest.raises(RuntimeError, match="fixture provider failure"):
        adapter.collect("failure", AS_OF)


def test_research_commit_allows_local_missing_and_replays_after_restart(tmp_path) -> None:
    request = {
        "security_id": "security-aster-001",
        "as_of": AS_OF,
        "evidence_set": evidence_set(missing=True),
        "candidate": candidate(),
    }
    first = open_application(tmp_path).research_commit(request, idempotency_key="research-orchid")
    replay = open_application(tmp_path).research_commit(request, idempotency_key="research-orchid")

    assert first.ok and replay.value == first.value
    assert first.value["limitations"] == ["free_cash_flow: fixture omission"]
    assert "valuation" not in first.value and "action" not in first.value


def test_research_rejects_valuation_or_action_content_and_rolls_back(tmp_path) -> None:
    request = {
        "security_id": "security-aster-001",
        "as_of": AS_OF,
        "evidence_set": evidence_set(),
        "candidate": candidate() | {"target_price": "99"},
    }
    rejected = open_application(tmp_path).research_commit(request, idempotency_key="bad-research")
    assert not rejected.ok and rejected.error["code"] == "INVALID_INPUT"

    failing = open_application(tmp_path, fault_at="before_commit").research_commit(
        request | {"candidate": candidate()}, idempotency_key="retry-research"
    )
    assert not failing.ok and failing.error["code"] == "PERSISTENCE_FAILURE"
    retry = open_application(tmp_path).research_commit(
        request | {"candidate": candidate()}, idempotency_key="retry-research"
    )
    assert retry.ok
