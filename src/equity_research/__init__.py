"""Deterministic equity-research core.

The public seam is deliberately small: build a :class:`ResearchRequest` and
pass it to :meth:`ResearchEngine.run`.  Skills, CLIs, and future UIs should
adapt their inputs to this contract instead of reimplementing workflow state.
"""

from .engine import ResearchEngine
from .financial import EquityBridge, EquityBridgeResult, FinancialInvariantError, FinancialQuantity
from .models import (
    AnalysisBundle,
    AnalysisResult,
    DebateResult,
    EvidenceClaim,
    ResearchRequest,
    ResearchRun,
    ResearchSynthesis,
    SourceRecord,
)

__all__ = [
    "AnalysisBundle",
    "AnalysisResult",
    "DebateResult",
    "EvidenceClaim",
    "EquityBridge",
    "EquityBridgeResult",
    "FinancialInvariantError",
    "FinancialQuantity",
    "ResearchEngine",
    "ResearchRequest",
    "ResearchRun",
    "ResearchSynthesis",
    "SourceRecord",
]
