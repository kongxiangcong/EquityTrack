from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_skill_uses_shared_application_command_envelope_and_no_direct_storage() -> None:
    skill = (ROOT / "skills/SKILL.md").read_text(encoding="utf-8")
    assert "ApplicationCommandEnvelope@1" in skill
    assert (
        "python -m trading_platform.cli application-command "
        "--data-root <root> --envelope-file <command.json>"
    ) in skill
    for command in (
        "account_snapshot.register_account@2",
        "account_snapshot.create_draft@1",
        "account_snapshot.confirm@1",
        "trade_plan.issue_confirmation_challenge@1",
        "trade_plan.confirm@1",
        "manual_portfolio_review.run@1",
        "decision_task.defer@1",
        "execution_record.declare@1",
        "discipline_review.confirm@1",
    ):
        assert command in skill
    assert "Skill is the interaction channel, not the decision actor." in skill
    assert "ad-hoc SQL" in skill
