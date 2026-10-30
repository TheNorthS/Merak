"""Prompt composition for bounded manuscript stages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .manuscript_text import read_json
from .workflow_user_constraints import render_user_constraints

Inventory = Callable[[Iterable[Path], Path], str]
WriteAssets = Callable[..., Path]


def build_stage_prompt(
    *, paths: dict[str, Path], stage_id: str,
    options: Optional[dict[str, Any]], revision_issues: Optional[list[str]],
    section_by_id: dict[str, Any], author_order: tuple[str, ...],
    inventory: Inventory, write_assets: WriteAssets,
) -> str:
    user_constraints = render_user_constraints(options)
    contracts = read_json(paths["contracts"])
    evidence = dict(contracts.get("evidence") or {})
    profile = read_json(paths["profile"]) or dict(contracts.get("manuscript_profile") or {})
    publication = dict(contracts.get("publication_style") or {})
    result_contract = next(
        (item for item in contracts.get("sections", [])
         if isinstance(item, dict) and item.get("id") == "results"), {}
    )
    result_roles = [str(item) for item in result_contract.get("required_moves", [])
                    if str(item).strip()]
    role_summary = ", ".join(result_roles) or (
        "primary estimate, controls, sensitivity, uncertainty, and negative cases"
    )
    archetype = str(profile.get("study_archetype") or "generic_empirical").casefold()
    authoring_assets = write_assets(
        paths["root"], paths["authoring_assets"],
        evidence_mode=str(evidence.get("mode") or "design_only"),
    )
    prompt = _base_prompt(
        paths, stage_id, options, evidence, profile, publication,
        authoring_assets, inventory,
    )
    prompt += _stage_prompt(
        paths, stage_id, contracts, evidence, profile, archetype, role_summary,
        section_by_id, author_order, inventory,
    )
    from .research_delivery_prompt import research_delivery_instruction
    prompt += research_delivery_instruction(options)
    if stage_id == "related_work":
        from .paper_citation_context import related_work_citation_context
        prompt += related_work_citation_context(paths["root"], int(profile.get("minimum_unique_citations") or 0))
    if evidence.get("mode") == "synthetic_preview" and stage_id != "experiments":
        prompt += _synthetic_manuscript_boundary()
    prompt += user_constraints
    if revision_issues:
        prompt += (
            "\nThe previous bounded draft failed local review. Resolve every issue "
            "in the target artifact and re-read it:\n"
            + "\n".join(f"- {item}" for item in revision_issues) + "\n"
        )
    return prompt


def _base_prompt(
    paths: dict[str, Path], stage_id: str, options: Optional[dict[str, Any]],
    evidence: dict[str, Any], profile: dict[str, Any], publication: dict[str, Any],
    authoring_assets: Path, inventory: Inventory,
) -> str:
    common = [
        paths["style"], paths["profile"], paths["contracts"], paths["blueprint"],
        paths["root"] / "paper" / "PAPER_PLAN.md",
        paths["root"] / "ideas" / "SELECTED_IDEA.json",
        paths["root"] / "experiments" / "METHOD_CONTRACT.json",
        paths["root"] / "experiments" / "EXPERIMENT_PLAN.md",
        paths["root"] / "experiments/src/models.py",
        paths["root"] / "experiments/src/objectives.py",
        paths["root"] / "experiments" / "results" / "analysis.md",
        paths["root"] / "experiments/results/simulated/SIMULATION_MANIFEST.json",
        paths["root"] / "experiments/results/simulated/reproducibility/scenario_parameters.json",
        paths["root"] / "experiments/results/simulated/reproducibility/generator_source.py",
        paths["root"] / "experiments/results/simulated/reproducibility/replay/REPLAY_VERIFICATION.json",
        paths["root"] / "experiments/results/simulated/reproducibility/replay/CONSTRUCTORS.md",
        paths["root"] / "NARRATIVE_REPORT.md",
        paths["root"] / "literature" / "survey.md",
        paths["paper"] / "references.bib", authoring_assets,
        paths["paper"] / "WRITING_REFERENCE_GUIDE.md",
    ]
    standards = ", ".join(
        str(item) for item in publication.get("reporting_standards", [])
    ) or "select the applicable standard from the project profile"
    requirements = "\n".join(
        f"- {item}" for item in publication.get("required_evidence", [])
    ) or "- Use the declared study design and its validity threats."
    return f"""Draft exactly one bounded stage of the manuscript.

