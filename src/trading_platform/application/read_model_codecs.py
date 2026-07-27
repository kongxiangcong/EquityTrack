from __future__ import annotations

import json
from dataclasses import fields
from enum import Enum
from typing import Mapping

from .read_models import ReadModelView


def encode_read_model(view: ReadModelView) -> bytes:
    view.validate()
    return json.dumps(
        {
            field.name: _json_value(getattr(view, field.name))
            for field in fields(view)
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return (
        str(value)
        if value.__class__.__module__ == "decimal"
        else value
    )


__all__ = ["encode_read_model"]
