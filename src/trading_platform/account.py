from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from trading_platform.account_import import SCHEMAS, TonghuashunImportPreviewer
from trading_platform.identity import canonical_hash
from trading_platform.persistence import PlatformStore
from trading_platform.persistence.locking import PersistenceError
from trading_platform.application.workflow_ledger import GenericObjectCommit


class AccountOpeningError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code); self.code = code


@dataclass(frozen=True)
class AccountOpeningResult:
    account_id: str
    import_batch_id: str
    portfolio_snapshot_id: str
    confirmed_as_of: str
    cash_decimal: str
    position_ids: tuple[str, ...]
    quality_issue_count: int
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class AccountPositionView:
    position_id: str
    security_id: str
    source_display_name: str
    quantity_decimal: str
    available_decimal: str
    frozen_decimal: str
    cost_price_decimal: str
    currency: str
    source_type: str
    source_row_identity: str
    source_price_decimal: str
    source_market_value_decimal: str
    source_day_pnl_decimal: str
    source_weight_decimal: str
    source_as_of: str


@dataclass(frozen=True)
class AccountOpeningDetail:
    opening: AccountOpeningResult
    positions: tuple[AccountPositionView, ...]
    source_objects: tuple[dict[str, object], ...]


def _decimal(value: str, code: str) -> Decimal:
    try: result = Decimal(value)
    except InvalidOperation as error: raise AccountOpeningError(code) from error
    if not result.is_finite() or result < 0: raise AccountOpeningError(code)
    return result