Canonical project: {paths['root']}
Stage: {stage_id}
Target venue: {str((options or {}).get('target_venue') or 'unspecified')}
Evidence mode: {evidence.get('mode', 'design_only')}
Submission-eligible evidence: {bool(evidence.get('submission_eligible'))}

Existing authoritative inputs:
{inventory(common, paths['root'])}

Read PAPER_STYLE_PROFILE.json, SECTION_CONTRACTS.json, PAPER_PROFILE.json, and
CONTRIBUTION_BLUEPRINT.md when present. Word, citation, and asset roles are a
shared contract. Use exemplars only for structure; never copy their prose or
claims. Use verified keys from paper/references.bib. Do not invent citations,
datasets, sample counts, metrics, or results. Internal IDs, workflow gates,
artifact paths, and readiness status must not enter manuscript prose. Never
write paper/main.tex; deterministic assembly owns it. In every evidence mode,
do not add visible watermarks, draft stamps, warning banners or boxes, corner badges or ribbons,
status headers, or provenance caveats to manuscript text, captions, tables, or figures.

Full-paper profile: {profile.get('profile_id', 'scientific-protocol-v1')}
Research family: {profile.get('research_family', 'generic_quantitative')}
Study design: {profile.get('study_archetype', 'generic_empirical')}
Main-text target: {profile.get('main_text_words', [3500, 5500])}
Unique-citation minimum: {profile.get('minimum_unique_citations', 18)}
Domain reporting standards: {standards}
Domain evidence requirements:
{requirements}
Use the domain terminology and evidence conventions; do not force ML terms
when the profile calls for cohorts, controls, assays, interventions, proofs,
or coding comparisons.
"""


def _stage_prompt(
    paths: dict[str, Path], stage_id: str, contracts: dict[str, Any],
    evidence: dict[str, Any], profile: dict[str, Any], archetype: str,
    role_summary: str, section_by_id: dict[str, Any],
    author_order: tuple[str, ...], inventory: Inventory,
) -> str:
    if stage_id == "blueprint":
        return _blueprint_prompt(paths)
    if stage_id == "front_matter":
        return _front_matter_prompt(paths)
    if stage_id == "consistency":
        return _consistency_prompt(paths, evidence, profile)
    return _section_prompt(
        paths, stage_id, contracts, evidence, archetype, role_summary,
        section_by_id, author_order, inventory,
    )


def _blueprint_prompt(paths: dict[str, Path]) -> str:
    return f"""
Write only {paths['blueprint']}. Use these headings:
Research Question; Closest-Work Gap; One-Sentence Contribution; Mechanism Logic;
Claims and Required Evidence; Alternative Explanations; Section Narrative; and
Evidence Boundary. Explain how every contribution can be falsified. This is an
authoring artifact, not manuscript prose. Minimum 900 words. Each required
heading must occur exactly once. When repairing an existing blueprint, read it
and make focused edits under its existing headings; never duplicate a heading.
"""


def _front_matter_prompt(paths: dict[str, Path]) -> str:
    return f"""
Read every accepted section first. Write exactly:
- {paths['title']}: one specific title on one line, without TeX commands.
- {paths['sections'] / '00_abstract.tex'}: abstract body only, 150--250 words.
Use the measured word count in Write/Edit responses, not a self-estimated count.
If outside the required range, edit again within this invocation before finishing.
Aim around 180--220 words to leave room for necessary scope qualifiers.
State the problem, gap, mechanism, evidence scope, and strongest
provenance-backed finding; summarize the registered quantitative benchmark findings
at benchmark-bounded scope; do not call the paper a protocol, do not add provenance
or internal evidence-mode language to rendered prose. For other
non-submission-eligible modes, explicitly describe a preregistered study/protocol
and do not imply experiments occurred. Use no citations and no undefined acronyms.
"""


def _consistency_prompt(
    paths: dict[str, Path], evidence: dict[str, Any], profile: dict[str, Any]
) -> str:
    prompt = rf"""
