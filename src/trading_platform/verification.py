from __future__ import annotations

import os
import re
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from subprocess import PIPE, Popen
from threading import Thread
from typing import Callable, Protocol, TextIO


VerificationEventSink = Callable[[dict[str, object]], None]


@dataclass(frozen=True)
class VerificationSuite:
    name: str
    command: tuple[str, ...]
    cwd: Path

    @property
    def display_command(self) -> str:
        return " ".join("python" if item == sys.executable else item for item in self.command)


@dataclass(frozen=True)
class VerificationSuiteResult:
    name: str
    status: str
    exit_code: int
    duration_seconds: float
    command: str
    failure_code: str | None = None
    summary: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReport:
    status: str
    duration_seconds: float
    suites: tuple[VerificationSuiteResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "suites": [suite.to_dict() for suite in self.suites],
        }


class VerificationSuiteExecutor(Protocol):
    def execute(
        self,
        suite: VerificationSuite,
        emit: VerificationEventSink,
        heartbeat_seconds: float,
    ) -> VerificationSuiteResult: ...


class SubprocessVerificationExecutor:
    """Run one suite with bounded diagnostics and observable progress."""

    OUTPUT_TAIL_LIMIT = 4_000
    OUTPUT_LINE_LIMIT = 1_000
    OUTPUT_LINE_COUNT = 100

    def __init__(self) -> None:
        self._redactor = VerificationOutputRedactor()

    def execute(
        self,
        suite: VerificationSuite,
        emit: VerificationEventSink,
        heartbeat_seconds: float,
    ) -> VerificationSuiteResult:
        started = time.monotonic()
        display_command = self._redactor.redact(suite.display_command)
        emit(
            {
                "event": "suite_started",
                "suite": suite.name,
                "command": display_command,
            }
        )
        try:
            process = Popen(
                suite.command,
                cwd=suite.cwd,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            stdout_lines: deque[str] = deque(maxlen=self.OUTPUT_LINE_COUNT)
            stderr_lines: deque[str] = deque(maxlen=self.OUTPUT_LINE_COUNT)
            readers = (
                Thread(
                    target=self._consume,
                    args=(process.stdout, "stdout", suite, stdout_lines, emit),
                    daemon=True,
                ),
                Thread(
                    target=self._consume,
                    args=(process.stderr, "stderr", suite, stderr_lines, emit),
                    daemon=True,
                ),
            )
            for reader in readers:
                reader.start()
            interval = max(heartbeat_seconds, 0.01)
            next_heartbeat = started + interval
            while process.poll() is None:
                time.sleep(min(interval, 0.1))
                now = time.monotonic()
                if now >= next_heartbeat:
                    emit(
                        {
                            "event": "suite_heartbeat",
                            "suite": suite.name,
                            "elapsed_seconds": round(now - started, 3),
                        }
                    )
                    next_heartbeat = now + interval
            for reader in readers:
                reader.join()
            summary = self._summary(stdout_lines)
            stdout_tail = self._tail(stdout_lines)
            stderr_tail = self._tail(stderr_lines)
            exit_code = int(process.returncode or 0)
            failure_code = "SUITE_EXIT_NONZERO" if exit_code else None
        except OSError as error:
            exit_code = -1
            failure_code = "SUITE_PROCESS_START_FAILED"
            summary = ""
            stdout_tail = ""
            stderr_tail = self._redactor.redact(str(error))[-self.OUTPUT_TAIL_LIMIT :]

        duration = round(time.monotonic() - started, 3)
        status = "passed" if exit_code == 0 else "failed"
        emit(
            {
                "event": "suite_finished",
                "suite": suite.name,
                "status": status,
                "exit_code": exit_code,
                "duration_seconds": duration,
            }
        )
        return VerificationSuiteResult(
            name=suite.name,
            status=status,
            exit_code=exit_code,
            duration_seconds=duration,
            command=display_command,
            failure_code=failure_code,
            summary=summary,
            stdout_tail=stdout_tail if exit_code else "",
            stderr_tail=stderr_tail if exit_code else "",
        )

    def _consume(
        self,
        stream: TextIO | None,
        stream_name: str,
        suite: VerificationSuite,
        lines: deque[str],
        emit: VerificationEventSink,
    ) -> None:
        if stream is None:
            return
        try:
            for raw_line in stream:
                line = self._redactor.redact(raw_line.rstrip())
                if not line:
                    continue
                line = line[-self.OUTPUT_LINE_LIMIT :]
                lines.append(line)
                emit(
                    {
                        "event": "suite_output",
                        "suite": suite.name,
                        "stream": stream_name,
                        "text": line,
                    }
                )
        finally:
            stream.close()

    def _tail(self, lines: deque[str]) -> str:
        return "\n".join(lines)[-self.OUTPUT_TAIL_LIMIT :]

    @staticmethod
    def _summary(lines: deque[str]) -> str:
        return " | ".join(tuple(lines)[-4:])[-1_000:]


class VerificationOutputRedactor:
    """Apply the verification command's fail-closed output security policy."""

    SENSITIVE_NAME = re.compile(
        r"(?:token|secret|password|passwd|api[_-]?key|credential|authorization)",
        re.IGNORECASE,
    )
    SENSITIVE_ASSIGNMENT = re.compile(
        r"(?i)\b(token|secret|password|passwd|api[_-]?key|credential|authorization)"
        r"\s*([=:])\s*[^\s,;]+"
    )
    BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;]+")

    def __init__(self) -> None:
        self._secret_values = tuple(
            sorted(
                {
                    value
                    for name, value in os.environ.items()
                    if value and len(value) >= 4 and self.SENSITIVE_NAME.search(name)
                },
                key=len,
                reverse=True,
            )
        )
        self._private_paths = tuple(
            sorted({str(Path.home()), os.environ.get("USERPROFILE", "")}, key=len, reverse=True)
        )

    def redact(self, value: str) -> str:
        redacted = value
        for secret in self._secret_values:
            redacted = redacted.replace(secret, "[REDACTED]")
        redacted = self.SENSITIVE_ASSIGNMENT.sub(
            lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
            redacted,
        )
        redacted = self.BEARER.sub("Bearer [REDACTED]", redacted)
        for path in self._private_paths:
            if path:
                redacted = redacted.replace(path, "<user-home>")
        return redacted