def _render(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return "0" if rendered == "-0" else rendered


class AccountOpeningService:
    LIMITATIONS = ("history_ledger_incomplete", "pre_initialization_returns_unavailable", "pre_initialization_cash_flows_unavailable", "acquisition_lots_not_reconstructed", "fee_and_tax_history_unavailable")
    MARKETS = {"深A": "SZSE", "深圳A股": "SZSE", "深圳Ａ股": "SZSE", "沪A": "SSE", "上海A股": "SSE", "上海Ａ股": "SSE"}

    def __init__(self, data_root: Path, repo_root: Path, migrations_root: Path | None = None) -> None:
        self.data_root = data_root.resolve(); self.repo_root = repo_root.resolve(); self.migrations_root = (migrations_root or self.repo_root / "migrations").resolve()

    def initialize(self, invocation_id: str, sources: Iterable[Path], account_alias: str, base_currency: str, confirmed_as_of: str, private_root: Path, trading_sessions: Iterable[str]) -> AccountOpeningResult:
        try: date.fromisoformat(confirmed_as_of)
        except ValueError as error: raise AccountOpeningError("ACCOUNT_AS_OF_INVALID") from error
        source_paths = tuple(Path(path).resolve() for path in sources)
        for preview_retry in range(40):
            try:
                preview = TonghuashunImportPreviewer(self.repo_root).preview(source_paths, account_alias, base_currency, private_root, trading_sessions); break
            except PermissionError:
                if preview_retry == 39: raise
                time.sleep(0.05)
        if confirmed_as_of not in preview.current_positions_as_of.candidate_dates: raise AccountOpeningError("ACCOUNT_AS_OF_NOT_CONFIRMED_CANDIDATE")
        rows = self._rows(preview, private_root)
        snapshot_hash = canonical_hash({"sources": sorted(item.source_object_sha256 for item in preview.files), "as_of": confirmed_as_of, "currency": base_currency})
        store = PlatformStore(self.data_root, self.migrations_root)
        try:
            existing = store.connection.execute("SELECT account_id FROM account_import_batch WHERE invocation_id=? OR source_snapshot_hash=?", (invocation_id, snapshot_hash)).fetchone()
            if existing: return self._result(store.connection, existing[0])
            try:
                return self._commit(store, invocation_id, preview, base_currency, confirmed_as_of, snapshot_hash, rows, private_root)
            except PersistenceError as error:
                if error.code != "RUNTIME_BUSY": raise
                for _ in range(40):
                    time.sleep(0.05)
                    replay = store.connection.execute("SELECT account_id FROM account_import_batch WHERE invocation_id=? OR source_snapshot_hash=?", (invocation_id, snapshot_hash)).fetchone()
                    if replay: return self._result(store.connection, replay[0])
                raise
        finally: store.close()

    def get(self, account_id: str) -> AccountOpeningResult:
        store = PlatformStore(self.data_root, self.migrations_root)
        try:
            if store.connection.execute("SELECT 1 FROM account WHERE account_id=?", (account_id,)).fetchone() is None:
                raise AccountOpeningError("ACCOUNT_NOT_FOUND")
            return self._result(store.connection, account_id)
        finally:
            store.close()

    def get_detail(self, account_id: str) -> AccountOpeningDetail:
        opening = self.get(account_id)
        store = PlatformStore(self.data_root, self.migrations_root)
        try:
            rows = store.connection.execute("SELECT p.position_id,p.security_id,p.source_display_name,p.quantity_decimal,p.available_decimal,p.frozen_decimal,l.cost_price_decimal,l.currency,l.source_type,l.source_row_identity,o.source_price_decimal,o.source_market_value_decimal,o.source_day_pnl_decimal,o.source_weight_decimal,o.source_as_of FROM account_position p JOIN account_position_lot l USING(position_id) JOIN account_position_observation o USING(position_id) WHERE p.account_id=? ORDER BY p.position_id", (account_id,)).fetchall()
            sources=tuple(dict(row) for row in store.connection.execute("SELECT source_role,source_schema_version,object_sha256,row_count FROM account_import_source WHERE import_batch_id=? ORDER BY source_role",(opening.import_batch_id,)))
            return AccountOpeningDetail(opening, tuple(AccountPositionView(*tuple(row)) for row in rows), sources)
        finally: store.close()

    def _commit(self, store: PlatformStore, invocation: str, preview, currency: str, as_of: str, snapshot_hash: str, rows: dict[str, list[list[str]]], private_root: Path) -> AccountOpeningResult:
        alias=preview.account_alias
        source_items={item.role:item for item in preview.files}
        for item in preview.files:
            payload=self._read_private_object(private_root, item.source_object_sha256)
            for retry in range(40):
                try:
                    published=store.workflow_ledger.commit_artifacts(GenericObjectCommit(payload)).sha256; break
                except PersistenceError as error:
                    if error.code!="RUNTIME_BUSY" or retry==39: raise
                    time.sleep(0.05)
            if published!=item.source_object_sha256: raise AccountOpeningError("SOURCE_OBJECT_PUBLISH_MISMATCH")
        positions = rows["current_positions"]; cash_rows = rows["cash_ledger"]
        source_currencies = {row[10] for row in cash_rows if row[10]}
        currency_names = {"CNY": "人民币", "HKD": "港币", "USD": "美元"}
        if source_currencies != {currency_names.get(currency)}: raise AccountOpeningError("CASH_CURRENCY_MISMATCH")
        latest_date = max(row[0] for row in cash_rows); latest_group = [row for row in cash_rows if row[0] == latest_date]; cash = _decimal(latest_group[-1][8], "OPENING_CASH_INVALID")
        cash_row_id = canonical_hash({"source_object":source_items["cash_ledger"].source_object_sha256,"role": "cash_ledger", "sequence": cash_rows.index(latest_group[-1]), "row": latest_group[-1]})
        issues = []
        for sequence, row in enumerate(cash_rows):
            if sequence and row[0] == cash_rows[sequence - 1][0]:
                try: delta = Decimal(row[8]) - (Decimal(cash_rows[sequence - 1][8]) + Decimal(row[7]))
                except InvalidOperation: raise AccountOpeningError("CASH_CHAIN_DECIMAL_INVALID")
                if delta != 0: issues.append((sequence, row, delta))
        prepared = []; market_value = Decimal(0)
        for sequence, row in enumerate(positions):
            market = self.MARKETS.get(row[17]); code = row[2].strip()
            if market is None or not code.isdigit() or len(code) != 6: raise AccountOpeningError("POSITION_SECURITY_INVALID")
            quantity, available, frozen = (_decimal(row[index], "POSITION_QUANTITY_INVALID") for index in (4, 5, 6))
            if available + frozen != quantity or any(value != value.to_integral_value() for value in (quantity, available, frozen)): raise AccountOpeningError("POSITION_QUANTITY_RELATION_INVALID")
            cost, price, source_value = (_decimal(row[index], "POSITION_DECIMAL_INVALID") for index in (7, 8, 13))
            if quantity * price != source_value: raise AccountOpeningError("POSITION_MARKET_VALUE_MISMATCH")
            day_pnl = Decimal(row[11]); weight = _decimal(row[14], "POSITION_WEIGHT_INVALID")
            if not day_pnl.is_finite(): raise AccountOpeningError("POSITION_DECIMAL_INVALID")
            security_id = f"security_{canonical_hash({'market':market,'code':code})[:24]}"; row_id = canonical_hash({"source_object":source_items["current_positions"].source_object_sha256,"role": "current_positions", "sequence": sequence, "row": row})
            prepared.append((security_id, market, code, row[3], quantity, available, frozen, cost, price, source_value, day_pnl, weight, row_id)); market_value += source_value
        total = cash + market_value
        if total <= 0: raise AccountOpeningError("PORTFOLIO_TOTAL_INVALID")
        for item in prepared:
            expected = item[9] / total * Decimal(100)
            if abs(expected - item[11]) > Decimal("0.01"): raise AccountOpeningError("POSITION_WEIGHT_RECONCILIATION_FAILED")
        account_id=f"account_{snapshot_hash[:24]}"; batch_id=f"account_import_{snapshot_hash[:24]}"; portfolio_id=f"portfolio_snapshot_{snapshot_hash[:24]}"; now=datetime.now(timezone.utc).isoformat()
        evidence={"schema_version":"AccountOpeningEvidence@1","confirmation":{"invocation_id":invocation,"confirmed_at":now,"account_alias":alias,"base_currency":currency,"confirmed_as_of":as_of,"candidates":asdict(preview.current_positions_as_of)},"cash_rule":"latest_date_then_file_occurrence_order","cash_source_row_identity":cash_row_id,"cash_source_date":latest_date,"source_snapshot_hash":snapshot_hash,"sources":[{"role":item.role,"sha256":item.source_object_sha256,"schema":item.source_schema_version,"rows":item.row_count} for item in preview.files],"quality_issue_count":len(issues),"limitations":self.LIMITATIONS}
        try:
            with store.writer_lock.acquire(f"account-opening:{account_id}"):
                replay = store.connection.execute("SELECT account_id FROM account_import_batch WHERE invocation_id=? OR source_snapshot_hash=?", (invocation, snapshot_hash)).fetchone()
                if replay: return self._result(store.connection, replay[0])
                store.connection.execute("BEGIN IMMEDIATE")
                store.connection.execute("INSERT INTO account VALUES(?,?,?,?,?)",(account_id,alias,currency,now,snapshot_hash))
                store.connection.execute("INSERT INTO account_import_batch VALUES(?,?,?,?,?,?,?)",(batch_id,account_id,invocation,as_of,snapshot_hash,"warning" if issues else "pass",json.dumps(evidence,sort_keys=True)))
                for item in preview.files: store.connection.execute("INSERT INTO account_import_source VALUES(?,?,?,?,?)",(batch_id,item.role,item.source_schema_version,item.source_object_sha256,item.row_count))
                store.connection.execute("INSERT INTO account_cash_opening VALUES(?,?,?,?,?,?)",(account_id,_render(cash),currency,cash_row_id,datetime.strptime(latest_date,"%Y%m%d").date().isoformat(),as_of))
                position_ids=[]
                for item in prepared:
                    _,market,code,display_name,quantity,available,frozen,cost,price,value,pnl,weight,row_id=item
                    valid = store.connection.execute("SELECT security_id FROM security_identifier WHERE market=? AND code=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?)",(market,code,as_of,as_of)).fetchall()
                    if len(valid)>1: raise AccountOpeningError("SECURITY_IDENTIFIER_AMBIGUOUS")
                    if valid: security_id=valid[0][0]
                    else:
                        if store.connection.execute("SELECT 1 FROM security_identifier WHERE market=? AND code=?",(market,code)).fetchone(): raise AccountOpeningError("SECURITY_IDENTIFIER_NOT_VALID_AT_AS_OF")
                        security_id=f"security_{canonical_hash({'market':market,'code':code,'valid_from':as_of})[:24]}"; store.connection.execute("INSERT INTO security VALUES(?,?)",(security_id,currency)); identifier_id=f"security_identifier_{canonical_hash({'security':security_id,'market':market,'code':code,'from':as_of})[:24]}"; store.connection.execute("INSERT INTO security_identifier VALUES(?,?,?,?,?,?,?,?)",(identifier_id,security_id,market,code,as_of,"date",None,None))
                    position_id=f"position_{canonical_hash({'account':account_id,'security':security_id})[:24]}"; lot_id=f"position_lot_{canonical_hash({'position':position_id,'source':row_id})[:24]}"; position_ids.append(position_id)
                    store.connection.execute("INSERT INTO account_position VALUES(?,?,?,?,?,?,?,?)",(position_id,account_id,security_id,display_name,_render(quantity),_render(available),_render(frozen),"opening_snapshot"))
                    store.connection.execute("INSERT INTO account_position_lot VALUES(?,?,?,?,?,?,?)",(lot_id,position_id,_render(quantity),_render(cost),currency,"opening_snapshot",row_id))
                    store.connection.execute("INSERT INTO account_position_observation VALUES(?,?,?,?,?,?)",(position_id,_render(price),_render(value),_render(pnl),_render(weight),as_of))
                for sequence,row,delta in issues:
                    row_id=canonical_hash({"source_object":source_items["cash_ledger"].source_object_sha256,"role":"cash_ledger","sequence":sequence,"row":row}); issue_id=f"account_quality_{canonical_hash({'batch':batch_id,'row':row_id})[:24]}"
                    store.connection.execute("INSERT INTO account_import_quality_issue VALUES(?,?,?,?,?)",(issue_id,batch_id,"CASH_RUNNING_BALANCE_JUMP",row_id,json.dumps({"delta":_render(delta)},sort_keys=True)))
                store.connection.execute("INSERT INTO portfolio_snapshot VALUES(?,?,?,?,?,?,?,?,?)",(portfolio_id,account_id,as_of,_render(cash),_render(market_value),_render(total),"reconciled",snapshot_hash,json.dumps(self.LIMITATIONS)))
                store.connection.commit()
        except Exception:
            store.connection.rollback(); raise
        return AccountOpeningResult(account_id,batch_id,portfolio_id,as_of,_render(cash),tuple(sorted(position_ids)),len(issues),self.LIMITATIONS)

    def _result(self, connection: sqlite3.Connection, account_id: str) -> AccountOpeningResult:
        account=connection.execute("SELECT * FROM account_import_batch WHERE account_id=?",(account_id,)).fetchone(); cash=connection.execute("SELECT * FROM account_cash_opening WHERE account_id=?",(account_id,)).fetchone(); portfolio=connection.execute("SELECT * FROM portfolio_snapshot WHERE account_id=?",(account_id,)).fetchone(); positions=tuple(row[0] for row in connection.execute("SELECT position_id FROM account_position WHERE account_id=? ORDER BY position_id",(account_id,))); count=connection.execute("SELECT count(*) FROM account_import_quality_issue WHERE import_batch_id=?",(account["import_batch_id"],)).fetchone()[0]
        return AccountOpeningResult(account_id,account["import_batch_id"],portfolio["portfolio_snapshot_id"],account["confirmed_as_of"],cash["amount_decimal"],positions,count,tuple(json.loads(portfolio["limitations_json"])))

    @staticmethod
    def _read_private_object(private_root: Path, digest: str) -> bytes:
        path = Path(private_root).resolve() / "sources/sha256" / digest[:2] / digest
        for attempt in range(40):
            try:
                return path.read_bytes()
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.05)
        raise AssertionError("unreachable")

    @staticmethod
    def _rows(preview, private_root: Path) -> dict[str,list[list[str]]]:
        result={}
        for item in preview.files:
            payload=AccountOpeningService._read_private_object(
                private_root, item.source_object_sha256
            )
            if hashlib.sha256(payload).hexdigest()!=item.source_object_sha256: raise AccountOpeningError("SOURCE_OBJECT_HASH_MISMATCH")
            lines=payload.decode("gb18030").splitlines(); header=lines[0].split("\t");
            if header[-1]=="": header.pop()
            role=item.role
            for row in lines[1:]:
                columns=row.split("\t")
                if columns and columns[-1]=="": columns.pop()
                result.setdefault(role,[]).append(columns)
        return result


__all__=["AccountOpeningDetail","AccountOpeningError","AccountOpeningResult","AccountOpeningService","AccountPositionView"]
