import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


class SkillEntrypointTests(unittest.TestCase):
    def test_equity_research_has_one_skill_entrypoint(self) -> None:
        entrypoints = sorted(path.name for path in SKILLS.glob("SKILL*.md"))

        self.assertEqual(["SKILL.md"], entrypoints)

    def test_entrypoint_contains_no_retired_routes(self) -> None:
        content = (SKILLS / "SKILL.md").read_text(encoding="utf-8")

        for retired in (
            "SKILL-v2",
            "SKILL-v3",
            "SKILL-equity-task1",
            "SKILL-task2-model",
            "SKILL-task3-report",
            "SKILL-tearsheet",
            "Task 1",
            "Task 2",
            "Task 3",
        ):
            self.assertNotIn(retired, content)

        self.assertIn("ResearchEngine.run(ResearchRequest) -> ResearchRun", content)
        self.assertIn("Evidence Ledger", content)
        self.assertIn("ResearchSynthesis", content)

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
            "references/source-manifest.md",
            "valuation/valuation-method-router.md",
            "valuation/industry-valuation-matrix.md",
            "valuation/dcf-and-sensitivity.md",
        ):
            self.assertTrue((SKILLS / relative_path).is_file(), relative_path)


if __name__ == "__main__":
    unittest.main()
