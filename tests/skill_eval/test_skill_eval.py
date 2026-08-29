from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_skill_eval_fixture_covers_ai_authority_boundaries() -> None:
    cases = json.loads((ROOT / "tests/skill_eval/cases.json").read_text(encoding="utf-8"))
    outputs = json.loads((ROOT / "tests/skill_eval/outputs.json").read_text(encoding="utf-8"))
    assert {case["case"] for case in cases} == {
        "fact-assumption-missing", "balanced-investment-case", "local-evidence-degradation",
        "financial-output-boundary", "process-outcome-separation",
    }
    assert all(case["expected_checks"] and case["forbidden"] for case in cases)
    by_case = {result["case"]: result for result in outputs["results"]}
    assert set(by_case) == {case["case"] for case in cases}
    for case in cases:
        result = by_case[case["case"]]
        assert result["response"]
        assert set(result["checks"]) == set(case["expected_checks"])
        assert all(check["pass"] for check in result["checks"].values())
        assert all(check["evidence"] in result["response"] for check in result["checks"].values())
        assert set(result["forbidden"]) == set(case["forbidden"])
        assert not any(check["present"] for check in result["forbidden"].values())


def test_skill_instructions_encode_every_eval_rubric_without_runtime_narrative() -> None:
    skill = (ROOT / "skills/SKILL.md").read_text(encoding="utf-8")
    research = (ROOT / "skills/tasks/research.md").read_text(encoding="utf-8")
    valuation = (ROOT / "skills/tasks/valuation.md").read_text(encoding="utf-8")
    review = (ROOT / "skills/tasks/review.md").read_text(encoding="utf-8")
    assert all(term in skill + research for term in ("事实", "假设", "估计", "缺失", "论点", "反方", "证伪", "不确定性"))
    assert all(term in skill + valuation for term in ("insufficient", "评级", "目标价", "个性化"))
    assert all(term in review for term in ("PROCESS", "OUTCOME", "冻结", "引用"))
    assert not list((ROOT / "skills").rglob("*.py"))
