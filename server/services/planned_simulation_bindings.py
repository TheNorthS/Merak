"""Validate and rebind current planned-result renderer identities at the producer."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLANNED_SIMULATION_MANIFEST = "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
_SIMULATION_MANIFEST = "experiments/results/simulated/SIMULATION_MANIFEST.json"


@dataclass(frozen=True)
class PlannedSimulationBinding:
    path: Path
    original: bytes
    payload: dict[str, Any]


def load_planned_simulation_binding(
    root: Path, manifest_hash: str, records: list[dict[str, Any]],
) -> PlannedSimulationBinding | None:
    """Reject stale current top-level and embedded identities before any mutation."""
    path = root / PLANNED_SIMULATION_MANIFEST
    if not path.exists():
        return None
    original = path.read_bytes()
    payload = json.loads(original.decode("utf-8-sig"))
    if (not isinstance(payload, dict) or payload.get("schema") != 5
            or payload.get("simulation_manifest") != _SIMULATION_MANIFEST
            or payload.get("simulation_manifest_sha256") != manifest_hash):
        raise ValueError("Simulation producer refuses a stale planned-result binding")
    figures = payload.get("figures")
    if not isinstance(figures, list) or any(not isinstance(item, dict) for item in figures):
        raise ValueError("Simulation producer requires declared planned-figure bindings")
    by_id = {record["id"]: record for record in records}
    if (len(figures) != len(by_id) or {item.get("id") for item in figures} != set(by_id)):
        raise ValueError("Simulation producer requires its complete planned-figure bundle")
    for figure in figures:
        _verify_planned_figure(figure, by_id[figure["id"]], manifest_hash)
    return PlannedSimulationBinding(path, original, payload)


def _verify_planned_figure(figure: dict[str, Any], record: dict[str, Any], manifest_hash: str) -> None:
    metadata = figure.get("metadata")
    if (not isinstance(metadata, dict) or metadata.get("simulation_manifest_sha256") != manifest_hash
            or figure.get("source_path") != record["source"]
            or figure.get("source_sha256") != record["source_sha256"]
            or figure.get("output_path") != record["outputs"]["pdf"]
            or figure.get("output_sha256") != record["output_sha256"]["pdf"]):
        raise ValueError(f"{figure.get('id')}: simulation producer refuses a stale planned-figure binding")
    for field, expected in (("rendered_variants", record["outputs"]),
                            ("rendered_variant_sha256", record["output_sha256"])):
        if field in metadata and metadata[field] != expected:
            raise ValueError(f"{figure['id']}: planned simulation variants conflict with their source")


def rebind_planned_simulation(
    binding: PlannedSimulationBinding, records: list[dict[str, Any]], manifest_hash: str,
    *, selected_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Project verified producer hashes only; never rewrite scientific input fields."""
    if binding.path.read_bytes() != binding.original:
        raise RuntimeError("Planned simulation bundle changed during producer refresh")
    payload = copy.deepcopy(binding.payload)
    by_id = {record["id"]: record for record in records}
    if set(by_id) != {figure["id"] for figure in payload["figures"]}:
        raise ValueError("Simulation producer may not change the complete evidence portfolio")
    payload["simulation_manifest_sha256"] = manifest_hash
    for figure in payload["figures"]:
        record = by_id[figure["id"]]
        figure["source_sha256"] = record["source_sha256"]
        figure["output_sha256"] = record["output_sha256"]["pdf"]
        metadata = figure["metadata"]
        metadata["simulation_manifest_sha256"] = manifest_hash
        for field, expected in (("rendered_variants", record["outputs"]),
                                ("rendered_variant_sha256", record["output_sha256"])):
            if field in metadata:
                metadata[field] = copy.deepcopy(expected)
        if selected_ids is not None:
            metadata["paper_selected"] = figure["id"] in selected_ids
    return payload
