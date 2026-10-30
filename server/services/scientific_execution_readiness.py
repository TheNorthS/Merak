"""Enforce declared scientific prerequisites before launching any compute backend."""

import json
from pathlib import Path

from ..contracts.implementation_readiness import ExecutionReadiness


def require_scientific_execution_ready(project_path: str | Path) -> None:
    path = Path(project_path).resolve() / "experiments/RUN_SPEC.json"
    if not path.is_file():
        return  # General terminal jobs have no research RUN_SPEC; their own policy still applies.
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Scientific execution requires a valid RUN_SPEC object")
    if not {"execution_readiness", "execution_prerequisites"}.intersection(payload):
        return  # Existing contracts remain subject to their preflight and implementation gates.
    readiness = ExecutionReadiness.model_validate(payload)
    if readiness.execution_readiness != "ready" or readiness.execution_prerequisites:
        pending = "; ".join(f"{item.id}: {item.description}" for item in readiness.execution_prerequisites)
        raise ValueError("Scientific execution prerequisites are unresolved: "
                         + (pending or readiness.execution_readiness))
