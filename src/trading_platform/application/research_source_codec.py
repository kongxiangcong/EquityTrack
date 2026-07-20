from __future__ import annotations

from html import escape


def encode_research_source_html(run_id: str, schema_version: int) -> bytes:
    """Serialize source identity without presenting research semantics."""

    safe_run_id = escape(run_id, quote=True)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Research source identity</title></head><body>"
        f"<p>Canonical Run {safe_run_id}</p>"
        f"<p>Schema v{schema_version}</p>"
        "</body></html>"
    ).encode("utf-8")


__all__ = ["encode_research_source_html"]
