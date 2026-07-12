from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_platform.account_import import ImportPreviewError, TonghuashunImportPreviewer
from trading_platform.operations import PlatformOperations


HEADERS = {
    "current_positions": "操作\t序号\t证券代码\t证券名称\t股票余额\t可用余额\t冻结数量\t成本价\t市价\t盈亏估算\t盈亏比例(%)\t当日盈亏\t当日盈亏比(%)\t市值\t仓位占比(%)\t当日买入\t当日卖出\t交易市场\t持股天数\t",
    "cash_ledger": "日期\t成交日期\t证券代码\t证券名称\t操作\t成交数量\t成交均价\t发生金额\t剩余余额\t交易市场\t货币单位\t",
    "holding_history": "明细\t证券代码\t证券名称\t建仓日期\t清仓日期\t持股天数\t总盈亏\t盈亏比例(%)\t买入均价\t卖出均价\t",
}


def _write(path: Path, role: str, rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join([HEADERS[role], *("\t".join(row) + "\t" for row in rows)])
    path.write_bytes(text.encode("gb18030"))
    return path


def _samples(tmp_path: Path) -> list[Path]:
    position = ["", "1", "000001", "样本甲", "100", "100", "0", "10", "11", "100", "10", "0", "0", "1100", "50", "0", "0", "深A", "2"]
    cash = [
        ["20260710", "20260710", "000001", "样本甲", "证券买入", "100", "10", "-1000", "9000", "深A", "人民币"],
        ["20260710", "20260710", "000001", "样本甲", "证券买入", "100", "10", "-1000", "8000", "深A", "人民币"],
        ["20250714", "20250714", "000002", "样本乙", "证券卖出", "50", "20", "1000", "7000", "深A", "人民币"],
        ["20250714", "20250714", "000002", "样本乙", "证券卖出", "50", "20", "1000", "8000", "深A", "人民币"],
    ]
    cash.extend([["20260101", "20260101", f"{index:06d}", "合成样本", f"操作{index}", "1", "1", str(index), str(10000 + index), "深A", "人民币"] for index in range(744)])
    history = [["", f"{index:06d}", "合成样本", "20250101", "20250201", "31", str(index), "10", "10", "11"] for index in range(120)]
    return [_write(tmp_path / "a.xls", "current_positions", [position, position]), _write(tmp_path / "b.xls", "cash_ledger", cash), _write(tmp_path / "c.xls", "holding_history", history)]


def test_preview_detects_content_preserves_collisions_and_stores_private_sources(tmp_path: Path) -> None:
    paths = _samples(tmp_path / "inputs")
    preview = TonghuashunImportPreviewer(Path.cwd()).preview(paths, "本地账户", "CNY", tmp_path / "private", ("2025-07-14", "2026-07-10"))

    assert {item.role: item.row_count for item in preview.files} == {"current_positions": 2, "cash_ledger": 748, "holding_history": 120}
    assert preview.cash_coverage == ("2025-07-14", "2026-07-10")
    assert preview.weak_key_collision_groups == 2 and preview.weak_key_collision_rows == 4
    assert preview.capabilities == {"initialize_current_state": True, "reconstruct_complete_ledger": False}
    assert preview.current_positions_as_of.status == "confirmation_required"
    assert preview.current_positions_as_of.trading_calendar_status == "latest_cash_is_trading_session"
    assert preview.account_alias == "本地账户" and preview.base_currency == "CNY"
    assert all(item.encoding == "gb18030" and item.delimiter == "tab" and item.source_object_sha256 for item in preview.files)
    assert all((tmp_path / "private/sources/sha256" / item.source_object_sha256[:2] / item.source_object_sha256).is_file() for item in preview.files)
    serialized = json.dumps(preview.to_safe_dict(), ensure_ascii=False)
    assert str(tmp_path) not in serialized and "样本甲" not in serialized and "9000" not in serialized


@pytest.mark.parametrize("mutation,code", [
    (lambda raw: raw.replace("证券代码", "未知代码", 1), "SOURCE_HEADER_UNKNOWN"),
    (lambda raw: raw + "\n截断\t一行", "SOURCE_ROW_TRUNCATED"),
    (lambda raw: raw.replace("2\t\n", "2\t多余\n", 1), "SOURCE_EXTRA_NONEMPTY_COLUMN"),
])
def test_unknown_header_truncation_and_extra_nonempty_column_fail_closed(tmp_path: Path, mutation, code: str) -> None:
    path = _samples(tmp_path / "inputs")[0]
    path.write_text(mutation(path.read_bytes().decode("gb18030")), encoding="gb18030")
    with pytest.raises(ImportPreviewError) as failed:
        TonghuashunImportPreviewer(Path.cwd()).preview([path], "账户", "CNY", tmp_path / "private")
    assert failed.value.code == code


def test_invalid_encoding_missing_identity_and_repo_private_root_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.xls"; path.write_bytes(b"\xff\xff\x00")
    previewer = TonghuashunImportPreviewer(Path.cwd())
    with pytest.raises(ImportPreviewError, match="SOURCE_ENCODING_INVALID"): previewer.preview([path], "账户", "CNY", tmp_path / "private")
    with pytest.raises(ImportPreviewError, match="ACCOUNT_IDENTITY_REQUIRED"): previewer.preview(_samples(tmp_path / "inputs"), "", "CNY", tmp_path / "private")
    with pytest.raises(ImportPreviewError, match="PRIVATE_ROOT_IN_GIT_WORKTREE"): previewer.preview(_samples(tmp_path / "inputs2"), "账户", "CNY", Path.cwd() / ".private-import")
    other_repo = tmp_path / "other-repo"; other_repo.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=other_repo, check=True)
    with pytest.raises(ImportPreviewError, match="PRIVATE_ROOT_IN_GIT_WORKTREE"): previewer.preview(_samples(tmp_path / "inputs3"), "账户", "CNY", other_repo / "private")


def test_privacy_doctor_blocks_unignored_or_tracked_personal_sources(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    personal = tmp_path / "docs/data/private.xls"; personal.parent.mkdir(parents=True); personal.write_bytes(b"private")
    assert PlatformOperations._privacy_source_errors(tmp_path) == ("PERSONAL_SOURCE_IN_GIT_WORKTREE",)
    (tmp_path / ".gitignore").write_text("docs/data/\n", encoding="utf-8")
    assert PlatformOperations._privacy_source_errors(tmp_path) == ()
    subprocess.run(["git", "add", "-f", "docs/data/private.xls"], cwd=tmp_path, check=True)
    assert PlatformOperations._privacy_source_errors(tmp_path) == ("PERSONAL_SOURCE_IN_GIT_WORKTREE",)


def test_preview_checks_selected_in_worktree_paths_outside_docs_data(tmp_path: Path) -> None:
    import subprocess
    repo = tmp_path / "repo"; repo.mkdir(); subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    sources = _samples(repo / "imports")
    previewer = TonghuashunImportPreviewer(repo)
    with pytest.raises(ImportPreviewError, match="PERSONAL_SOURCE_IN_GIT_WORKTREE"):
        previewer.preview(sources, "账户", "CNY", tmp_path / "private")
    (repo / ".gitignore").write_text("imports/\n", encoding="utf-8")
    assert previewer.preview(sources, "账户", "CNY", tmp_path / "private").capabilities["initialize_current_state"]
    subprocess.run(["git", "add", "-f", "imports/a.xls"], cwd=repo, check=True)
    with pytest.raises(ImportPreviewError, match="PERSONAL_SOURCE_IN_GIT_WORKTREE"):
        previewer.preview(sources, "账户", "CNY", tmp_path / "private2")
