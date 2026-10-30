"""Attach publication roles, plot grammars, and renderer routes to assets."""

from __future__ import annotations

import re
from typing import Any

from .figure_semantic_projection import project_figure_semantics
from .figure_routing import recommend_figure_route


_BRIEF_TOKEN_STOPWORDS = {
    "and", "for", "from", "into", "mechanism", "method", "model", "the",
    "this", "under", "with",
}


def route_scientific_assets(
    assets: list[dict[str, Any]],
    publication_style: dict[str, Any],
    style_path: str,
    archetype_plot_roles: dict[str, dict[str, str]],
) -> None:
    role_descriptions = {
        str(item[0]): str(item[1])
        for item in publication_style.get("figure_roles", [])
        if isinstance(item, (list, tuple)) and len(item) >= 2
    }
    plot_by_role = _plot_roles(publication_style, archetype_plot_roles)
    canonical_role = {
        "result": "main_comparison",
        "robustness": "robustness_or_error_analysis",
        "calibration": "calibration_or_efficiency",
    }
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        role = str(asset.get("scientific_role") or "")
        publication_role = canonical_role.get(role, role)
        asset["publication_role"] = publication_role
        asset["publication_role_description"] = role_descriptions.get(
            publication_role, ""
        )
        asset["recommended_plot_type"] = plot_by_role.get(
            role, plot_by_role.get(publication_role, "domain_specific")
        )
        if str(asset.get("evidence_status") or "") == "executed":
            asset["visual_encoding"] = _executed_visual_encoding(
                str(asset["recommended_plot_type"]),
                str(asset.get("visual_encoding") or "Domain-specific evidence encoding"),
            )
        asset["publication_style_path"] = style_path
        asset["research_family"] = publication_style.get("family")
        asset["study_archetype"] = publication_style.get("study_archetype")
        if asset.get("kind") == "figure":
            asset.update(recommend_figure_route(asset, publication_style))
            asset["design_brief"] = _design_brief(asset)


def _design_brief(asset: dict[str, Any]) -> dict[str, Any]:
    """Persist the small, renderer-independent brief used by every producer."""
    labels = [
        str(item.get("display_text") or "").strip()
        for item in asset.get("publication_labels") or []
        if isinstance(item, dict) and str(item.get("display_text") or "").strip()
    ]
    labels = _projection_consistent_labels(asset, labels)
    contract = asset.get("scene_contract")
    contract = contract if isinstance(contract, dict) else {}
    budget = contract.get("complexity_budget")
    budget = budget if isinstance(budget, dict) else {}
    boundary = str(asset.get("content_boundary") or "").strip()
    return {
        "schema": 1,
        "scientific_question": str(asset.get("scientific_question") or "").strip(),
        "reading_goal": str(
            asset.get("intended_comparison")
            or asset.get("visual_encoding")
            or asset.get("scientific_question")
            or ""
        ).strip(),
        "must_show": labels[:7],
        "must_not_show": [boundary] if boundary else [],
        "source_bindings": [
            str(value).strip() for value in asset.get("source_data") or []
            if str(value).strip()
        ],
        "placement": "double_column" if float(
            contract.get("target_width_fraction") or 1.0
        ) >= 0.95 else "single_column",
        "minimum_font_pt": float(
            contract.get("minimum_placed_font_pt")
            or budget.get("minimum_placed_font_pt")
            or 8.0
        ),
        "maximum_primary_objects": int(
            contract.get("maximum_primary_nodes")
            or budget.get("maximum_primary_objects")
            or 8
        ),
    }


def _brief_tokens(value: object) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) >= 3 and token not in _BRIEF_TOKEN_STOPWORDS
    }


def _projection_consistent_labels(
    asset: dict[str, Any], labels: list[str],
) -> list[str]:
    """Remove only labels that clearly name an entity projected out of this figure."""
    projection = project_figure_semantics(asset)
    excluded_ids = {
        str(identity) for identity in (projection.get("excluded") or {})
    }
    if not excluded_ids:
        return labels
    scene = asset.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    objects = [
        item for item in scene.get("objects") or [] if isinstance(item, dict)
    ]
    excluded_tokens = [
        _brief_tokens(" ".join(str(item.get(key) or "") for key in (
            "id", "label", "display_name", "source_symbol",
        )))
        for item in objects if str(item.get("id") or "") in excluded_ids
    ]
    included_tokens = [
        _brief_tokens(" ".join(str(item.get(key) or "") for key in (
            "id", "label", "display_name", "source_symbol",
        )))
        for item in objects if str(item.get("id") or "") not in excluded_ids
    ]
    retained: list[str] = []
    for label in labels:
        tokens = _brief_tokens(label)
        excluded_overlap = max(
            (len(tokens & candidate) for candidate in excluded_tokens), default=0,
        )
        included_overlap = max(
            (len(tokens & candidate) for candidate in included_tokens), default=0,
        )
        if excluded_overlap >= 2 and excluded_overlap > included_overlap:
            continue
        retained.append(label)
    return retained


def _plot_roles(
    publication_style: dict[str, Any],
    archetype_plot_roles: dict[str, dict[str, str]],
) -> dict[str, str]:
    archetype = str(publication_style.get("study_archetype") or "")
    selected = archetype_plot_roles.get(
        archetype, archetype_plot_roles["generic_empirical"]
    )
    evaluation_plot = (
        "participant_or_sample_flow"
        if archetype in {
            "observational_cohort", "diagnostic_prognostic", "intervention_trial",
            "omics_discovery", "qualitative_mixed",
        }
        else "evaluation_protocol_diagram"
    )
    return {
        "method": "editable_vector_diagram",
        "evaluation_design": evaluation_plot,
        "result": selected["result"],
        "main_comparison": selected["result"],
        "ablation": selected["ablation"],
        "robustness": selected["robustness"],
        "calibration": selected["calibration"],
    }


def _executed_visual_encoding(plot_type: str, fallback: str) -> str:
    return {
        "forest_effect": "Effect estimates with reported confidence intervals and a null reference",
        "subgroup_forest": "Subgroup estimates with confidence intervals and a null reference",
        "coefficient_plot": "Coefficient estimates with uncertainty and a null reference",
        "dot_interval": "Raw or aggregated condition estimates with uncertainty",
        "dose_response": "Response over registered dose or concentration with uncertainty",
        "replicate_distribution": "Raw replicate distribution with the group mean",
        "time_course": "Outcome over registered time points with uncertainty",
        "scaling_curve": "Quality or resource outcome over registered scale",
        "tail_latency": "Tail metric over workload or percentile",
        "tradeoff_frontier": "Registered quality-resource trade-off",
        "pathway_enrichment": "Ranked biological terms by adjusted evidence strength",
        "calibration": "Observed outcome against prediction with an ideal reference",
        "decision_curve": "Net benefit over the registered decision threshold",
        "bound_comparison": "Guarantees or bounds over the declared problem classes",
        "evidence_matrix": "Theme-by-case matrix of traceable coded evidence",
        "theme_map": "Theme relationships grounded in coded evidence",
        "case_comparison": "Case contrasts and negative-case coverage",
    }.get(plot_type, fallback)
