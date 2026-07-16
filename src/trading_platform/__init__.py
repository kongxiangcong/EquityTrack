"""Deterministic local trading-platform application boundary."""

from .application import ApplicationFacade, ProductionCompositionRoot
from .research_presentation import render_research_decision_html
from .research_view import (
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
    "ApplicationFacade",
    "ProductionCompositionRoot",
    "ResearchDecisionView",
    "ResearchDecisionViewBuilder",
    "ResearchViewError",
    "ValuationWorkbookAdapter",
    "ValuationWorkbookError",
    "ValuationWorkbookExport",
    "render_research_decision_html",
]
