"""Render simulation figures and bind them to paper projections and claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..utils.atomic_write import atomic_write_text
from .simulation_figure_portfolio import selected_simulation_figures
from .simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA,
    SIMULATION_RENDERER_VERSION,
    simulation_manifest_contract_issues,
)


async def render_simulation_bundle(
    *, root: Path, render_specs: list[dict[str, Any]], metric_direction: str,
    render_script: Callable[[Path], Awaitable[tuple[bool, str]]],
    simulation_tables: Callable[..., str], figures_tex: Callable[..., str],
    simulated_main: list[dict[str, str]], simulated_ablation: list[dict[str, str]],
    simulated_robustness: list[dict[str, str]],
    simulated_calibration: list[dict[str, str]],
    simulated_efficiency: list[dict[str, str]],
    simulated_case_analysis: list[dict[str, str]],
    claim_evidence_rows: list[dict[str, str]], paired_rows: list[dict[str, str]],
    axis: str, metric_label: str, asset_profile: dict[str, Any],
    claim_ids: list[str], table_dir: Path,
) -> tuple[list[dict[str, Any]], Path, Path, dict[str, Any]]:
    contribution = str(asset_profile.get("contribution_type") or "")
    selected_simulation_figures(render_specs, contribution)
    previous = _previous_manifest(root)
    rendered = []
    for spec in render_specs:
        rendered.append(await _render_one(
            root, spec, metric_direction, render_script, previous,
        ))
    preview_table = table_dir / "synthetic_preview_results.tex"
    preview_figures = root / "paper" / "synthetic_preview_figures.tex"
    atomic_write_text(preview_table, simulation_tables(
        simulated_main, simulated_ablation, simulated_robustness,
        simulated_calibration, simulated_efficiency, simulated_case_analysis,
        claim_evidence_rows, paired_rows, axis, metric_label, asset_profile,
        metric_direction,
    ))
    atomic_write_text(preview_figures, figures_tex(
        selected_simulation_figures(rendered, contribution),
    ))
    claim_map = _claim_evidence_map(
        root, claim_ids, rendered, claim_evidence_rows, preview_table,
    )
    return rendered, preview_table, preview_figures, claim_map


async def _render_one(
    root: Path, spec: dict[str, Any], metric_direction: str,
    render_script: Callable[[Path], Awaitable[tuple[bool, str]]],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    spec["metric_direction"] = (
        "minimize" if spec["id"] in {
            "synthetic_preview_error_analysis", "synthetic_preview_calibration",
        } else metric_direction
    )
    script = Path(spec["script"])
    outputs = {
        suffix[1:]: script.with_name(f"{spec['stem']}{suffix}")
        for suffix in (".pdf", ".svg", ".png")
    }
    if _can_reuse(root, spec, script, outputs, previous):
        return {**spec, "outputs": outputs}
    atomic_write_text(script, str(spec["code"]))
    success, error = await render_script(script)
    if not success:
        raise RuntimeError(f"Synthetic preview rendering failed for {spec['id']}: {error}")
    if any(not path.is_file() or path.stat().st_size == 0 for path in outputs.values()):
        raise RuntimeError(f"Synthetic preview output is incomplete for {spec['id']}")
    return {**spec, "outputs": outputs}


def _previous_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (payload.get("schema") != SIMULATION_MANIFEST_SCHEMA
            or payload.get("renderer_version") != SIMULATION_RENDERER_VERSION):
        return None
    try:
        issues = simulation_manifest_contract_issues(payload)
    except (KeyError, TypeError, ValueError):
        return None
    if issues:
        return None
    return payload


def _can_reuse(
    root: Path, spec: dict[str, Any], script: Path,
    outputs: dict[str, Path], previous: dict[str, Any] | None,
) -> bool:
    """Reuse only a current, source/data/output hash-bound figure."""
    if previous is None:
        return False
    entries = [item for item in previous.get("figure_files") or []
               if isinstance(item, dict) and item.get("id") == spec["id"]]
    if len(entries) != 1:
        return False
    item = entries[0]
    output_hashes = item.get("output_sha256")
    if not isinstance(output_hashes, dict):
        return False
    data = Path(spec["data"])
    try:
        data_path = data.relative_to(root).as_posix()
        source_path = script.relative_to(root).as_posix()
        expected_paths = {kind: path.relative_to(root).as_posix()
                          for kind, path in outputs.items()}
        data_entries = [record for record in previous.get("data_files") or []
                        if isinstance(record, dict) and record.get("path") == data_path]
        if len(data_entries) != 1 or item.get("source") != source_path:
            return False
        if item.get("outputs") != expected_paths:
            return False
        if _sha256_file(data) != data_entries[0].get("sha256"):
            return False
        source_digest = hashlib.sha256(str(spec["code"]).encode("utf-8")).hexdigest()
        if source_digest != item.get("source_sha256") or _sha256_file(script) != source_digest:
            return False
        return all(
            path.is_file() and path.stat().st_size > 0
            and _sha256_file(path) == output_hashes.get(kind)
            for kind, path in outputs.items()
        )
    except (OSError, ValueError, TypeError):
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _claim_evidence_map(
    root: Path, claim_ids: list[str], rendered: list[dict[str, Any]],
    evidence_rows: list[dict[str, str]], preview_table: Path,
) -> dict[str, Any]:
    shared = [
        "experiments/results/simulated/claim_evidence.csv",
        "experiments/results/simulated/run_level_results.csv",
        "experiments/results/simulated/paired_comparisons.csv",
        "experiments/results/simulated/run_ledger.csv",
        "experiments/results/simulated/latency_samples.csv",
        "experiments/results/simulated/registered_axis_results.csv",
        "experiments/results/simulated/provenance_join_audit.csv",
        "experiments/results/simulated/runtime_artifacts.json",
    ]
    return {claim_id: {
        "figure_ids": [str(item["id"]) for item in rendered if claim_id in item["claim_ids"]],
        "data_files": [
            Path(item["data"]).relative_to(root).as_posix()
            for item in rendered if claim_id in item["claim_ids"]
        ] + shared,
        "required_outcomes": [
            row["registered_outcome"] for row in evidence_rows
            if row["claim_id"] == claim_id
        ],
        "evidence_row_ids": [
            row["row_id"] for row in evidence_rows if row["claim_id"] == claim_id
        ],
        "table": preview_table.relative_to(root).as_posix(),
        "manuscript_section": "Results",
    } for claim_id in claim_ids}
