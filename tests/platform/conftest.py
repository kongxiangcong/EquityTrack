from __future__ import annotations

import pytest

from tests.platform.owning_adapter_fixture import (
    close_open_owning_adapter_connections,
)


@pytest.fixture(autouse=True)
def close_owning_sqlite_connections_after_test():
    yield
    close_open_owning_adapter_connections()
