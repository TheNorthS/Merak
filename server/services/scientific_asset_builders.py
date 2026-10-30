"""Construct core design and result assets from normalized evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .scientific_record_models import QualitativeEvidenceRecord, ResultRecord
from .publication_figure_labels import concept_labels
from .publication_labels import publication_metric_label


def _portfolio_item(story: dict[str, Any], asset_id: str) -> dict[str, Any]:
    return next((
        dict(item) for item in story.get("figure_portfolio") or []
        if isinstance(item, dict) and item.get("asset_id") == asset_id
    ), {})


def _scene_contract(
    story: dict[str, Any], portfolio_item: dict[str, Any],
) -> dict[str, Any]:
    """Project one portfolio role into the compatible scene contract."""
    selected = dict(portfolio_item or {})
    budget = dict(
        selected.get("complexity_budget")
        or story.get("complexity_budget")
        or {}
    )
    return {
        **story,
        **selected,
        "complexity_budget": budget,
        "maximum_primary_nodes": int(
            budget.get("maximum_primary_objects")
            or story.get("maximum_primary_nodes")
            or 8
        ),
        "maximum_primary_branches": int(
            budget.get("maximum_primary_branches")
            or story.get("maximum_primary_branches")
            or 2
        ),
        "maximum_visible_labels": int(
            budget.get("maximum_visible_labels")
            or story.get("maximum_visible_labels")
            or 12
        ),
        "minimum_placed_font_pt": float(
            budget.get("minimum_placed_font_pt")
            or story.get("minimum_placed_font_pt")
            or 8.0
        ),
    }


def _method_brief(
    context: dict[str, Any], architecture: dict[str, Any],
    publication: dict[str, Any], story: dict[str, Any],
) -> dict[str, Any]:
    method_contract = context.get("method_contract")
    method_contract = method_contract if isinstance(method_contract, dict) else {}
    from .evaluation_conditions_projection import project_evaluation_conditions

    return {
        "title": context.get("title", ""), "hypothesis": context.get("hypothesis", ""),
        "models": list(context.get("models") or []), "datasets": list(context.get("datasets") or []),
        "tasks": list(context.get("tasks") or []), "study_conditions": list(context.get("adaptation_regimes") or []),
        "inputs": list(context.get("inputs") or []), "outputs": list(context.get("outputs") or []),
        "endpoints": list(context.get("endpoints") or []), "comparators": list(context.get("comparators") or []),
        "mechanism_nodes": [dict(item) for item in context.get("mechanisms") or []],
        "evaluation_contract": dict(method_contract.get("evaluation_contract") or {}),
        "evaluation_conditions": project_evaluation_conditions(method_contract, publication),
        "evaluation_protocol": _evaluation_protocol(context.get("run_spec"), context.get("config"),
            plan_bytes=context.get("experiment_plan_bytes")),
        "claim_evidence_plan": [
            dict(item) for item in method_contract.get("claim_evidence_plan") or []
            if isinstance(item, dict)
        ],
        "probe_configuration": [
            dict(item) for item in context.get("probe_configuration") or []
            if isinstance(item, dict)
        ],
        "architecture_blueprint": architecture, "publication": publication,
        "visual_story": story,
    }


def _evaluation_protocol(run_spec: Any, config: Any = None, *, plan_bytes: bytes | None = None) -> dict[str, Any]:
    """Expose only declared protocol facts needed by the public evaluation figure."""
    from .evaluation_protocol_projection import project_evaluation_protocol

    return project_evaluation_protocol(run_spec, config, plan_bytes=plan_bytes)


def _projected_mechanism_caption(asset: dict[str, Any], method_name: str) -> str:
    """Describe only authored objects/relations in this detail's actual projection."""
    from .figure_semantic_projection import project_figure_semantics

    projection = project_figure_semantics(asset)
    labels = list(dict.fromkeys(str(item.get("label") or "").strip()
        for item in projection["entities_states_transformations"] if str(item.get("label") or "").strip()))
    if not labels:
        raise ValueError("Mechanism-detail caption requires source-projected scientific objects")
    relations = list(dict.fromkeys(str(item.get("label") or "").strip()
        for item in projection["relations"] if str(item.get("label") or "").strip()))
    caption = f"{method_name}: internal transformations and operative interaction of " + "; ".join(labels) + "."
    return caption + (" Authored relations: " + "; ".join(relations) + "." if relations else "")


