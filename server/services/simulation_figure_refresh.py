"""Refresh trusted comparison rendering without regenerating simulation evidence.

Only the canonical primary-comparison producer is eligible. Existing scientific
rows and bundle identities remain byte-for-byte unchanged; staging must pass the
same raster geometry checks before source, variants and hash manifests commit.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, atomic_write_text
from .simulation_artifact_io import render_simulation_script
from .simulation_comparison_plots import _multitask_matrix_script
from .simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION,
    simulation_manifest_contract_issues,
)
from .planned_simulation_bindings import (
    PlannedSimulationBinding, load_planned_simulation_binding, rebind_planned_simulation,
)


_PRIMARY_ID = "synthetic_preview_main_comparison"
_PRIMARY_STEM = "simulated_main_comparison"
_MANIFEST = "experiments/results/simulated/SIMULATION_MANIFEST.json"
RenderScript = Callable[[Path], Awaitable[tuple[bool, str]]]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(root: Path, value: Any) -> Path:
    path = (root / str(value)).resolve()
    if not path.is_relative_to(root) or not str(value):
        raise ValueError("Simulation figure refresh path escapes its project")
    return path


def _load_current(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads((root / _MANIFEST).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or (
        payload.get("schema") != SIMULATION_MANIFEST_SCHEMA
        or payload.get("renderer_version") != SIMULATION_RENDERER_VERSION
    ):
        raise ValueError("Simulation rendering refresh requires the current bundle schema")
    issues = simulation_manifest_contract_issues(payload)
    if issues:
        raise ValueError("Simulation rendering refresh contract failed: " + "; ".join(issues[:8]))
    data_paths = [str(item.get("path") or "") for item in payload["data_files"]]
    figure_ids = [str(item.get("id") or "") for item in payload["figure_files"]]
    if len(set(data_paths)) != len(data_paths) or len(set(figure_ids)) != len(figure_ids):
        raise ValueError("Simulation rendering refresh refuses duplicate paths or figure identifiers")
    for record in payload["data_files"]:
        path = _inside(root, record["path"])
        if not path.is_file() or _digest(path) != record.get("sha256"):
            raise ValueError(f"Simulation rendering refresh data hash mismatch: {record['path']}")
    for record in payload["figure_files"]:
        _verify_figure_files(root, record)
    records = [item for item in payload["figure_files"] if item.get("id") == _PRIMARY_ID]
    if len(records) != 1:
        raise ValueError("Simulation rendering refresh needs one primary comparison")
    return payload, records[0]


def _verify_figure_files(root: Path, record: dict[str, Any]) -> None:
    if not isinstance(record.get("outputs"), dict) or not {
        "pdf", "svg", "png",
    } <= record["outputs"].keys():
        raise ValueError("Simulation figure refresh requires all three canonical variants")
    files = [(record.get("source"), record.get("source_sha256")),
             *((path, (record.get("output_sha256") or {}).get(kind))
               for kind, path in (record.get("outputs") or {}).items())]
    for relative, expected in files:
        path = _inside(root, relative)
        if not path.is_relative_to(root / "figures/simulated"):
            raise ValueError("Simulation figure refresh file is outside its canonical directory")
        if not path.is_file() or not expected or _digest(path) != expected:
            raise ValueError(f"Simulation figure refresh file hash mismatch: {relative}")


def _primary_input(root: Path, payload: dict[str, Any], record: dict[str, Any]) -> tuple[Path, str]:
    profile = next(item for item in payload["domain_asset_profile"]
                   if item.get("semantic_id") == _PRIMARY_ID)
    relative = f"experiments/results/simulated/{profile['data_file']}"
    declared = {item["path"] for item in payload["data_files"]}
    if relative not in declared or profile.get("analysis_subtype") != "cross_dataset_task_matrix":
        raise ValueError("Simulation comparison refresh input is not a declared task matrix")
    source = f"figures/simulated/{_PRIMARY_STEM}.py"
    expected = {kind: f"figures/simulated/{_PRIMARY_STEM}.{kind}"
                for kind in ("pdf", "svg", "png")}
    if record.get("source") != source or record.get("outputs") != expected:
        raise ValueError("Simulation comparison refresh source or variants are not canonical")
    if _digest(root / source) != record.get("source_sha256"):
        raise ValueError("Simulation comparison refresh source hash mismatch")
    return _inside(root, relative), source


def _commit(
    root: Path, stage: Path, payload: dict[str, Any], record: dict[str, Any],
    original_manifest: bytes, code: str, planned: PlannedSimulationBinding | None,
) -> None:
    from .figure_artifacts import figure_artifact_registry

    manifest_path = root / _MANIFEST
    if manifest_path.read_bytes() != original_manifest:
        raise RuntimeError("Simulation bundle changed during rendering refresh")
    for data in payload["data_files"]:
        if _digest(_inside(root, data["path"])) != data["sha256"]:
            raise RuntimeError("Simulation data changed during rendering refresh")
    registry = _verified_registration(root, payload, _digest(manifest_path))
    records = {item["id"]: item for item in payload["figure_files"]}
    existing = {item["id"]: item for item in registry["figures"] if item.get("id") in records}
    if set(existing) != set(records):
        raise ValueError("Simulation rendering refresh requires its complete registered figure bundle")
    if planned is not None and planned.path.read_bytes() != planned.original:
        raise RuntimeError("Planned simulation bundle changed during rendering refresh")
    targets = [root / record["source"], *(root / path for path in record["outputs"].values()),
               manifest_path, root / "figures/FIGURE_MANIFEST.json",
               root / "figures/FIGURE_MANIFEST.md"]
    if planned is not None:
        targets.append(planned.path)
    before = {path: path.read_bytes() if path.is_file() else None for path in targets}
    try:
        for relative in (record["source"], *record["outputs"].values()):
            atomic_write_bytes(root / relative, (stage / relative).read_bytes())
        record["source_sha256"] = _digest(root / record["source"])
        record["render_code_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
        record["output_sha256"] = {kind: _digest(root / relative)
                                   for kind, relative in record["outputs"].items()}
        from .paper_artifacts import simulation_manifest_semantic_hash

        if simulation_manifest_semantic_hash(payload) != simulation_manifest_semantic_hash(json.loads(original_manifest)):
            raise RuntimeError("Simulation rendering refresh must preserve scientific identity")
        atomic_write_json(manifest_path, payload)
        _register_current(root, payload, existing, figure_artifact_registry)
        if planned is not None:
            atomic_write_json(planned.path, rebind_planned_simulation(
                planned, payload["figure_files"], _digest(manifest_path),
            ))
    except BaseException:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, content)
        raise


def _register_current(root: Path, payload: dict[str, Any], existing: dict, registry: Any) -> None:
    from .simulation_presentation_policy import simulation_presentation_fields
    manifest_hash = _digest(root / _MANIFEST)
    for record in payload["figure_files"]:
        entry = existing[record["id"]]
        metadata = {**dict(entry.get("metadata") or {}), "simulation_manifest_sha256": manifest_hash,
                    "rendered_variants": record["outputs"],
                    "rendered_variant_sha256": record["output_sha256"]}
        from .simulation_publication_attestation import _attested_registration_route

        metadata.update(_attested_registration_route(record, metadata))
        metadata.update(simulation_presentation_fields(metadata))
        registry.record(
            output_dir=root / "figures", figure_type="matplotlib",
            description=simulation_presentation_fields(entry)["description"], output_path=str(root / record["outputs"]["pdf"]),
            source_path=str(root / record["source"]), metadata=metadata,
        )


def _verified_registration(root: Path, payload: dict[str, Any], manifest_hash: str) -> dict[str, Any]:
    from .figure_artifacts import figure_artifact_registry
    from .simulation_publication_attestation import _canonical_conflicts, _registration_updates

    registry = figure_artifact_registry.load(root / "figures", strict=True)
    if registry.get("schema") != 1:
        raise ValueError("Simulation rendering refresh requires the current figure registry")
    _canonical_conflicts(root, payload["figure_files"])
    _registration_updates(root, payload, registry, manifest_hash)
    return registry


async def _refresh_primary_comparison(
    root: Path, *, render_script: RenderScript = render_simulation_script,
) -> list[str]:
    """Refresh changed canonical comparison code; never generate or alter data.

    Missing bundles are not handled here. Invalid, modified or unsupported
    evidence fails closed. The caller owns workflow authorization and must
    revalidate any accepted snapshot affected by updated renderer provenance.
    """
    from .figure_artifacts import figure_artifact_registry
    from .publication_labels import publication_metric_label

    root = root.resolve()
    manifest_path = root / _MANIFEST
    if not manifest_path.is_file():
        return []
    original = manifest_path.read_bytes()
    payload, record = _load_current(root)
    planned = load_planned_simulation_binding(root, _digest(manifest_path), payload["figure_files"])
    _verified_registration(root, payload, _digest(manifest_path))
    if payload.get("specialized_domain") not in {"eeg", "vision", "language", "timeseries"}:
        return []
    data, source_relative = _primary_input(root, payload, record)
    style = json.loads((root / "paper/PUBLICATION_STYLE.json").read_text(encoding="utf-8-sig"))
    code = _multitask_matrix_script(
        data.relative_to(root).as_posix(), publication_metric_label(payload["primary_metric"]),
        _PRIMARY_STEM, style, payload["metric_direction"],
    )
    if (root / source_relative).read_bytes() == code.encode("utf-8"):
        from .simulation_publication_attestation import attest_existing_simulation_figures

        return attest_existing_simulation_figures(root)
    transactions = root / ".merak/transactions"
    transactions.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="simulation-render-", dir=transactions) as directory:
        stage = Path(directory)
        stage_data = stage / data.relative_to(root)
        stage_data.parent.mkdir(parents=True)
        shutil.copy2(data, stage_data)
        script = stage / source_relative
        atomic_write_text(script, code)
        success, error = await render_script(script)
        if not success:
            raise RuntimeError("Simulation comparison rendering refresh failed: " + error)
        if any(not (stage / path).is_file() or not (stage / path).stat().st_size
               for path in record["outputs"].values()):
            raise RuntimeError("Simulation comparison rendering refresh produced incomplete variants")
        png = script.with_suffix(".png")
        issues = [*figure_artifact_registry.raster_visual_quality_issues(png),
                  *figure_artifact_registry.raster_layout_issues(png)]
        from PIL import Image

        with Image.open(png) as image:
            width, height = image.size
        if width < 1000 or height < 450:
            issues.append("Simulation comparison refresh preview is too small")
        if not 0.7 <= width / max(1, height) <= 4.2:
            issues.append("Simulation comparison refresh has an extreme aspect ratio")
        if issues:
            raise ValueError("Simulation comparison rendering refresh rejected: " + "; ".join(issues))
        _commit(root, stage, payload, record, original, code, planned)
    return [_PRIMARY_ID]


async def refresh_existing_simulation_figures(
    root: Path, *, render_script: RenderScript = render_simulation_script,
) -> list[str]:
    """Refresh trusted plots from frozen rows with per-asset atomic publication."""
    from .simulation_plot_layout_refresh import refresh_cropped_plot_labels

    changed = await _refresh_primary_comparison(root, render_script=render_script)
    return list(dict.fromkeys([*changed, *await refresh_cropped_plot_labels(root, render_script)]))
