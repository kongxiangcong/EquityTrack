from __future__ import annotations

from equity_research import ResearchEngine

from tests.platform.test_financial_pipeline_bundle_applicability import (
    _request_and_evidence,
)
from trading_platform.research import ResearchEvaluation
from trading_platform.research.analysis_plan import (
    ResearchAnalysisPlanCompiler,
)


class _CountingCompiler:
    IDENTITY = ResearchAnalysisPlanCompiler.IDENTITY

    def __init__(self) -> None:
        self.calls = 0

    def compile(self, *, request, evidence):
        self.calls += 1
        return ResearchAnalysisPlanCompiler().compile(
            request=request,
            evidence=evidence,
        )


def test_prepared_evaluation_compiles_one_plan_for_fingerprint_and_execution() -> None:
    request, evidence = _request_and_evidence()
    compiler = _CountingCompiler()
    evaluator = ResearchEvaluation(
        ResearchEngine(),
        analysis_plan_compiler=compiler,
    )

    prepared = evaluator.prepare(request, evidence)
    first = evaluator.evaluate(request, evidence, prepared)
    second = evaluator.evaluate(request, evidence, prepared)

    assert compiler.calls == 1
    assert first.bundle_id == second.bundle_id
    assert prepared.analysis_plan.identity.startswith(
        "research_analysis_plan_"
    )
