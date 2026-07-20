"""Deterministic local trading-platform application boundary."""

from .research_presentation import render_research_decision_html
from .research_view import (
    ResearchDecisionInput,
    ResearchDecisionView,
    ResearchDecisionViewBuilder,
    ResearchViewError,
)
from .valuation_workbook import (
    ValuationWorkbookAdapter,
    ValuationWorkbookError,
    ValuationWorkbookExport,
)

__all__ = [
    "ResearchDecisionInput",
    "ResearchDecisionView",
    "ResearchDecisionViewBuilder",
    "ResearchViewError",
    "ValuationWorkbookAdapter",
    "ValuationWorkbookError",
    "ValuationWorkbookExport",
    "render_research_decision_html",
]