def _mechanism_detail_asset(
    context: dict[str, Any], architecture: dict[str, Any], publication: dict[str, Any],
    story: dict[str, Any], scene: dict[str, Any], sources: list[str], enabled: bool,
) -> dict[str, Any] | None:
    mechanisms = [dict(item) for item in context.get("mechanisms") or [] if isinstance(item, dict)]
    detail_story = _portfolio_item(story, "core_mechanism")
    if not enabled or not detail_story:
        return None
    if not mechanisms:
        raise ValueError("core_mechanism was explicitly planned without a named mechanism")
    names = [str(item.get("publication_name") or item.get("name") or "").strip() for item in mechanisms]
    names = [name for name in names if name]
    focus = names[:4]
    if not focus:
        return None
    method_name = str(publication.get("method_name") or "Proposed method")
    focus_text = ", ".join(focus)
    from .scientific_scene import plan_scientific_layout

    contract = _scene_contract(story, detail_story or {
        "narrative_level": "mechanism_detail",
        "visual_grammar": "domain_mechanism_zoom",
    })
    layout_plan = plan_scientific_layout(
        scene,
        maximum_nodes=int(contract["maximum_primary_nodes"]),
        complexity_budget=contract["complexity_budget"],
    )
    asset = {
        "id": "core_mechanism", "kind": "figure", "generation_phase": "phase_2b",
        "illustration_mode": "auto", "scientific_role": "method",
        "figure_type": str(detail_story.get("figure_type") or "mechanism_detail"),
        "narrative_level": "mechanism_detail",
        "scientific_question": f"How do {focus_text} transform and interact inside {method_name}?",
        "claim_ids": [item["id"] for item in context.get("claims", [])][:2],
        "source_data": sources, "intended_comparison": "Internal mechanism interactions and operative rule",
        "visual_encoding": "Zoomed domain-native mechanism internals with explicit transformations and merge rule",
        "uncertainty_encoding": "Not applicable to a mechanism schematic",
        "evidence_status": "implemented_design" if architecture else "planned_design",
        "manuscript_section": "Method", "label": "fig:core-mechanism",
        "required": True, "manuscript_eligible": True,
        "provenance_kind": "design_contract", "producer_kind": "model",
        "publication_labels": concept_labels(focus, namespace="method.detail", limit=4),
        "architecture_blueprint": architecture,
        "method_brief": _method_brief(context, architecture, publication, story),
        "publication_language": publication["language"], "scientific_scene": scene,
        "preferred_backend": story["preferred_backend"],
        "layout_plan": layout_plan,
        "scene_contract": {**contract, "detail_focus": focus},
    }
    asset["caption"] = _projected_mechanism_caption(asset, method_name)
    return asset


