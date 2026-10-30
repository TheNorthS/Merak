"""Evidence-backed fallback manuscript assembly."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

from ..utils.atomic_write import atomic_write_text
from .paper_compiler import BibEntry
from .paper_evidence import PaperEvidence, _latex, _read_json_object
from .run_spec import execution_seeds
from .simulation_policy import SIMULATION_END_DISCLOSURE, SIMULATION_END_DISCLOSURE_TITLE

_RESULT_ROLES = frozenset({
    "result", "ablation", "robustness", "analysis", "efficiency",
    "calibration", "error_analysis", "sensitivity", "training_dynamics",
})
_EVALUATION_ROLES = frozenset({"evaluation_design", "dataset", "data", "study_overview"})


def write_fallback_manuscript(
    evidence: PaperEvidence, backup_main: Callable[[Path], None]
) -> Path:
    paper_dir = evidence.root / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    main_path = paper_dir / "main.tex"
    backup_main(main_path)
    facts = _study_facts(evidence)
    references = _reference_context(evidence.bib_entries)
    figures = _figure_context(evidence)
    results = _result_context(evidence, paper_dir, figures["result_discussion"])
    simulation = _simulation_context(evidence)
    closing = _closing_context(evidence, facts, results["abstract"])
    manuscript = _render_document(
        evidence, facts, references, figures, results, simulation, closing
    )
    atomic_write_text(main_path, manuscript)
    return main_path


def _study_facts(evidence: PaperEvidence) -> dict[str, Any]:
    selected = evidence.selected_idea
    problem = str(
        selected.get("problem_statement") or selected.get("hypothesis") or evidence.title
    ).strip()
    hypothesis = str(
        selected.get("hypothesis") or evidence.asset_plan.get("hypothesis") or problem
    ).strip()
    mechanisms = [
        item for item in selected.get("mechanisms", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    names = [str(item.get("name") or "").strip() for item in mechanisms]
    mechanism_prose = " ".join(
        f"{item.get('name')}: {item.get('description')}" for item in mechanisms
    ) or f"The proposed study operationalizes {hypothesis}."
    endpoints = [
        str(endpoint).strip()
        for claim in selected.get("claims", []) if isinstance(claim, dict)
        for endpoint in claim.get("measurable_endpoints", []) if str(endpoint).strip()
    ]
    run_spec = evidence.run_spec
    return {
        "problem": problem, "hypothesis": hypothesis, "mechanism_names": names,
        "mechanism_prose": mechanism_prose,
        "endpoints": "; ".join(endpoints[:8]) or "the prespecified primary endpoint",
        "models": _joined(run_spec, "models", "the declared comparison models"),
        "datasets": _joined(run_spec, "datasets", "the declared study cohorts"),
        "tasks": _joined(run_spec, "tasks", "the declared downstream tasks"),
        "conditions": _joined(run_spec, "adaptation_regimes", "matched experimental conditions"),
        "seeds": ", ".join(str(item) for item in execution_seeds(run_spec))
        or "the prespecified random seeds",
    }


def _joined(container: dict[str, Any], name: str, fallback: str) -> str:
    value = container.get(name)
    if not isinstance(value, list):
        return fallback
    cleaned = [" ".join(str(item).replace("_", " ").split()) for item in value]
    return ", ".join(item for item in cleaned if item) or fallback


def _reference_context(entries: Iterable[BibEntry]) -> dict[str, str]:
    entries = list(entries)
    publication = [
        entry for entry in entries
        if entry.key and entry.title and entry.authors and entry.year
    ] or [entry for entry in entries if entry.key]
    publication = publication[:40]
    keys = [_cite_key(entry.key) for entry in publication]
    return {
        "citations": rf"\cite{{{','.join(keys)}}}"
        if keys else "the accompanying literature review",
        "bibliography": _inline_bibliography(publication),
    }


def _figure_context(evidence: PaperEvidence) -> dict[str, str]:
    groups: dict[str, list[dict[str, Any]]] = {"method": [], "evaluation": [], "result": []}
    discussions: dict[str, list[str]] = {"method": [], "evaluation": [], "result": []}
    for item in evidence.figures:
        metadata = dict(item.get("metadata") or {})
        role = str(metadata.get("scientific_role") or "").casefold()
        group = "result" if role in _RESULT_ROLES else "evaluation" if role in _EVALUATION_ROLES else "method"
        groups[group].append(item)
        label = str(metadata.get("label") or "").strip()
        if label.startswith("fig:"):
            discussions[group].append(_figure_discussion(group, label, role))
    return {
        "method_input": r"\input{generated_method_figures}" if groups["method"] else "",
        "evaluation_input": r"\input{generated_evaluation_figures}" if groups["evaluation"] else "",
        "result_input": r"\input{generated_result_figures}" if groups["result"] else "",
        "method_discussion": " ".join(discussions["method"]) or
        "The method is specified textually because no validated domain figure is available.",
        "evaluation_discussion": " ".join(discussions["evaluation"]),
        "result_discussion": " ".join(discussions["result"]),
    }


def _figure_discussion(group: str, label: str, role: str) -> str:
    if group == "evaluation":
        return rf"Figure~\ref{{{label}}} defines the leakage-safe partitions, held-out conditions, endpoints, and independent uncertainty units."
    if group == "method":
        return rf"Figure~\ref{{{label}}} summarizes the scientific pipeline from study inputs through the proposed mechanisms to the reported endpoints."
    return rf"Figure~\ref{{{label}}} reports the {role or 'scientific'} analysis using the comparison and uncertainty encoding declared for that endpoint."


def _result_context(
    evidence: PaperEvidence, paper_dir: Path, result_discussion: str
) -> dict[str, str]:
    executed_input = (
        r"\input{tables/main_results}"
        if not evidence.experiments_pending and (paper_dir / "tables" / "main_results.tex").is_file()
        else ""
    )
    preview_input = (
        r"\input{synthetic_preview_figures}" "\n" r"\input{tables/synthetic_preview_results}"
        if evidence.synthetic_preview
        and (paper_dir / "synthetic_preview_figures.tex").is_file()
        and (paper_dir / "tables" / "synthetic_preview_results.tex").is_file()
        else ""
    )
    if preview_input:
        return {"input": preview_input, "table_input": executed_input,
                "prose": _synthetic_result_prose(evidence.root),
                "abstract": "The controlled benchmark provides source-bound comparisons and uncertainty records for the selected scientific questions. The registered values, independent units and decision rules determine whether a contrast supports or contradicts the proposed explanation."}
    if executed_input:
        return {"input": "", "table_input": executed_input,
                "prose": r"Table~\ref{tab:main-results} reports the primary comparison with run-level dispersion and confidence intervals. The interpretation is restricted to the recorded splits, seeds, and metrics. " + result_discussion,
                "abstract": "Provenance-backed result artifacts provide the primary comparison and run-level uncertainty."}
    prose = (
        "The current project snapshot contains no provenance-backed measurements. "
        "Accordingly, this manuscript defines the scientific analysis and its decisive "
        "endpoints without asserting a model ordering, effect size, or significance result."
    )
    return {"input": "", "table_input": "", "prose": prose, "abstract": prose}


def _synthetic_result_prose(root: Path) -> str:
    """Describe only current selected references, without inventing a winning outcome."""
    from .paper_asset_reference_contract import result_publication_references

    public_roles = {
        "result": "primary comparison", "main_comparison": "primary comparison",
        "ablation": "registered component comparison", "sensitivity": "registered sensitivity comparison",
        "analysis": "registered analysis trajectory", "training_dynamics": "registered progression",
        "robustness": "registered stress and robustness conditions",
        "calibration": "registered calibration and selective-risk conditions",
        "error_analysis": "registered failure slices", "efficiency": "registered resource comparison",
    }
    references = result_publication_references(root)
    if not references:
        raise ValueError("A benchmark fallback requires actual selected result references; no labels were invented")
    sentences = [
        rf"{reference.kind.title()}~\ref{{{reference.label}}} presents the "
        + public_roles.get(reference.scientific_role, "registered scientific comparison")
        + " from its bound source."
        for reference in references
    ]
    return " ".join([*sentences,
        "Endpoint direction, independent units, interval definitions and matched controls "
        "determine the interpretation. The registered values and uncertainty must be "
        "read together; no favorable ordering or mechanism support is inferred merely "
        "from the presence of an asset. Null outcomes and contrary conditions remain "
        "valid findings within the declared benchmark scope."])


def _simulation_context(evidence: PaperEvidence) -> dict[str, str]:
    if not evidence.synthetic_preview:
        return {"setup": "", "disclosure": ""}
    manifest = _read_json_object(
        evidence.root / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json"
    )
    seed = str(manifest.get("simulation_seed") or "").strip()
    seed_description = f"fixed seed {seed}" if seed else "the fixed seed recorded in the benchmark manifest"
    setup = (
        f"The registered evaluation uses {seed_description} and a matched scenario grid "
        "spanning the primary comparison, controlled component removals, training "
        "trajectories, stress conditions, failure slices, retained-coverage levels, "
        "and resource settings. Primary scores, resource variables, trajectories, and "
        "uncertainty intervals follow the prespecified calculation and aggregation rules. "
        "All methods share the same scenario inputs, comparison budget, endpoints, and rules."
    )
    disclosure = f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n{SIMULATION_END_DISCLOSURE}\n"
    return {"setup": setup, "disclosure": disclosure}


def _closing_context(
    evidence: PaperEvidence, facts: dict[str, Any], abstract_result: str
) -> dict[str, str]:
    if evidence.synthetic_preview:
        return {
            "discussion": "Within the defined benchmark, interpretation follows the selected source-bound comparisons, independent units and registered uncertainty. A favorable estimate alone does not establish mechanism support; matched controls, null outcomes and contrary conditions must be considered together.",
            "limitations": "External validity is bounded by the registered scenario families, parameter ranges, calculation rules, and uncertainty widths. Follow-up work should vary benchmark assumptions and test whether the ordering persists under independently collected measurements.",
            "conclusion": "The defined benchmark preserves the registered comparisons and their evidence boundaries. The bound endpoint values and decision rules determine the scientific conclusion; the presence of a generated figure or table does not itself establish a performance gain or mechanism effect.",
        }
    return {
        "discussion": "The central question is whether the observed pattern changes under controlled conditions without being explained by budget, split, or preprocessing differences. Positive and stable results are both informative because analysis is defined independently of the desired conclusion.",
        "limitations": "The study is limited by checkpoint availability, dataset licensing, metadata completeness, and the number of independent evaluation units. Optimization equality and budget comparability must be reported with compute cost, trainable parameters, and excluded runs. " + abstract_result,
        "conclusion": f"We formulate {evidence.title} as a controlled scientific analysis with explicit mechanisms, comparison dimensions, endpoints, and negative-result interpretations.",
    }


def _formalization(facts: dict[str, Any], title: str) -> str:
    blob = " ".join((title, facts["problem"], facts["hypothesis"],
                     facts["mechanism_prose"], facts["endpoints"])).casefold()
    if any(term in blob for term in ("rank", "ranking", "inversion")):
        return r"""Let $x$ denote one analysis unit, $b\in\mathcal{B}$ a controlled condition,
