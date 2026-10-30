"""Coordinate evidence selection, asset construction, routing, and persistence."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, path_lock
from .figure_routing import normalize_illustration_mode
from .publication_style import publication_style_service
from .scientific_record_models import ResultRecord


def build_asset_plan(
    service: Any, project_path: str | Path, *, experiment_requested: bool,
    requested_evidence_mode: str, illustration_mode: str, direction: str,
    target_venue: str, research_family: str, study_archetype: str,
    archetype_plot_roles: dict[str, dict[str, str]],
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    style = _publication_style(
        root, direction, target_venue, research_family, study_archetype
    )
    style_path = (
        "paper/PUBLICATION_STYLE.json"
        if (root / "paper" / "PUBLICATION_STYLE.json").is_file() else ""
    )
    context = service._contract_context(root)
    requested_mode = str(requested_evidence_mode or "").strip().casefold()
    evidence = _select_evidence(
        service, root, style, experiment_requested, requested_mode
    )
    phase_mode = normalize_illustration_mode(illustration_mode)
    architecture = dict(context.get("architecture_blueprint") or {})
    if evidence["mode"] == "synthetic_preview":
        _mark_simulation_verified_architecture(architecture)
    from .scientific_asset_builders import build_core_assets

    assets = build_core_assets(
        root, context, records=evidence["records"],
        qualitative_records=evidence["qualitative_records"],
        evidence_mode=evidence["mode"], phase_2b_enabled=phase_mode != "false",
        architecture_blueprint=architecture,
        write_csv=service._write_csv, primary_group=service._primary_group,
        comparison_count=service._comparison_unit_count,
        aggregate=service._aggregate,
        attach_secondary=service._attach_secondary_measure,
        publication_style=style,
    )
    _append_and_route(
        root, assets, context, evidence["mode"], style, style_path,
        archetype_plot_roles,
    )
    missing = _missing_requirements(
        experiment_requested, evidence, assets
    )
    payload = _plan_payload(
        context, style, style_path, evidence, assets, missing,
        requested_mode, experiment_requested, phase_mode,
    )
    return _persist_plan(service, root, payload)


def _publication_style(
    root: Path, direction: str, target_venue: str,
    research_family: str, study_archetype: str,
) -> dict[str, Any]:
    style = publication_style_service.load(root)
    requested_venue = str(target_venue or "unspecified")
    mismatch = bool(
        not style
        or str(style.get("target_venue") or "unspecified") != requested_venue
        or (research_family and research_family != "auto"
            and style.get("family") != research_family)
        or (study_archetype and study_archetype != "auto"
            and style.get("study_archetype") != study_archetype)
    )
    if mismatch:
        style = publication_style_service.build(
            context=publication_style_service.context(root, direction),
            target_venue=target_venue, research_family=research_family,
            study_archetype=study_archetype,
        )
    return style


def _select_evidence(
    service: Any, root: Path, style: dict[str, Any],
    experiment_requested: bool, requested_mode: str,
) -> dict[str, Any]:
    runtime = service.collect_records(root)
    qualitative = service.collect_qualitative_records(root)
    qualitative_applicable = (
        str(style.get("study_archetype") or "") == "qualitative_mixed"
        or str(style.get("family") or "") == "qualitative_humanities"
    )
    secondary: list[ResultRecord] = []
    issues: list[str] = []
    sources: list[str] = []
    if not experiment_requested and requested_mode == "secondary_analysis":
        secondary, issues, sources = service.collect_secondary_records(root)
    if experiment_requested and (runtime or qualitative_applicable and qualitative):
        return _evidence("executed", runtime, qualitative if qualitative_applicable else [], issues, sources)
    if experiment_requested:
        return _evidence("execution_pending", [], [], issues, sources)
    if requested_mode == "existing_results" and (runtime or qualitative_applicable and qualitative):
        return _evidence("existing_results", runtime, qualitative if qualitative_applicable else [], issues, sources)
    if requested_mode == "secondary_analysis" and secondary and not issues:
        return _evidence("secondary_analysis", secondary, [], issues, sources)
    if requested_mode in {"synthetic_preview", "existing_results", "secondary_analysis"}:
        return _evidence(requested_mode, [], [], issues, sources)
    return _evidence("design_only", [], [], issues, sources)


def _evidence(
    mode: str, records: list[ResultRecord], qualitative: list[Any],
    issues: list[str], sources: list[str],
) -> dict[str, Any]:
    eligible = bool(
        mode in {"executed", "existing_results", "secondary_analysis"}
        and (records or qualitative) and not issues
    )
    return {
        "mode": mode, "records": records,
        "qualitative_records": qualitative, "secondary_issues": issues,
        "secondary_sources": sources, "submission_eligible": eligible,
    }


def _append_and_route(
    root: Path, assets: list[dict[str, Any]], context: dict[str, Any],
    mode: str, style: dict[str, Any], style_path: str,
    plot_roles: dict[str, dict[str, str]],
) -> None:
    if mode == "synthetic_preview":
        from .scientific_simulation_assets import append_simulation_assets

        append_simulation_assets(
            root, assets, [item["id"] for item in context["claims"]]
        )
    from .scientific_asset_routing import route_scientific_assets

    route_scientific_assets(assets, style, style_path, plot_roles)


def _mark_simulation_verified_architecture(architecture: dict[str, Any]) -> None:
    if not architecture:
        return
    family = str(architecture.get("implementation_family") or "")
    name = {
        "machine_learning": "model_architecture",
        "formal_verification": "formal_reasoning_architecture",
        "external_protocol": "protocol_analysis_architecture",
        "computational_general": "computational_method_architecture",
    }.get(family, "scientific_method_architecture")
    architecture["diagram_kind"] = f"simulation_verified_{name}"
    architecture["implementation_status"] = "simulation_verified"
    architecture["completeness_issues"] = [
        issue for issue in architecture.get("completeness_issues") or []
        if "runtime implementation check" not in str(issue).casefold()
        and "runtime training check" not in str(issue).casefold()
    ]


def _missing_requirements(
    experiment_requested: bool, evidence: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[str]:
    mode, records = evidence["mode"], evidence["records"]
    qualitative = evidence["qualitative_records"]
    missing = []
    if experiment_requested and mode != "executed":
        missing.append("No current metric file is hash-linked to a successful experiment execution event.")
    if mode == "existing_results" and not (records or qualitative):
        missing.append("Existing-results mode requires hash-verified runtime-owned scientific evidence artifacts.")
    if mode == "secondary_analysis" and not records:
        missing.append("Secondary-analysis mode requires source-cited, hash-verified imported result artifacts.")
    if mode == "secondary_analysis":
        missing.extend(evidence["secondary_issues"])
    if mode == "executed" and not any(item.get("id") == "main_comparison" for item in assets):
        missing.append("Executed evidence does not contain a valid primary comparison or a traceable qualitative evidence matrix.")
    return missing


def _plan_payload(
    context: dict[str, Any], style: dict[str, Any], style_path: str,
    evidence: dict[str, Any], assets: list[dict[str, Any]], missing: list[str],
    requested_mode: str, experiment_requested: bool, phase_mode: str,
) -> dict[str, Any]:
    records = evidence["records"]
    return {
        "schema": 2, "generated_at": time.time(), "evidence_mode": evidence["mode"],
        "requested_evidence_mode": requested_mode or ("executed" if experiment_requested else "design_only"),
        "illustration_mode": phase_mode,
        "quantitative_figure_policy": "real_metrics_only" if records else "complete_benchmark" if evidence["mode"] == "synthetic_preview" else "skip_without_real_metrics",
        "submission_eligible": evidence["submission_eligible"],
        "manuscript_eligible": evidence["mode"] == "synthetic_preview" or evidence["submission_eligible"],
        "secondary_sources": evidence["secondary_sources"],
        "experiment_requested": bool(experiment_requested),
        "publication_style": _style_summary(style, style_path),
        "publication_style_contract": style, "selected_idea": context["title"],
        "hypothesis": context["hypothesis"], "claims": context["claims"],
        "mechanisms": context["mechanisms"],
        "falsification_conditions": context["falsification"],
        "figure_portfolio": [{
            key: item.get(key) for key in (
                "id", "figure_type", "scientific_role", "narrative_level",
                "scientific_question", "content_boundary", "figure_nature",
                "production_strategy", "producer_kind", "composition_owner",
                "full_svg_authority", "recommended_backend",
            )
        } for item in assets if (
            isinstance(item, dict)
            and item.get("kind") == "figure"
            and item.get("generation_phase") == "phase_2b"
        )],
        "record_count": len(records),
        "qualitative_record_count": len(evidence["qualitative_records"]),
        "missing_requirements": missing, "assets": assets,
    }


def _style_summary(style: dict[str, Any], path: str) -> dict[str, Any]:
    keys = (
        "schema_version", "family", "family_label", "study_archetype",
        "implementation_family", "target_venue", "visual_standard",
        "reporting_standards", "required_evidence", "domain_evidence_contract",
    )
    return {"path": path, **{key: style.get(key, [] if key in {"reporting_standards", "required_evidence"} else {}) for key in keys}}


def _persist_plan(service: Any, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    from .scientific_assets import _json

    path = root / service.plan_relative_path
    with path_lock(path):
        existing = _json(path)
        old = {key: value for key, value in existing.items() if key != "generated_at"}
        new = {key: value for key, value in payload.items() if key != "generated_at"}
        if existing and old == new:
            return existing
        atomic_write_json(path, payload)
        return payload
