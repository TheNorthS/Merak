"""Collect one immutable view of paper-facing research evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .figure_artifacts import figure_artifact_registry
from .method_contract import normalize_claim_evidence_plan
from .paper_compiler import bib_manager
from .paper_evidence import (
    MetricEvidence,
    PaperEvidence,
    _collect_metrics,
    _extract_title,
    _read,
    _read_json_object,
    _read_yaml_object,
)
from .scientific_assets import scientific_asset_service


def figure_priority(item: dict[str, Any], has_metrics: bool) -> tuple[int, str]:
    metadata = dict(item.get("metadata") or {})
    role = str(metadata.get("scientific_role") or "").strip().casefold()
    status = str(metadata.get("evidence_status") or "artifact").strip().casefold()
    if status in {"placeholder", "synthetic"}:
        rank = 5
    elif has_metrics and role in {
        "result", "ablation", "robustness", "analysis", "efficiency",
        "calibration", "error_analysis", "sensitivity", "training_dynamics",
    }:
        rank = 0
    elif role == "method":
        rank = 1
    elif role in {"dataset", "qualitative"}:
        rank = 2
    else:
        rank = 3
    return rank, str(item.get("output_path") or "")


def _metrics(root: Path, asset_plan: dict[str, Any]) -> list[MetricEvidence]:
    metrics = _collect_metrics(root)
    if asset_plan.get("evidence_mode") != "secondary_analysis":
        return metrics
    records, issues, _details = scientific_asset_service.collect_secondary_records(root)
    if issues:
        return metrics
    return [
        MetricEvidence(
            name=f"{record.method}.{record.metric}", value=record.value,
            source=record.source, split=record.split,
        )
        for record in records[:40]
    ]


def collect_paper_evidence(
    project_path: str | Path, direction: str = "",
) -> PaperEvidence:
    root = Path(project_path).expanduser().resolve()
    idea = _read(root / "ideas" / "ideas.md")
    selected = _read_json_object(root / "ideas" / "SELECTED_IDEA.json")
    method = _read_json_object(root / "experiments" / "METHOD_CONTRACT.json")
    if method:
        method["claim_evidence_plan"] = normalize_claim_evidence_plan(
            method.get("claim_evidence_plan")
        )
    run_spec = _read_json_object(root / "experiments" / "RUN_SPEC.json")
    config = _read_yaml_object(root / "experiments" / "configs" / "main.yaml")
    plan = _read(root / "experiments" / "EXPERIMENT_PLAN.md") or _read(root / "EXPERIMENT_PLAN.md")
    survey = _read(root / "literature" / "survey.md")
    narrative = _read(root / "NARRATIVE_REPORT.md")
    analysis = _read(root / "experiments" / "results" / "analysis.md")
    bibliography_path = root / "literature" / "references.bib"
    bibliography = bib_manager.parse_bib_file(str(bibliography_path)) if bibliography_path.exists() else []
    asset_plan = scientific_asset_service.load(root)
    metrics = _metrics(root, asset_plan)
    has_figure_portfolio = isinstance(asset_plan.get("assets"), list)
    planned_figures = {
        str(item.get("id") or "") for item in asset_plan.get("assets") or []
        if isinstance(item, dict) and item.get("kind") == "figure"
        and str(item.get("generation_policy") or "generate") != "skip"
    }
    figures_root = root / "figures"
    if figure_artifact_registry.manifest_path(figures_root).exists():
        figure_artifact_registry.reconcile(figures_root)
    figures = [
        item for item in figure_artifact_registry.paper_ready_entries(figures_root)
        if (item.get("metadata") or {}).get("evidence_status") != "placeholder"
        and (not has_figure_portfolio or bool(planned_figures) and str(
            (item.get("metadata") or {}).get("semantic_key") or item.get("id") or ""
        ) in planned_figures)
    ]
    figures.sort(key=lambda item: figure_priority(item, bool(metrics)))
    return PaperEvidence(
        root=root,
        title=" ".join(str(selected.get("title") or "").split())[:180]
        or _extract_title(direction, idea, plan),
        direction=direction, idea_text=idea, survey_text=survey,
        narrative_text=narrative, plan_text=plan, analysis_text=analysis,
        bib_entries=bibliography, metrics=metrics, figures=figures,
        asset_plan=asset_plan, selected_idea=selected, method_contract=method,
        run_spec=run_spec, resolved_config=config,
    )
