from __future__ import annotations

import threading
import sys
from pathlib import Path

from trading_platform.verification import (
    ProjectVerification,
    SubprocessVerificationExecutor,
    VerificationSuite,
    VerificationSuiteResult,
)


class RecordingExecutor:
    def __init__(self) -> None:
        self.suites = []

    def execute(self, suite, emit, heartbeat_seconds):
        del emit, heartbeat_seconds
        self.suites.append(suite)
        return VerificationSuiteResult(
            name=suite.name,
            status="passed",
            exit_code=0,
            duration_seconds=0.01,
            command=suite.display_command,
        )


class ConcurrentExecutor:
    def __init__(self, expected_suites: int) -> None:
        self.barrier = threading.Barrier(expected_suites)
        self.started: set[str] = set()
        self.lock = threading.Lock()

    def execute(self, suite, emit, heartbeat_seconds):
        del heartbeat_seconds
        with self.lock:
            self.started.add(suite.name)
        emit({"event": "suite_started", "suite": suite.name})
        self.barrier.wait(timeout=1)
        failed = suite.name == "platform-2"
        return VerificationSuiteResult(
            name=suite.name,
            status="failed" if failed else "passed",
            exit_code=1 if failed else 0,
            duration_seconds=0.02,
            command=suite.display_command,
            failure_code="SUITE_EXIT_NONZERO" if failed else None,
            stderr_tail="assertion failed" if failed else "",
        )


def test_project_verification_runs_every_test_file_once_without_nested_acceptance() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    executor = RecordingExecutor()

    report = ProjectVerification(
        executor=executor,
        npm_executable="npm.cmd",
        platform_shards=4,
    ).run(repo_root)

    python_arguments = [
        argument.replace("\\", "/")
        for suite in executor.suites
        if suite.name != "web"
        for argument in suite.command
        if argument.endswith(".py")
    ]
    expected = sorted(
        path.relative_to(repo_root).as_posix()
        for root in (repo_root / "tests", repo_root / "tests/platform")
        for path in root.glob("test_*.py")
    )

    assert sorted(python_arguments) == expected
    assert len(python_arguments) == len(set(python_arguments))
    assert all("release_acceptance" not in suite.command for suite in executor.suites)
    assert report.status == "passed"
    assert {suite.name for suite in executor.suites} == {
        "core",
        "platform-1",
        "platform-2",
        "platform-3",
        "platform-4",
        "web",
    }


def test_project_verification_runs_suites_concurrently_and_keeps_failure_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    executor = ConcurrentExecutor(expected_suites=6)
    events: list[dict[str, object]] = []

    report = ProjectVerification(
        executor=executor,
        npm_executable="npm.cmd",
        platform_shards=4,
    ).run(repo_root, events.append)

    assert report.status == "failed"
    assert executor.started == {
        "core",
        "platform-1",
        "platform-2",
        "platform-3",
        "platform-4",
        "web",
    }
    assert [suite.name for suite in report.suites] == [
        "core",
        "platform-1",
        "platform-2",
        "platform-3",
        "platform-4",
        "web",
    ]
    failure = next(suite for suite in report.suites if suite.status == "failed")
    assert failure.name == "platform-2"
    assert failure.failure_code == "SUITE_EXIT_NONZERO"
    assert failure.stderr_tail == "assertion failed"
    assert {event["suite"] for event in events} == executor.started


def test_subprocess_verification_streams_redacted_progress_and_failure_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "verification-secret-must-not-leak"
    monkeypatch.setenv("TEST_API_TOKEN", secret)
    suite = VerificationSuite(
        name="failing-smoke",
        command=(
            sys.executable,
            "-c",
            (
                "import os,sys,time; "
                "print('中文诊断 step-one=' + os.environ['TEST_API_TOKEN'], flush=True); "
                "time.sleep(0.08); "
                "print('token=' + os.environ['TEST_API_TOKEN'], file=sys.stderr, flush=True); "
                "raise SystemExit(3)"
            ),
        ),
        cwd=tmp_path,
    )
    events: list[dict[str, object]] = []

    result = SubprocessVerificationExecutor().execute(
        suite,
        events.append,
        heartbeat_seconds=0.02,
    )

    assert result.status == "failed"
    assert result.exit_code == 3
    assert result.failure_code == "SUITE_EXIT_NONZERO"
    assert secret not in result.summary
    assert secret not in result.stdout_tail
    assert secret not in result.stderr_tail
    assert "[REDACTED]" in result.stdout_tail
    assert "中文诊断" in result.stdout_tail
    output_events = [event for event in events if event["event"] == "suite_output"]
    assert output_events
    assert secret not in str(output_events)
    assert events[0]["event"] == "suite_started"
    assert events[-1]["event"] == "suite_finished"
    assert any(event["event"] == "suite_heartbeat" for event in events)


def test_subprocess_verification_preserves_process_start_failure_code(
    tmp_path: Path,
) -> None:
    suite = VerificationSuite(
        name="missing-runtime",
        command=(str(tmp_path / "missing-runtime.exe"),),
        cwd=tmp_path,
    )

    result = SubprocessVerificationExecutor().execute(suite, lambda event: None, 1)

    assert result.status == "failed"
    assert result.failure_code == "SUITE_PROCESS_START_FAILED"
    assert result.stderr_tail
