"""Deterministic equity-research core.

The public seam is deliberately small: build a :class:`ResearchRequest` and
pass it to :meth:`ResearchEngine.run`.  Skills, CLIs, and future UIs should
adapt their inputs to this contract instead of reimplementing workflow state.
"""

from .engine import ResearchEngine
from .models import ResearchRequest, ResearchRun, SourceRecord

__all__ = ["ResearchEngine", "ResearchRequest", "ResearchRun", "SourceRecord"]
