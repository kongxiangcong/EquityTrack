from __future__ import annotations

from trading_platform.data.service import DataSyncService
from trading_platform.domain.data import SyncRequest, SyncResult
from .watchlist import Watchlist
from .provider_job import ProviderJob


def _register_job_security(watchlist: Watchlist, job: ProviderJob) -> None:
    identity = job.security_identity
    if identity is None:
        return
    watchlist.add(job.security_invocation_id or f"provider-security:{identity.security_id}", identity)


class DataSynchronization:
    """Own the complete configured data-sync application journey."""

    def __init__(
        self,
        job: ProviderJob,
        request: SyncRequest,
        watchlist: Watchlist,
        data: DataSyncService,
    ) -> None:
        self._job = job
        self._request = request
        self._watchlist = watchlist
        self._data = data

    def run(self) -> SyncResult:
        _register_job_security(self._watchlist, self._job)
        return self._data.sync(self._request)

__all__ = ["DataSynchronization"]
