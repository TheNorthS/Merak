"""Compose node-specific gates and deterministic verifier layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .acceptance_context import AcceptanceContext


def node_specific_gate(context: AcceptanceContext) -> dict[str, Any] | None:
    host, node, run = context.host, context.node, context.run
    if node.id == "figure":
        return host._figure_acceptance_gate(run.project_path)
    if node.id == "paper":
        return host._paper_acceptance_gate(
            run.project_path,
            require_innovation=context.innovation_mode,
            require_page_budget=True,
            require_staged=True,
            paper_options=context.options,
        )
    if node.id == "review":
        return host._review_acceptance_gate(
            run.project_path,
            review_started_at=node.started_at if context.require_fresh else None,
            **({"delivery_goal": context.options["delivery_goal"]} if context.options.get("delivery_goal") else {}),
        )
    if node.id == "audit":
        mode = (
            "executed"
            if context.options.get("run_experiment") is True
            else str(
                context.options.get("non_experiment_evidence_mode") or "design_only"
            )
        )
        return host._audit_acceptance_gate(
            run.project_path,
            context.assurance,
            context.result,
            evidence_mode=mode,
            run_id=run.id,
            **({"delivery_goal": context.options["delivery_goal"]} if context.options.get("delivery_goal") else {}),
        )
    return None


def _reviewer_summary(context: AcceptanceContext) -> tuple[str, str]:
    if (
        context.node.id == "exp-run"
        and context.options.get("run_experiment") is not True
    ):
        return (
            "deterministic:code-check-only",
            "Experiment execution was disabled; code and config artifacts were verified instead.",
        )
    if context.node.id == "exp-run":
        gate = context.managed_output_gate
        return (
            str(
                gate.get("reviewer")
                or "deterministic:managed-experiment-output-contract"
            ),
            str(
                gate.get("summary")
                or "Managed experiment outputs and provenance were verified."
            ),
        )
    return (
        "deterministic:artifact-exists",
        f"Verified required artifact(s) for {context.node.id}.",
    )


def generic_artifact_gate(context: AcceptanceContext) -> dict[str, Any]:
    host, node, run = context.host, context.node, context.run
    integrity = None
    if node.id in {"exp-design", "exp-run"}:
        integrity = host._experiment_code_integrity_gate(run.project_path)
        if not integrity.get("passed"):
            return {
                "accepted": False,
                "reason": "experiment code integrity failed",
                "summary": "; ".join(integrity.get("issues", [])[:8]),
                "details": {"code_integrity": integrity},
            }
    reviewer, summary = _reviewer_summary(context)
    mode = (
        "content-baseline"
        if context.content_baseline is not None
        else ("mtime" if context.freshness_since is not None else "validation-only")
    )
    return {
        "accepted": True,
        "verdict_id": host._verdict_id(f"artifact:{node.id}", context.requirements),
        "reviewer": reviewer,
        "summary": summary,
        "details": {
            "artifacts": [str(path) for path in context.requirements],
            "fresh_since": context.freshness_since,
            "freshness_mode": mode,
            "code_integrity": integrity,
            "profile_specialists": context.specialist_gate,
            "managed_experiment_outputs": (
                context.managed_output_gate.get("details", {})
                if node.id == "exp-run"
                and context.options.get("run_experiment") is True
                else None
            ),
        },
    }


def method_alignment_gate(
    context: AcceptanceContext,
    gate: dict[str, Any],
) -> dict[str, Any]:
    if context.node.id != "exp-design" or not gate.get("accepted"):
        return gate
    direction = str(
        context.run_state.get("config", {}).get("direction")
        or context.options.get("research_direction")
        or ""
    )
    alignment = context.host._exp_design_method_alignment_gate(context.run, direction)
    if not alignment.get("accepted"):
        return alignment
    details = alignment.get("details")
    details = details if isinstance(details, dict) else {}
    gate.setdefault("details", {})["method_alignment"] = details
    gate["details"]["implementation_contract"] = dict(
        details.get("implementation_contract") or {}
    )
    gate["summary"] = (
        str(gate.get("summary") or "") + " " + str(alignment.get("summary") or "")
    ).strip()
    return gate


def novelty_contract_gate(
    context: AcceptanceContext,
    gate: dict[str, Any],
) -> dict[str, Any]:
    if not gate.get("accepted") or context.node.id != "novelty":
        return gate
    from ..services.method_contract import method_contract_service

    selected = context.host._extract_selected_idea(
        Path(context.run.project_path),
        context.result,
        str(context.options.get("research_direction") or ""),
    )
    passed, issues, details = method_contract_service.validate_selected_idea(
        context.run.project_path,
        selected,
    )
    if not passed:
        return {
            "accepted": False,
            "reason": "selected idea contract is incomplete or inconsistent",
            "summary": "; ".join(issues[:8]),
            "details": details,
        }
    gate.update(
        {
            "verdict_id": context.host._verdict_id(
                "selected-idea-contract", context.requirements
            ),
            "reviewer": "deterministic:selected-idea-contract",
            "summary": f"Accepted and froze the selected idea contract: {selected}.",
        }
    )
    gate.setdefault("details", {}).update(
        {
            "selected_idea_contract": details,
            "selected_idea_contract_sha256": details["sha256"],
        }
    )
    return gate
