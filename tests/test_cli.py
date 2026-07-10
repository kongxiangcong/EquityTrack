from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.equity_research.cli import _acquire_publish_lock, _release_publish_lock


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "yihua-002897"


class CliBehaviorTests(unittest.TestCase):
    def test_run_command_writes_one_canonical_json_and_one_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "research.py"),
                    "run",
                    "--manifest",
                    str(EXAMPLE / "source_manifest.json"),
                    "--estimates",
                    str(EXAMPLE / "estimate_overlay.json"),
                    "--context",
                    str(EXAMPLE / "research_context.json"),
                    "--as-of-date",
                    "2026-07-07",
                    "--output-dir",
                    tmp,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            run_path = Path(tmp) / "research_run.json"
            report_path = Path(tmp) / "research_report.html"
            self.assertTrue(run_path.is_file())
            self.assertTrue(report_path.is_file())
            payload = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual("completed_with_limits", payload["status"])
            self.assertEqual("ready", payload["capabilities"]["research_core"]["status"])

    def test_run_refuses_artifact_named_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "managed-output"
            disguised = output / "research_run.json"
            disguised.mkdir(parents=True)
            marker = disguised / "user-data.txt"
            marker.write_text("keep", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "research.py"),
                    "run",
                    "--manifest",
                    str(EXAMPLE / "source_manifest.json"),
                    "--estimates",
                    str(EXAMPLE / "estimate_overlay.json"),
                    "--context",
                    str(EXAMPLE / "research_context.json"),
                    "--as-of-date",
                    "2026-07-07",
                    "--output-dir",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(2, completed.returncode)
            self.assertTrue(marker.is_file())
            self.assertIn("ARTIFACT_PUBLISH_FAILED", completed.stderr)

    def test_run_reuses_an_unlocked_publish_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "managed-output"
            lock = Path(tmp) / ".managed-output.publish.lock"
            lock.write_text(
                json.dumps({"pid": 999_999_999, "created_at": 0}),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "research.py"),
                    "run",
                    "--manifest",
                    str(EXAMPLE / "source_manifest.json"),
                    "--estimates",
                    str(EXAMPLE / "estimate_overlay.json"),
                    "--context",
                    str(EXAMPLE / "research_context.json"),
                    "--as-of-date",
                    "2026-07-07",
                    "--output-dir",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(lock.is_file())
            self.assertTrue((output / "research_run.json").is_file())

    def test_publish_lock_excludes_a_second_writer_and_can_be_reacquired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / ".managed-output.publish.lock"
            first_handle = _acquire_publish_lock(lock)
            try:
                with self.assertRaisesRegex(ValueError, "Another publisher"):
                    _acquire_publish_lock(lock)
            finally:
                _release_publish_lock(first_handle)

            second_handle = _acquire_publish_lock(lock)
            _release_publish_lock(second_handle)


if __name__ == "__main__":
    unittest.main()
