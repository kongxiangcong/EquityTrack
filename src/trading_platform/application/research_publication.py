from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol

from trading_platform.chart import AnnotationError
from trading_platform.research_chart import render_price_chart_html
from trading_platform.research_view import ResearchDecisionView, ResearchViewError

from .watchlist import Watchlist
from .workflow_ledger import (
    DecisionViewPayloadQuery,
    WorkflowLedgerPort,
    WorkspaceWorkflowQuery,
)
from .web_tasks import ChartWorkspace


class ResearchPublicationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PublishLatestResearch:
    security_id: str
    requested_at: str


@dataclass(frozen=True)
class ResearchPublicationResult:
    subject: str
    as_of: str
    status: str
    data_quality_grade: str
    valuation_view: Mapping[str, object]
    risk_reward_summary: str
    key_uncertainties: tuple[str, ...]
    what_would_change_the_view: tuple[str, ...]
    artifact_paths: Mapping[str, Path]
    limitations: tuple[str, ...]


class ResearchPublicationRepository(Protocol):
    def publish(
        self,
        *,
        subject: str,
        as_of: str,
        published_at: str,
        artifacts: Mapping[str, bytes],
        limitations: tuple[str, ...],
    ) -> Mapping[str, Path]: ...


class ResearchPublication:
    """Publishes the newest complete research view and chart for a user."""

    def __init__(
        self,
        ledger: WorkflowLedgerPort,
        charts: ChartWorkspace,
        watchlist: Watchlist,
        publications: ResearchPublicationRepository,
    ) -> None:
        self._ledger = ledger
        self._charts = charts
        self._watchlist = watchlist
        self._publications = publications

    def publish(
        self, command: PublishLatestResearch
    ) -> ResearchPublicationResult:
        try:
            requested = datetime.fromisoformat(command.requested_at)
        except ValueError as error:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_TIME_INVALID"
            ) from error
        if (
            not command.security_id
            or requested.tzinfo is None
            or requested.utcoffset() is None
        ):
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_REQUEST_INVALID"
            )
        identity = next(
            (
                item
                for item in self._watchlist.list()
                if item.security_id == command.security_id
            ),
            None,
        )
        if identity is None:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_SECURITY_NOT_FOUND"
            )
        workspace = self._ledger.load(
            WorkspaceWorkflowQuery(command.security_id)
        )
        payload = None
        incomplete_count = 0
        for workflow in workspace.workflows:
            if workflow.get("status") not in {
                "succeeded",
                "succeeded_with_limits",
            }:
                continue
            completed_at = workflow.get("completed_at")
            if completed_at is not None:
                completed = datetime.fromisoformat(str(completed_at))
                if completed > requested:
                    continue
            try:
                payload = self._ledger.load(
                    DecisionViewPayloadQuery(
                        str(workflow["workflow_run_id"])
                    )
                )
            except Exception as error:
                if getattr(error, "code", None) != (
                    "RESEARCH_DECISION_VIEW_INCOMPLETE"
                ):
                    raise
                incomplete_count += 1
                continue
            break
        if payload is None:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_NOT_AVAILABLE"
            )
        try:
            view = ResearchDecisionView.from_dict(
                json.loads(payload.json_bytes)
            )
        except (UnicodeDecodeError, ValueError, ResearchViewError) as error:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_VIEW_INVALID"
            ) from error
        if view.security_id != command.security_id:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_SECURITY_MISMATCH"
            )
        try:
            chart = self._charts.get_latest_series(command.security_id)
        except AnnotationError as error:
            raise ResearchPublicationError(
                "RESEARCH_PUBLICATION_CHART_UNAVAILABLE"
            ) from error
        subject = f"{identity.code}.{_market_suffix(identity.market)}"
        workbook_name = (
            "research-workbook.xlsx"
            if payload.workbook_status == "ready"
            else "research-workbook-limitation.json"
        )
        limitations = tuple(
            item
            for item in (
                (
                    "newer_incomplete_research_runs_skipped"
                    if incomplete_count
                    else None
                ),
                payload.workbook_reason_code,
            )
            if item is not None
        )
        paths = self._publications.publish(
            subject=subject,
            as_of=view.as_of,
            published_at=command.requested_at,
            artifacts={
                "research-report.json": payload.json_bytes,
                "research-report.html": payload.html_bytes,
                "research-report.pdf": payload.pdf_bytes,
                workbook_name: payload.workbook_bytes,
                "price-chart.html": render_price_chart_html(
                    subject, chart
                ),
            },
            limitations=limitations,
        )
        return ResearchPublicationResult(
            subject=subject,
            as_of=view.as_of,
            status=view.status,
            data_quality_grade=view.data_quality_grade,
            valuation_view=view.valuation_view,
            risk_reward_summary=view.risk_reward_summary,
            key_uncertainties=view.key_uncertainties,
            what_would_change_the_view=(
                view.what_would_change_the_view
            ),
            artifact_paths=paths,
            limitations=limitations,
        )


def _market_suffix(market: str) -> str:
    try:
        return {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[market]
    except KeyError as error:
        raise ResearchPublicationError(
            "RESEARCH_PUBLICATION_MARKET_UNSUPPORTED"
        ) from error


__all__ = [
    "PublishLatestResearch",
    "ResearchPublication",
    "ResearchPublicationError",
    "ResearchPublicationRepository",
    "ResearchPublicationResult",
]