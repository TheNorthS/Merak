"""Coordinate result planning without coupling domain selection to persistence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .planned_result_bundle import PlannedResultBundle, write_planned_result_bundle
from .planned_result_manifest import persist_planned_result_manifest
from .planned_study_contract import PlannedStudyContract, planned_study_contract
from .publication_style import publication_style_service


@dataclass(frozen=True)
class ResultPlanningRequest:
    root: Path
    direction: str
    synthetic: bool
    mode: str
    input_hash: str
    context: str
    style: dict[str, Any]
    study: PlannedStudyContract


async def ensure_planned_results(
    service: Any, project_path: str | Path, direction: str = "", *,
    evidence_mode: str = "design_only", target_venue: str = "",
    research_family: str = "", study_archetype: str = "",
) -> dict[str, Any]:
    request = _prepare(
        service, project_path, direction, evidence_mode, target_venue,
        research_family, study_archetype,
    )
    bundle = _write_bundle(service, request)
    simulation = await _simulation(service, request, bundle)
    result = _persist(request, bundle, simulation)
    from .planning_input_identity import planning_identity
    from ..utils.atomic_write import atomic_write_json
    atomic_write_json(request.root / ".merak/PLANNING_INPUTS.json", planning_identity(
        request.root, direction, evidence_mode=evidence_mode, target_venue=target_venue,
        research_family=research_family, study_archetype=study_archetype,
    ))
    return result


def _prepare(
    service: Any, project_path: str | Path, direction: str, evidence_mode: str,
    target_venue: str, research_family: str, study_archetype: str,
) -> ResultPlanningRequest:
    root = Path(project_path).expanduser().resolve()
    synthetic = str(evidence_mode or "design_only").strip().casefold() == "synthetic_preview"
    mode = "synthetic_preview" if synthetic else "design_only"
    input_hash = service.input_bundle_sha256(
        root, direction, evidence_mode=mode, target_venue=target_venue,
        research_family=research_family, study_archetype=study_archetype,
    )
    if not synthetic:
        service._clear_simulation_preview(root)
    if (root / "figures" / "FIGURE_MANIFEST.json").is_file():
        from .figure_artifacts import figure_artifact_registry
        figure_artifact_registry.reconcile(root / "figures")
    context = service._context(root, direction)
    style = publication_style_service.prepare(
        root, direction, target_venue=target_venue,
        research_family=research_family, study_archetype=study_archetype,
    )
    study = planned_study_contract(
        service._json_object(root / "ideas" / "SELECTED_IDEA.json"),
        service._json_object(root / "experiments" / "METHOD_CONTRACT.json"),
        service._yaml_object(root / "experiments" / "configs" / "main.yaml"),
        service._json_object(root / "experiments" / "RUN_SPEC.json"), style, context,
    )
    return ResultPlanningRequest(root, direction, synthetic, mode, input_hash, context, style, study)


def _write_bundle(service: Any, request: ResultPlanningRequest) -> PlannedResultBundle:
    study = request.study
    return write_planned_result_bundle(
        service, request.root, methods=study.methods, model_ids=study.model_id_by_method,
        primary_metric=study.primary_metric, metric_direction=study.metric_direction,
        secondary_metric=study.secondary_metric, calibration_metric=study.calibration_metric,
        axis=study.axis, levels=study.levels, ablation_settings=study.ablation_settings,
        registered_factors=study.registered_single_factors,
        matched_fields=list(study.method_ablation_contract.get("matched_fields", [])),
        validation_labels=study.validation_curve_labels, publication_style=request.style,
        archetype=study.archetype, analysis_rationale=study.analysis_rationale,
    )


async def _simulation(
    service: Any, request: ResultPlanningRequest, bundle: PlannedResultBundle,
) -> dict[str, Any]:
    if not request.synthetic:
        return {
            "simulation_manifest": "", "simulation_manifest_sha256": "",
            "synthetic_preview_table": "", "synthetic_preview_figures": "",
            "asset_domain": "", "asset_roles": [], "progression_kind": "",
            "progression_axis": "", "error_slice_kind": "",
            "case_analysis_axis": "", "figures": [],
        }
    study = request.study
    return await service._build_simulation_preview(
        root=request.root, publication_style=request.style,
        research_context=request.context, direction=request.direction,
        main_rows=bundle.main_rows, ablation_rows=bundle.ablation_rows,
        robustness_rows=bundle.robustness_rows, calibration_rows=bundle.calibration_rows,
        efficiency_rows=bundle.efficiency_rows, claim_ids=study.claim_ids,
        axis=study.axis, primary_metric=study.primary_metric,
        metric_direction=study.metric_direction, validation_curve_labels=study.validation_curve_labels,
    )


def _persist(
    request: ResultPlanningRequest, bundle: PlannedResultBundle, simulation: dict[str, Any],
) -> dict[str, Any]:
    study = request.study
    return persist_planned_result_manifest(
        request.root, bundle.main_csv.parent, input_bundle_sha256=request.input_hash,
        synthetic_preview=request.synthetic, effective_mode=request.mode,
        publication_style=request.style, components=study.components,
        ablation_settings=study.ablation_settings, methods=study.methods,
        primary_metric=study.primary_metric, metric_direction=study.metric_direction,
        axis=study.axis, main_csv=bundle.main_csv, ablation_csv=bundle.ablation_csv,
        robustness_csv=bundle.robustness_csv, calibration_csv=bundle.calibration_csv,
        efficiency_csv=bundle.efficiency_csv, planned_tex=bundle.planned_tex,
        analysis_rationale=study.analysis_rationale, validation_curve_labels=study.validation_curve_labels,
        resource_labels=bundle.resource_labels, simulation_result=simulation,
    )
