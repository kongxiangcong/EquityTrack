from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator, Mapping
from typing import Any, TypeAlias, Union


FrozenValue: TypeAlias = Union[str, int, float, bool, None, tuple["FrozenValue", ...], "FrozenFields"]


@dataclass(frozen=True)
class FrozenFields(Mapping[str, FrozenValue]):
    _items: tuple[tuple[str, FrozenValue], ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "FrozenFields":
        return cls(tuple((str(key), freeze_value(item)) for key, item in sorted(value.items())))

    def __getitem__(self, key: str) -> FrozenValue:
        return dict(self._items)[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def as_dict(self) -> dict[str, Any]:
        return {key: thaw_value(value) for key, value in self._items}


def freeze_value(value: object) -> FrozenValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return FrozenFields.from_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    raise TypeError("canonical record fields must be JSON-compatible")


def thaw_value(value: FrozenValue) -> Any:
    if isinstance(value, FrozenFields):
        return value.as_dict()
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    return value


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    value: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @classmethod
    def success(cls, value: dict[str, Any]) -> "OperationResult":
        return cls(ok=True, value=value)

    @classmethod
    def failure(cls, code: str, message: str, *, step: str) -> "OperationResult":
        return cls(ok=False, error={"code": code, "message": message, "step": step})


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, *, step: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.step = step
