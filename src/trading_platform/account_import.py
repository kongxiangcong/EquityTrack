from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


class ImportPreviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


SCHEMAS = {
    "current_positions": ("tonghuashun-current-positions@1", ("操作", "序号", "证券代码", "证券名称", "股票余额", "可用余额", "冻结数量", "成本价", "市价", "盈亏估算", "盈亏比例(%)", "当日盈亏", "当日盈亏比(%)", "市值", "仓位占比(%)", "当日买入", "当日卖出", "交易市场", "持股天数")),
    "cash_ledger": ("tonghuashun-cash-ledger@1", ("日期", "成交日期", "证券代码", "证券名称", "操作", "成交数量", "成交均价", "发生金额", "剩余余额", "交易市场", "货币单位")),
    "holding_history": ("tonghuashun-holding-history@1", ("明细", "证券代码", "证券名称", "建仓日期", "清仓日期", "持股天数", "总盈亏", "盈亏比例(%)", "买入均价", "卖出均价")),
}


def personal_source_privacy_errors(repo_root: Path, paths: Iterable[Path]) -> tuple[str, ...]:
    repo_root = repo_root.resolve()
    for candidate in paths:
        path = Path(candidate).resolve()
        if path != repo_root and repo_root not in path.parents:
            continue
        relative = path.relative_to(repo_root).as_posix()
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", relative], cwd=repo_root, capture_output=True, check=False).returncode == 0
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", relative], cwd=repo_root, capture_output=True, check=False).returncode == 0
        if tracked or not ignored:
            return ("PERSONAL_SOURCE_IN_GIT_WORKTREE",)
    return ()


@dataclass(frozen=True)
class PreviewFile:
    role: str
    source_schema_version: str
    encoding: str
    delimiter: str
    row_count: int
    mapped_fields: tuple[str, ...]
    source_object_sha256: str


@dataclass(frozen=True)
class AsOfCandidate:
    status: str
    candidate_dates: tuple[str, ...]
    rationale: str
    trading_calendar_status: str
    export_time_basis: str


@dataclass(frozen=True)
class ImportPreview:
    schema_version: str
    account_alias: str
    base_currency: str
    files: tuple[PreviewFile, ...]
    cash_coverage: tuple[str, str] | None
    weak_key_collision_groups: int
    weak_key_collision_rows: int
    current_positions_as_of: AsOfCandidate
    missing_information: tuple[str, ...]
    capabilities: dict[str, bool]
    expires_at: str

    def to_safe_dict(self) -> dict[str, object]:
        return asdict(self)


