"""Recompile current benchmark paper selection without executing scientific code.

This producer owns the derived include and its manifest bindings. It only accepts
current, hash-verified bundles; unsupported schemas and edited inputs fail closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, atomic_write_text, path_lock
from .simulation_artifact_io import simulation_figures_tex
from .simulation_figure_portfolio import selected_simulation_figures, simulation_contribution_type
from .planned_simulation_bindings import (
    PLANNED_SIMULATION_MANIFEST, load_planned_simulation_binding, rebind_planned_simulation,
)
from .simulation_publication_attestation import (
    MANIFEST_RELATIVE, _assert_inputs_unchanged, _canonical_conflicts,
    _current_bundle, _registration_updates, _verify,
)


_PAPER_FIGURES = "paper/synthetic_preview_figures.tex"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _projection(root: Path, payload: dict[str, Any], entries: dict[str, dict]) -> tuple[str, set[str]]:
    from .simulation_interval_caption import scenario_interval_caption
    records = selected_simulation_figures(payload["figure_files"], simulation_contribution_type(root))
    rendered = []
    for record in records:
        pdf = Path(record["outputs"]["pdf"])
        if pdf.parent.as_posix() != "figures/simulated" or pdf.stem != Path(record["source"]).stem:
            raise ValueError("Simulation paper projection requires its canonical flat output paths")
        entry = entries[record["id"]]
        if (entry.get("metadata") or {}).get("label") != record.get("label"):
            raise ValueError(f"{record['id']}: registered public label conflicts with its source")
        rendered.append({"id": record["id"], "stem": Path(record["outputs"]["pdf"]).stem,
                         "description": scenario_interval_caption(entry["metadata"].get("caption") or entry["description"],
                             assigned_bounds=record['id'] in {'synthetic_preview_ablation', 'synthetic_preview_robustness', 'synthetic_preview_calibration'}),
                         "label": record["label"]})
    return simulation_figures_tex(rendered), {record["id"] for record in records}


def _commit_projection(
    root: Path, payload: dict[str, Any], original: bytes, text: str,
    selected: set[str], entries: dict[str, dict], registry: Any, idea: bytes,
) -> None:
    from .paper_artifacts import simulation_manifest_semantic_hash

    after = copy.deepcopy(payload)
    after["paper_figures_sha256"] = _digest(text.encode("utf-8"))
    if simulation_manifest_semantic_hash(after) != simulation_manifest_semantic_hash(payload):
        raise RuntimeError("Simulation paper selection must not change scientific identity")
    # Match the canonical atomic JSON writer before updating every hash binding.
    new_bytes = json.dumps(after, ensure_ascii=False, indent=2).encode("utf-8")
    new_hash = _digest(new_bytes)
    binding = load_planned_simulation_binding(root, _digest(original), payload["figure_files"])
    planned = rebind_planned_simulation(binding, after["figure_files"], new_hash,
                                       selected_ids=selected) if binding else None
    from .simulation_table_projection_binding import PUBLICATION_BINDING
    proof_path = root / PUBLICATION_BINDING
    proof = json.loads(proof_path.read_bytes()) if proof_path.is_file() else None
    if proof is not None:
        proof["simulation_manifest_sha256"] = new_hash
    targets = [root / _PAPER_FIGURES, root / MANIFEST_RELATIVE,
               root / "figures/FIGURE_MANIFEST.json", root / "figures/FIGURE_MANIFEST.md"]
    if planned is not None:
        targets.append(root / PLANNED_SIMULATION_MANIFEST)
    if proof is not None:
        targets.append(proof_path)
    before = {path: path.read_bytes() if path.exists() else None for path in targets}
    try:
        _assert_inputs_unchanged(root, payload, original)
        if (root / "ideas/SELECTED_IDEA.json").read_bytes() != idea:
            raise RuntimeError("Selected scientific contribution changed during paper projection")
        atomic_write_text(root / _PAPER_FIGURES, text)
        atomic_write_bytes(root / MANIFEST_RELATIVE, new_bytes)
        if proof is not None:
            atomic_write_json(proof_path, proof)
        for record in payload["figure_files"]:
            entry = entries[record["id"]]
            metadata = {**entry["metadata"], "simulation_manifest_sha256": new_hash,
                        "paper_selected": record["id"] in selected}
            registry.record(output_dir=root / "figures", figure_type=entry["type"],
                            description=entry["description"], metadata=metadata,
                            output_path=str(root / entry["output_path"]),
                            source_path=str(root / entry["source_path"]))
        if planned is not None:
            atomic_write_json(root / PLANNED_SIMULATION_MANIFEST, planned)
        _assert_inputs_unchanged(root, after, new_bytes)
        if (root / "ideas/SELECTED_IDEA.json").read_bytes() != idea:
            raise RuntimeError("Selected scientific contribution changed during paper projection")
    except BaseException:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, content)
        raise


def refresh_simulation_paper_projection(root: Path) -> bool:
    """Explicitly rebuild the current include at its producer, preserving all evidence.

    No model, script, renderer, training or evidence generation is invoked. A
    second call is byte-stable. Consumer gates remain read-only and blocking.
    """
    from .figure_artifacts import figure_artifact_registry

    root = root.resolve()
    manifest_path = root / MANIFEST_RELATIVE
    if not manifest_path.is_file():
        return False
    with path_lock(root / "figures/FIGURE_MANIFEST.json"):
        original = manifest_path.read_bytes()
        payload = _current_bundle(root)
        if payload.get("paper_figures") != _PAPER_FIGURES:
            raise ValueError("Simulation paper projection requires its canonical include path")
        _verify(root, _PAPER_FIGURES, payload.get("paper_figures_sha256"))
        from .simulation_table_projection_binding import verify_simulation_table_projection
        verify_simulation_table_projection(root, payload)
        _canonical_conflicts(root, payload["figure_files"])
        manifest = figure_artifact_registry.load(root / "figures", strict=True)
        if manifest.get("schema") != 1:
            raise ValueError("Simulation paper projection requires the current figure registry")
        _registration_updates(root, payload, manifest, _digest(original))
        entries = {item["id"]: item for item in manifest["figures"]}
        idea = (root / "ideas/SELECTED_IDEA.json").read_bytes()
        text, selected = _projection(root, payload, entries)
        binding = load_planned_simulation_binding(root, _digest(original), payload["figure_files"])
        planned_selected = binding is None or all(
            item["metadata"].get("paper_selected") is (item["id"] in selected)
            for item in binding.payload["figures"]
        )
        if (root / _PAPER_FIGURES).read_bytes() == text.encode("utf-8") and all(
            entries[item["id"]]["metadata"].get("paper_selected") is (item["id"] in selected)
            for item in payload["figure_files"]
        ) and planned_selected:
            return False
        _commit_projection(root, payload, original, text, selected, entries, figure_artifact_registry, idea)
    return True
