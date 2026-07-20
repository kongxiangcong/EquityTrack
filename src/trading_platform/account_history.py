from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from trading_platform.account import AccountOpeningError, _render
from trading_platform.account_import import TonghuashunImportPreviewer
from trading_platform.identity import canonical_hash
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.locking import PersistenceError
from trading_platform.application.workflow_ledger import GenericObjectCommit


class HistoryImportError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HistoryImportResult:
    history_import_batch_id: str
    account_id: str
    source_snapshot_hash: str
    new_event_count: int
    reused_event_count: int
    transaction_count: int
    cash_entry_count: int
    informational_count: int
    holding_summary_count: int
    revision_count: int
    opening_history_gap_count: int
    cash_transition_count: int
    reconciliation_status: str
    account_history_snapshot_id: str | None
    limitations: tuple[str, ...]


class AccountHistoryImportService:
    EVENT_TYPES = {
        "证券买入": "security_buy",
        "证券卖出": "security_sell",
        "银行转存": "bank_deposit",
        "银行转取": "bank_withdrawal",
        "股息入账": "dividend_credit",
        "股息红利税补缴": "dividend_tax_debit",
        "利息归本": "interest_credit",
        "申购配号": "subscription_allocation_info",
    }
    LIMITATIONS = (
        "opening_history_incomplete",
        "realized_pnl_limited",
        "twr_unavailable",
        "mwr_unavailable",
        "tax_breakdown_unavailable",
        "acquisition_lots_incomplete",
    )
    MARKETS = {
        "深A": "SZSE",
        "深圳A股": "SZSE",
        "深圳Ａ股": "SZSE",
        "沪A": "SSE",
        "上海A股": "SSE",
        "上海Ａ股": "SSE",
    }

    def __init__(
        self,
        data_root: Path,
        repo_root: Path,
        migrations_root: Path | None = None,
        fault_injector=None,
    ) -> None:
        self.data_root = data_root.resolve()
        self.repo_root = repo_root.resolve()
        self.migrations_root = (
            migrations_root or self.repo_root / "migrations"
        ).resolve()
        self.fault_injector = fault_injector

    def import_history(
        self,
        invocation_id: str,
        account_id: str,
        sources: Iterable[Path],
        private_root: Path,
        trading_sessions: Iterable[str],
    ) -> HistoryImportResult:
        paths = tuple(Path(p).resolve() for p in sources)
        preview = TonghuashunImportPreviewer(self.repo_root).preview(
            paths, "history-import-local", "CNY", private_root, trading_sessions
        )
        by_role = {item.role: item for item in preview.files}
        rows = self._rows(preview, private_root)
        source_hash = canonical_hash(
            {
                "account": account_id,
                "sources": {
                    role: item.source_object_sha256
                    for role, item in sorted(by_role.items())
                },
            }
        )
        store = PlatformStore(self.data_root, self.migrations_root)
        try:
            if (
                store.connection.execute(
                    "SELECT 1 FROM account WHERE account_id=?", (account_id,)
                ).fetchone()
                is None
            ):
                raise HistoryImportError("ACCOUNT_NOT_FOUND")
            existing = self._existing_batch(
                store, invocation_id, account_id, source_hash
            )
            if existing:
                return self._result(store, existing[0])
            for item in preview.files:
                payload = (
                    Path(private_root).resolve()
                    / "sources/sha256"
                    / item.source_object_sha256[:2]
                    / item.source_object_sha256
                ).read_bytes()
                self._publish(store, payload, item.source_object_sha256)
            return self._commit(
                store, invocation_id, account_id, source_hash, preview, rows
            )
        finally:
            store.close()

    def _commit(
        self,
        store: PlatformStore,
        invocation: str,
        account_id: str,
        source_hash: str,
        preview,
        rows,
    ) -> HistoryImportResult:
        cash_source = next(item for item in preview.files if item.role == "cash_ledger")
        history_source = next(
            item for item in preview.files if item.role == "holding_history"
        )
        if any(row[10] != "人民币" for row in rows["cash_ledger"]):
            raise HistoryImportError("CASH_CURRENCY_MISMATCH")
        indexed = sorted(
            enumerate(rows["cash_ledger"]), key=lambda pair: (pair[1][0], pair[0])
        )
        replay_rows = [(source_index, row) for source_index, row in indexed]
        cash_rows = [pair for pair in replay_rows if pair[1][4] != "申购配号"]
        for index in range(1, len(cash_rows)):
            previous = cash_rows[index - 1][1]
            current = cash_rows[index][1]
            try:
                valid = Decimal(current[8]) == Decimal(previous[8]) + Decimal(
                    current[7]
                )
            except InvalidOperation as error:
                raise HistoryImportError("CASH_DECIMAL_INVALID") from error
            if not valid:
                raise HistoryImportError("CASH_CHAIN_MISMATCH")
        content_counts = Counter()
        weak_counts = Counter()
        candidates = []
        informational_anomalies = []
        last_cash_balance = None
        for event_sequence, (source_sequence, row) in enumerate(replay_rows):
            operation = row[4]
            if operation not in self.EVENT_TYPES:
                raise HistoryImportError("EVENT_TYPE_UNKNOWN")
            content_hash = canonical_hash(row)
            cash_effect = operation != "申购配号"
            amount = self._signed(row[7])
            balance = self._signed(row[8])
            previous_balance = balance - amount if cash_effect else last_cash_balance
            if (
                not cash_effect
                and last_cash_balance is not None
                and balance != last_cash_balance
            ):
                informational_anomalies.append(content_hash)
            if cash_effect:
                last_cash_balance = balance
            identity_context = previous_balance if cash_effect else None
            occurrence = content_counts[(row[0], content_hash)]
            content_counts[(row[0], content_hash)] += 1
            weak_key = (
                row[0],
                row[2],
                operation,
                row[5],
                row[6],
                _render(identity_context) if identity_context is not None else None,
            )
            weak_ordinal = weak_counts[weak_key]
            weak_counts[weak_key] += 1
            row_id = canonical_hash(
                {
                    "account": account_id,
                    "date": row[0],
                    "content": content_hash,
                    "previous_cash_balance": (
                        _render(identity_context)
                        if identity_context is not None
                        else None
                    ),
                    "occurrence": occurrence,
                }
            )
            weak_id = canonical_hash(
                {"account": account_id, "weak": weak_key, "occurrence": weak_ordinal}
            )
            candidates.append(
                (
                    event_sequence,
                    source_sequence,
                    row,
                    content_hash,
                    occurrence,
                    row_id,
                    weak_id,
                )
            )
        batch_id = f"history_import_{source_hash[:24]}"
        now = datetime.now(timezone.utc).isoformat()
        new_events = []
        reused = 0
        revisions = []
        history_rows = rows["holding_history"]
        window_start = min(row[0] for row in rows["cash_ledger"])
        window_end = max(row[0] for row in rows["cash_ledger"])
        running_quantity: dict[str, Decimal] = defaultdict(Decimal)
        opening_gap_codes: set[str] = set()
        for _, row in replay_rows:
            if row[4] not in {"证券买入", "证券卖出"}:
                continue
            quantity = abs(self._signed(row[5]))
            running_quantity[row[2]] += quantity if row[4] == "证券买入" else -quantity
            if running_quantity[row[2]] < 0:
                opening_gap_codes.add(row[2])
        try:
            with store.writer_lock.acquire(f"history-import:{account_id}"):
                replay = self._existing_batch(
                    store, invocation, account_id, source_hash
                )
                if replay:
                    return self._result(store, replay[0])
                store.connection.execute("BEGIN IMMEDIATE")
                store.connection.execute(
                    "INSERT INTO history_import_batch VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        batch_id,
                        account_id,
                        invocation,
                        source_hash,
                        self._iso(window_start),
                        self._iso(window_end),
                        "date_asc+source_occurrence_order",
                        json.dumps(
                            {
                                "cash": [item[5] for item in candidates],
                                "holding_history": [
                                    canonical_hash(row) for row in history_rows
                                ],
                            },
                            sort_keys=True,
                        ),
                        "{}",
                        "[]",
                        now,
                    ),
                )
                for item in preview.files:
                    store.connection.execute(
                        "INSERT INTO history_import_source VALUES(?,?,?,?,?)",
                        (
                            batch_id,
                            item.role,
                            item.source_schema_version,
                            item.source_object_sha256,
                            item.row_count,
                        ),
                    )
                for (
                    event_sequence,
                    source_sequence,
                    row,
                    content_hash,
                    occurrence,
                    row_id,
                    weak_id,
                ) in candidates:
                    if store.connection.execute(
                        "SELECT 1 FROM account_event WHERE source_row_identity=?",
                        (row_id,),
                    ).fetchone():
                        reused += 1
                        continue
                    prior = store.connection.execute(
                        "SELECT account_event_id,canonical_row_hash FROM account_event WHERE account_id=? AND weak_row_identity=? ORDER BY event_date LIMIT 1",
                        (account_id, weak_id),
                    ).fetchone()
                    if prior and prior["canonical_row_hash"] != content_hash:
                        revision_id = f"history_revision_{canonical_hash({'prior':prior['account_event_id'],'candidate':content_hash})[:24]}"
                        store.connection.execute(
                            "INSERT OR IGNORE INTO history_source_revision VALUES(?,?,?,?,?,?,?,?)",
                            (
                                revision_id,
                                account_id,
                                weak_id,
                                prior["account_event_id"],
                                content_hash,
                                cash_source.source_object_sha256,
                                "conflict_pending",
                                batch_id,
                            ),
                        )
                        revisions.append(revision_id)
                        continue
                    event_type = self.EVENT_TYPES[row[4]]
                    cash_effect = int(row[4] != "申购配号")
                    security_id = (
                        self._security(
                            store, row[2], row[9], self._iso(row[0]), account_id
                        )
                        if row[2]
                        else None
                    )
                    quantity = abs(self._signed(row[5])) if row[5] else None
                    price = self._number(row[6]) if row[6] else None
                    amount = self._signed(row[7])
                    balance = self._signed(row[8])
                    charges = None
                    if row[4] in {"证券买入", "证券卖出"}:
                        gross = quantity * price
                        charges = (
                            (abs(amount) - gross)
                            if row[4] == "证券买入"
                            else (gross - amount)
                        )
                    event_id = f"account_event_{row_id[:24]}"
                    store.connection.execute(
                        "INSERT INTO account_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            event_id,
                            account_id,
                            self._iso(row[0]),
                            event_sequence,
                            event_type,
                            cash_effect,
                            security_id,
                            _render(quantity) if quantity is not None else None,
                            _render(price) if price is not None else None,
                            _render(amount),
                            _render(balance),
                            _render(charges) if charges is not None else None,
                            content_hash,
                            weak_id,
                            occurrence,
                            cash_source.source_object_sha256,
                            row_id,
                            batch_id,
                        ),
                    )
                    new_events.append(event_id)
                    if row[4] in {"证券买入", "证券卖出"}:
                        store.connection.execute(
                            "INSERT INTO account_transaction VALUES(?,?,?,?,?,?,?,?)",
                            (
                                f"transaction_{row_id[:24]}",
                                event_id,
                                "buy" if row[4] == "证券买入" else "sell",
                                _render(quantity),
                                _render(price),
                                _render(quantity * price),
                                _render(charges),
                                "aggregate_charges_inferred",
                            ),
                        )
                    if cash_effect:
                        store.connection.execute(
                            "INSERT INTO cash_ledger_entry VALUES(?,?,?,?,?,?,?)",
                            (
                                f"cash_entry_{row_id[:24]}",
                                event_id,
                                account_id,
                                self._iso(row[0]),
                                _render(amount),
                                _render(balance),
                                row_id,
                            ),
                        )
                summaries = 0
                summary_counts = Counter()
                summary_weak_counts = Counter()
                for source_sequence, row in enumerate(history_rows):
                    content = canonical_hash(row)
                    ordinal = summary_counts[content]
                    summary_counts[content] += 1
                    row_id = canonical_hash(
                        {
                            "account": account_id,
                            "content": content,
                            "occurrence": ordinal,
                        }
                    )
                    weak_key = (row[1], row[3], row[4], row[5])
                    weak_ordinal = summary_weak_counts[weak_key]
                    summary_weak_counts[weak_key] += 1
                    weak_id = canonical_hash(
                        {
                            "account": account_id,
                            "weak": weak_key,
                            "occurrence": weak_ordinal,
                        }
                    )
                    if store.connection.execute(
                        "SELECT 1 FROM holding_history_summary WHERE source_row_identity=?",
                        (row_id,),
                    ).fetchone():
                        continue
                    security_id = self._security_by_code(store, row[1])
                    if security_id is None:
                        raise HistoryImportError("HISTORY_SECURITY_UNRESOLVED")
                    prior = store.connection.execute(
                        "SELECT holding_history_summary_id,source_row_identity FROM holding_history_summary WHERE account_id=? AND weak_row_identity=?",
                        (account_id, weak_id),
                    ).fetchone()
                    if prior:
                        revision_id = f"holding_revision_{canonical_hash({'prior':prior[0],'candidate':content})[:24]}"
                        store.connection.execute(
                            "INSERT OR IGNORE INTO holding_history_revision VALUES(?,?,?,?,?,?,?,?)",
                            (
                                revision_id,
                                account_id,
                                weak_id,
                                prior[0],
                                content,
                                history_source.source_object_sha256,
                                "conflict_pending",
                                batch_id,
                            ),
                        )
                        revisions.append(revision_id)
                        continue
                    values = [self._optional(row[i]) for i in (6, 7, 8, 9)]
                    summary_id = f"holding_summary_{row_id[:24]}"
                    store.connection.execute(
                        "INSERT INTO holding_history_summary VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            summary_id,
                            account_id,
                            security_id,
                            self._optional_date(row[3]),
                            self._optional_date(row[4]),
                            int(row[5]) if row[5] else None,
                            *values,
                            weak_id,
                            row_id,
                            history_source.source_object_sha256,
                            batch_id,
                        ),
                    )
                    summaries += 1
                for code in sorted(opening_gap_codes):
                    security_id = self._security_by_code(store, code)
                    issue_id = f"history_quality_{canonical_hash({'batch':batch_id,'security':security_id})[:24]}"
                    store.connection.execute(
                        "INSERT INTO account_history_quality_issue VALUES(?,?,?,?)",
                        (
                            issue_id,
                            batch_id,
                            "opening_history_incomplete",
                            json.dumps({"security_id": security_id}),
                        ),
                    )
                for anomaly_ordinal, content_hash in enumerate(informational_anomalies):
                    issue_id = f"history_quality_{canonical_hash({'batch':batch_id,'informational':content_hash,'occurrence':anomaly_ordinal})[:24]}"
                    store.connection.execute(
                        "INSERT INTO account_history_quality_issue VALUES(?,?,?,?)",
                        (
                            issue_id,
                            batch_id,
                            "informational_balance_anomaly",
                            json.dumps({"canonical_row_hash": content_hash}),
                        ),
                    )
                if self.fault_injector is not None:
                    self.fault_injector("before_history_snapshot")
                opening_cash = store.connection.execute(
                    "SELECT amount_decimal FROM account_cash_opening WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0]
                latest_cash = self._signed(cash_rows[-1][1][8])
                cash_matches = Decimal(opening_cash) == latest_cash
                positions_match = self._positions_match(
                    store, account_id, rows["current_positions"]
                )
                if not cash_matches or not positions_match or revisions:
                    reconciliation = "blocked"
                elif opening_gap_codes:
                    reconciliation = "limited_opening_history"
                else:
                    reconciliation = "reconciled"
                limitations = tuple(
                    item
                    for item in self.LIMITATIONS
                    if opening_gap_codes or item != "opening_history_incomplete"
                )
                snapshot_id = None
                if not revisions:
                    snapshot_id = f"account_history_snapshot_{canonical_hash({'account':account_id,'batch':batch_id})[:24]}"
                    counts = (
                        len(new_events),
                        sum(
                            1
                            for _, _, row, *_ in candidates
                            if row[4] in {"证券买入", "证券卖出"}
                        ),
                        sum(1 for _, _, row, *_ in candidates if row[4] != "申购配号"),
                        summaries,
                    )
                    store.connection.execute(
                        "INSERT INTO account_history_snapshot VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            snapshot_id,
                            account_id,
                            batch_id,
                            self._iso(window_end),
                            *counts,
                            reconciliation,
                            json.dumps(limitations),
                            now,
                        ),
                    )
                counts = {
                    "new_events": len(new_events),
                    "reused_events": reused,
                    "transactions": store.connection.execute(
                        "SELECT count(*) FROM account_transaction t JOIN account_event e USING(account_event_id) WHERE e.created_by_batch_id=?",
                        (batch_id,),
                    ).fetchone()[0],
                    "cash_entries": store.connection.execute(
                        "SELECT count(*) FROM cash_ledger_entry c JOIN account_event e USING(account_event_id) WHERE e.created_by_batch_id=?",
                        (batch_id,),
                    ).fetchone()[0],
                    "informational": store.connection.execute(
                        "SELECT count(*) FROM account_event WHERE created_by_batch_id=? AND cash_effect=0",
                        (batch_id,),
                    ).fetchone()[0],
                    "summaries": summaries,
                    "revisions": len(revisions),
                    "opening_gaps": len(opening_gap_codes),
                    "informational_balance_anomalies": len(informational_anomalies),
                    "cash_transitions": max(0, len(cash_rows) - 1),
                }
                store.connection.execute(
                    "UPDATE history_import_batch SET result_counts_json=?,quality_issues_json=? WHERE history_import_batch_id=?",
                    (
                        json.dumps(counts, sort_keys=True),
                        json.dumps(
                            ["opening_history_incomplete"] * len(opening_gap_codes)
                            + ["informational_balance_anomaly"]
                            * len(informational_anomalies)
                            + (["source_revision_pending"] if revisions else [])
                        ),
                        batch_id,
                    ),
                )
                store.connection.commit()
        except Exception:
            store.connection.rollback()
            raise
        return self._result(store, batch_id)

    def _result(self, store, batch_id):
        row = store.connection.execute(
            "SELECT * FROM history_import_batch WHERE history_import_batch_id=?",
            (batch_id,),
        ).fetchone()
        counts = json.loads(row["result_counts_json"])
        snapshot = store.connection.execute(
            "SELECT account_history_snapshot_id,reconciliation_status,limitations_json FROM account_history_snapshot WHERE history_import_batch_id=?",
            (batch_id,),
        ).fetchone()
        return HistoryImportResult(
            batch_id,
            row["account_id"],
            row["source_snapshot_hash"],
            counts.get("new_events", 0),
            counts.get("reused_events", 0),
            counts.get("transactions", 0),
            counts.get("cash_entries", 0),
            counts.get("informational", 0),
            counts.get("summaries", 0),
            counts.get("revisions", 0),
            counts.get("opening_gaps", 0),
            counts.get("cash_transitions", 0),
            snapshot["reconciliation_status"] if snapshot else "blocked",
            snapshot["account_history_snapshot_id"] if snapshot else None,
            (
                tuple(json.loads(snapshot["limitations_json"]))
                if snapshot
                else self.LIMITATIONS
            ),
        )

    def _security(self, store, code, market_name, on_date, account_id):
        market = self.MARKETS.get(market_name)
        if market is None:
            raise HistoryImportError("EVENT_MARKET_UNKNOWN")
        rows = store.connection.execute(
            "SELECT DISTINCT security_id FROM security_identifier WHERE market=? AND code=?",
            (market, code),
        ).fetchall()
        if len(rows) > 1:
            raise HistoryImportError("EVENT_SECURITY_AMBIGUOUS")
        if rows:
            return rows[0][0]
        account_currency = store.connection.execute(
            "SELECT base_currency FROM account WHERE account_id=?", (account_id,)
        ).fetchone()[0]
        security_id = f"security_{canonical_hash({'market':market,'code':code})[:24]}"
        store.connection.execute(
            "INSERT OR IGNORE INTO security VALUES(?,?)",
            (security_id, account_currency),
        )
        identifier = f"security_identifier_{canonical_hash({'security':security_id,'market':market,'code':code,'from':on_date})[:24]}"
        store.connection.execute(
            "INSERT INTO security_identifier VALUES(?,?,?,?,?,?,?,?)",
            (identifier, security_id, market, code, on_date, "date", None, None),
        )
        return security_id

    @staticmethod
    def _security_by_code(store, code):
        rows = store.connection.execute(
            "SELECT DISTINCT security_id FROM security_identifier WHERE code=?", (code,)
        ).fetchall()
        return rows[0][0] if len(rows) == 1 else None

    @staticmethod
    def _existing_batch(store, invocation_id, account_id, source_hash):
        invocation = store.connection.execute(
            "SELECT history_import_batch_id,account_id FROM history_import_batch WHERE invocation_id=?",
            (invocation_id,),
        ).fetchone()
        if invocation and invocation["account_id"] != account_id:
            raise HistoryImportError("INVOCATION_ACCOUNT_MISMATCH")
        if invocation:
            return invocation
        return store.connection.execute(
            "SELECT history_import_batch_id,account_id FROM history_import_batch WHERE source_snapshot_hash=?",
            (source_hash,),
        ).fetchone()

    @classmethod
    def _positions_match(cls, store, account_id, rows):
        expected = {}
        for row in rows:
            security_id = cls._security_by_code(store, row[2])
            if security_id is None:
                return False
            expected[security_id] = tuple(
                _render(cls._signed(row[index])) for index in (4, 5, 6)
            )
        actual = {
            row[0]: (row[1], row[2], row[3])
            for row in store.connection.execute(
                "SELECT security_id,quantity_decimal,available_decimal,frozen_decimal FROM account_position WHERE account_id=?",
                (account_id,),
            )
        }
        return actual == expected

    @staticmethod
    def _number(value):
        try:
            v = Decimal(value)
        except InvalidOperation as e:
            raise HistoryImportError("EVENT_DECIMAL_INVALID") from e
        if not v.is_finite() or v < 0:
            raise HistoryImportError("EVENT_DECIMAL_INVALID")
        return v

    @staticmethod
    def _signed(value):
        try:
            v = Decimal(value)
        except InvalidOperation as e:
            raise HistoryImportError("EVENT_DECIMAL_INVALID") from e
        if not v.is_finite():
            raise HistoryImportError("EVENT_DECIMAL_INVALID")
        return v

    @staticmethod
    def _optional(value):
        return _render(Decimal(value)) if value else None

    @staticmethod
    def _iso(value):
        return datetime.strptime(value, "%Y%m%d").date().isoformat()

    @staticmethod
    def _optional_date(value):
        return AccountHistoryImportService._iso(value) if value else None

    @staticmethod
    def _rows(preview, private_root):
        result = {}
        for item in preview.files:
            payload = (
                Path(private_root).resolve()
                / "sources/sha256"
                / item.source_object_sha256[:2]
                / item.source_object_sha256
            ).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item.source_object_sha256:
                raise HistoryImportError("SOURCE_OBJECT_HASH_MISMATCH")
            lines = payload.decode("gb18030").splitlines()
            parsed = []
            for line in lines[1:]:
                columns = line.split("\t")
                if columns and columns[-1] == "":
                    columns.pop()
                parsed.append(columns)
            result[item.role] = parsed
        return result

    @staticmethod
    def _publish(store, payload, expected):
        for retry in range(40):
            try:
                actual = store.workflow_ledger.commit_artifacts(GenericObjectCommit(payload)).sha256
                break
            except PersistenceError as error:
                if error.code != "RUNTIME_BUSY" or retry == 39:
                    raise
                time.sleep(0.05)
        if actual != expected:
            raise HistoryImportError("SOURCE_OBJECT_PUBLISH_MISMATCH")

__all__ = ["AccountHistoryImportService", "HistoryImportError", "HistoryImportResult"]
