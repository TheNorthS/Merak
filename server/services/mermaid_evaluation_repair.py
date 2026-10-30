"""Deterministic compaction repair for evaluation Mermaid diagrams."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_text
from .publication_figure_labels import publication_label_texts


def _spec(root: Path, figure_id: str) -> dict[str, Any] | None:
    try:
        payload = json.loads((root / "figures" / "FIGURE_SPECS.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return next((
        item for item in payload.get("figures") or payload.get("assets") or []
        if isinstance(item, dict) and str(item.get("id") or "") == figure_id
    ), None)


def _source(registry: Any, root: Path, figure_id: str, spec: dict[str, Any]) -> Path | None:
    source_value = str(spec.get("source_path") or "").strip()
    if not source_value:
        try:
            manifest = registry.load(root / "figures")
        except Exception:
            manifest = {}
        entry = next((
            item for item in manifest.get("figures") or []
            if isinstance(item, dict) and str(item.get("id") or "") == figure_id
        ), {})
        source_value = str(entry.get("source_path") or "").strip()
    source = (root / source_value).resolve() if source_value else None
    return source if source and source.suffix.casefold() in {".mmd", ".mermaid"} else None


def _labels(registry: Any, spec: dict[str, Any], previous: str) -> tuple[str, str, str]:
    terms = [
        " ".join(str(value).replace("_", " ").split())
        for value in publication_label_texts(spec.get("publication_labels"))
    ]
    data = terms[0] if terms else "Study data"
    split = terms[1] if len(terms) > 1 else "Leakage-safe split"
    heldout = terms[2] if len(terms) > 2 else "Held-out evaluation"
    if registry.mermaid_concept_present("Leakage-safe split", previous):
        split = "Leakage-safe split"
    if registry.mermaid_concept_present("Held-out evaluation", previous):
        heldout = "Held-out evaluation"
    return data, split, heldout


def _compact(data: str, split: str, heldout: str, previous: str) -> str:
    eeg_like = any(term in previous.casefold() for term in (
        "eeg", "montage", "spectral", "topology", "subject",
    ))
    stress = "Unseen montage stress" if eeg_like else "Registered stress tests"
    endpoints = (
        "accuracy · identity probe<br/>spectral/topology · paired CI"
        if eeg_like else "primary outcome · robustness<br/>calibration · paired CI"
    )
    return f'''%%{{init: {{"theme":"base","themeVariables":{{"fontFamily":"Arial, Helvetica, sans-serif","fontSize":"40px","primaryTextColor":"#172033","lineColor":"#334155"}},"flowchart":{{"htmlLabels":true,"curve":"basis","nodeSpacing":42,"rankSpacing":56,"padding":76,"useMaxWidth":true}}}}}}%%
flowchart LR
    classDef data fill:#E8F4F1,stroke:#16806A,color:#15332E,stroke-width:2px;
    classDef split fill:#EAF2FF,stroke:#2563EB,color:#172554,stroke-width:2px;
    classDef process fill:#F2ECFF,stroke:#7651C8,color:#2E1065,stroke-width:2px;
    classDef heldout fill:#FFF0E5,stroke:#D65A1F,color:#431407,stroke-width:2px;
    classDef summary fill:#FFF7D6,stroke:#A56A00,color:#422006,stroke-width:2px;
    linkStyle default stroke:#334155,stroke-width:3px;

    data["{data}<br/>versioned records · metadata"]
    split["{split}<br/>group / record / dataset isolation"]
    develop["Matched development<br/>train-only transforms · fixed budget"]
    heldout["{heldout}<br/>locked test · {stress}"]
    endpoints["Subject-level endpoints<br/>{endpoints}"]

    data --> split --> develop --> heldout --> endpoints
    class data data;
    class split split;
    class develop process;
    class heldout heldout;
    class endpoints summary;
'''


def repair_evaluation_mermaid(
    registry: Any, project_path: str | Path, figure_id: str,
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    spec = _spec(root, figure_id)
    if not isinstance(spec, dict):
        return {"changed": False, "reason": "figure specs unavailable or figure spec not found"}
    source = _source(registry, root, figure_id, spec)
    if source is None:
        return {"changed": False, "reason": "asset is not Mermaid"}
    try:
        previous = source.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {"changed": False, "reason": "Mermaid source unavailable"}
    compact = _compact(*_labels(registry, spec, previous), previous)
    if compact == previous:
        return {"changed": False, "reason": "already compact"}
    atomic_write_text(source, compact)
    return {
        "changed": True, "source_path": str(source),
        "before_sha256": hashlib.sha256(previous.encode("utf-8")).hexdigest(),
        "after_sha256": hashlib.sha256(compact.encode("utf-8")).hexdigest(),
    }
