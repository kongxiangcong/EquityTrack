from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Mapping

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors


class ResearchDecisionPdf:
    """Deterministic local projection of persisted ResearchDecisionView@2."""

    SCHEMA_VERSION = "ResearchDecisionPdf@1"
    MEDIA_TYPE = "application/pdf"

    def render(self, view: Mapping[str, Any]) -> bytes:
        if view.get("schema_version") != "ResearchDecisionView@2":
            raise ValueError("RESEARCH_DECISION_PDF_VIEW_INVALID")
        canonical = json.dumps(
            view,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        view_hash = hashlib.sha256(canonical).hexdigest()
        output = io.BytesIO()
        document = SimpleDocTemplate(
            output,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=f"ResearchDecisionView {view.get('view_id', '')}",
            author="trading_platform",
            subject=f"{self.SCHEMA_VERSION}:{view_hash}",
            invariant=1,
            pageCompression=1,
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Research Decision", styles["Title"]),
            Spacer(1, 4 * mm),
            Table(
                [
                    ("Schema", str(view["schema_version"])),
                    ("View identity", str(view.get("view_id", ""))),
                    ("Subject", str(view.get("subject_id", ""))),
                    ("As of", str(view.get("as_of", ""))),
                    ("Status", str(view.get("status", ""))),
                    ("Content SHA-256", view_hash),
                ],
                colWidths=(35 * mm, 125 * mm),
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F3")),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB8BF")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("LEADING", (0, 0), (-1, -1), 10),
                    ]
                ),
            ),
            Spacer(1, 6 * mm),
            Paragraph(
                "Decision boundary",
                styles["Heading2"],
            ),
            Paragraph(str(view.get("boundary", "")), styles["BodyText"]),
            Spacer(1, 5 * mm),
            Paragraph("Evaluation status", styles["Heading2"]),
            Paragraph(
                "No numeric valuation conclusion is published when the "
                "frozen evidence is insufficient.",
                styles["BodyText"],
            ),
            PageBreak(),
            Paragraph("Audit binding", styles["Heading2"]),
            Paragraph(
                json.dumps(
                    view.get("audit", {}),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                styles["Code"],
            ),
        ]
        document.build(story)
        return output.getvalue()


__all__ = ["ResearchDecisionPdf"]
