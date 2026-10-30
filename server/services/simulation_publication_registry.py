"""Register complete simulation figures and project the final bundle result."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .figure_engine import PUBLICATION_STYLE_PROFILE
from .figure_routing import recommend_figure_route
from .simulation_figure_portfolio import selected_simulation_figure_ids
from .simulation_presentation_policy import simulation_presentation_fields


def simulation_figure_production_route(record: dict[str, Any]) -> dict[str, Any]:
    """Declare the actual runtime-owned quantitative producer, not a model call."""
    if record.get("producer_kind") != "deterministic":
        raise ValueError("Simulation figures must retain their declared deterministic producer")
    return recommend_figure_route({
        "id": record["id"], "kind": "figure", "figure_nature": "quantitative",
        "producer_kind": "deterministic", "production_strategy": "deterministic_plot",
        "scientific_role": record.get("scientific_role") or record.get("role") or "result",
    })


def register_simulation_figures(
    root: Path, rendered: list[dict[str, Any]], publication_style: dict[str, Any],
    simulation_id: str, simulation_seed: str, disclosure: str,
    simulation_manifest: Path, manifest_sha256: str,
) -> list[dict[str, Any]]:
    from .figure_artifacts import figure_artifact_registry

    selected_ids = selected_simulation_figure_ids(root, rendered)
    registered: list[dict[str, Any]] = []
    for item in rendered:
        item = {**item, **simulation_presentation_fields(item)}
        outputs = dict(item["outputs"])
        source_data_path = Path(item["data"])
        source_data_relative = source_data_path.relative_to(root).as_posix()
        _, entry = figure_artifact_registry.record(
            output_dir=root / "figures",
            figure_type="matplotlib",
            description=str(item["description"]),
            output_path=str(outputs["pdf"]),
            source_path=str(item["script"]),
            metadata={
                **simulation_figure_production_route(item),
                "semantic_key": str(item["id"]),
                "producer_kind": item["producer_kind"],
                "publication_labels": item["publication_labels"],
                "scientific_role": str(item["role"]),
                "domain_asset_role": str(item["domain_asset_role"]),
                "metric_direction": str(item["metric_direction"]),
                "scientific_question": str(item["scientific_question"]),
                "claim_ids": list(item["claim_ids"]),
                "label": str(item["label"]),
                "caption": str(item["description"]),
                "intended_comparison": str(item["intended_comparison"]),
                "visual_encoding": str(item["visual_encoding"]),
                "plot_family": str(item["plot_family"]),
                "uncertainty_encoding": str(item["uncertainty_encoding"]),
                "style_profile": PUBLICATION_STYLE_PROFILE,
                "publication_style_path": "paper/PUBLICATION_STYLE.json",
                "research_family": str(publication_style.get("family") or ""),
                "study_archetype": str(
                    publication_style.get("study_archetype") or ""
                ),
                **(
                    {"analysis_subtype": str(item["analysis_subtype"])}
                    if item.get("analysis_subtype")
                    else {}
                ),
                **(
                    {"axis_field": str(item["axis_field"])}
                    if item.get("axis_field")
                    else {}
                ),
                "evidence_status": "synthetic_preview",
                "paper_selected": item["id"] in selected_ids,
                "manuscript_eligible": True,
                "submission_eligible": False,
                "provenance_kind": "deterministic_simulation_preview",
                "simulation_id": simulation_id,
                "simulation_kind": "deterministic_layout_scenario",
                "explicit_user_mode": "synthetic_preview",
                "source_data": [source_data_relative],
                "source_data_sha256": {
                    source_data_relative: _sha256_file(source_data_path),
                },
                "simulation_manifest": simulation_manifest.relative_to(root).as_posix(),
                "simulation_manifest_sha256": manifest_sha256,
                "simulation_seed": simulation_seed,
                "disclosure": disclosure,
                "rendered_variants": {
                    kind: path.relative_to(root).as_posix()
                    for kind, path in outputs.items()
                },
                "rendered_variant_sha256": {
                    kind: _sha256_file(path)
                    for kind, path in outputs.items()
                },
            },
        )
        registered.append(entry)
    return registered


def simulation_result(
    root: Path, simulation_manifest: Path, manifest_sha256: str,
    preview_table: Path, preview_figures: Path, asset_profile: dict[str, Any],
    assets: dict[str, dict[str, str]], progression_axis: str,
    progression_levels: list[int | float], configured_training_horizon: int | None,
    slice_field: str, primary_metric: str, metric_direction: str,
    registered: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "simulation_manifest": simulation_manifest.relative_to(root).as_posix(),
        "simulation_manifest_sha256": manifest_sha256,
        "synthetic_preview_table": preview_table.relative_to(root).as_posix(),
        "synthetic_preview_figures": preview_figures.relative_to(root).as_posix(),
        "asset_domain": str(asset_profile["domain"]),
        "asset_roles": [
            {
                "stable_role": str(item["completeness_role"]),
                "domain_role": str(item["domain_asset_role"]),
                "scientific_role": str(item["scientific_role"]),
                "label": str(item["label"]),
            }
            for item in assets.values()
        ],
        "progression_kind": str(
            assets["progression"]["domain_asset_role"]
        ),
        "progression_axis": progression_axis,
        "progression_contract": {
            "axis": progression_axis,
            "levels": list(progression_levels),
            "configured_training_horizon": configured_training_horizon,
            "horizon_source": (
                "execution.max_epochs"
                if configured_training_horizon is not None
                else "domain_profile"
            ),
        },
        "error_slice_kind": str(
            assets["case_analysis"]["domain_asset_role"]
        ),
        "case_analysis_axis": slice_field,
        "primary_metric": primary_metric,
        "metric_direction": metric_direction,
        "figures": registered,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
