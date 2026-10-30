"""Pure Markdown projections for the canonical manuscript plan."""

from __future__ import annotations

from typing import Any, Callable


Cleaner = Callable[[Any, int], str]


def claims_table(
    claims: list[dict[str, Any]],
    claim_plans: dict[str, dict[str, Any]],
    evidence_mode: str,
    clean: Cleaner,
) -> list[str]:
    lines = [
        "## Claims-Evidence Matrix", "",
        "| Internal claim | Manuscript claim | Decisive evidence | Maturity |",
        "|---|---|---|---|",
    ]
    if not claims:
        lines.append("| pending | Define the primary falsifiable claim | Bind it to a decisive comparison | pending |")
        return lines
    for index, claim in enumerate(claims, start=1):
        claim_id = clean(claim.get("id") or f"claim-{index}", 80)
        statement = clean(
            claim.get("statement") or claim.get("description") or claim.get("name"),
            1000,
        )
        plan = claim_plans.get(claim_id, {})
        outcomes = plan.get("outcomes") if isinstance(plan.get("outcomes"), list) else []
        evidence = "; ".join(clean(item, 300) for item in outcomes if clean(item, 300))
        if not evidence:
            evidence = "Matched main comparison, uncertainty, and declared falsification test"
        maturity = "benchmark-supported" if evidence_mode == "synthetic_benchmark" else clean(plan.get("evidence_status") or evidence_mode, 100)
        lines.append(f"| {claim_id} | {statement} | {evidence} | {maturity} |")
    return lines


def mechanism_section(
    mechanisms: list[dict[str, Any]],
    clean: Cleaner,
) -> list[str]:
    lines = ["## Method and Mechanism Contract", ""]
    if not mechanisms:
        lines.append("- The manuscript must formalize the selected mechanism before making a performance claim.")
        return lines
    for mechanism in mechanisms:
        name = clean(mechanism.get("name") or mechanism.get("id") or "Mechanism", 1000)
        description = clean(
            mechanism.get("description") or mechanism.get("rationale"), 1000
        )
        lines.append(f"- **{name}:** {description}")
    return lines


def section_plan(section_pages: dict[str, float]) -> list[str]:
    sections = [
        ("Abstract", "State the problem, mechanism, contribution, evidence maturity, and strongest bounded conclusion."),
        ("Introduction", "Motivate the scientific gap, position nearest work, and state falsifiable contributions."),
        ("Related Work", "Synthesize methodological families and isolate the claim-level novelty delta."),
        ("Method", "Define the study objects, mechanism or analytical framework, assumptions, procedure, and reproducibility boundary."),
        ("Experiments", "Prespecify analysis units, sampling or separation, controls or comparators, endpoints, uncertainty, validity checks, and failure criteria."),
        ("Results and Discussion", "Report only provenance-backed outcomes; otherwise retain planned analyses and replacement slots."),
        ("Limitations", "Describe alternative explanations, scope limits, negative evidence, and deployment risks."),
        ("Conclusion", "Restate only claims supported at the current evidence maturity."),
    ]
    lines = ["## Section Plan", ""]
    for section, purpose in sections:
        pages = section_pages.get(section)
        budget = f" (about {pages:g} pages)" if pages else ""
        lines.extend((f"### {section}{budget}", "", purpose, ""))
    return lines


def asset_table(
    assets: list[dict[str, Any]],
    evidence_mode: str,
    clean: Cleaner,
) -> list[str]:
    lines = [
        "## Figure and Table Plan", "",
        "| Asset | Type | Scientific question | Evidence state |",
        "|---|---|---|---|",
    ]
    if not assets:
        return lines + [
            "| method_architecture | figure | How does the proposed mechanism operate? | design contract |",
            "| main_comparison | table/figure | Does the primary claim survive matched controls? | pending |",
        ]
    for item in assets[:12]:
        asset_id = clean(item.get("id") or item.get("name") or "asset", 100)
        kind = clean(item.get("kind") or "figure", 60)
        question = clean(
            item.get("scientific_question") or item.get("purpose")
            or item.get("caption")
            or "Connect the selected mechanism to a decisive comparison",
            1000,
        )
        state = clean(item.get("evidence_status") or evidence_mode, 100)
        lines.append(f"| {asset_id} | {kind} | {question} | {state} |")
    return lines


def evidence_gap_section(
    selected: dict[str, Any],
    evidence_mode: str,
    narrative_present: bool,
    clean: Cleaner,
) -> list[str]:
    raw_conditions = selected.get("falsification_conditions")
    conditions = [
        clean(item, 1000) for item in raw_conditions
        if clean(item, 1000)
    ] if isinstance(raw_conditions, list) else []
    lines = ["## Evidence Gaps and Falsification", ""]
    lines.extend(conditions or [
        "- Define an operational rejection, counterexample, or disconfirmation condition for every principal claim."
    ])
    if conditions:
        lines[-len(conditions):] = [f"- {item}" for item in conditions]
    if evidence_mode == "pending":
        lines.append("- Experiments are not yet executed; preview values and placeholder assets are not manuscript evidence.")
    if narrative_present:
        lines.append("- Reconcile the final prose with NARRATIVE_REPORT.md without importing internal workflow narration.")
    return lines + [
        "- Verify every citation key against literature/references.bib and remove uncited inventory entries.",
        "- Keep internal claim IDs in this plan and audit sidecars; write domain-facing prose in the submission manuscript.",
        "", "## Completion Criteria", "",
        "- Every contribution maps to evidence, counterevidence, and a maturity label.",
        "- Every figure answers a manuscript question and has an editable source plus rendered output.",
        "- Page count remains a soft planning target; scientific completeness and evidence integrity take priority.",
    ]
