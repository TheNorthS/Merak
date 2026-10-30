"""Question-driven scientific figure portfolios independent of research domain.

The planner deliberately chooses a *set* of figures before any renderer is
selected. Stable artifact ids are retained for workflow compatibility, while
``figure_type`` and ``narrative_level`` tell the author what scientific job
each figure owns. This keeps method, evaluation, and evidence questions out of
one overloaded schematic.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_COMPLEXITY_BUDGET: dict[str, Any] = {
    "maximum_scientific_questions": 1,
    "maximum_primary_objects": 8,
    "maximum_primary_branches": 2,
    "maximum_visible_labels": 12,
    "maximum_label_words": 6,
    "minimum_placed_font_pt": 8.0,
    "overflow_action": "split",
    "caption_owns": [
        "statistical detail",
        "limitations",
        "provenance detail",
        "secondary implementation detail",
    ],
}


_PRIMARY_FIGURES = {
    "model_architecture": (
        "How do the proposed internal computations transform inputs into outputs?",
        "computational_architecture", "Core computation and information flow",
    ),
    "objective_mechanism": (
        "How do the proposed objectives interact, conflict, or cooperate?",
        "mechanism_interaction", "Shared computation and named objective branches",
    ),
    "experimental_protocol": (
        "How does the intervention and control protocol isolate the claimed effect?",
        "controlled_protocol", "Intervention, control, measurement, and outcome flow",
    ),
    "system_architecture": (
        "How do system components exchange state, work, and feedback?",
        "system_topology", "System topology and operational data flow",
    ),
    "dataset_benchmark": (
        "How are data, tasks, partitions, and comparisons organized?",
        "benchmark_landscape", "Benchmark composition and comparison structure",
    ),
    "empirical_discovery": (
        "How are observations transformed into the reported scientific finding?",
        "evidence_pipeline", "Observation, analysis, and validation chain",
    ),
    "theory_proof": (
        "Which assumptions and constructions lead to the principal result?",
        "logical_dependency", "Assumption, construction, and conclusion structure",
    ),
    "clinical_biological_mechanism": (
        "How do samples, interventions, biological processes, and outcomes connect?",
        "biological_mechanism", "Cohort or specimen flow and mechanistic readouts",
    ),
    "qualitative_framework": (
        "How do sampling, coding, interpretation, and triangulation support the themes?",
        "qualitative_evidence", "Sampling, coding, negative cases, and triangulation",
    ),
}


_PRIMARY_TYPES = {
    "model_architecture": "method_architecture",
    "objective_mechanism": "shared_objective_architecture",
    "experimental_protocol": "controlled_protocol_overview",
    "system_architecture": "component_dataflow",
    "dataset_benchmark": "benchmark_landscape",
    "empirical_discovery": "evidence_pipeline",
    "theory_proof": "proof_dependency",
    "clinical_biological_mechanism": "cohort_specimen_mechanism",
    "qualitative_framework": "coding_interpretation_pipeline",
}


_DETAIL_TYPES = {
    "model_architecture": "computational_mechanism",
    "objective_mechanism": "objective_interaction",
    "system_architecture": "operational_mechanism",
    "theory_proof": "proof_construction",
    "clinical_biological_mechanism": "biological_mechanism",
}


_EVALUATION_TYPES = {
    "model_architecture": "matched_model_evaluation",
    "objective_mechanism": "mechanism_ablation_protocol",
    "experimental_protocol": "registered_decision_protocol",
    "system_architecture": "deployment_testbed_protocol",
    "dataset_benchmark": "benchmark_comparison_protocol",
    "empirical_discovery": "validation_and_alternative_explanations",
    "theory_proof": "verification_and_counterexample_design",
    "clinical_biological_mechanism": "endpoint_and_external_validation",
    "qualitative_framework": "triangulation_and_negative_case_audit",
}


_EVALUATION_QUESTIONS = {
    "model_architecture": "Which held-out comparisons establish that the proposed computation improves the registered endpoints?",
    "objective_mechanism": "Which matched removals and held-out tests distinguish the named mechanisms from alternative explanations?",
    "experimental_protocol": "Which allocation, controls, measurements, and decision rules make the hypothesis test decisive?",
    "system_architecture": "Which workloads, configurations, and resource endpoints test the system under matched conditions?",
    "dataset_benchmark": "Which partitions, tasks, metrics, and aggregation rules make benchmark comparisons valid?",
    "empirical_discovery": "Which validation, sensitivity, and alternative-explanation checks support the reported finding?",
    "theory_proof": "Which proof obligations, counterexamples, and assumption checks validate the principal result?",
    "clinical_biological_mechanism": "Which cohort flow, endpoints, subgroups, and external checks make the conclusion clinically decisive?",
    "qualitative_framework": "Which sampling, coding, negative-case, and triangulation checks support the interpretation?",
}


_ARCHETYPE_EVALUATION_TYPES = {
    "algorithm_benchmark": "held_out_comparison_protocol",
    "observational_cohort": "cohort_flow_and_sensitivity",
    "diagnostic_prognostic": "development_external_validation_flow",
    "intervention_trial": "allocation_participant_endpoint_flow",
    "omics_discovery": "specimen_qc_discovery_validation_flow",
    "controlled_experiment": "specimen_intervention_readout_flow",
    "systems_testbed": "workload_configuration_measurement_flow",
    "simulation_modeling": "assumption_solver_verification_validation_flow",
    "formal_theory": "assumption_obligation_counterexample_flow",
    "qualitative_mixed": "sampling_coding_triangulation_flow",
    "generic_empirical": "held_out_validation_protocol",
}


_CONCEPTUAL_PRODUCTION = {
    "figure_nature": "conceptual",
    "production_strategy": "deterministic_architecture",
    "producer_kind": "deterministic",
    "composition_owner": "runtime",
    "full_svg_authority": False,
}

_PROTOCOL_PRODUCTION = {
    "figure_nature": "standard_protocol",
    "production_strategy": "deterministic_template",
    "producer_kind": "deterministic",
    "composition_owner": "runtime",
    "full_svg_authority": False,
}


def _primary_production(contribution_type: str) -> dict[str, Any]:
    """Standard protocols and conceptual relations use separate runtime producers."""
    return (
        _PROTOCOL_PRODUCTION
        if contribution_type == "experimental_protocol"
        else _CONCEPTUAL_PRODUCTION
    )


def complexity_budget(contribution_type: str) -> dict[str, Any]:
    """Return the publication complexity budget for one scientific question."""
    if contribution_type not in _PRIMARY_FIGURES:
        raise ValueError(f"unsupported contribution portfolio: {contribution_type}")
    budget = deepcopy(DEFAULT_COMPLEXITY_BUDGET)
    if contribution_type in {"system_architecture", "theory_proof"}:
        budget["maximum_primary_branches"] = 3
    if contribution_type in {
        "experimental_protocol", "clinical_biological_mechanism",
        "qualitative_framework",
    }:
        budget["maximum_primary_objects"] = 7
    return budget


def _bind_portfolio_context(
    figures: list[dict[str, Any]], contribution: str,
    research_family: str, study_archetype: str,
) -> list[dict[str, Any]]:
    for item in figures:
        item.update({
            "contribution_type": contribution,
            "research_family": str(research_family or ""),
            "study_archetype": str(study_archetype or ""),
        })
    return figures


def _declares_detail(contract: dict[str, Any]) -> bool:
    """Recognize an explicit core-mechanism asset without inferring it from type."""
    for key in ("required_figure_assets", "figure_portfolio"):
        declared = contract.get(key)
        if isinstance(declared, dict):
            declared = declared.get("figures", declared.get("assets", []))
        if not isinstance(declared, list):
            continue
        for item in declared:
            if item == "core_mechanism":
                return True
            if isinstance(item, dict) and (
                item.get("asset_id") == "core_mechanism"
                or item.get("id") == "core_mechanism"
            ) and item.get("required", True) is True:
                return True
    return False


def mechanism_detail_reason(
    publication: dict[str, Any], method_contract: dict[str, Any],
    mechanisms: list[dict[str, Any]], scene: dict[str, Any],
    overview_layout: dict[str, Any],
) -> str:
    """Require a separate detail only for a mandate or real method overflow.

    Overflow alone is insufficient: the scene must contain an internal
    relation or a compound internal object that can answer a distinct question.
    """
    if _declares_detail(publication) or _declares_detail(method_contract):
        return "explicit_contract"
    if not mechanisms or not overview_layout.get("split_required"):
        return ""
    reasons = set(overview_layout.get("split_reasons") or [])
    if not reasons.intersection({
        "primary_object_budget", "visible_label_budget", "primary_branch_budget",
    }):
        return ""
    internal = {
        str(item.get("id")) for item in scene.get("objects") or []
        if isinstance(item, dict) and item.get("kind") not in {
            "input", "output", "sample", "measurement",
        }
    }
    if any(
        relation.get("from") in internal and relation.get("to") in internal
        and relation.get("kind") != "containment"
        for relation in scene.get("relations") or []
        if isinstance(relation, dict)
    ):
        return "method_overview_overflow"
    if any(
        len(item.get("subitems") or []) >= 2
        for item in scene.get("objects") or []
        if isinstance(item, dict) and str(item.get("id")) in internal
    ):
        return "method_overview_overflow"
    return ""


def _detail_figure(
    contribution: str, budget: dict[str, Any], reason: str,
) -> dict[str, Any]:
    return {
        **_CONCEPTUAL_PRODUCTION,
        "asset_id": "core_mechanism",
        "figure_type": _DETAIL_TYPES.get(contribution, "focused_method_detail"),
        "scientific_role": "method",
        "narrative_level": "mechanism_detail",
        "scientific_question": (
            "What domain-native transformation, interaction, or rule realizes "
            "the principal mechanism?"
        ),
        "visual_grammar": "domain_mechanism_zoom",
        "visual_encoding": "Mechanism internals and the operative relation",
        "required_if": reason,
        "content_boundary": (
            "Show only the operative mechanism; leave end-to-end context in "
            "the overview and validation criteria in the evaluation figure."
        ),
        "complexity_budget": deepcopy(budget),
    }


def publication_contribution_type(publication: dict[str, Any]) -> str:
    """Validate publication ownership before scene or renderer selection."""
    contribution = str(publication.get("contribution_type") or "")
    if contribution not in _PRIMARY_FIGURES:
        raise ValueError(
            "current publication contribution_type is required before asset planning"
        )
    return contribution


def figure_portfolio(
    publication: dict[str, Any], *, research_family: str = "",
    study_archetype: str = "", detail_reason: str = "",
) -> list[dict[str, Any]]:
    """Choose a bounded figure combination from contribution and study design.

    Artifact ids remain stable because they are workflow contracts. The
    contribution-specific ``figure_type`` is the semantic choice; renderers
    must not interpret every ``method_architecture`` id as a neural network.
    """
    contribution = publication_contribution_type(publication)
    question, grammar, encoding = _PRIMARY_FIGURES[contribution]
    budget = complexity_budget(contribution)
    figures = [{
        **_primary_production(contribution),
        "asset_id": "method_architecture",
        "figure_type": _PRIMARY_TYPES[contribution],
        "scientific_role": "method",
        "narrative_level": "method_overview",
        "scientific_question": question,
        "visual_grammar": grammar,
        "visual_encoding": encoding,
        "required_if": "always",
        "content_boundary": (
            "Show inputs, the proposed scientific operation, and outputs; "
            "leave validation, audit, and numerical results to companion figures."
        ),
        "complexity_budget": deepcopy(budget),
    }]
    selected_reason = detail_reason or (
        "explicit_contract" if _declares_detail(publication) else ""
    )
    if selected_reason:
        figures.append(_detail_figure(contribution, budget, selected_reason))
    evaluation_type = _ARCHETYPE_EVALUATION_TYPES.get(
        str(study_archetype or ""), _EVALUATION_TYPES[contribution]
    )
    figures.append({
        **_PROTOCOL_PRODUCTION,
        "asset_id": "evaluation_design",
        "figure_type": evaluation_type,
        "scientific_role": "evaluation_design",
        "narrative_level": "study_protocol",
        "scientific_question": _EVALUATION_QUESTIONS[contribution],
        "visual_grammar": "study_validation",
        "visual_encoding": (
            "Registered units and partitions through controls, held-out checks, "
            "uncertainty, and a typed decision rule"
        ),
        "required_if": "always",
        "content_boundary": (
            "Show how evidence decides the hypothesis; do not repeat internal "
            "method components or report unbound result values."
        ),
        "complexity_budget": deepcopy(budget),
    })
    return _bind_portfolio_context(
        figures, contribution, research_family, study_archetype,
    )


def method_story(
    publication: dict[str, Any], *, research_family: str = "",
    study_archetype: str = "", detail_reason: str = "",
) -> dict[str, Any]:
    """Return the compatible primary story plus its full figure portfolio."""
    portfolio = figure_portfolio(
        publication,
        research_family=research_family,
        study_archetype=study_archetype,
        detail_reason=detail_reason,
    )
    primary = portfolio[0]
    contribution = str(publication.get("contribution_type") or "")
    method = str(publication.get("method_name") or "Proposed method")
    budget = primary["complexity_budget"]
    return {
        "contribution_type": contribution,
        "scientific_question": primary["scientific_question"],
        "visual_grammar": primary["visual_grammar"],
        "visual_encoding": primary["visual_encoding"],
        "figure_type": primary["figure_type"],
        "narrative_level": primary["narrative_level"],
        "content_boundary": primary["content_boundary"],
        "caption": f"{method}: {str(primary['visual_encoding']).casefold()}.",
        "complexity_budget": deepcopy(budget),
        # Compatibility keys used by print and preflight contracts.
        "maximum_primary_nodes": budget["maximum_primary_objects"],
        "maximum_primary_branches": budget["maximum_primary_branches"],
        "maximum_visible_labels": budget["maximum_visible_labels"],
        "maximum_label_words": budget["maximum_label_words"],
        "minimum_placed_font_pt": budget["minimum_placed_font_pt"],
        "target_width_fraction": 1.0,
        # Domain adapters contribute semantics, not renderer geometry.
        "preferred_backend": (
            "rich_svg" if contribution == "experimental_protocol" else "figurespec"
        ),
        "figure_portfolio": portfolio,
    }


def method_story_for_scene(
    publication: dict[str, Any], method_contract: dict[str, Any],
    mechanisms: list[dict[str, Any]], scene: dict[str, Any], *,
    research_family: str = "", study_archetype: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Choose the portfolio after measuring the authored method scene."""
    from .scientific_scene import plan_scientific_layout

    budget = complexity_budget(str(publication.get("contribution_type") or ""))
    overview_layout = plan_scientific_layout(
        scene,
        maximum_nodes=int(budget["maximum_primary_objects"]),
        complexity_budget=budget,
    )
    detail_reason = mechanism_detail_reason(
        publication, method_contract, mechanisms, scene, overview_layout,
    )
    story = method_story(
        publication,
        research_family=research_family,
        study_archetype=study_archetype,
        detail_reason=detail_reason,
    )
    return story, overview_layout
