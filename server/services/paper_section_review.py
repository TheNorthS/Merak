"""Local semantic review for one staged manuscript section."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Pattern

from .manuscript_language import (
    find_internal_contract_references,
    find_visible_code_artifact_references,
)
from .manuscript_text import (
    DISPLAY_MATH_RE,
    bib_keys,
    citation_keys,
    read_text,
    reference_keys,
    sha256,
    strip_tex,
    word_count,
)
from .paper_contribution_validation import falsifiable_contribution_structure
from .publication_style import publication_style_service
from .simulation_policy import (
    FORBIDDEN_RENDERED_SIMULATION_LABELS,
    rendered_mode_framing_hits,
    strip_latex_comments,
    visible_latex_prose,
)

AnalysisRequirements = Callable[[str], dict[str, str]]


@dataclass
class SectionReviewPolicy:
    admin: Pattern[str]
    ai_ism: Pattern[str]
    superiority: Pattern[str]
    algorithm_mechanism: Pattern[str]
    alternative_explanation: Pattern[str]
    negative_result: Pattern[str]
    preview_figure_labels: tuple[str, ...]
    preview_table_labels: tuple[str, ...]
    synthetic_analysis_requirements: AnalysisRequirements


@dataclass
class SectionContext:
    root: Path
    spec: Any
    evidence: dict[str, Any]
    required_mechanisms: list[str]
    policy: SectionReviewPolicy
    path: Path
    text: str
    lower: str
    rendered_prose: str
    rendered_lower: str
    archetype: str
    words: int
    citations: set[str]
    issues: list[str]
    title_match: re.Match[str] | None
    paragraphs: list[str]


def review_section(
    root: Path,
    spec: Any,
    evidence: dict[str, Any],
    required_mechanisms: list[str],
    policy: SectionReviewPolicy,
) -> dict[str, Any]:
    context = _build_context(root, spec, evidence, required_mechanisms, policy)
    _review_common(context)
    reviewer = {
        "introduction": _review_introduction,
        "related_work": _review_related_work,
        "method": _review_method,
        "experiments": _review_experiments,
        "results": _review_results,
        "discussion": _review_discussion,
        "limitations": _review_limitations,
    }.get(spec.id)
    if reviewer:
        reviewer(context)
    return {
        "passed": not context.issues,
        "issues": context.issues,
        "path": str(context.path),
        "words": context.words,
        "paragraphs": len(context.paragraphs),
        "citation_keys": sorted(context.citations),
        "sha256": sha256(context.path),
    }


def _build_context(
    root: Path,
    spec: Any,
    evidence: dict[str, Any],
    required_mechanisms: list[str],
    policy: SectionReviewPolicy,
) -> SectionContext:
    path = root / "paper" / "sections" / spec.filename
    text = read_text(path)
    rendered = visible_latex_prose(text)
    return SectionContext(
        root=root,
        spec=spec,
        evidence=evidence,
        required_mechanisms=required_mechanisms,
        policy=policy,
        path=path,
        text=text,
        lower=text.casefold(),
        rendered_prose=rendered,
        rendered_lower=rendered.casefold(),
        archetype=str(
            publication_style_service.load(root).get("study_archetype")
            or "generic_empirical"
        ),
        words=word_count(text),
        citations=citation_keys(text),
        issues=[],
        title_match=re.search(r"\\section\*?\{([^}]+)\}", text),
        paragraphs=[
            item
            for item in re.split(r"\n\s*\n", strip_tex(text))
            if len(item.split()) >= 20
        ],
    )


def _review_common(context: SectionContext) -> None:
    text, spec, issues = context.text, context.spec, context.issues
    from .manuscript_math_syntax import math_delimiter_issues
    from .paper_table_ownership import registered_table_copy_issues
    issues.extend(math_delimiter_issues(text))
    issues.extend(registered_table_copy_issues(context.root, text))
    if not text.strip():
        issues.append("section is missing or empty")
    if "\\documentclass" in text or "\\begin{document}" in text:
        issues.append("section contains a standalone document wrapper")
    if not context.title_match:
        issues.append("section has no top-level section heading")
    if context.words < spec.minimum_words:
        issues.append(f"section too short ({context.words}; minimum {spec.minimum_words})")
    if context.words > int(spec.maximum_words * 1.2):
        issues.append(
            f"section unfocused ({context.words}; preferred maximum {spec.maximum_words})"
        )
    if len(context.citations) < spec.minimum_citations:
        issues.append(
            f"section uses {len(context.citations)} citations; minimum {spec.minimum_citations}"
        )
    unknown = sorted(context.citations - bib_keys(context.root / "paper" / "references.bib"))
    if unknown:
        issues.append("unknown BibTeX keys: " + ", ".join(unknown))
    _review_visible_language(context)
    if len(context.paragraphs) < 2 and spec.id != "conclusion":
        issues.append("section has fewer than two substantive paragraphs")


def _review_visible_language(context: SectionContext) -> None:
    policy, issues = context.policy, context.issues
    if policy.admin.search(context.rendered_prose) or find_internal_contract_references(context.text):
        issues.append("section exposes workflow or contract metadata")
    code_artifacts = find_visible_code_artifact_references(context.text)
    if code_artifacts:
        issues.append(
            "section exposes implementation symbols or artifact paths: "
            + ", ".join(code_artifacts[:6])
        )
    if policy.ai_ism.search(context.text):
        issues.append("section contains avoidable AI-style phrasing")
    if (
        not context.evidence.get("submission_eligible")
        and context.evidence.get("mode") != "synthetic_preview"
        and policy.superiority.search(context.text)
    ):
        issues.append("section claims superiority without eligible evidence")
    if context.evidence.get("mode") == "synthetic_preview":
        hits = rendered_mode_framing_hits(context.text)
        if hits:
            issues.append(
                "section repeats simulation, preview, draft, or evidence-mode framing "
                "outside the assembly-managed end disclosure: " + ", ".join(hits[:6])
            )


def _review_introduction(context: SectionContext) -> None:
    if not re.search(r"\b(?:however|yet|despite|remains?|unresolved)\b", context.lower):
        context.issues.append("introduction lacks a specific unresolved gap")
    if not re.search(
        r"\b(?:we|this (?:paper|work|study))\s+(?:therefore\s+)?"
        r"(?:propose|introduce|develop|study|investigate|address|examine|"
        r"evaluate|test|present|operationali[sz]e|formulate|implement|instantiate|specify|use)\b"
        r"|\bour\s+(?:approach|method|protocol|framework)\s+"
        r"(?:prospectively\s+)?(?:defines|specifies|keeps|holds|uses|combines|compares|pairs|isolates|conditions|constructs|learns|encodes)\b",
        context.lower,
    ):
        context.issues.append("introduction does not preview the approach")
    structure = falsifiable_contribution_structure(context.text)
    if structure["contributions"] < 2 or structure["falsification_conditions"] < 2:
        context.issues.append("introduction lacks two or more falsifiable contributions")


def _review_related_work(context: SectionContext) -> None:
    if len(re.findall(r"\\(?:subsection|paragraph)\*?\{", context.text)) < 3:
        context.issues.append("related work needs three methodological categories")
    if not re.search(
        r"\b(?:unlike|in contrast|differs?|closest|whereas|our work)\b", context.lower
    ):
        context.issues.append("related work does not position this paper against alternatives")


def _review_method(context: SectionContext) -> None:
    equation_required = context.archetype in {
        "algorithm_benchmark", "simulation_modeling", "formal_theory"
    }
    if equation_required and not DISPLAY_MATH_RE.search(context.text):
        context.issues.append("method has no formal objective, governing equation, or bound")
    for mechanism in context.required_mechanisms:
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]{4,}", mechanism.casefold())
            if token not in {"with", "from", "using", "model", "method"}
        }
        threshold = max(1, (len(tokens) + 1) // 2)
        if tokens and sum(token in context.lower for token in tokens) < threshold:
            context.issues.append(f"method does not cover required mechanism: {mechanism}")
    if not any(label.startswith("fig:") for label in reference_keys(context.text)):
        context.issues.append("method does not interpret the method figure")


def _review_experiments(context: SectionContext) -> None:
    checks = {
        "data or analysis units": (
            r"\b(?:data|dataset|partition|analysis unit|observation|cohort|subject|"
            r"sample|participant|case|corpus|assumption|definition)\b"
        ),
        "endpoints or outcomes": r"\b(?:metric|accuracy|f1|auroc|loss|endpoint|outcome|effect|theme|theorem|bound)\b",
        "uncertainty or validity": r"\b(?:confidence interval|uncertainty|statistical|replicate|sensitivity|validation|negative case|counterexample)\b",
    }
    checks.update(_archetype_experiment_checks(context.archetype))
    for name, pattern in checks.items():
        if not re.search(pattern, context.lower):
            context.issues.append(f"experimental setup omits {name}")
    if context.evidence.get("mode") == "synthetic_preview" and any(
        marker.casefold() in context.rendered_lower
        for marker in FORBIDDEN_RENDERED_SIMULATION_LABELS
    ):
        context.issues.append(
            "experimental setup contains a forbidden simulation warning instead of "
            "ordinary methodological disclosure"
        )
    if "fig:evaluation-design" not in reference_keys(context.text):
        context.issues.append(
            "experimental setup does not interpret the evaluation-design figure"
        )


def _archetype_experiment_checks(archetype: str) -> dict[str, str]:
    return {
        "algorithm_benchmark": {
            "leakage-safe splits": r"\b(?:split|leakage|disjoint|held-out)\b",
            "matched baselines": r"\b(?:baselines?|comparators?|controls?)\b",
            "compute/implementation": r"\b(?:implementation|optimizer|epoch|gpu|compute|runtime)\b",
        },
        "systems_testbed": {
            "controlled testbed": r"\b(?:testbed|workload|hardware|software|warm-up|repetition)\b",
            "baselines": r"\b(?:baselines?|existing systems?|comparators?)\b",
            "resource measurement": r"\b(?:latency|throughput|memory|energy|cost|runtime)\b",
        },
        "observational_cohort": {
            "eligibility and confounding": r"\b(?:inclusion|exclusion|confound|adjust|missing data|covariate)\b",
            "analysis separation": r"\b(?:temporal|external|validation|held-out|train|test)\b",
        },
        "diagnostic_prognostic": {
            "reference standard": r"\b(?:reference standard|outcome|follow-up|threshold)\b",
            "calibration or utility": r"\b(?:calibration|decision|utility|discrimination)\b",
        },
        "intervention_trial": {
            "allocation and masking": r"\b(?:random|allocation|mask|blind|conceal)\b",
            "harms and deviations": r"\b(?:harm|adverse|deviation|adherence|intention-to-treat)\b",
        },
        "omics_discovery": {
            "assay quality control": r"\b(?:assay|quality control|qc|batch|filter)\b",
            "multiple testing": r"\b(?:multiple testing|false discovery|fdr|adjusted p)\b",
        },
        "controlled_experiment": {
            "controls and replicates": r"\b(?:control|replicate|random|blind|technical|biological)\b",
            "acquisition protocol": r"\b(?:instrument|acquisition|condition|dose|time point)\b",
        },
        "simulation_modeling": {
            "verification": r"\b(?:verification|convergence|discret|manufactured solution)\b",
            "validation and sensitivity": r"\b(?:validation|sensitivity|uncertainty|identifiability)\b",
        },
        "formal_theory": {
            "assumptions and definitions": r"\b(?:assumption|definition|lemma|theorem)\b",
            "proof or counterexample": r"\b(?:proof|counterexample|bound|complexity)\b",
        },
        "qualitative_mixed": {
            "sampling and context": r"\b(?:sampling|participant|case|corpus|context|positionality)\b",
            "coding and triangulation": r"\b(?:cod(?:e|ing)|theme|triangulat|reflexiv|audit trail)\b",
        },
    }.get(archetype, {
        "sampling or separation": r"\b(?:sample|split|held-out|inclusion|exclusion)\b",
        "controls or protocol": r"\b(?:controls?|baselines?|protocols?|comparisons?)\b",
    })


def _review_results(context: SectionContext) -> None:
    _review_result_evidence_boundary(context)
    primary, robustness = _result_analysis_patterns(
        context.archetype, context.policy.algorithm_mechanism
    )
    if not re.search(primary, context.lower):
        context.issues.append(
            "results/planned analyses omit the domain's primary control or sensitivity analysis"
        )
    if not re.search(robustness, context.lower):
        context.issues.append(
            "results/planned analyses omit the domain's robustness, validity, or negative-case analysis"
        )


def _review_result_evidence_boundary(context: SectionContext) -> None:
    simulation = context.evidence.get("mode") == "synthetic_preview"
    if simulation or not context.evidence.get("submission_eligible"):
        if not simulation and context.title_match and "result" in context.title_match.group(1).casefold():
            context.issues.append("non-empirical analysis must not be titled Results")
        if not simulation and not re.search(
            r"\b(?:planned|protocol|will be|decision rule|registered|"
            r"synthetic preview|illustrative|replacement)\b",
            context.lower,
        ):
            context.issues.append("non-empirical analysis is not framed as a protocol")
        if simulation:
            _review_synthetic_results(context)
    elif not (re.search(r"\\input\s*\{", context.text) or reference_keys(context.text)):
        context.issues.append("results do not reference a persisted table or figure")


def _review_synthetic_results(context: SectionContext) -> None:
    required = _required_preview_labels(context)
    missing = sorted(required - reference_keys(context.text))
    if missing:
        context.issues.append(
            "synthetic results preview omits registered asset references: "
            + ", ".join(missing)
        )
    required_inputs = {"synthetic_preview_figures", "tables/synthetic_preview_results"}
    missing_inputs = sorted(required_inputs - set(re.findall(r"\\input\{([^}]+)\}", context.text)))
    if missing_inputs:
        context.issues.append(
            "synthetic results preview omits registered asset inputs: "
            + ", ".join(missing_inputs)
        )
    analytical = strip_tex(context.text).casefold()
    from .paper_asset_reference_contract import selected_result_analysis_requirements
    requirements = selected_result_analysis_requirements(
        context.root, context.policy.synthetic_analysis_requirements(context.archetype),
    )
    for name, pattern in requirements.items():
        if not re.search(pattern, analytical):
            context.issues.append(
                "synthetic results preview lacks analytical prose about " + name
            )
    if any(marker.casefold() in analytical for marker in FORBIDDEN_RENDERED_SIMULATION_LABELS):
        context.issues.append(
            "simulation results contain a forbidden warning banner or evidence-status phrase"
        )


def _required_preview_labels(context: SectionContext) -> set[str]:
    from .paper_asset_reference_contract import result_publication_references
    from .table_panel_reference_contract import section_primary_panel_parents

    required = {reference.label for reference in result_publication_references(context.root)}
    try:
        parents = section_primary_panel_parents(context.root, context.path)
    except (OSError, UnicodeError, ValueError) as error:
        context.issues.append(f"registered primary table panel reference is invalid: {error}")
        return required
    prose = re.sub(r"\\begin\{(?:figure|table)\*?\}.*?\\end\{(?:figure|table)\*?\}",
                   " ", strip_latex_comments(context.text), flags=re.DOTALL)
    parent_refs = reference_keys(prose)
    return required - {label for label, parent in parents.items() if parent in parent_refs}


def _result_analysis_patterns(
    archetype: str, algorithm_pattern: Pattern[str]
) -> tuple[str | Pattern[str], str]:
    return {
        "algorithm_benchmark": (algorithm_pattern, r"\b(?:robust|shift|stress|failure|error analysis)\b"),
        "systems_testbed": (r"\b(?:component|configuration|matched|control|variant)\b", r"\b(?:scale|stress|failure|tail|workload)\b"),
        "observational_cohort": (r"\b(?:adjust|sensitivity|subgroup|specification|confound)\b", r"\b(?:external|temporal|sensitivity|missing|negative)\b"),
        "diagnostic_prognostic": (r"\b(?:calibrat|threshold|subgroup|sensitivity|reference)\b", r"\b(?:external|subgroup|decision|failure|shift)\b"),
        "intervention_trial": (r"\b(?:treatment|intervention|comparator|subgroup|sensitivity)\b", r"\b(?:harm|adverse|protocol deviation|missing|negative)\b"),
        "omics_discovery": (r"\b(?:validation|pathway|batch|feature|sensitivity)\b", r"\b(?:external|orthogonal|batch|false discovery|negative)\b"),
        "controlled_experiment": (r"\b(?:control|dose|condition|replicate|factor)\b", r"\b(?:orthogonal|replicate|time|dose|failure)\b"),
        "simulation_modeling": (r"\b(?:sensitivity|parameter|boundary|component)\b", r"\b(?:convergence|validation|uncertainty|limiting|failure)\b"),
        "formal_theory": (r"\b(?:assumption|lemma|theorem|bound)\b", r"\b(?:counterexample|boundary|limiting|necessity)\b"),
        "qualitative_mixed": (r"\b(?:theme|code|case|triangulat|alternative)\b", r"\b(?:negative case|rival|triangulat|reflexiv|limitation)\b"),
    }.get(archetype, (
        r"\b(?:component|sensitivity|alternative|control)\b",
        r"\b(?:robust|shift|stress|failure|sensitivity|negative)\b",
    ))


def _review_discussion(context: SectionContext) -> None:
    prose = " ".join(visible_latex_prose(context.text).split())
    if not context.policy.alternative_explanation.search(prose):
        context.issues.append("discussion omits alternative explanations")
    if not context.policy.negative_result.search(prose):
        context.issues.append("discussion omits negative/null-result interpretation")


def _review_limitations(context: SectionContext) -> None:
    if not re.search(r"\b(?:limitations?|threats?|bias(?:es)?|validity)\b", context.lower):
        context.issues.append("limitations omit concrete validity threats")
    if not re.search(r"\b(?:mitigat\w*|future|require\w*|address\w*)\b", context.lower):
        context.issues.append("limitations give no mitigation")