Read paper/main.tex and every paper/sections/*.tex file. Inspect terminology and
acronym drift, citation keys, label/reference mismatches, unsupported claims,
duplicated prose, and contradictions in data, metrics, mechanisms, or evidence.
The manuscript must substantively use at least {profile.get('minimum_unique_citations', 5)}
distinct verified keys from paper/references.bib where relevant claims require them;
an unused bibliography key is not automatically relevant; do not create citation dumps.
You are the independent cross-section reviewer, not another section author.
Do not edit section files, table sources, bibliography entries or main.tex.
For every unresolved issue identify the exact responsible artifact and its producer.
For generated tables or figure projections use `Responsible runtime artifact:` with the canonical path;
do not assign the issue to a section merely because that section includes the artifact.
Use `Responsible authored section:` only for scientific prose authored in that section.
Write only {paths['cross_review']} with headings
Checks Performed, Edits Applied, Remaining Evidence Gaps, and Final Consistency
Verdict. State that edits are deferred to the responsible authors when applicable.
For each blocking numbered finding state `Responsible authored section:` or `Responsible runtime artifact:` and
`Required scientific repair:` and quote the precise current offending statement.
For visible-text claims, exclude LaTeX comments and unreachable historical projections.
Keep correctly disclosed limitations under Remaining
Evidence Gaps without treating them as requests to manufacture missing evidence.
PASS is allowed only when the current manuscript actually has no contradiction,
unresolved reference or citation gap; changing this report cannot pass a failed gate.
"""
    if evidence.get("mode") == "synthetic_preview":
        prompt += """
Describe simulation construction, synthetic inputs, fixed seeds and uncertainty
honestly wherever scientifically needed. Internal paths, workflow mode names,
preview badges and submission status remain outside scientific prose. The
end disclosure is supplementary and never replaces a reproducible Methods account.
Deterministic assembly appends exactly one
disclosure paragraph after the
Conclusion and before the bibliography.
"""
    from .paper_review_source_inventory import consistency_source_inventory
    return prompt + consistency_source_inventory(paths["root"])


def _section_prompt(
    paths: dict[str, Path], stage_id: str, contracts: dict[str, Any],
    evidence: dict[str, Any], archetype: str, role_summary: str,
    section_by_id: dict[str, Any], author_order: tuple[str, ...],
    inventory: Inventory,
) -> str:
    spec = section_by_id[stage_id]
    contract = next(
        (item for item in contracts.get("sections", [])
         if isinstance(item, dict) and item.get("id") == stage_id), {}
    )
    target = paths["sections"] / spec.filename
    previous = _previous_sections(paths, stage_id, section_by_id, author_order)
    prompt = rf"""
Write only {target}. Begin with \section{{{contract.get('title') or spec.title}}}.
If this file exists, read it first and revise only concrete failed requirements or
contradictions with current sources. Preserve verified formulas, evidence limitations,
citations and unaffected paragraphs. A changed upstream fingerprint alone is not a
request for a new chapter. Check actual experiments/src implementation before changing
an implemented input requirement or objective; distinguish planned capabilities from
implemented capabilities. Return without rewriting if no content defect needs repair.
Target {spec.minimum_words}--{spec.maximum_words} words and at least
{spec.minimum_citations} distinct verified citation keys.

Purpose:
{spec.purpose}

Required moves:
{chr(10).join(f'- {item}' for item in contract.get('required_moves', spec.required_moves))}

Required mechanisms:
{chr(10).join(f'- {item}' for item in contract.get('required_mechanisms', [])) or '- (none)'}

Previously accepted sections available for continuity:
{inventory(previous, paths['root'])}
"""
    prompt += _section_specific_prompt(stage_id, evidence, archetype, role_summary, root=paths["root"])
    return prompt


def _previous_sections(
    paths: dict[str, Path], stage_id: str, section_by_id: dict[str, Any],
    author_order: tuple[str, ...],
) -> list[Path]:
    position = author_order.index(stage_id)
    return [
        paths["sections"] / section_by_id[item].filename
        for item in author_order[:position] if item in section_by_id
    ]


def _section_specific_prompt(
    stage_id: str, evidence: dict[str, Any], archetype: str, role_summary: str, *, root: Path,
) -> str:
    if stage_id == "method":
        return _method_prompt(archetype)
    if stage_id == "experiments":
        return _experiments_prompt(evidence)
    if stage_id == "results":
        if evidence.get("mode") == "synthetic_preview":
            return _synthetic_results_prompt(archetype, role_summary, root=root)
        if not evidence.get("submission_eligible"):
            return _planned_results_prompt(role_summary)
        return _executed_results_prompt()
    return ""


def _method_prompt(archetype: str) -> str:
    freeze = {
        "algorithm_benchmark": "Freeze one primary implementable model or algorithm, input representation, objective, and inference formulation consistent with contract, configuration, and code.",
        "systems_testbed": "Freeze one concrete system design, component boundary, control policy, workload interface, and measurement path.",
        "observational_cohort": "Freeze cohort construction, estimand, adjustment set, missing-data strategy, and sensitivity specifications.",
        "formal_theory": "Freeze definitions, assumptions, construction, theorem statements, proof dependencies, and counterexample domain.",
        "qualitative_mixed": "Freeze sampling logic, corpus or cases, coding framework, interpretation, negative-case analysis, reflexivity, and triangulation.",
    }.get(archetype, "Freeze one concrete study method, analysis unit, controls, endpoints, and inferential procedure consistent with implementation and contracts.")
    return rf"""
Use the registered method figure when available: include
generated_method_figures and explain it in prose with its declared fig: label.
Reference the method-components table only when its manifest marks it as a
manuscript table. Never copy or reconstruct a registered table inside the section;
its canonical source is included exactly once by its declared placement. {freeze} Alternatives belong only in
named comparators, controls, sensitivity analyses, or boundary cases; do not
leave a menu such as "may use A or B" as the proposed method.
""" + _figure_scope_instruction()


def _experiments_prompt(evidence: dict[str, Any]) -> str:
    prompt = r"""
Use registered study-design and method-components tables when they exist.
Reference each in prose and explain the scientific comparison it controls.
Use registered evaluation figures only when present and explain their actual
visible scientific comparison using their declared public labels.
"""
    prompt += _figure_scope_instruction()
    if evidence.get("mode") == "synthetic_preview":
        prompt += r"""
Specify fixed evaluation seed, scenario construction, sampling logic,
comparison controls, uncertainty calculation, and endpoints for reproduction.
Explicitly identify these as simulation results. Explain the actual generator,
inputs, fixed parameters, comparator construction and interval procedure from
the registered sources. Do not describe generated seed summaries as trained EEG
measurements or subject-level bootstrap. Internal paths and submission status
remain sidecar metadata; the scientific data-generating process belongs here.
"""
    return prompt


def _figure_scope_instruction() -> str:
    return """
For every figure interpretation, Read the registered authoring asset's canonical
source_path (JSON/SVG or other declared source) and inspect its current figure.
Attribute only the objects, labels and relations actually visible in that
projection. Its caption, scientific question or full method contract is not
proof that an operation is drawn. Respect any declared covered/excluded scope;
internal component IDs guide source reading and must not appear in public prose.
When the figure is narrower than the full scientific method, preserve the
remaining scientific operations in separate equations or prose, without saying
that the figure depicts them. Do not invent, remove or redraw scientific content
to reconcile that difference.
"""


def _executed_results_prompt() -> str:
    return """
In executed mode, use only registered result tables and figures and interpret
uncertainty. Include complete results and analyze findings within the defined
benchmark rather than enumerating assets.
"""


def _planned_results_prompt(role_summary: str) -> str:
    return rf"""
This is a non-executed study draft. Present the registered evaluation protocol
and planned analyses, not findings. Do not include synthetic values, imagined
rankings, or outcome claims. Explain decision rules for these field-specific
roles: {role_summary}.
"""


def _synthetic_results_prompt(archetype: str, role_summary: str, *, root: Path) -> str:
    from .paper_asset_reference_contract import selected_reference_prompt
    references = selected_reference_prompt(root)
    return rf"""
This is the Results section of a complete benchmark study. Include and interpret
the registered field-specific result roles: {role_summary}. Read semantic roles
from manifests instead of forcing ML terminology. The complete evidence package
is distinct from the contribution-selected manuscript portfolio.
Do not describe assets as previews, placeholders, illustrative values, or
replacement targets. Include exactly \input{{synthetic_preview_figures}} and
\input{{tables/synthetic_preview_results}}. Discuss the selected registered references:
{references}
Use only these real labels. Do not infer a missing paired-comparison, error-analysis,
or efficiency table merely because the evidence package contains its CSV. Never
delete a scientifically necessary reference to pass review: route the missing
asset or unsupported claim to its responsible producer or section owner.
Analyze ordering, interval overlap, deltas, and uncertainty in the selected
method comparison at benchmark-bounded scope. Add progression trends, failure
slices, or performance--resource alternatives only when their scientific role
belongs to this selected manuscript portfolio. Interpret these as findings of
the defined benchmark, and do not add warning banners
or submission-status language. Do not
imply physical, clinical, field, or production measurements without independent
evidence.
"""


def _synthetic_manuscript_boundary() -> str:
    return """
Write a scientific manuscript with accurate simulation methodology and evidence
scope. Use simulation, simulated or synthetic where those words correctly name
the study design or data source; never disguise generated data as measured
outcomes. Exclude preview/draft badges, submission eligibility, internal mode
keys and repeated warning banners. The abstract, discussion, limitations and
conclusion must distinguish scenario findings from validated empirical claims.
"""
