"""Deterministic equity-research core.

The public seam is deliberately small: build a :class:`ResearchRequest` and
pass it to :meth:`ResearchEngine.run`.  Skills, CLIs, and future UIs should
adapt their inputs to this contract instead of reimplementing workflow state.
"""

from .engine import ResearchEngine
from .financial import (
    EquityBridge,
    EquityBridgeResult,
    FinancialInvariantError,
    FinancialQuantity,
)
from .models import (
    AnalysisBundle,
    AnalysisResult,
    DebateResult,
    EvidenceClaim,
    MethodResult,
    ResearchRequest,
    ResearchRun,
    ResearchSynthesis,
    SourceRecord,
)
from .simulation import (
    AffineSimulationModel,
    CalibrationEvidence,
    CalibratedDistribution,
    DependencyCalibrationEvidence,
    validated_income_calibration_vectors,
    DependencyModel,
    DeterministicValueFallback,
    SimulationBudget,
    SimulationInvariantError,
    SimulationTerm,
    ValuationSimulationEngine,
    ValuationSimulationRequest,
    ValuationSimulationResult,
)
from .market_path import (
    MarketConstraintPolicy,
    MarketPathBudget,
    MarketPathCalibration,
    MarketPathEngine,
    MarketPathInvariantError,
    MarketPathObservation,
    MarketPathRequest,
    MarketPathResult,
)
from .source_validation import validate_source_manifest_runtime
from .forecast_review import (
    ActualResultEvidence,
    CalibrationChange,
    ComparabilityStatus,
    ForecastReviewEngine,
    ForecastReviewInvariantError,
    ForecastReviewRequest,
    ForecastReviewResult,
    NumericForecastTarget,
    ProbabilityForecastTarget,
)

__all__ = [
    "AnalysisBundle",
    "AnalysisResult",
    "DebateResult",
    "EvidenceClaim",
    "MethodResult",
    "EquityBridge",
    "EquityBridgeResult",
    "FinancialInvariantError",
    "FinancialQuantity",
    "AffineSimulationModel",
    "CalibrationEvidence",
    "CalibratedDistribution",
    "DependencyCalibrationEvidence",
    "validated_income_calibration_vectors",
    "DependencyModel",
    "DeterministicValueFallback",
    "SimulationBudget",
    "SimulationInvariantError",
    "SimulationTerm",
    "ValuationSimulationEngine",
    "ValuationSimulationRequest",
    "ValuationSimulationResult",
    "MarketConstraintPolicy",
    "MarketPathBudget",
    "MarketPathCalibration",
    "MarketPathEngine",
    "MarketPathInvariantError",
    "MarketPathObservation",
    "MarketPathRequest",
    "MarketPathResult",
    "validate_source_manifest_runtime",
    "ActualResultEvidence",
    "CalibrationChange",
    "ComparabilityStatus",
    "ForecastReviewEngine",
    "ForecastReviewInvariantError",
    "ForecastReviewRequest",
    "ForecastReviewResult",
    "NumericForecastTarget",
    "ProbabilityForecastTarget",
    "ResearchEngine",
    "ResearchRequest",
    "ResearchRun",
    "ResearchSynthesis",
    "SourceRecord",
]
