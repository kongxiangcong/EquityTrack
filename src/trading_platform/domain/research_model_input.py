from __future__ import annotations

from typing import Mapping


def exact_model_path(field: Mapping[str, object]) -> str:
    value = field.get("model_path")
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError("RESEARCH_MODEL_INPUT_PATH_INVALID")
    return value


def typed_model_field_failure(
    field: Mapping[str, object],
    *,
    expected_subject_id: str,
) -> str | None:
    path = exact_model_path(field)
    if field.get("subject_id") != expected_subject_id:
        return "RESEARCH_COMPONENT_INPUT_SUBJECT_INVALID"
    if (
        field.get("field_name") != path
        or field.get("semantic_role") != "typed_research_model_input"
        or not _exact_non_empty_text(field.get("period"))
        or not _exact_non_empty_text(field.get("unit"))
        or not _exact_non_empty_text(field.get("currency"))
        or not model_value_is_valid(field.get("value"))
    ):
        return "RESEARCH_MODEL_INPUT_SCHEMA_INVALID"
    return None


def model_value_is_valid(value: object) -> bool:
    return (
        value is not None
        and not isinstance(value, (bool, bytes, float, Mapping, list, tuple, set))
        and (not isinstance(value, str) or bool(value))
    )


def _exact_non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


__all__ = [
    "exact_model_path",
    "model_value_is_valid",
    "typed_model_field_failure",
]
