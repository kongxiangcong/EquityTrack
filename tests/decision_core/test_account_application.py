from __future__ import annotations

from trading_platform.application import open_application
import pytest


def account_candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "account_id": "account-orchid",
        "as_of": "2035-04-18T08:00:00+00:00",
        "confirmed": True,
        "confirmed_by": "synthetic-user",
        "cash": None,
        "positions": [
            {
                "security_id": "security-aster-001",
                "quantity": "120",
                "available_quantity": None,
                "cost_basis": None,
            }
        ],
    }
    candidate.update(overrides)
    return candidate


def test_account_confirm_replays_and_preserves_unknowns_after_restart(tmp_path) -> None:
    app = open_application(tmp_path)
    first = app.account_confirm(account_candidate(), idempotency_key="confirm-orchid")

    assert first.ok
    assert first.value["cash"] is None
    assert first.value["positions"][0]["cost_basis"] is None

    replay = open_application(tmp_path).account_confirm(
        account_candidate(), idempotency_key="confirm-orchid"
    )
    shown = open_application(tmp_path).account_show("account-orchid")

    assert replay.ok and replay.value["snapshot_id"] == first.value["snapshot_id"]
    assert shown.ok and shown.value == first.value


def test_same_idempotency_key_with_changed_request_conflicts(tmp_path) -> None:
    app = open_application(tmp_path)
    assert app.account_confirm(account_candidate(), idempotency_key="same-key").ok

    conflict = app.account_confirm(
        account_candidate(as_of="2035-04-19T08:00:00+00:00"),
        idempotency_key="same-key",
    )

    assert not conflict.ok
    assert conflict.error["code"] == "IDEMPOTENCY_CONFLICT"


def test_revision_appends_without_replacing_history(tmp_path) -> None:
    app = open_application(tmp_path)
    original = app.account_confirm(account_candidate(), idempotency_key="original")
    revised = app.account_confirm(
        account_candidate(
            cash={"amount": "8000", "currency": "XCU"},
            change_kind="revision",
            replaces_snapshot_id=original.value["snapshot_id"],
        ),
        idempotency_key="revision",
    )

    assert revised.ok
    assert revised.value["replaces_snapshot_id"] == original.value["snapshot_id"]
    assert revised.value["snapshot_id"] != original.value["snapshot_id"]
    assert app.account_confirm(account_candidate(), idempotency_key="original").value == original.value


def test_correction_appends_and_names_the_snapshot_it_corrects(tmp_path) -> None:
    app = open_application(tmp_path)
    original = app.account_confirm(account_candidate(), idempotency_key="original-correction")
    corrected = app.account_confirm(
        account_candidate(
            cash={"amount": "8100", "currency": "XCU"},
            change_kind="correction",
            correction_reason="Fixture cash transcription correction.",
            replaces_snapshot_id=original.value["snapshot_id"],
        ),
        idempotency_key="correction",
    )

    assert corrected.ok
    assert corrected.value["change_kind"] == "correction"
    assert corrected.value["replaces_snapshot_id"] == original.value["snapshot_id"]
    assert corrected.value["snapshot_id"] != original.value["snapshot_id"]


def test_failed_commit_leaves_no_account_or_idempotency_record(tmp_path) -> None:
    failing = open_application(tmp_path, fault_at="before_commit")
    failed = failing.account_confirm(account_candidate(), idempotency_key="retry-me")

    assert not failed.ok and failed.error["code"] == "PERSISTENCE_FAILURE"
    assert not open_application(tmp_path).account_show("account-orchid").ok

    retry = open_application(tmp_path).account_confirm(
        account_candidate(), idempotency_key="retry-me"
    )
    assert retry.ok


@pytest.mark.parametrize("actor", [None, ""])
def test_account_confirmation_requires_a_named_user(tmp_path, actor) -> None:
    result = open_application(tmp_path).account_confirm(
        account_candidate(confirmed_by=actor), idempotency_key=f"missing-actor-{actor!r}"
    )

    assert not result.ok and result.error["code"] == "INVALID_INPUT"


@pytest.mark.parametrize(
    "override",
    [
        {"cash": {}},
        {"cash": {"amount": "NaN", "currency": "XCU"}},
        {"positions": [{"security_id": "security-aster-001", "quantity": "Infinity"}]},
    ],
)
def test_account_confirmation_rejects_malformed_or_non_finite_money(tmp_path, override) -> None:
    result = open_application(tmp_path).account_confirm(
        account_candidate(**override), idempotency_key=f"invalid-money-{override!r}"
    )

    assert not result.ok and result.error["code"] == "INVALID_INPUT"