and $s_{m,b,d}$ the score of model $m$ on dataset or task $d$. We construct
\begin{equation}
r_{b,d}=\operatorname{rank}_m(s_{m,b,d}),
\end{equation}
and apply the registered diagnostic
$D(r_{b,d},r_{b',d})$ across matched conditions. Uncertainty is estimated over
the independent units specified by the study design."""
    return r"""Let $x$ denote one analysis unit, $m$ its metadata, and $f_\theta(x,m)$
the proposed procedure. The objective is
\begin{equation}
\mathcal{L}(\theta)=\mathcal{L}_{\mathrm{primary}}+
\sum_k\lambda_k\mathcal{L}_k,
\end{equation}
where each auxiliary term is a declared component. A component is credited only
when its matched removal changes the prespecified endpoint as expected."""


def _render_document(
    evidence: PaperEvidence, facts: dict[str, Any], references: dict[str, str],
    figures: dict[str, str], results: dict[str, str], simulation: dict[str, str],
    closing: dict[str, str],
) -> str:
    names = ", ".join(facts["mechanism_names"]) or evidence.title
    parts = [
        _preamble(evidence.title),
        _abstract_and_introduction(evidence, facts, results["abstract"], names),
        _related_and_method(facts, references, figures, _formalization(facts, evidence.title)),
        _experiments(facts, figures, simulation["setup"]),
        _results(facts, figures, results),
        _closing_sections(closing, simulation["disclosure"], references["bibliography"]),
    ]
    return "\n\n".join(parts) + "\n"


def _preamble(title: str) -> str:
    return rf"""\documentclass[11pt]{{article}}
\usepackage[UTF8,scheme=plain]{{ctex}}
\usepackage[margin=1in]{{geometry}}
\usepackage{{graphicx,booktabs,tabularx}}
\usepackage{{amsmath,amssymb,amsfonts}}
\usepackage[hidelinks]{{hyperref}}
\usepackage{{microtype}}
\graphicspath{{{{../figures/plots/}}{{../figures/diagrams/}}{{../figures/assets/}}}}
\title{{{_latex(title)}}}
\author{{Anonymous Authors}}
\date{{}}
\begin{{document}}
\maketitle"""


def _abstract_and_introduction(
    evidence: PaperEvidence, facts: dict[str, Any], abstract_result: str, names: str
) -> str:
    return rf"""\begin{{abstract}}
{_latex(facts['problem'])} We investigate this problem through {_latex(names)}.
The study varies {_latex(facts['conditions'])} while holding data, preprocessing,
model selection, and evaluation rules fixed. Its primary analysis reports
{_latex(facts['endpoints'])}. {_latex(abstract_result)}
\end{{abstract}}

\section{{Introduction}}
{_latex(facts['problem'])} Existing comparisons can conflate the phenomenon of
interest with adaptation, preprocessing, data access, or evaluation budget. We
therefore study the narrower hypothesis that {_latex(facts['hypothesis'])}

Our contribution is a domain-specific analysis built around {_latex(names)}. The
design separates controlled conditions from endpoints, retains uncertainty at
the appropriate unit, and treats stable or null effects as informative outcomes."""


def _related_and_method(
    facts: dict[str, Any], references: dict[str, str], figures: dict[str, str],
    formalization: str,
) -> str:
    return rf"""\section{{Related Work}}
The study is positioned against the verified local bibliography {references['citations']}.
The independent variable, comparison budget, and diagnostic endpoints are fixed
before interpretation, preventing a leaderboard from being mistaken for evidence
about the proposed mechanism. Prior studies motivate the representation,
adaptation, and evaluation choices, but their reported scores are not treated as
interchangeable when cohorts, partitions, or tuning resources differ. We therefore
use the literature to define plausible alternatives and boundary conditions, then
reserve empirical support for comparisons executed under the registered protocol.
This separation also makes a null finding interpretable: it may contradict the
mechanistic hypothesis without invalidating the broader task or benchmark.

\section{{Method}}
{_latex(facts['mechanism_prose'])} These components form one scientific procedure.
Each component has an explicit input, transformation, and observable consequence.
The complete configuration and every controlled removal share the same upstream
data contract and downstream measurement rule. Consequently, a change in the
primary endpoint can be attributed to the declared intervention more directly
than in comparisons that simultaneously alter architecture, preprocessing, and
optimization. Intermediate representations are used for diagnosis only when
their extraction rule is fixed before outcome inspection.

{formalization}

{figures['method_discussion']}
{figures['method_input']}

Table~\ref{{tab:method-components}} identifies each component's function and test.
\input{{tables/method_components}}"""


def _experiments(
    facts: dict[str, Any], figures: dict[str, str], simulation_setup: str
) -> str:
    return rf"""\section{{Experimental Setup}}
{_latex(simulation_setup)}
{figures['evaluation_discussion']}
{figures['evaluation_input']}
The comparison includes {_latex(facts['models'])} on {_latex(facts['datasets'])}
for {_latex(facts['tasks'])}. Conditions are {_latex(facts['conditions'])}, with
repeated evaluation using {_latex(facts['seeds'])}. Splits, preprocessing,
checkpoint selection, and tuning budgets remain matched. Available grouping
identifiers remain disjoint; missing metadata is reported as unknown.

Model selection uses only the designated fitting and validation partitions. The
final partition is opened after configuration choices are frozen, and all failed
or excluded runs remain part of the provenance ledger. Statistical summaries use
the declared independent unit rather than treating correlated predictions as
replicates. Alongside the primary endpoint, the analysis reports uncertainty,
component sensitivity, failure slices, and resource measurements whenever those
artifacts are present. These controls distinguish a repeatable scientific effect
from an apparent gain caused by data access or unequal search opportunity.

Table~\ref{{tab:study-design}} summarizes the controlled study dimensions.
\input{{tables/study_design}}"""


def _results(
    facts: dict[str, Any], figures: dict[str, str], results: dict[str, str]
) -> str:
    return rf"""\section{{Results}}
{results['prose']}
{figures['result_input']}
{results['table_input']}
{results['input']}
The decisive quantities are {_latex(facts['endpoints'])}. A null pattern weakens
the hypothesis; an effect lost under matched tuning or leakage-safe filtering is
protocol sensitivity rather than support for the proposed explanation. Effect
direction, interval width, and consistency across the registered conditions are
interpreted together; no single favorable cell is promoted to a general claim.
Secondary analyses explain where the primary pattern holds or fails, but they do
not replace the prespecified endpoint."""


def _closing_sections(
    closing: dict[str, str], disclosure: str, bibliography: str
) -> str:
    return rf"""\section{{Discussion}}
{closing['discussion']}

\section{{Limitations}}
{closing['limitations']}

\section{{Conclusion}}
{_latex(closing['conclusion'])}

{disclosure}
{bibliography}
\end{{document}}"""


def _cite_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:.+-]", "", value) or "reference"


def _inline_bibliography(entries: Iterable[BibEntry]) -> str:
    entries = list(entries)
    if not entries:
        return ""
    lines = [r"\begin{thebibliography}{99}"]
    for entry in entries:
        details = ". ".join(
            part for part in (entry.authors, entry.title, entry.venue, entry.year) if part
        )
        key = _cite_key(entry.key)
        lines.append(rf"\bibitem{{{key}}} {_latex(details or key)}.")
    lines.append(r"\end{thebibliography}")
    return "\n".join(lines)