def build_core_assets(
    root: Path, context: dict[str, Any], *, records: list[ResultRecord],
    qualitative_records: list[QualitativeEvidenceRecord], evidence_mode: str,
    phase_2b_enabled: bool, architecture_blueprint: dict[str, Any],
    write_csv: Callable[[Path, list[dict[str, str]]], None],
    primary_group: Callable[[list[ResultRecord]], tuple[str, str, list[ResultRecord]]],
    comparison_count: Callable[[list[ResultRecord]], int],
    aggregate: Callable[[list[ResultRecord]], list[dict[str, str]]],
    attach_secondary: Callable[[list[dict[str, str]], list[ResultRecord], str], None],
    publication_style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    assets = design_assets(
        context, architecture_blueprint, phase_2b_enabled,
        publication_style=publication_style,
    )
    if qualitative_records:
        assets.extend(qualitative_assets(root, context, qualitative_records, write_csv))
    elif records:
        assets.extend(quantitative_assets(
            root, context, records, evidence_mode, write_csv,
            primary_group, comparison_count, aggregate, attach_secondary,
        ))
    return assets


def _design_asset_records(
    *, claims: list[str], sources: list[str], architecture: dict[str, Any],
    publication: dict[str, Any], story: dict[str, Any],
    method_figure: dict[str, Any], evaluation_figure: dict[str, Any],
    method_contract: dict[str, Any], evaluation_contract: dict[str, Any],
    method_labels: list[dict[str, Any]], evaluation_labels: list[dict[str, Any]],
    method_brief: dict[str, Any], scene: dict[str, Any],
    layout_plan: dict[str, Any], enabled: bool,
) -> list[dict[str, Any]]:
    evidence_status = "implemented_design" if architecture else "planned_design"
    method = {
        "id": "method_architecture", "kind": "figure", "generation_phase": "phase_2b",
        "illustration_mode": "auto", "scientific_role": "method",
        "figure_type": method_figure["figure_type"],
        "narrative_level": method_figure["narrative_level"],
        "scientific_question": method_figure["scientific_question"],
        "claim_ids": claims[:3], "source_data": sources,
        "intended_comparison": method_figure["visual_encoding"],
        "visual_encoding": method_figure["visual_encoding"],
        "content_boundary": method_figure["content_boundary"],
        "uncertainty_encoding": "Not applicable to a method schematic",
        "evidence_status": evidence_status,
        "manuscript_section": "Method", "label": "fig:method-architecture",
        "caption": story["caption"], "required": enabled,
        "manuscript_eligible": enabled, "provenance_kind": "design_contract",
        "producer_kind": "model", "publication_labels": method_labels,
        "architecture_blueprint": architecture, "method_brief": method_brief,
        "scene_contract": method_contract,
        "preferred_backend": story["preferred_backend"],
        "publication_language": publication["language"],
        "scientific_scene": scene, "layout_plan": layout_plan,
    }
    evaluation = {
        "id": "evaluation_design", "kind": "figure", "generation_phase": "phase_2b",
        "illustration_mode": "auto", "scientific_role": "evaluation_design",
        "figure_type": evaluation_figure["figure_type"],
        "narrative_level": evaluation_figure["narrative_level"],
        "scientific_question": evaluation_figure["scientific_question"],
        "claim_ids": claims[:3], "source_data": sources,
        "intended_comparison": evaluation_figure["visual_encoding"],
        "visual_encoding": evaluation_figure["visual_encoding"],
        "content_boundary": evaluation_figure["content_boundary"],
        "uncertainty_encoding": "Independent analysis unit and repeated-run aggregation are named",
        "evidence_status": evidence_status,
        "manuscript_section": "Experiments", "label": "fig:evaluation-design",
        "caption": _evaluation_caption(method_brief),
        "required": enabled, "manuscript_eligible": enabled,
        "provenance_kind": "design_contract", "producer_kind": "model",
        "publication_labels": evaluation_labels or concept_labels(
            ["registered comparison", "evaluation split"],
            namespace="evaluation.term", limit=2,
        ),
        "method_brief": method_brief,
        "publication_language": publication["language"],
        "scene_contract": evaluation_contract,
    }
    matrix = {
        "id": "experimental_design_matrix", "kind": "internal_table",
        "scientific_role": "internal_protocol",
        "scientific_question": "Does every claim have a decisive contrast, control, metric, and rejection rule?",
        "claim_ids": claims, "source_data": sources, "evidence_status": "planned_design",
        "manuscript_section": "", "label": "", "required": False,
        "manuscript_eligible": False,
    }
    return [method, evaluation, matrix]


def _evaluation_caption(method_brief: dict[str, Any]) -> str:
    """Keep principal comparison compact while preserving declared controls."""
    caption = (
        "Evaluation design showing declared comparisons, the evaluation split, "
        "and endpoint aggregation."
    )
    declared = method_brief.get("evaluation_conditions") or {}
    if declared.get("mode") == "declared_conditions":
        caption = ("Overview of selected declared evaluation conditions and separately declared holdouts. "
                   "It does not enumerate the complete mechanism-test family.")
        return caption + " Condition labels are shown in the diagram; the Methods and Results specify the full protocol."
    contract = method_brief.get("evaluation_contract") or {}
    controls = contract.get("comparators_or_controls") or method_brief.get("comparators") or []
    names = [str(value).strip().replace("_", " ") for value in controls if str(value).strip()]
    principal = str(contract.get("primary_comparator") or "").strip().replace("_", " ")
    if not principal:
        return caption + (" Declared conditions: " + "; ".join(names) + "." if names else "")
    focal = str(contract.get("focal_condition") or (method_brief.get("publication") or {}).get("method_name")
                or "").strip().replace("_", " ")
    secondary = [value for value in names if value not in {principal, focal}]
    if secondary:
        caption += " Additional declared controls: " + "; ".join(secondary) + "."
    return caption


def design_assets(
    context: dict[str, Any], architecture: dict[str, Any], enabled: bool,
    *, publication_style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from .scientific_asset_portfolio import (
        method_story_for_scene, publication_contribution_type,
    )
    from .scientific_scene import build_scientific_scene
    claims = [item["id"] for item in context.get("claims", [])]
    publication = dict(context.get("publication") or {})
    publication_contribution_type(publication)
    style = publication_style or {}
    scene = build_scientific_scene(context)
    story, layout_plan = method_story_for_scene(
        publication, dict(context.get("method_contract") or {}),
        list(context.get("mechanisms") or []), scene,
        research_family=str(style.get("family") or ""),
        study_archetype=str(style.get("study_archetype") or ""),
    )
    method_figure = _portfolio_item(story, "method_architecture")
    evaluation_figure = _portfolio_item(story, "evaluation_design")
    method_contract = _scene_contract(story, method_figure)
    evaluation_contract = _scene_contract(story, evaluation_figure)
    sources = context.get("source_artifacts", [])
    method_labels = concept_labels(
        (item.get("name") for item in context.get("mechanisms", [])),
        namespace="method.mechanism", limit=6,
    )
    # The evaluation figure must name the mechanism or endpoint it tests.
    # Keep broad task prose out of the compact design brief.
    focal_mechanism = next((
        item for item in context.get("mechanisms") or []
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and not any(term in str(item.get("name") or "").casefold()
                    for term in ("evaluation", "validation", "audit"))
    ), None)
    mechanism_name = str((focal_mechanism or {}).get("publication_name")
                         or (focal_mechanism or {}).get("name") or "").strip()
    from .evaluation_design_contract import (
        declared_removal_conditions, is_heldout_split,
    )

    protocol = _evaluation_protocol(context.get("run_spec"), context.get("config"),
        plan_bytes=context.get("experiment_plan_bytes"))
    method_brief = _method_brief(context, architecture, publication, story)
    neutral_conditions = bool(method_brief["evaluation_conditions"])

    evaluation_values = [
        *([mechanism_name] if mechanism_name else []),
        *(["Matched removal"] if not neutral_conditions and declared_removal_conditions(
            context.get("adaptation_regimes"),
        ) else []),
        "Held-out test" if is_heldout_split(protocol.get("primary_split"))
        else "Evaluation split",
    ]
    evaluation_labels = concept_labels(
        evaluation_values, namespace="evaluation.term", limit=3,
    )
    assets = _design_asset_records(
        claims=claims, sources=sources, architecture=architecture,
        publication=publication, story=story, method_figure=method_figure,
        evaluation_figure=evaluation_figure, method_contract=method_contract,
        evaluation_contract=evaluation_contract, method_labels=method_labels,
        evaluation_labels=evaluation_labels, method_brief=method_brief,
        scene=scene, layout_plan=layout_plan, enabled=enabled,
    )
    detail = _mechanism_detail_asset(
        context, architecture, publication, story, scene, sources, enabled,
    )
    if detail:
        assets.insert(1, detail)
    return assets

def qualitative_assets(
    root: Path, context: dict[str, Any], records: list[QualitativeEvidenceRecord],
    write_csv: Callable[[Path, list[dict[str, str]]], None],
) -> list[dict[str, Any]]:
    aggregate = root / "experiments" / "results" / "aggregates"
    matrix = aggregate / "qualitative_evidence_matrix.csv"
    write_csv(matrix, [{
        "theme": item.theme, "case": item.case, "source_id": item.source_id,
        "evidence_excerpt": item.evidence, "polarity": item.polarity,
        "coder": item.coder, "triangulation_source": item.triangulation_source,
        "source_data": item.source,
    } for item in records])
    all_cases = {item.case for item in records}
    summaries = []
    for theme in sorted({item.theme for item in records}):
        selected = [item for item in records if item.theme == theme]
        cases = {item.case for item in selected}
        summaries.append({
            "method": theme, "metric": "Case coverage", "split": "coded corpus",
            "mean": f"{len(cases) / max(1, len(all_cases)):.10g}", "std": "",
            "n": str(len(cases)), "ci95_low": "", "ci95_high": "", "theme": theme,
            "evidence_count": str(len(selected)), "case_count": str(len(cases)),
            "negative_case_count": str(sum(item.polarity.casefold() in {"negative", "contradictory", "disconfirming", "rival"} for item in selected)),
            "source_count": str(len({item.source for item in selected})),
            "source_data": ";".join(sorted({item.source for item in selected})),
        })
    summary = aggregate / "main_comparison.csv"
    write_csv(summary, summaries)
    common = {
        "kind": "figure", "scientific_role": "result",
        "producer_kind": "model",
        "publication_labels": concept_labels(
            ['Case coverage'], namespace='main_comparison', kind='metric',
        ),
        "scientific_question": "How are principal themes supported, contrasted, and triangulated across cases?",
        "claim_ids": [item["id"] for item in context.get("claims", [])][:2],
        "source_data": sorted({item.source for item in records}), "evidence_status": "executed",
        "manuscript_section": "Findings", "required": True, "manuscript_eligible": True,
        "provenance_kind": "runtime_owned", "split": "coded corpus",
    }
    assets = [
        {**common, "id": "main_comparison", "label": "fig:main-comparison",
         "data_path": matrix.relative_to(root).as_posix(),
         "intended_comparison": "Theme-by-case evidence coverage including negative cases",
         "visual_encoding": "Evidence matrix; cells count traceable coded records",
         "uncertainty_encoding": "Case coverage, coder identity, negative cases, and triangulation sources are retained"},
        {**common, "id": "main_results", "kind": "table", "label": "tab:main-results",
         "data_path": summary.relative_to(root).as_posix(), "metric": "Case coverage"},
    ]
    return assets


def quantitative_assets(
    root: Path, context: dict[str, Any], records: list[ResultRecord],
    evidence_mode: str, write_csv: Callable[[Path, list[dict[str, str]]], None],
    primary_group: Callable[[list[ResultRecord]], tuple[str, str, list[ResultRecord]]],
    comparison_count: Callable[[list[ResultRecord]], int],
    aggregate: Callable[[list[ResultRecord]], list[dict[str, str]]],
    attach_secondary: Callable[[list[dict[str, str]], list[ResultRecord], str], None],
) -> list[dict[str, Any]]:
    metric, split, selected = primary_group(records)
    if not selected or comparison_count(selected) < 2:
        return []
    rows = aggregate(selected)
    attach_secondary(rows, records, metric)
    for row in rows:
        row.update({"metric": metric, "split": split or "unspecified"})
    data_path = root / "experiments" / "results" / "aggregates" / "main_comparison.csv"
    write_csv(data_path, rows)
    common = {
        "scientific_question": "How does the measured endpoint vary across the registered conditions and analysis methods?",
        "producer_kind": "model",
        "publication_labels": concept_labels(
            [publication_metric_label(metric)], namespace='main_comparison', kind='metric',
        ),
        "claim_ids": [item["id"] for item in context.get("claims", [])][:1],
        "source_data": sorted({item.source for item in selected}),
        "data_path": data_path.relative_to(root).as_posix(), "evidence_status": "executed",
        "manuscript_section": "Results", "required": True, "manuscript_eligible": True,
        "provenance_kind": "public_secondary_source" if evidence_mode == "secondary_analysis" else "runtime_owned",
        "metric": metric, "split": split or "unspecified",
    }
    assets = [
        {**common, "id": "main_comparison", "kind": "figure", "scientific_role": "result",
         "label": "fig:main-comparison", "intended_comparison": "Proposed method versus all recorded comparison methods",
         "visual_encoding": "Point estimates with 95% confidence intervals",
         "uncertainty_encoding": "95% Student-t confidence interval across recorded runs; unavailable when n=1"},
        {**common, "id": "main_results", "kind": "table", "scientific_role": "result",
         "label": "tab:main-results"},
    ]
    assets.extend(_secondary_quantitative_assets(
        root, context, records, evidence_mode, write_csv,
        primary_group, comparison_count, aggregate, attach_secondary,
    ))
    return assets



def _secondary_quantitative_assets(
    root: Path, context: dict[str, Any], records: list[ResultRecord],
    evidence_mode: str, write_csv: Callable[[Path, list[dict[str, str]]], None],
    primary_group: Callable[[list[ResultRecord]], tuple[str, str, list[ResultRecord]]],
    comparison_count: Callable[[list[ResultRecord]], int],
    aggregate: Callable[[list[ResultRecord]], list[dict[str, str]]],
    attach_secondary: Callable[[list[dict[str, str]], list[ResultRecord], str], None],
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for role, asset_id, label in (("ablation", "component_ablation", "fig:component-ablation"), ("robustness", "robustness_sensitivity", "fig:robustness-sensitivity")):
        selected = [item for item in records if item.role == role]
        if comparison_count(selected) < 2:
            continue
        normalized = [ResultRecord(method=item.method, metric=item.metric, value=item.value, source=item.source, seed=item.seed, split=item.split, condition_name=item.condition_name, condition_value=item.condition_value, role="result", ci_low=item.ci_low, ci_high=item.ci_high) for item in selected]
        metric, split, grouped = primary_group(normalized)
        if not grouped:
            continue
        rows = aggregate(grouped)
        attach_secondary(rows, selected, metric)
        for row in rows:
            row.update({"metric": metric, "split": split or "unspecified"})
        path = root / "experiments" / "results" / "aggregates" / f"{asset_id}.csv"
        write_csv(path, rows)
        assets.append({"id": asset_id, "kind": "figure", "scientific_role": role, "scientific_question": "Is the proposed component necessary under matched comparison?" if role == "ablation" else "Does the claimed effect persist under declared stress conditions?", "claim_ids": [item["id"] for item in context.get("claims", [])][:2], "source_data": sorted({item.source for item in selected}), "data_path": path.relative_to(root).as_posix(), "intended_comparison": "Full method versus prespecified alternatives", "visual_encoding": "Point estimates with 95% confidence intervals", "uncertainty_encoding": "95% Student-t confidence interval across recorded runs; unavailable when n=1", "evidence_status": "executed", "manuscript_section": "Results", "label": label, "required": False, "manuscript_eligible": True, "provenance_kind": "public_secondary_source" if evidence_mode == "secondary_analysis" else "runtime_owned", "metric": metric, "split": split or "unspecified"})
        assets[-1].update({
            'producer_kind': 'model',
            'publication_labels': concept_labels(
                [publication_metric_label(metric)], namespace=asset_id, kind='metric',
            ),
        })
    return assets
