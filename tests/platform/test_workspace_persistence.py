from __future__ import annotations

from pathlib import Path

import pytest

from tests.platform.owning_adapter_fixture import SQLiteOwningAdapterFixture
from tests.platform.test_chart_annotations import _root
from trading_platform.application.web_tasks import WorkspaceUpdateCommand


def test_update_authorization_rows_are_storage_immutable(tmp_path: Path) -> None:
    root = _root(tmp_path)
    root.update_authorizations.authorize(
        WorkspaceUpdateCommand(
            "workspace-persistence:create",
            "security_yihua",
            "2026-07-11",
            "2026-07-10",
        )
    )
    adapter = SQLiteOwningAdapterFixture(root.data_root)
    with pytest.raises(Exception, match="UPDATE_AUTHORIZATION_IMMUTABLE"):
        adapter.execute("DELETE FROM update_authorization")
    adapter.close()
    root.close()