class TonghuashunImportPreviewer:
    """Content-first, local-only preflight; it never creates account ledger state."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def preview(self, paths: Iterable[Path], account_alias: str, base_currency: str, private_root: Path | None = None, trading_sessions: Iterable[str] = ()) -> ImportPreview:
        alias = account_alias.strip()
        if not alias or len(alias) > 120 or any(ord(character) < 32 or character in "\\/" for character in alias) or base_currency not in {"CNY", "HKD", "USD"}:
            raise ImportPreviewError("ACCOUNT_IDENTITY_REQUIRED")
        if private_root is None:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            private_root = base / "TradingPlatform/private-import"
        private_root = private_root.resolve()
        if private_root == self.repo_root or self.repo_root in private_root.parents or any((parent / ".git").exists() for parent in (private_root, *private_root.parents)):
            raise ImportPreviewError("PRIVATE_ROOT_IN_GIT_WORKTREE")
        private_root.mkdir(parents=True, exist_ok=True)
        parsed: dict[str, tuple[PreviewFile, list[list[str]], Path]] = {}
        source_paths = tuple(Path(path).resolve() for path in paths)
        privacy_errors = personal_source_privacy_errors(self.repo_root, source_paths)
        if privacy_errors:
            raise ImportPreviewError(privacy_errors[0])
        for source_path in source_paths:
            raw = source_path.read_bytes()
            if b"\x00" in raw:
                raise ImportPreviewError("SOURCE_ENCODING_INVALID")
            try:
                text = raw.decode("gb18030")
            except UnicodeDecodeError as error:
                raise ImportPreviewError("SOURCE_ENCODING_INVALID") from error
            lines = text.splitlines()
            if len(lines) < 2 or "\t" not in lines[0]:
                raise ImportPreviewError("SOURCE_HEADER_UNKNOWN")
            header_parts = lines[0].split("\t")
            if header_parts and header_parts[-1] == "": header_parts.pop()
            role = next((key for key, (_, header) in SCHEMAS.items() if tuple(header_parts) == header), None)
            if role is None:
                raise ImportPreviewError("SOURCE_HEADER_UNKNOWN")
            if role in parsed:
                raise ImportPreviewError("SOURCE_ROLE_DUPLICATE")
            schema_version, header = SCHEMAS[role]
            rows: list[list[str]] = []
            for line in lines[1:]:
                columns = line.split("\t")
                if len(columns) == len(header) + 1:
                    if columns[-1] != "": raise ImportPreviewError("SOURCE_EXTRA_NONEMPTY_COLUMN")
                    columns.pop()
                elif len(columns) < len(header):
                    raise ImportPreviewError("SOURCE_ROW_TRUNCATED")
                elif len(columns) > len(header):
                    raise ImportPreviewError("SOURCE_EXTRA_NONEMPTY_COLUMN")
                rows.append(columns)
            digest = hashlib.sha256(raw).hexdigest()
            target = private_root / "sources/sha256" / digest[:2] / digest
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and (target.stat().st_size != len(raw) or hashlib.sha256(target.read_bytes()).hexdigest() != digest):
                raise ImportPreviewError("SOURCE_OBJECT_HASH_MISMATCH")
            if not target.exists():
                descriptor, temporary_name = tempfile.mkstemp(prefix=f".{digest}.", dir=target.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary_name, target)
                finally:
                    Path(temporary_name).unlink(missing_ok=True)
            target.chmod(stat.S_IREAD)
            parsed[role] = (PreviewFile(role, schema_version, "gb18030", "tab", len(rows), tuple(header), digest), rows, source_path)
        required = set(SCHEMAS)
        if set(parsed) != required:
            raise ImportPreviewError("SOURCE_ROLE_MISSING")
        cash_rows = parsed["cash_ledger"][1]
        dates = [self._date(row[0]) for row in cash_rows]
        weak: dict[tuple[str, ...], list[tuple[int, str]]] = {}
        for sequence, row in enumerate(cash_rows):
            key = tuple(value for index, value in enumerate(row) if index != 8)
            weak.setdefault(key, []).append((sequence, row[8]))
        collisions = [items for items in weak.values() if len(items) > 1]
        export_date = datetime.fromtimestamp(parsed["current_positions"][2].stat().st_mtime).astimezone().date().isoformat()
        latest_cash = max(dates).isoformat()
        sessions = {self._date(value.replace("-", "")).isoformat() for value in trading_sessions}
        calendar_status = "latest_cash_is_trading_session" if latest_cash in sessions else "trading_calendar_confirmation_required"
        candidates = tuple(dict.fromkeys((latest_cash, export_date)))
        return ImportPreview(
            "TonghuashunImportPreview@1", alias, base_currency,
            tuple(parsed[role][0] for role in ("current_positions", "cash_ledger", "holding_history")),
            (min(dates).isoformat(), max(dates).isoformat()), len(collisions), sum(len(items) for items in collisions),
            AsOfCandidate("confirmation_required", candidates, "latest_cash_date+trading_calendar+local_export_time_candidate_not_source_fact", calendar_status, "filesystem_mtime_in_local_timezone_not_source_field"),
            ("execution_timestamp", "broker_contract_or_execution_id", "fee_and_tax_breakdown", "complete_corporate_actions", "opening_positions_before_window"),
            {"initialize_current_state": True, "reconstruct_complete_ledger": False},
            (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(microsecond=0).isoformat(),
        )

    @staticmethod
    def _date(value: str) -> date:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError as error:
            raise ImportPreviewError("SOURCE_DATE_INVALID") from error


__all__ = ["ImportPreview", "ImportPreviewError", "TonghuashunImportPreviewer"]
