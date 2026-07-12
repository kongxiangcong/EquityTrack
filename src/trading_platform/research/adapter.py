from __future__ import annotations

from equity_research import ResearchEngine, ResearchRequest, ResearchRun


class ResearchAdapter:
    """The only approved platform adapter to the existing research seam."""

    def __init__(self, engine: ResearchEngine) -> None:
        self._engine = engine

    def run(self, request: ResearchRequest) -> ResearchRun:
        return self._engine.run(request)
