"""Derive independently visible mechanism labels from one figure specification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .figure_semantic_projection import project_figure_semantics


_GENERIC = {"consistency", "mechanism", "objective", "protocol", "method"}


def _tokens(value: object) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) > 2 and token not in _GENERIC
    }


def _figure_spec(root: Path, artifact_name: str) -> dict[str, Any]:
    path = root / "figures" / "FIGURE_SPECS.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"figure specifications are missing or invalid: {path}") from error
    return next((
        dict(item) for item in payload.get("figures") or []
        if isinstance(item, dict) and str(item.get("id") or "") == artifact_name
    ), {})


def required_mechanism_labels(root: Path, artifact_name: str) -> list[str]:
    """Return focal publication mechanisms that cannot be collapsed in the IR."""
    asset = _figure_spec(root, artifact_name)
    if not asset:
        return []
    projection = project_figure_semantics(asset)
    excluded_ids = set((projection.get("excluded") or {}).keys())
    scene = asset.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    excluded_tokens = set().union(*(
        _tokens(item.get("label"))
        for item in scene.get("objects") or []
        if isinstance(item, dict) and str(item.get("id") or "") in excluded_ids
    )) if excluded_ids else set()
    labels = []
    for item in asset.get("publication_labels") or []:
        if not isinstance(item, dict) or ".mechanism." not in str(item.get("id") or ""):
            continue
        label = " ".join(str(item.get("display_text") or "").split())
        label_tokens = _tokens(label)
        if label and not label_tokens.intersection(excluded_tokens):
            labels.append(label)
    return list(dict.fromkeys(labels))


def validate_required_mechanisms(
    mechanism_ir: dict[str, Any], required_labels: list[str],
) -> None:
    """Require one independently routed primitive for every focal mechanism label."""
    primitive_labels = {
        str(item.get("public_label") or "").strip().casefold(): str(item.get("id") or "")
        for item in mechanism_ir.get("primitives") or []
    }
    missing = [label for label in required_labels if label.casefold() not in primitive_labels]
    if missing:
        raise ValueError(
            "mechanism_ir must represent each focal publication mechanism as a "
            "separate primitive with its exact public_label: " + ", ".join(missing)
        )
