"""Pure evidence-bounded Markdown composition for the narrative stage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .narrative_evidence import (
    benchmark_description_lines, claim_decision, current_narrative_evidence, protocol_narrative_lines,
)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _text(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return ""


def clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").replace("|", "/").split())[:limit]


def narrative_context(root: Path, research_direction: str) -> dict[str, Any]:
    selected = _json(root / "ideas" / "SELECTED_IDEA.json")
    method = _json(root / "experiments" / "METHOD_CONTRACT.json")
    manifest = _json(
        root / "experiments" / "results" / "templates" / "PLANNED_RESULT_MANIFEST.json"
    )
    evidence_mode = str(manifest.get("evidence_mode") or "planned").strip().casefold()
    return {
        "title": clean(selected.get("title") or research_direction or "Selected research idea", 500),
        "problem": clean(selected.get("problem_statement") or "The frozen research contract identifies a concrete unresolved scientific problem.", 1600),
        "hypothesis": clean(selected.get("hypothesis") or "The selected mechanism has a measurable consequence that remains to be tested.", 1600),
        "claims": [item for item in selected.get("claims") or [] if isinstance(item, dict)],
        "mechanisms": [item for item in selected.get("mechanisms") or [] if isinstance(item, dict) and item.get("required", True)],
        "claim_plans": {
            str(item.get("idea_claim_id") or ""): item
            for item in method.get("claim_evidence_plan") or []
            if isinstance(item, dict) and item.get("idea_claim_id")
        },
        "falsification": [clean(item, 1600) for item in selected.get("falsification_conditions") or [] if clean(item, 1600)],
        "analysis": _text(root / "experiments" / "results" / "analysis.md"),
        "evidence_mode": evidence_mode,
        "executed": evidence_mode in {"executed", "existing_results", "secondary_analysis"},
        "synthetic": evidence_mode == "synthetic_preview",
        **current_narrative_evidence(root, synthetic=evidence_mode == "synthetic_preview"),
    }


def _mechanism_lines(context: dict[str, Any]) -> list[str]:
    mechanisms = context["mechanisms"]
    if not mechanisms:
        return ["- The implementation mechanism is not yet frozen in a machine-readable contract."]
    return [
        f"- **{clean(item.get('id'), 40)} - {clean(item.get('name'), 300)}:** {clean(item.get('description'), 1400)}"
        for item in mechanisms
    ]


def _claim_lines(context: dict[str, Any]) -> list[str]:
    claims = context["claims"] or [{"id": "C1", "statement": context["hypothesis"]}]
    rows: list[str] = []
    for index, claim in enumerate(claims):
        claim_id = clean(claim.get("id") or f"C{index + 1}", 50)
        status, decision_reason = claim_decision(context, claim_id) if context["synthetic"] else (
            "REQUIRES_RESULT_AUDIT" if context["executed"] else "PENDING_NOT_EXECUTED", "")
        plan = context["claim_plans"].get(str(claim.get("id") or ""), {})
        outcomes = [clean(item, 700) for item in plan.get("outcomes") or [] if clean(item, 700)]
        failures = [clean(item, 700) for item in plan.get("failure_conditions") or [] if clean(item, 700)]
        required = "; ".join(outcomes[:2]) or (
            "Registered comparison within the deterministic benchmark"
            if context["synthetic"] else "Runtime-owned comparison under the frozen evaluation protocol"
        )
        falsification = context["falsification"]
        rejection = failures[0] if failures else (
            falsification[min(index, len(falsification) - 1)] if falsification
            else "Reject or narrow the claim when the prespecified criterion is not met"
        )
        if decision_reason:
            required += "; current decision: " + clean(decision_reason, 2000)
        rows.append(f"| {claim_id}: {clean(claim.get('statement') or claim.get('claim'), 700)} | {status} | {required} | {rejection} |")
    return rows


def _finding_lines(context: dict[str, Any]) -> list[str]:
    if context["synthetic"]:
        return [
            "BENCHMARK_RESULT_REVIEW is a descriptive evidence track, not a supported-claim verdict. "
            "Registered scientific claims remain subject to their individual current decisions above.", "",
            *benchmark_description_lines(context), "", *protocol_narrative_lines(context), "",
            "Benchmark scope does not establish that the registered research protocol was executed. "
            "Neither historical analysis prose nor legacy support labels can override unresolved claim decisions.",
        ]
    if context["executed"]:
        return [
            "Machine-readable result artifacts are present, but this narrative does not independently promote them to supported claims. Claim status remains subject to provenance, split, uncertainty, and result-to-claim audit.",
            "", clean(context["analysis"], 2200) or "The result analysis artifact is currently unavailable.",
            *protocol_narrative_lines(context),
        ]
    return [
        "The experiment was not executed in this workflow. No accuracy, effect size, significance, superiority, robustness, or calibration conclusion is currently supported. Existing schemas and planning previews are NOT EVIDENCE.",
        *protocol_narrative_lines(context),
    ]


def _ending_lines(context: dict[str, Any]) -> list[str]:
    if context["synthetic"]:
        limitations = [
            "External validity is bounded by the registered benchmark scenarios, parameter ranges, response functions, and uncertainty widths.",
            "Stress, error-slice and resource conclusions require their own bound measurements; a focal method need not lead the primary endpoint.",
            "Independent measurements and broader generator families are required before extending a current verified table ordering beyond the benchmark.",
        ]
        meaning = "The current artifact describes a deterministic benchmark evidence track, not proof that "
        meaning += "the registered research was executed or that every scientific claim is supported. "
        meaning += "Resolve each UNRESOLVED claim through its source-bound decision rule and address the protocol "
        meaning += "readiness findings before drawing a stronger conclusion; no training or execution is authorized by this narrative."
    else:
        limitations = [
            "The current artifact state cannot establish empirical effectiveness unless runtime-owned metrics, predictions, seeds, splits, and uncertainty estimates pass audit.",
            "The selected mechanism may be unnecessary if a matched simpler control performs equivalently.",
            "Leakage, dependent samples, unfair tuning, incomplete prior-art coverage, or implementation drift can invalidate the intended contribution.",
        ]
        meaning = "The current contribution describes a proposed auditable research protocol, not proof of protocol-conformant implementation or a validated performance claim. Resolve readiness gaps and obtain explicit execution authorization before testing the frozen primary comparison and controls; preserve immutable provenance and classify every claim by its current evidence."
    falsification = context["falsification"] or [
        "The strongest matched control explains the effect.",
        "The locked primary evaluation does not meet its decision criterion.",
    ]
    return [
        "## Limitations and Threats to Validity", "",
        *[f"- {item}" for item in limitations], "",
        "## Falsification and Pivot Conditions", "",
        *[f"- {item}" for item in falsification], "",
        "## Meaning and Next Evidence Actions", "", meaning,
    ]


def render_narrative(context: dict[str, Any]) -> str:
    lines = [
        f"# Research Narrative: {context['title']}", "",
        "## Motivation and Research Position", "", context["problem"], "",
        f"The frozen hypothesis is: **{context['hypothesis']}**", "",
        "## Method and Mechanism Logic", "", *_mechanism_lines(context), "",
        "## Experiment and Falsification Logic", "",
        "The experiment design must isolate each required mechanism from matched controls, preserve the declared independent analysis unit, and reject leakage before interpreting any metric.", "",
        "| Claim | Current evidence status | Required decisive evidence | Rejection or narrowing rule |",
        "|---|---|---|---|", *_claim_lines(context), "",
        "## Findings and Evidence Boundary", "", *_finding_lines(context), "",
        "## Scientific Assets and Argument Role", "",
        "- Claim-bearing figures are generated in the next workflow stage from the frozen claims, method contract, result analysis, and this narrative.", "",
        *_ending_lines(context),
    ]
    return "\n".join(lines) + "\n"
