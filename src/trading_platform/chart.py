from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from trading_platform.domain.market_time import supported_market_timezone
from trading_platform.domain.chart import (
    AnnotationAnchor,
    AnnotationCommand,
    AnnotationDraft,
    AnnotationLifecycleCommand,
    AnnotationLink,
    AnnotationVersion,
    ChartBar,
    ChartSeries,
    CoordinateMigration,
    CoordinateMigrationResult,
)
from trading_platform.identity import canonical_hash
from trading_platform.persistence.locking import DataRootWriterLock


class AnnotationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChartService:
    def __init__(
        self, connection: sqlite3.Connection, writer_lock: DataRootWriterLock
    ) -> None:
        self.connection = connection
        self.writer_lock = writer_lock

    def get_latest_series(self, security_id: str) -> ChartSeries:
        row = self.connection.execute(
            """SELECT s.data_snapshot_id FROM data_snapshot s
            WHERE s.scope_id=? AND EXISTS(
              SELECT 1 FROM data_snapshot_member m
              JOIN ohlcv_version o USING(normalized_version_id)
              WHERE m.data_snapshot_id=s.data_snapshot_id
                AND o.security_id=s.scope_id
            )
            ORDER BY s.effective_session_date DESC,
                     s.data_snapshot_id DESC LIMIT 1""",
            (security_id,),
        ).fetchone()
        if row is None:
            raise AnnotationError("CHART_SNAPSHOT_NOT_FOUND")
        return self.get_series(security_id, str(row[0]))

    def get_series(
        self,
        security_id: str,
        snapshot_id: str,
        interval: str = "1d",
        adjustment_mode: str = "none",
        factor_snapshot_id: str | None = None,
    ) -> ChartSeries:
        if (
            interval != "1d"
            or adjustment_mode != "none"
            or factor_snapshot_id is not None
        ):
            raise AnnotationError("CHART_MAPPING_UNAVAILABLE")
        snapshot = self.connection.execute(
            "SELECT * FROM data_snapshot WHERE data_snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if snapshot is None or snapshot["scope_id"] != security_id:
            raise AnnotationError("CHART_SNAPSHOT_INVALID")
        rows = self.connection.execute(
            """SELECT o.* FROM data_snapshot_member m
            JOIN ohlcv_version o USING(normalized_version_id)
            WHERE m.data_snapshot_id=? AND o.security_id=? ORDER BY o.session_date""",
            (snapshot_id, security_id),
        ).fetchall()
        bars = tuple(
            ChartBar(
                f"{row['session_date']}T15:00:00+08:00",
                row["open_decimal"],
                row["high_decimal"],
                row["low_decimal"],
                row["close_decimal"],
                row["volume_decimal"],
            )
            for row in rows
        )
        return ChartSeries(
            security_id,
            interval,
            adjustment_mode,
            snapshot_id,
            factor_snapshot_id,
            snapshot["effective_session_date"],
            snapshot["freshness_status"],
            bars,
        )

    def apply(self, command: AnnotationLifecycleCommand) -> AnnotationVersion:
        if command.operation == "create":
            if command.annotation_id is not None or command.expected_version_no != 0:
                raise AnnotationError("ANNOTATION_CREATE_INVALID")
            if command.kind is None or command.style is None:
                raise AnnotationError("ANNOTATION_CREATE_INVALID")
            frame = self.get_series(
                command.security_id,
                command.data_snapshot_id,
            )
            draft = AnnotationDraft(
                command.security_id,
                frame.interval,
                frame.adjustment_mode,
                command.data_snapshot_id,
                frame.factor_snapshot_id,
                command.kind,
                command.style,
                command.author_id,
                command.anchors,
            )
            return self.create(AnnotationCommand(command.invocation_id, None, 0, draft))

        if command.annotation_id is None:
            raise AnnotationError("ANNOTATION_ID_REQUIRED")
        history = self.get_history(command.annotation_id)
        if not history:
            raise AnnotationError("ANNOTATION_NOT_FOUND")
        current = history[-1]
        frame = current.draft
        if (
            frame.security_id != command.security_id
            or frame.data_snapshot_id != command.data_snapshot_id
        ):
            raise AnnotationError("ANNOTATION_NOT_FOUND")
        base = AnnotationCommand(
            command.invocation_id,
            command.annotation_id,
            command.expected_version_no,
        )
        if command.operation == "revise":
            if command.kind is None or command.style is None:
                raise AnnotationError("ANNOTATION_REVISION_INVALID")
            draft = replace(
                current.draft,
                kind=command.kind,
                style=command.style,
                anchors=command.anchors,
            )
            return self.revise(replace(base, draft=draft))
        if command.operation == "delete":
            return self.delete(base)
        if command.operation == "restore":
            return self.restore(base)
        raise AnnotationError("ANNOTATION_OPERATION_INVALID")

    def create(self, command: AnnotationCommand) -> AnnotationVersion:
        if (
            command.annotation_id is not None
            or command.expected_version_no != 0
            or command.draft is None
        ):
            raise AnnotationError("ANNOTATION_CREATE_INVALID")
        self._validate_draft(command.draft)
        fingerprint = self._command_fingerprint("create_annotation", command)
        with self.writer_lock.acquire(f"annotation-invocation:{command.invocation_id}"):
            replay = self._receipt(
                command.invocation_id, "create_annotation", fingerprint
            )
            if replay is not None:
                return replay
            annotation_id = f"annotation_{uuid.uuid4().hex}"
            return self._append(
                command.invocation_id,
                "create_annotation",
                fingerprint,
                annotation_id,
                1,
                None,
                "active",
                command.draft,
            )

    def revise(self, command: AnnotationCommand) -> AnnotationVersion:
        if command.draft is None:
            raise AnnotationError("ANNOTATION_REVISION_INVALID")
        self._validate_draft(command.draft)
        fingerprint = self._command_fingerprint("revise_annotation", command)
        with self.writer_lock.acquire(f"annotation-invocation:{command.invocation_id}"):
            replay = self._receipt(
                command.invocation_id, "revise_annotation", fingerprint
            )
            if replay is not None:
                return replay
            current = self._current(command)
            if current.status != "active":
                raise AnnotationError("ANNOTATION_REVISION_INVALID")
            if self._frame_identity(current.draft) != self._frame_identity(
                command.draft
            ):
                raise AnnotationError("ANNOTATION_FRAME_CHANGE_REQUIRES_MIGRATION")
            return self._append(
                command.invocation_id,
                "revise_annotation",
                fingerprint,
                current.annotation_id,
                current.version_no + 1,
                current.annotation_version_id,
                "active",
                command.draft,
            )

    def delete(self, command: AnnotationCommand) -> AnnotationVersion:
        fingerprint = self._command_fingerprint("delete_annotation", command)
        with self.writer_lock.acquire(f"annotation-invocation:{command.invocation_id}"):
            replay = self._receipt(
                command.invocation_id, "delete_annotation", fingerprint
            )
            if replay is not None:
                return replay
            current = self._current(command)
            if current.status != "active":
                raise AnnotationError("ANNOTATION_ALREADY_DELETED")
            return self._append(
                command.invocation_id,
                "delete_annotation",
                fingerprint,
                current.annotation_id,
                current.version_no + 1,
                current.annotation_version_id,
                "deleted",
                current.draft,
            )

    def restore(self, command: AnnotationCommand) -> AnnotationVersion:
        fingerprint = self._command_fingerprint("restore_annotation", command)
        with self.writer_lock.acquire(f"annotation-invocation:{command.invocation_id}"):
            replay = self._receipt(
                command.invocation_id, "restore_annotation", fingerprint
            )
            if replay is not None:
                return replay
            current = self._current(command)
            if current.status != "deleted":
                raise AnnotationError("ANNOTATION_NOT_DELETED")
            return self._append(
                command.invocation_id,
                "restore_annotation",
                fingerprint,
                current.annotation_id,
                current.version_no + 1,
                current.annotation_version_id,
                "active",
                current.draft,
            )

    def migrate(self, command: CoordinateMigration) -> CoordinateMigrationResult:
        fingerprint = canonical_hash(
            {
                "command": "migrate_annotation_coordinates",
                "request": {
                    "invocation_id": command.invocation_id,
                    "annotation_id": command.annotation_id,
                    "expected_version_no": command.expected_version_no,
                    "target_interval": command.target_interval,
                    "target_adjustment_mode": command.target_adjustment_mode,
                    "target_data_snapshot_id": command.target_data_snapshot_id,
                    "target_factor_snapshot_id": command.target_factor_snapshot_id,
                    "anchor_mapping": {
                        self._anchor_identity(AnnotationAnchor(key, "1"))[
                            "market_timestamp"
                        ]: self._anchor_identity(value)
                        for key, value in sorted(command.anchor_mapping.items())
                    },
                },
            }
        )
        with self.writer_lock.acquire(f"annotation-invocation:{command.invocation_id}"):
            replay = self._receipt(
                command.invocation_id, "migrate_annotation_coordinates", fingerprint
            )
            if replay is not None:
                return CoordinateMigrationResult("migrated", replay, None)
            return self._migrate_locked(command, fingerprint)

    def _migrate_locked(
        self, command: CoordinateMigration, fingerprint: str
    ) -> CoordinateMigrationResult:
        history = self.get_history(command.annotation_id)
        if not history or history[-1].version_no != command.expected_version_no:
            raise AnnotationError("ANNOTATION_VERSION_CONFLICT")
        current = history[-1]
        if (
            command.target_interval != current.draft.interval
            or command.target_adjustment_mode != current.draft.adjustment_mode
            or command.target_data_snapshot_id != current.draft.data_snapshot_id
            or command.target_factor_snapshot_id != current.draft.factor_snapshot_id
        ):
            return CoordinateMigrationResult(
                "unresolved_requires_confirmation",
                None,
                "COORDINATE_MAPPING_CAPABILITY_UNAVAILABLE",
            )
        keys = {anchor.market_timestamp for anchor in current.draft.anchors}
        if set(command.anchor_mapping) != keys or len(
            {
                (value.market_timestamp, value.exact_price_decimal)
                for value in command.anchor_mapping.values()
            }
        ) != len(keys):
            return CoordinateMigrationResult(
                "unresolved_requires_confirmation",
                None,
                "COORDINATE_MAPPING_NOT_UNIQUE",
            )
        originals = {
            anchor.market_timestamp: anchor for anchor in current.draft.anchors
        }
        if any(command.anchor_mapping[key] != originals[key] for key in keys):
            return CoordinateMigrationResult(
                "unresolved_requires_confirmation",
                None,
                "COORDINATE_MAPPING_CAPABILITY_UNAVAILABLE",
            )
        draft = replace(
            current.draft,
            interval=command.target_interval,
            adjustment_mode=command.target_adjustment_mode,
            data_snapshot_id=command.target_data_snapshot_id,
            factor_snapshot_id=command.target_factor_snapshot_id,
            anchors=tuple(command.anchor_mapping[key] for key in sorted(keys)),
        )
        try:
            version = self._append(
                command.invocation_id,
                "migrate_annotation_coordinates",
                fingerprint,
                current.annotation_id,
                current.version_no + 1,
                current.annotation_version_id,
                current.status,
                draft,
            )
        except AnnotationError as error:
            return CoordinateMigrationResult(
                "unresolved_requires_confirmation", None, error.code
            )
        return CoordinateMigrationResult("migrated", version, None)

    def get_history(self, annotation_id: str) -> tuple[AnnotationVersion, ...]:
        rows = self.connection.execute(
            "SELECT * FROM chart_annotation_version WHERE annotation_id=? ORDER BY version_no",
            (annotation_id,),
        ).fetchall()
        return tuple(self._hydrate(row) for row in rows)

    def list_history(self, security_id: str) -> tuple[AnnotationVersion, ...]:
        identifiers = self.connection.execute(
            "SELECT annotation_id FROM chart_annotation WHERE security_id=? ORDER BY created_at",
            (security_id,),
        ).fetchall()
        return tuple(
            version
            for identifier in identifiers
            for version in self.get_history(identifier[0])
        )

    def _current(self, command: AnnotationCommand) -> AnnotationVersion:
        if command.annotation_id is None:
            raise AnnotationError("ANNOTATION_ID_REQUIRED")
        history = self.get_history(command.annotation_id)
        if not history or history[-1].version_no != command.expected_version_no:
            raise AnnotationError("ANNOTATION_VERSION_CONFLICT")
        return history[-1]

    def _append(
        self,
        invocation_id: str,
        command_name: str,
        request_fingerprint: str,
        annotation_id: str,
        version_no: int,
        supersedes: str | None,
        status: str,
        draft: AnnotationDraft,
    ) -> AnnotationVersion:
        self._validate_draft(draft)
        identity = self.connection.execute(
            "SELECT security_id FROM chart_annotation WHERE annotation_id=?",
            (annotation_id,),
        ).fetchone()
        if identity is not None and identity[0] != draft.security_id:
            raise AnnotationError("ANNOTATION_SECURITY_CONFLICT")
        content = {
            "status": status,
            "draft": self._draft_identity(draft),
            "supersedes": supersedes,
        }
        content_hash = canonical_hash(content)
        version_id = f"annotation_version_{canonical_hash({'annotation': annotation_id, 'version': version_no, 'content': content_hash})[:24]}"
        created_at = _now()
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO chart_annotation VALUES(?,?,?)",
                (annotation_id, draft.security_id, created_at),
            )
            self.connection.execute(
                "INSERT INTO chart_annotation_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    annotation_id,
                    version_no,
                    supersedes,
                    status,
                    draft.interval,
                    draft.adjustment_mode,
                    draft.data_snapshot_id,
                    draft.factor_snapshot_id,
                    draft.kind,
                    draft.style,
                    draft.author_id,
                    created_at,
                    content_hash,
                ),
            )
            for anchor_no, anchor in enumerate(draft.anchors):
                self.connection.execute(
                    "INSERT INTO chart_annotation_anchor VALUES(?,?,?,?)",
                    (
                        version_id,
                        anchor_no,
                        anchor.market_timestamp,
                        anchor.exact_price_decimal,
                    ),
                )
            for link_no, link in enumerate(draft.links):
                self.connection.execute(
                    "INSERT INTO chart_annotation_link VALUES(?,?,?,?,?)",
                    (
                        version_id,
                        link_no,
                        link.link_type,
                        link.link_id,
                        link.resolution_status,
                    ),
                )
            self.connection.execute(
                "INSERT INTO command_receipt VALUES(?,?,?,?,?)",
                (
                    invocation_id,
                    command_name,
                    request_fingerprint,
                    "ChartAnnotationVersion",
                    version_id,
                ),
            )
        return self.get_history(annotation_id)[-1]

    def _receipt(
        self, invocation_id: str, command_name: str, request_fingerprint: str
    ) -> AnnotationVersion | None:
        row = self.connection.execute(
            "SELECT * FROM command_receipt WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        if row is None:
            return None
        if (
            row["command_name"] != command_name
            or row["request_hash"] != request_fingerprint
            or row["result_type"] != "ChartAnnotationVersion"
        ):
            raise AnnotationError("INVOCATION_CONFLICT")
        version = self.connection.execute(
            "SELECT * FROM chart_annotation_version WHERE annotation_version_id=?",
            (row["result_id"],),
        ).fetchone()
        if version is None:
            raise AnnotationError("INVOCATION_RESULT_MISSING")
        return self._hydrate(version)

    def _validate_draft(self, draft: AnnotationDraft) -> None:
        if (
            draft.interval != "1d"
            or draft.adjustment_mode not in {"none", "forward", "backward"}
            or draft.kind not in {"trend_line", "horizontal_line", "note"}
            or draft.style not in {"accent", "warning", "neutral"}
        ):
            raise AnnotationError("ANNOTATION_ENUM_INVALID")
        if not 1 <= len(draft.anchors) <= 8 or len(draft.author_id) > 80:
            raise AnnotationError("ANNOTATION_SIZE_INVALID")
        if draft.adjustment_mode != "none" or draft.factor_snapshot_id is not None:
            raise AnnotationError("ANNOTATION_ADJUSTMENT_CAPABILITY_UNAVAILABLE")
        snapshot = self.connection.execute(
            "SELECT scope_id,market_timezone FROM data_snapshot WHERE data_snapshot_id=?",
            (draft.data_snapshot_id,),
        ).fetchone()
        if snapshot is None or snapshot[0] != draft.security_id:
            raise AnnotationError("ANNOTATION_SNAPSHOT_INVALID")
        sessions = {
            row[0]
            for row in self.connection.execute(
                "SELECT o.session_date FROM data_snapshot_member m JOIN ohlcv_version o USING(normalized_version_id) WHERE m.data_snapshot_id=? AND o.security_id=?",
                (draft.data_snapshot_id, draft.security_id),
            )
        }
        for anchor in draft.anchors:
            try:
                price = self._parse_price(anchor.exact_price_decimal)
                timestamp = datetime.fromisoformat(
                    anchor.market_timestamp.replace("Z", "+00:00")
                )
            except InvalidOperation as error:
                raise AnnotationError("ANNOTATION_PRICE_INVALID") from error
            except ValueError as error:
                raise AnnotationError("ANNOTATION_ANCHOR_INVALID") from error
            if (
                not price.is_finite()
                or price <= 0
                or timestamp.tzinfo is None
                or timestamp.utcoffset() is None
            ):
                raise AnnotationError("ANNOTATION_ANCHOR_INVALID")
            if (
                timestamp.astimezone(
                    supported_market_timezone(snapshot["market_timezone"])
                )
                .date()
                .isoformat()
                not in sessions
            ):
                raise AnnotationError("ANNOTATION_NON_TRADING_ANCHOR")
        if len(draft.links) > 32 or any(
            link.link_type
            not in {"ResearchRun", "Evidence", "TradePlanVersion", "MarketEvent"}
            or link.resolution_status not in {"resolved", "unresolved_external"}
            or not 1 <= len(link.link_id) <= 160
            for link in draft.links
        ):
            raise AnnotationError("ANNOTATION_LINK_INVALID")
        if any(
            len(anchor.market_timestamp) > 64
            or len(anchor.exact_price_decimal) > 80
            or any(ord(character) < 32 for character in anchor.market_timestamp)
            for anchor in draft.anchors
        ):
            raise AnnotationError("ANNOTATION_PAYLOAD_INVALID")
        for link in draft.links:
            if link.resolution_status == "resolved":
                if (
                    link.link_type != "ResearchRun"
                    or self.connection.execute(
                        "SELECT 1 FROM research_run_record WHERE research_run_id=?",
                        (link.link_id,),
                    ).fetchone()
                    is None
                ):
                    raise AnnotationError("ANNOTATION_LINK_UNRESOLVED")

    def _command_fingerprint(
        self, command_name: str, command: AnnotationCommand
    ) -> str:
        return canonical_hash(
            {
                "command": command_name,
                "request": {
                    "invocation_id": command.invocation_id,
                    "annotation_id": command.annotation_id,
                    "expected_version_no": command.expected_version_no,
                    "draft": (
                        self._draft_identity(command.draft)
                        if command.draft is not None
                        else None
                    ),
                },
            }
        )

    @classmethod
    def _draft_identity(cls, draft: AnnotationDraft) -> dict[str, object]:
        return {
            "security_id": draft.security_id,
            "interval": draft.interval,
            "adjustment_mode": draft.adjustment_mode,
            "data_snapshot_id": draft.data_snapshot_id,
            "factor_snapshot_id": draft.factor_snapshot_id,
            "kind": draft.kind,
            "style": draft.style,
            "author_id": draft.author_id,
            "anchors": [cls._anchor_identity(anchor) for anchor in draft.anchors],
            "links": [asdict(link) for link in draft.links],
        }

    @staticmethod
    def _anchor_identity(anchor: AnnotationAnchor) -> dict[str, str]:
        try:
            price = ChartService._parse_price(anchor.exact_price_decimal)
            timestamp = datetime.fromisoformat(
                anchor.market_timestamp.replace("Z", "+00:00")
            )
        except (InvalidOperation, ValueError) as error:
            raise AnnotationError("ANNOTATION_ANCHOR_INVALID") from error
        if not price.is_finite() or timestamp.tzinfo is None:
            raise AnnotationError("ANNOTATION_ANCHOR_INVALID")
        decimal_text = format(price.normalize(), "f")
        timestamp_text = (
            timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return {"market_timestamp": timestamp_text, "exact_price_decimal": decimal_text}

    @staticmethod
    def _parse_price(value: str) -> Decimal:
        if not re.fullmatch(r"(?:0|[1-9]\d{0,19})(?:\.\d{1,12})?", value):
            raise AnnotationError("ANNOTATION_PRICE_INVALID")
        price = Decimal(value)
        if not price.is_finite() or price <= 0:
            raise AnnotationError("ANNOTATION_PRICE_INVALID")
        return price

    @staticmethod
    def _frame_identity(
        draft: AnnotationDraft,
    ) -> tuple[str, str, str, str, str | None]:
        return (
            draft.security_id,
            draft.interval,
            draft.adjustment_mode,
            draft.data_snapshot_id,
            draft.factor_snapshot_id,
        )

    def _hydrate(self, row: sqlite3.Row) -> AnnotationVersion:
        anchors = tuple(
            AnnotationAnchor(item["market_timestamp"], item["exact_price_decimal"])
            for item in self.connection.execute(
                "SELECT * FROM chart_annotation_anchor WHERE annotation_version_id=? ORDER BY anchor_no",
                (row["annotation_version_id"],),
            )
        )
        links = tuple(
            AnnotationLink(
                item["link_type"], item["link_id"], item["resolution_status"]
            )
            for item in self.connection.execute(
                "SELECT * FROM chart_annotation_link WHERE annotation_version_id=? ORDER BY link_no",
                (row["annotation_version_id"],),
            )
        )
        security_id = self.connection.execute(
            "SELECT security_id FROM chart_annotation WHERE annotation_id=?",
            (row["annotation_id"],),
        ).fetchone()[0]
        draft = AnnotationDraft(
            security_id,
            row["interval_code"],
            row["adjustment_mode"],
            row["data_snapshot_id"],
            row["factor_snapshot_id"],
            row["annotation_kind"],
            row["style_name"],
            row["author_id"],
            anchors,
            links,
        )
        return AnnotationVersion(
            row["annotation_id"],
            row["annotation_version_id"],
            row["version_no"],
            row["supersedes_version_id"],
            row["status"],
            draft,
            row["created_at"],
            row["content_hash"],
        )
