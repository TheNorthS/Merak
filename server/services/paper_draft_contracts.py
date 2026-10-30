"""Publication style and section-contract construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import paper_draft_state
from .manuscript_text import read_json, write_json
from .paper_profile import paper_profile_service
from .publication_style import publication_style_service

AnalyseSource = Callable[[Path], dict[str, Any]]
ProjectOptionsFn = Callable[[str | Path, Optional[dict[str, Any]]], Any]

RESULT_MOVES = {
    "algorithm_benchmark": ["primary benchmark comparison", "matched ablations", "robustness and error slices", "uncertainty and efficiency"],
    "systems_testbed": ["effectiveness and performance", "matched configurations", "scale and tail behavior", "failure and resource trade-offs"],
    "observational_cohort": ["primary effect estimate", "adjusted and unadjusted analyses", "subgroup and sensitivity analyses", "external or temporal validity"],
    "diagnostic_prognostic": ["discrimination and uncertainty", "calibration and clinical utility", "external validation", "subgroup and failure analysis"],
    "intervention_trial": ["participant flow", "primary treatment effect", "secondary outcomes and harms", "protocol deviations and sensitivity analyses"],
    "omics_discovery": ["quality-control evidence", "effect sizes with multiplicity control", "independent or orthogonal validation", "biological interpretation"],
    "controlled_experiment": ["raw replicate distributions", "effect sizes and controls", "dose, time, or perturbation response", "orthogonal validation"],
    "simulation_modeling": ["verification and convergence", "validation against observations", "sensitivity and identifiability", "uncertainty propagation"],
    "formal_theory": ["main theorem or guarantee", "proof dependencies", "comparison bounds", "counterexamples and assumption necessity"],
    "qualitative_mixed": ["themes with traceable evidence", "case contrasts", "negative cases and rival readings", "triangulation and reflexivity"],
    "generic_empirical": ["primary estimate", "controls and alternatives", "robustness and negative cases", "uncertainty"],
}

SECTION_TITLES = {
    "algorithm_benchmark": {"method": "Method", "experiments": "Experimental Setup", "results": "Results"},
    "systems_testbed": {"method": "System Design", "experiments": "Evaluation Methodology", "results": "Evaluation"},
    "observational_cohort": {"method": "Analysis Framework", "experiments": "Cohort and Statistical Methods", "results": "Results"},
    "diagnostic_prognostic": {"method": "Model and Estimands", "experiments": "Participants and Validation Methods", "results": "Results"},
    "intervention_trial": {"method": "Intervention and Estimand", "experiments": "Trial Methods", "results": "Results"},
    "omics_discovery": {"method": "Analysis Framework", "experiments": "Samples, Assays, and Statistical Analysis", "results": "Results"},
    "controlled_experiment": {"method": "Mechanistic Framework", "experiments": "Materials and Methods", "results": "Results"},
    "simulation_modeling": {"method": "Model Formulation", "experiments": "Verification and Validation", "results": "Results"},
    "formal_theory": {"method": "Definitions and Construction", "experiments": "Assumptions and Analysis Protocol", "results": "Main Results"},
    "qualitative_mixed": {"method": "Analytical Framework", "experiments": "Methodology", "results": "Findings"},
    "generic_empirical": {"method": "Methods", "experiments": "Study Design", "results": "Results"},
}

METHOD_MOVES = {
    "algorithm_benchmark": ["problem setup", "implemented mechanisms", "objective or decision rule", "training and inference", "complexity and implementation", "method figure interpretation"],
    "systems_testbed": ["design goals", "component architecture", "control policy", "workload interface", "failure handling", "system figure interpretation"],
    "observational_cohort": ["target population", "estimand", "exposure and outcome definitions", "adjustment strategy", "missing-data strategy", "analysis figure interpretation"],
    "diagnostic_prognostic": ["target population", "index model or assay", "reference standard", "prediction horizon", "calibration and decision rule", "method figure interpretation"],
    "intervention_trial": ["eligibility", "intervention and comparator", "allocation and masking", "estimand", "follow-up and analysis population", "trial figure interpretation"],
    "omics_discovery": ["sample and assay model", "quality control", "normalization", "statistical model", "multiplicity control", "pipeline figure interpretation"],
    "controlled_experiment": ["experimental units", "conditions and perturbations", "controls", "measurement procedure", "replication and analysis", "protocol figure interpretation"],
    "simulation_modeling": ["governing model", "assumptions", "initial and boundary conditions", "numerical method", "verification and validation", "model figure interpretation"],
    "formal_theory": ["definitions", "assumptions", "construction", "main statements", "proof dependencies", "logical figure interpretation"],
    "qualitative_mixed": ["sampling and cases", "coding framework", "interpretive procedure", "negative cases", "reflexivity and triangulation", "method figure interpretation"],
    "generic_empirical": ["study objects", "mechanisms or exposures", "controls", "endpoints", "inferential procedure", "method figure interpretation"],
}


def build_style_profile(
    root: Path, options: Optional[dict[str, Any]], *,
    analyse_source: AnalyseSource, schema: int,
    exemplars: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    raw = options or {}
    evidence = paper_draft_state.evidence_status(root)
    target_venue = str(raw.get("target_venue") or "unspecified")
    style = publication_style_service.prepare(
        root, str(raw.get("research_direction") or ""), target_venue=target_venue,
        research_family=str(raw.get("research_family") or ""),
        study_archetype=str(raw.get("study_archetype") or ""),
    )
    manuscript = paper_profile_service.prepare(
        root, target_venue=target_venue,
        evidence_mode=str(evidence.get("mode") or "design_only"),
        submission_eligible=bool(evidence.get("submission_eligible")),
        research_family=str(style.get("family") or "generic_quantitative"),
        study_archetype=str(style.get("study_archetype") or "generic_empirical"),
    )
    profile = {
        "schema_version": schema, "profile_kind": "aggregate-structural-guidance",
        "target_venue": target_venue,
        "venue_template_path": str(raw.get("venue_template_path") or "").strip(),
        "built_in_exemplars": [dict(item) for item in exemplars
                               if str(item.get("research_family") or "machine_learning") == str(style.get("family") or "")],
        "local_structural_references": _local_profiles(root, raw, analyse_source),
        "manuscript_profile": manuscript, "publication_visual_style": style,
        "adopted_principles": _adopted_principles(),
        "anti_patterns": _anti_patterns(),
    }
    write_json(root / "paper" / "PAPER_STYLE_PROFILE.json", profile)
    return profile


def _local_profiles(
    root: Path, options: dict[str, Any], analyse_source: AnalyseSource
) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    reference = str(options.get("ref_paper") or "").strip()
    if reference and Path(reference).expanduser().exists():
        candidates.append(Path(reference).expanduser().resolve())
    library = root / "literature" / "papers"
    if library.is_dir():
        candidates.extend(sorted(library.rglob("*.tex"))[:6])
    profiles, seen = [], set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            profiles.append(analyse_source(candidate))
    return profiles


def _adopted_principles() -> list[str]:
    return [
        "Introduction: value -> prior families -> unresolved limitation -> mechanism -> falsifiable contributions.",
        "Related Work: organize by assumptions and methods, not paper-by-paper summaries.",
        "Method: define study objects, constructs, or notation before mechanisms and bind each step to an observable or inferential consequence.",
        "Study design: freeze analysis units, sampling or separation, comparators, endpoints, uncertainty, and validity controls.",
        "Results: answer registered questions through primary estimates, controls, sensitivity, negative cases, and uncertainty.",
        "Write title, abstract, and conclusion after the technical body.",
    ]


def _anti_patterns() -> list[str]:
    return [
        "single-pass whole-paper generation",
        "generic field survey without closest-work positioning",
        "internal claim IDs or workflow status in manuscript prose",
        "figures/tables included only to satisfy a count",
        "synthetic values presented as measurements",
        "result claims without run-level provenance and uncertainty",
    ]


def build_section_contracts(
    root: Path, options: Optional[dict[str, Any]], *, specs: Iterable[Any],
    author_order: Iterable[str], schema: int, source_signature: ProjectOptionsFn,
    authoring_signature: ProjectOptionsFn,
) -> dict[str, Any]:
    selected = read_json(root / "ideas" / "SELECTED_IDEA.json")
    evidence = paper_draft_state.evidence_status(root)
    manuscript = paper_profile_service.load(root)
    style = publication_style_service.load(root)
    mechanisms, claims = _claims_and_mechanisms(selected)
    archetype = str(style.get("study_archetype") or "generic_empirical")
    specs = tuple(specs)
    sections = [
        _section_contract(spec, evidence, style, archetype, mechanisms)
        for spec in specs
    ]
    payload = {
        "schema_version": schema,
        "source_signature": source_signature(root, options),
        "authoring_signature": authoring_signature(root, options),
        "authoring_inputs": paper_draft_state.authoring_input_hashes(root),
        "authoring_options": paper_draft_state.signature_options(options),
        "title_seed": str((selected.get("publication") or {}).get("title") or "").strip(),
        "central_hypothesis": str(selected.get("hypothesis") or "").strip(),
        "required_mechanisms": mechanisms, "claims": claims, "evidence": evidence,
        "manuscript_profile": manuscript, "publication_style": _style_contract(style),
        "authoring_order": list(author_order), "sections": sections,
        "front_matter": {
            "title_path": "paper/TITLE.txt", "abstract_path": "paper/sections/00_abstract.tex",
            "abstract_words": [150, 250], "written_after": [item.id for item in specs],
        },
        "consistency_checks": [
            "terminology and acronym consistency", "citation-key reachability",
            "label/reference closure", "claim-to-result alignment", "numeric provenance",
            "duplicate paragraph detection", "evidence-calibrated front matter and conclusion",
        ],
    }
    write_json(root / "paper" / "SECTION_CONTRACTS.json", payload)
    return payload


def _claims_and_mechanisms(
    selected: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    mechanisms = [
        " ".join(str(item.get("publication_name") or "").split())
        for item in selected.get("mechanisms", [])
        if isinstance(item, dict) and item.get("required", True)
        and str(item.get("publication_name") or "").strip()
    ]
    claims = [
        {
            "id": str(item.get("id") or ""),
            "text": " ".join(str(item.get("publication_statement") or "").split()),
            "endpoints": [" ".join(str(value).split())
                          for value in item.get("measurable_endpoints", []) if str(value).strip()],
        }
        for item in selected.get("claims", []) if isinstance(item, dict)
    ]
    return mechanisms, claims


def _section_contract(
    spec: Any, evidence: dict[str, Any], style: dict[str, Any],
    archetype: str, mechanisms: list[str],
) -> dict[str, Any]:
    title = SECTION_TITLES[archetype].get(spec.id, spec.title)
    if spec.id == "results" and not evidence["submission_eligible"] and evidence.get("mode") != "synthetic_preview":
        title = "Evaluation Protocol and Planned Analyses"
    moves = list(spec.required_moves)
    if spec.id == "method":
        moves = METHOD_MOVES[archetype]
    elif spec.id == "experiments":
        moves = list(style.get("required_evidence") or moves)
    elif spec.id == "results":
        moves = RESULT_MOVES[archetype]
    return {
        "id": spec.id, "path": f"paper/sections/{spec.filename}", "title": title,
        "minimum_words": spec.minimum_words, "maximum_words": spec.maximum_words,
        "minimum_citations": spec.minimum_citations, "purpose": spec.purpose,
        "required_moves": moves,
        "required_mechanisms": mechanisms if spec.id == "method" else [],
        "domain_emphasis": list(style.get("section_emphasis") or []),
        "evidence_mode": evidence["mode"],
        "may_report_empirical_results": evidence["submission_eligible"],
    }


def _style_contract(style: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": style.get("family"), "family_label": style.get("family_label"),
        "study_archetype": style.get("study_archetype"),
        "reporting_standards": style.get("reporting_standards", []),
        "required_evidence": style.get("required_evidence", []),
        "section_emphasis": style.get("section_emphasis", []),
    }
