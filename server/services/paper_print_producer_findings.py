"""Keep paper-only renderer failures scoped to their runtime-owned asset.

Canonical figures and their provenance are read-only evidence, not manuscript
repair targets. Failed projection cannot authorize an author to re-sign them.
"""

from __future__ import annotations

import copy
import re
from typing import Any


def scoped_print_projection_error(entry: dict[str, Any], cause: ValueError) -> ValueError:
    """Preserve bounded render history and add exact entry context before it is lost."""
    from .paper_derived_figure_rendering import PaperFigureProjectionError

    metadata = entry.get("metadata") or {}
    identity = str(metadata.get("semantic_key") or entry.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity):
        return cause
    if isinstance(cause, PaperFigureProjectionError):
        error = cause
    else:
        error = PaperFigureProjectionError(identity, str(cause))
    error.producer_context = {
        "asset_id": identity, "source_path": str(entry.get("source_path") or ""),
        "producer_kind": str(metadata.get("producer_kind") or ""),
        "production_strategy": str(metadata.get("production_strategy") or ""),
        "output_path": str(entry.get("output_path") or ""),
        "rendered_variants": copy.deepcopy(metadata.get("rendered_variants") or {}),
    }
    return error


def print_projection_finding(error: ValueError) -> dict[str, Any]:
    """Expose a platform repair target; never a canonical figure/model write target."""
    identity = str(getattr(error, "asset_id", "") or "")
    safe_identity = bool(re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity))
    targets = [f"paper/derived-figures/{identity}/PROVENANCE.json"] if safe_identity else []
    return {
        "id": "PAPER-PRINT-PRODUCER", "severity": "blocker", "category": "visual_layout",
        "owner_node": "paper", "target_files": targets,
        "asset_ids": [identity] if safe_identity else [], "producer_kind": "deterministic",
        "repair_capability": "paper-print-projection", "validator": "paper-print-contract-v1",
        "runtime_operation": "derive_paper_figure", "legal_write_targets": [],
        "producer_context": copy.deepcopy(getattr(error, "producer_context", {}) or {}),
        "message": str(error), "render_attempts": list(getattr(error, "render_attempts", []) or []),
        "remediation": "Repair the runtime-owned printed-figure projection; preserve canonical figures, scientific inputs and manuscript sections. Models must not edit provenance or rendering metadata.",
    }
