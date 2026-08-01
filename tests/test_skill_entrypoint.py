import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


class SkillEntrypointTests(unittest.TestCase):
    def test_equity_research_has_one_skill_entrypoint(self) -> None:
        entrypoints = sorted(path.name for path in SKILLS.glob("SKILL*.md"))
        self.assertEqual(["SKILL.md"], entrypoints)

    def test_entrypoint_is_the_six_task_natural_language_router(self) -> None:
        content = (SKILLS / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("这是本项目唯一的用户入口", content)
        self.assertEqual(6, sum(line.startswith("### ") for line in content.splitlines()))
        for label in (
            "查看当前账户",
            "更新今天状态",
            "本周或指定周期复盘",
            "研究一只股票并生成图表报告",
            "创建交易计划",
            "更新交易计划",
        ):
            self.assertIn(label, content)
        self.assertNotIn("python -m trading_platform.cli", content)
        self.assertNotIn("ApplicationCommandEnvelope@1", content)

    def test_active_skill_tree_does_not_reference_retired_entrypoints(self) -> None:
        retired_names = (
            "SKILL-v2",
            "SKILL-v3",
            "SKILL-equity-task1",
            "SKILL-task2-model",
            "SKILL-task3-report",
            "SKILL-tearsheet",
        )
        occurrences: list[str] = []
        for path in SKILLS.rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            for retired in retired_names:
                if retired in content:
                    occurrences.append(f"{path.relative_to(SKILLS)}: {retired}")
        self.assertEqual([], occurrences)

    def test_all_entrypoint_reference_paths_exist(self) -> None:
        for relative_path in (
            "tasks/account-status.md",
            "tasks/cycle-review.md",
            "tasks/equity-research.md",
            "tasks/trade-plan.md",
            "references/platform-control-plane.md",
            "references/source-manifest.md",
            "references/output-schema.md",
            "references/financial-model-spec.md",
            "valuation/valuation-method-router.md",
            "valuation/industry-valuation-matrix.md",
            "valuation/dcf-and-sensitivity.md",
            "output/report-layout.md",
        ):
            self.assertTrue((SKILLS / relative_path).is_file(), relative_path)

    def test_internal_research_reference_names_the_formal_route(self) -> None:
        internal = (SKILLS / "references/platform-control-plane.md").read_text(
            encoding="utf-8"
        )
        research = (SKILLS / "tasks/equity-research.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "ResearchWorkflow.handle(StartResearchWorkflow(request))",
            internal,
        )
        self.assertIn("ResearchWorkflow", research)
        self.assertNotIn("scripts\\research.py", internal + research)
        self.assertNotIn("ApplicationFacade", internal + research)


if __name__ == "__main__":
    unittest.main()