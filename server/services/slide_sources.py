"""Source-bundle identity for generated or model-authored slide decks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .latex_bundle import latex_source_bundle
from .slide_figures import deck_figures, project_file


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def slide_source_paths(root: Path) -> list[Path]:
    explicit = [
        root / "ideas" / "SELECTED_IDEA.json",
        root / "experiments" / "METHOD_CONTRACT.json",
        root / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        root / "figures" / "FIGURE_MANIFEST.json",
        root / "experiments" / "results" / "analysis.md",
        root / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json",
        root / "paper" / "main.tex",
    ]
    assets = _json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
    manifest = _json(root / "figures" / "FIGURE_MANIFEST.json")
    standard, synthetic = deck_figures(root, assets, manifest)
    synthetic_objects = {id(item) for item in synthetic}
    bound: list[Path] = []
    for item in [*standard, *synthetic]:
        output = project_file(root, item.get("output_path"))
        if output is not None:
            bound.append(output)
        for relative in (item.get("slide_presentation") or {}).get("source_paths") or []:
            source = project_file(root, relative)
            if source is not None:
                bound.append(source)
        if id(item) in synthetic_objects:
            for relative in dict(item.get("metadata") or {}).get("source_data") or []:
                source = project_file(root, relative)
                if source is not None:
                    bound.append(source)
    _, paper_bundle = latex_source_bundle(root / "paper")
    return list(dict.fromkeys([*explicit, *paper_bundle, *bound]))


def slide_source_hash(root: Path, sources: list[Path]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        try:
            identity = source.relative_to(root).as_posix()
        except ValueError:
            identity = source.as_posix()
        digest.update(identity.encode("utf-8"))
        digest.update(b"::")
        digest.update(source.read_bytes() if source.is_file() else b"<missing>")
        digest.update(b"\n")
    return digest.hexdigest()
