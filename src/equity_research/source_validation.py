from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any, Mapping


def validate_source_manifest_runtime(
    manifest: Mapping[str, Any], manifest_path: Path
) -> Mapping[str, Any]:
    """Execute the platform-authoritative source gate through the public package."""

    validator_path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "scripts"
        / "source_manifest_validator.py"
    )
    module_name = "_equity_research_source_gate"
    spec = importlib.util.spec_from_file_location(module_name, validator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SOURCE_GATE_RUNTIME_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.SourceManifestValidator(manifest, manifest_path).validate()
