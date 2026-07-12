from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .canonical import canonical_hash


@dataclass(frozen=True)
class CodeIdentity:
    commit: Optional[str]
    source_hash: str
    lock_hash: str
    migration_hash: str
    workflow_hash: str
    frontend_hash: str
    config_hash: str
    package_build_hash: str
    model_policy_hash: str
    dependency_license_hash: str
    random_seed: None = None
    determinism_basis: str = "deterministic"


def _hash_files(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _git(root: Path, *args: str) -> Optional[str]:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def build_code_identity(root: Path, deterministic_config: object) -> CodeIdentity:
    root = root.resolve()
    commit = _git(root, "rev-parse", "HEAD")
    tracked = (_git(root, "ls-files") or "").splitlines()
    untracked = (_git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines()
    source_paths = [root / name for name in tracked + untracked if name.startswith(("src/", "scripts/", "web/", "migrations/"))]
    locks = [root / name for name in tracked + untracked if Path(name).name in {"pyproject.toml", "package-lock.json", "requirements.lock", "uv.lock"}]
    package_build = [root / name for name in tracked + untracked if Path(name).name in {"pyproject.toml", "setup.cfg", "setup.py", "MANIFEST.in"}]
    model_policy = [
        root / name
        for name in tracked + untracked
        if name.startswith(("src/trading_platform/market/", "src/trading_platform/plans/", "src/trading_platform/domain/market.py", "src/trading_platform/market.py", "src/equity_research/"))
        and name.endswith(".py")
    ]
    licenses = [root / name for name in tracked + untracked if Path(name).name.lower().startswith(("license", "notice", "third_party"))]
    return CodeIdentity(
        commit=commit,
        source_hash=_hash_files(root, source_paths),
        lock_hash=_hash_files(root, locks),
        migration_hash=_hash_files(root, (root / "migrations").glob("**/*") if (root / "migrations").exists() else ()),
        workflow_hash=_hash_files(root, (root / "src/trading_platform/workflows").glob("**/*") if (root / "src/trading_platform/workflows").exists() else ()),
        frontend_hash=_hash_files(root, (root / "web").glob("**/*") if (root / "web").exists() else ()),
        config_hash=canonical_hash(deterministic_config),
        package_build_hash=_hash_files(root, package_build),
        model_policy_hash=_hash_files(root, model_policy),
        dependency_license_hash=_hash_files(root, licenses),
    )
