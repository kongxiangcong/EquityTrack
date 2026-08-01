from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import zipfile
from typing import Mapping, Protocol

from trading_platform.research_view import ResearchDecisionView


OOXML_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "spreadsheetml.sheet"
)


class ResearchWorkbookProjectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResearchWorkbookArtifact:
    payload: bytes
    media_type: str
    schema_version: str
    filename: str
    status: str
    reason_code: str | None

    @classmethod
    def ready(cls, payload: bytes) -> "ResearchWorkbookArtifact":
        result = cls(
            payload=payload,
            media_type=OOXML_MEDIA_TYPE,
            schema_version="ResearchDecisionWorkbook@1",
            filename="research-decision.xlsx",
            status="ready",
            reason_code=None,
        )
        result.validate()
        return result

    @classmethod
    def limited(
        cls,
        *,
        view_id: str,
        reason_code: str,
    ) -> "ResearchWorkbookArtifact":
        content = {
            "schema_version": "ResearchWorkbookProjection@1",
            "status": "limited",
            "reason_code": reason_code,
            "view_id": view_id,
            "intended_filename": "research-decision.xlsx",
            "produced_filename": "research-workbook-limitation.json",
        }
        result = cls(
            payload=json.dumps(
                content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            media_type="application/json",
            schema_version="ResearchWorkbookProjection@1",
            filename="research-workbook-limitation.json",
            status="limited",
            reason_code=reason_code,
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.status == "ready":
            try:
                with zipfile.ZipFile(BytesIO(self.payload)) as workbook:
                    names = set(workbook.namelist())
            except (OSError, zipfile.BadZipFile) as error:
                raise ResearchWorkbookProjectionError(
                    "RESEARCH_WORKBOOK_ARTIFACT_INVALID"
                ) from error
            if (
                self.media_type != OOXML_MEDIA_TYPE
                or self.schema_version != "ResearchDecisionWorkbook@1"
                or self.filename != "research-decision.xlsx"
                or self.reason_code is not None
                or not {
                    "[Content_Types].xml", "xl/workbook.xml",
                }.issubset(names)
            ):
                raise ResearchWorkbookProjectionError(
                    "RESEARCH_WORKBOOK_ARTIFACT_INVALID"
                )
            return
        if self.status != "limited":
            raise ResearchWorkbookProjectionError(
                "RESEARCH_WORKBOOK_ARTIFACT_INVALID"
            )
        try:
            value = json.loads(self.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResearchWorkbookProjectionError(
                "RESEARCH_WORKBOOK_LIMITATION_INVALID"
            ) from error
        expected = {
            "schema_version",
            "status",
            "reason_code",
            "view_id",
            "intended_filename",
            "produced_filename",
        }
        if (
            self.media_type != "application/json"
            or self.schema_version != "ResearchWorkbookProjection@1"
            or self.filename != "research-workbook-limitation.json"
            or not self.reason_code
            or not isinstance(value, Mapping)
            or set(value) != expected
            or value.get("schema_version")
            != "ResearchWorkbookProjection@1"
            or value.get("status") != "limited"
            or value.get("reason_code") != self.reason_code
            or not value.get("view_id")
            or value.get("intended_filename") != "research-decision.xlsx"
            or value.get("produced_filename") != self.filename
        ):
            raise ResearchWorkbookProjectionError(
                "RESEARCH_WORKBOOK_LIMITATION_INVALID"
            )


class ResearchWorkbookProjector(Protocol):
    def project(
        self, view: ResearchDecisionView
    ) -> ResearchWorkbookArtifact: ...


__all__ = [
    "OOXML_MEDIA_TYPE",
    "ResearchWorkbookArtifact",
    "ResearchWorkbookProjectionError",
    "ResearchWorkbookProjector",
]