class ProjectVerification:
    """Discover and execute each project test exactly once."""

    def __init__(
        self,
        *,
        executor: VerificationSuiteExecutor,
        npm_executable: str,
        platform_shards: int = 4,
        heartbeat_seconds: float = 10.0,
    ) -> None:
        if platform_shards < 1:
            raise ValueError("VERIFICATION_SHARD_COUNT_INVALID")
        self.executor = executor
        self.npm_executable = npm_executable
        self.platform_shards = platform_shards
        self.heartbeat_seconds = heartbeat_seconds

    def run(
        self,
        repo_root: Path,
        emit: VerificationEventSink | None = None,
    ) -> VerificationReport:
        root = repo_root.resolve()
        sink = emit or (lambda event: None)
        started = time.monotonic()
        suites = self._plan(root)
        with ThreadPoolExecutor(
            max_workers=len(suites),
            thread_name_prefix="project-verification",
        ) as workers:
            futures = tuple(
                workers.submit(
                    self.executor.execute,
                    suite,
                    sink,
                    self.heartbeat_seconds,
                )
                for suite in suites
            )
            results = tuple(future.result() for future in futures)
        return VerificationReport(
            status=(
                "passed"
                if all(result.status == "passed" for result in results)
                else "failed"
            ),
            duration_seconds=round(time.monotonic() - started, 3),
            suites=results,
        )

    def _plan(self, repo_root: Path) -> tuple[VerificationSuite, ...]:
        tests_root = repo_root / "tests"
        core_files = tuple(
            path.relative_to(repo_root).as_posix()
            for path in sorted(tests_root.glob("test_*.py"))
        )
        platform_files = sorted(
            (tests_root / "platform").glob("test_*.py"),
            key=lambda path: (-path.stat().st_size, path.name),
        )
        shard_count = min(self.platform_shards, max(1, len(platform_files)))
        shards: list[list[Path]] = [[] for _ in range(shard_count)]
        shard_sizes = [0] * shard_count
        for path in platform_files:
            index = min(range(shard_count), key=lambda item: (shard_sizes[item], item))
            shards[index].append(path)
            shard_sizes[index] += path.stat().st_size

        suites = [
            VerificationSuite(
                name="core",
                command=(sys.executable, "-m", "pytest", "-vv", "--tb=short", *core_files),
                cwd=repo_root,
            )
        ]
        suites.extend(
            VerificationSuite(
                name=f"platform-{index}",
                command=(
                    sys.executable,
                    "-m",
                    "pytest",
                    "-vv",
                    "--tb=short",
                    *(
                        path.relative_to(repo_root).as_posix()
                        for path in sorted(shard)
                    ),
                ),
                cwd=repo_root,
            )
            for index, shard in enumerate(shards, start=1)
        )
        suites.append(
            VerificationSuite(
                name="web",
                command=(self.npm_executable, "test"),
                cwd=repo_root / "web",
            )
        )
        return tuple(suites)
