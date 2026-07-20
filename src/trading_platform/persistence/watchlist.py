from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from trading_platform.application.contracts import SecurityIdentity, WatchlistView
from trading_platform.identity import canonical_hash

from .locking import DataRootWriterLock, PersistenceError


class SQLiteWatchlist:
    def __init__(self, connection: sqlite3.Connection, writer_lock: DataRootWriterLock) -> None:
        self.connection = connection
        self.writer_lock = writer_lock

    def add(self, invocation_id: str, security: SecurityIdentity) -> WatchlistView:
        if security.identifier_date_precision != "date":
            raise PersistenceError("DATE_PRECISION_INVALID", "Identifier precision must be date.")
        request_hash = canonical_hash(security)
        with self.writer_lock.acquire(f"command:{invocation_id}"):
            receipt = self.connection.execute("SELECT * FROM command_receipt WHERE invocation_id=?", (invocation_id,)).fetchone()
            if receipt:
                if receipt["request_hash"] != request_hash:
                    raise PersistenceError("INVOCATION_CONFLICT", "Invocation id was already used for different input.")
                return self.get(receipt["result_id"])
            existing = self.connection.execute("SELECT currency FROM security WHERE security_id=?", (security.security_id,)).fetchone()
            if existing and existing["currency"] != security.currency:
                raise PersistenceError("SECURITY_IDENTITY_CONFLICT", "Security currency conflicts with stable identity.")
            owner = self.connection.execute("SELECT security_id FROM security_identifier WHERE market=? AND code=? AND valid_to IS NULL", (security.market, security.code)).fetchone()
            if owner and owner["security_id"] != security.security_id:
                raise PersistenceError("SECURITY_IDENTITY_CONFLICT", "Identifier belongs to another Security.")
            item_id = f"watch_{canonical_hash({'watchlist': 'watchlist_default', 'security': security.security_id})[:20]}"
            identifier_id = f"sid_{canonical_hash({'security': security.security_id, 'market': security.market, 'code': security.code, 'from': security.identifier_valid_from})[:20]}"
            with self.connection:
                self.connection.execute("INSERT OR IGNORE INTO security VALUES(?,?)", (security.security_id, security.currency))
                self.connection.execute("INSERT OR IGNORE INTO security_identifier VALUES(?,?,?,?,?,?,?,?)", (identifier_id, security.security_id, security.market, security.code, security.identifier_valid_from, "date", None, None))
                self.connection.execute("INSERT OR IGNORE INTO watchlist_item VALUES(?,?,?,?)", (item_id, "watchlist_default", security.security_id, datetime.now(timezone.utc).isoformat()))
                self.connection.execute("INSERT INTO command_receipt VALUES(?,?,?,?,?)", (invocation_id, "add_watchlist_item", request_hash, "WatchlistItem", item_id))
            return self.get(item_id)

    def get(self, item_id: str) -> WatchlistView:
        row = self.connection.execute("SELECT wi.watchlist_item_id,s.security_id,s.currency,si.market,si.code FROM watchlist_item wi JOIN security s USING(security_id) JOIN security_identifier si USING(security_id) WHERE wi.watchlist_item_id=? AND si.valid_to IS NULL", (item_id,)).fetchone()
        if row is None:
            raise PersistenceError("REFERENCE_MISSING", "Watchlist item reference is missing.")
        return WatchlistView(row["watchlist_item_id"], row["security_id"], row["market"], row["code"], row["currency"])

    def list(self) -> tuple[WatchlistView, ...]:
        return tuple(self.get(row[0]) for row in self.connection.execute("SELECT watchlist_item_id FROM watchlist_item ORDER BY watchlist_item_id"))
