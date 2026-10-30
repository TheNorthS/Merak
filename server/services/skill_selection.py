"""Policy mutations used to select one bounded workflow skill plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .figure_routing import normalize_illustration_mode


IMPLEMENTATION_FAMILIES = {
    "machine_learning", "computational_general", "external_protocol",
    "formal_verification",
}


def implementation_family(project_path: str, options: dict[str, Any]) -> str:
    configured = str(options.get("implementation_family") or "").strip().casefold()
    if configured in IMPLEMENTATION_FAMILIES:
        return configured
    path = Path(project_path).expanduser().resolve() / "experiments" / "IMPLEMENTATION_BLUEPRINT.json"
    if not path.exists():
        return "computational_general"
    try:
        blueprint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Implementation blueprint is unreadable: {path}") from exc
    if not isinstance(blueprint, dict):
        raise RuntimeError(f"Implementation blueprint root must be an object: {path}")
    return str(blueprint.get("implementation_family") or "computational_general").strip().casefold()


def apply_family_specialists(
    node_id: str,
    family: str,
    specialists: list[str],
    reasons: list[str],
) -> list[str]:
    if node_id not in {"exp-design", "exp-run", "results"}:
        return specialists
    routes = {
        "formal_verification": (
            ["formula-derivation", "proof-checker", "experiment-audit", "result-to-claim"],
            "formal verification uses proof obligations, counterexamples, and bound audits",
        ),
        "external_protocol": (
            ["experiment-plan", "research-review", "result-to-claim", "experiment-audit"],
            "external protocol uses population/corpus, bias, estimand/coding, and negative-case audits",
        ),
        "computational_general": (
            ["experiment-plan", "formula-derivation", "experiment-audit", "result-to-claim"],
            "computational research uses algorithm, sensitivity, stability, and resource audits",
        ),
    }
    route = routes.get(family)
    if route:
        reasons.append(route[1])
        return route[0]
    return specialists


def apply_feature_specialists(
    node_id: str,
    specialists: list[str],
    reasons: list[str],
    options: dict[str, Any],
) -> list[str]:
    if str(options.get("research_mode") or "from_scratch") == "paper_code_innovation" and node_id in {"idea", "novelty", "exp-design"}:
        specialists.insert(0, "prior-art-search")
        reasons.append("reference-paper/code innovation requires explicit nearest-work delta")
    if options.get("enable_patent_search") and node_id == "novelty":
        specialists = ["patent-novelty-check", "prior-art-search", *specialists]
        reasons.append("patent search enabled; novelty must include non-paper prior art")
    if options.get("enable_meta_optimization") and node_id in {"review", "audit"}:
        specialists = ["meta-optimize", *specialists]
        reasons.append("self-optimization enabled in proposal-only, human-approved mode")
    strategy = dict(options.get("research_strategy") or {})
    if str(strategy.get("evidence_policy") or "") == "systematic" and node_id in {"lit", "novelty"}:
        specialists.append("openalex")
        reasons.append("systematic evidence policy adds a bibliographic coverage specialist")
    return specialists


def apply_execution_mode(
    node_id: str,
    family: str,
    specialists: list[str],
    reasons: list[str],
    options: dict[str, Any],
) -> list[str]:
    if options.get("run_experiment") is True:
        return specialists
    if node_id == "exp-run":
        specialists = [
            "experiment-plan",
            "training-check" if family == "machine_learning" else "research-review",
            "experiment-audit",
        ]
        reasons.append("execution disabled; specialize in family-appropriate runnable design and static integrity")
    if node_id in {"results", "figure"}:
        from .results_execution_policy import PLANNED_RESULTS_RUNTIME, resolve_results_execution_policy

        policy = resolve_results_execution_policy(options)
        reasons.append(policy.reason)
        if policy.runtime_service == PLANNED_RESULTS_RUNTIME and not policy.issues:
            specialists.append("experiment-plan")
    return specialists


def figure_owner(
    node_id: str,
    primary: str,
    available: set[str],
    reasons: list[str],
    options: dict[str, Any],
    *,
    project_path: str | Path | None = None,
) -> str:
    if node_id != "figure":
        return primary
    illustration_mode = normalize_illustration_mode(options.get("illustration_mode"))
    if node_id == "figure" and project_path:
        from .figure_execution_policy import resolve_figure_execution_policy

        policy = resolve_figure_execution_policy(project_path)
        reasons.append(policy.reason)
        if policy.kind == "runtime_owned":
            return primary
        if policy.model_skills:
            owner = policy.model_skills[0]
            if not available or owner in available:
                return owner
    evidence_mode = str(options.get("non_experiment_evidence_mode") or "design_only").strip().casefold()
    if options.get("run_experiment") is True or evidence_mode in {"existing_results", "secondary_analysis"}:
        return primary
    owner = {
        "auto": "rich-svg-figure", "figurespec": "rich-svg-figure",
        "gemini": "paper-illustration", "mermaid": "mermaid-diagram",
    }.get(illustration_mode)
    if owner and (not available or owner in available):
        reasons.append(
            "no real quantitative evidence; skip /paper-figure Phase 2a "
            f"and execute Phase 2b with /{owner}"
        )
        return owner
    if illustration_mode == "false":
        reasons.append(
            "no real quantitative evidence and Phase 2b disabled; "
            "/paper-figure is plan-only and must not create a data plot"
        )
    return primary


def apply_venue_and_assurance(
    node_id: str,
    specialists: list[str],
    validators: list[str],
    reasons: list[str],
    options: dict[str, Any],
) -> None:
    venue = str(options.get("target_venue") or "").strip().casefold()
    if node_id == "paper" and venue in {"osdi", "sosp", "asplos", "nsdi", "eurosys"}:
        specialists.insert(0, "writing-systems-papers")
        reasons.append("systems venue selected; add the systems-paper structural specialist")
    if str(options.get("assurance") or "") in {"conference-ready", "submission"}:
        validators.extend(["citation-audit", "proof-checker"])
        reasons.append("submission assurance adds independent citation/proof validation")
