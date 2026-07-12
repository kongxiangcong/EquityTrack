from __future__ import annotations

from .facade import ApplicationFacade


class ProductionCompositionRoot:
    """Owns one facade instance and, later, its production dependencies."""

    def __init__(self) -> None:
        self._facade = ApplicationFacade()

    @property
    def facade(self) -> ApplicationFacade:
        return self._facade
