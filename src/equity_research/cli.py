from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence

from .engine import ResearchEngine
from .models import ResearchRequest


def _load_json(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    file_path = Path(path).resolve()
    try:
        value = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"Cannot read JSON file {file_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {file_path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON root must be an object: {file_path}")
    return value


ARTIFACT_NAMES = {"research_run.json", "research_report.html"}


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse_flag = 0x400
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _assert_real_path(path: Path) -> None:
    for candidate in (path, *path.parents):
        if _is_link_or_reparse(candidate):
            raise ValueError(f"Output path cannot traverse a link or reparse point: {candidate}")


def _directory_inventory(path: Path) -> dict[str, tuple[int, int, int]]:
    inventory: dict[str, tuple[int, int, int]] = {}
    for item in path.iterdir():
        metadata = os.lstat(item)
        inventory[item.name] = (
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
    return inventory


def _acquire_publish_lock(lock_path: Path) -> BinaryIO:
    lock_handle = lock_path.open("a+b")
    lock_handle.seek(0, os.SEEK_END)
    if lock_handle.tell() == 0:
        lock_handle.write(b"\0")
        lock_handle.flush()
    lock_handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock_handle.close()
        raise ValueError(
            f"Another publisher holds the output lock: {lock_path}"
        ) from exc
    try:
        lock_handle.seek(0)
        lock_handle.truncate()
        lock_handle.write(
            json.dumps(
                {"last_owner_pid": os.getpid()},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        lock_handle.flush()
    except Exception:
        _release_publish_lock(lock_handle)
        raise
    return lock_handle


def _release_publish_lock(lock_handle: BinaryIO) -> None:
    try:
        lock_handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    finally:
        lock_handle.close()


def _publish_artifacts(
    output_dir: Path,
    payload: str,
    report: str,
) -> tuple[Path, Path, tuple[str, ...]]:
    output_dir = output_dir.absolute()
    _assert_real_path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    _assert_real_path(output_dir.parent)
    lock_path = output_dir.parent / f".{output_dir.name}.publish.lock"
    lock_handle = _acquire_publish_lock(lock_path)

    staging: Path | None = None
    backup = output_dir.parent / f".{output_dir.name}.backup-{uuid.uuid4().hex}"
    warnings: list[str] = []
    try:
        expected_inventory: dict[str, tuple[int, int, int]] = {}
        if output_dir.exists():
            if not output_dir.is_dir() or _is_link_or_reparse(output_dir):
                raise ValueError("Output path must be a real directory managed by this command.")
            entries = list(output_dir.iterdir())
            unexpected = {item.name for item in entries} - ARTIFACT_NAMES
            if unexpected:
                raise ValueError(
                    "Output directory contains unmanaged files: "
                    + ", ".join(sorted(unexpected))
                )
            invalid_artifacts = [
                item.name
                for item in entries
                if item.name in ARTIFACT_NAMES
                and (not item.is_file() or _is_link_or_reparse(item))
            ]
            if invalid_artifacts:
                raise ValueError(
                    "Managed artifact names must be regular files: "
                    + ", ".join(sorted(invalid_artifacts))
                )
            expected_inventory = _directory_inventory(output_dir)

        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_dir.name}.staging-",
                dir=output_dir.parent,
            )
        )
        (staging / "research_run.json").write_text(payload, encoding="utf-8")
        (staging / "research_report.html").write_text(report, encoding="utf-8")
        if output_dir.exists():
            os.replace(output_dir, backup)
            try:
                inventory_changed = _directory_inventory(backup) != expected_inventory
            except Exception:
                if backup.exists() and not output_dir.exists():
                    os.replace(backup, output_dir)
                raise
            if inventory_changed:
                os.replace(backup, output_dir)
                raise ValueError(
                    "Output directory changed during publication; original files were preserved."
                )
        try:
            os.replace(staging, output_dir)
            staging = None
        except OSError:
            if backup.exists() and not output_dir.exists():
                os.replace(backup, output_dir)
            raise
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                warnings.append(f"BACKUP_CLEANUP_PENDING:{backup}:{exc}")
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        _release_publish_lock(lock_handle)
    return (
        output_dir / "research_run.json",
        output_dir / "research_report.html",
        tuple(warnings),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="equity-research",
        description="Run the deterministic, capability-gated equity research core.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_inputs(command: argparse.ArgumentParser) -> None:
        command.add_argument("--manifest", required=True, help="Source manifest JSON path.")
        command.add_argument("--estimates", help="Optional estimate overlay JSON path.")
        command.add_argument("--context", help="Optional structured research context JSON path.")
        command.add_argument("--as-of-date", help="Locked research date (YYYY-MM-DD).")
        command.add_argument(
            "--profile",
            choices=("quick", "standard", "deep"),
            default="standard",
            help="Collection/render profile. It does not change safety invariants.",
        )

    run = subparsers.add_parser("run", help="Assess evidence and write canonical JSON + HTML.")
    add_inputs(run)
    run.add_argument("--output-dir", required=True, help="Artifact output directory.")

    assess = subparsers.add_parser("assess", help="Print canonical JSON without writing artifacts.")
    add_inputs(assess)
    assess.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = _load_json(args.manifest)
        estimates = _load_json(args.estimates)
        context = _load_json(args.context)
        assert manifest is not None
        as_of_date = (
            args.as_of_date
            or str((estimates or {}).get("as_of_date", ""))
            or str((context or {}).get("as_of_date", ""))
        ).strip()
        if not as_of_date:
            raise ValueError("--as-of-date is required unless an input JSON declares as_of_date.")

        request = ResearchRequest(
            manifest=manifest,
            estimates=estimates,
            context=context,
            as_of_date=as_of_date,
            profile=args.profile,
            render_html=args.command == "run",
        )
        run = ResearchEngine().run(request)
    except ValueError as exc:
        print(json.dumps({"error": "REQUEST_INVALID", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    payload = run.to_dict()
    if args.command == "assess":
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    else:
        output_dir = Path(args.output_dir).absolute()
        try:
            run_path, report_path, publish_warnings = _publish_artifacts(
                output_dir,
                json.dumps(payload, ensure_ascii=False, indent=2),
                run.html,
            )
        except (OSError, ValueError) as exc:
            print(
                json.dumps(
                    {"error": "ARTIFACT_PUBLISH_FAILED", "message": str(exc)},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "research_run": str(run_path),
                    "research_report": str(report_path),
                    "warnings": list(publish_warnings),
                },
                ensure_ascii=False,
            )
        )
    return 2 if run.status == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
