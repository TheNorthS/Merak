"""Composition of delivery readiness from independently validated artifacts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .scientific_evidence import scientific_evidence_service
from .simulation_policy import is_complete_evidence_mode


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _accepted(phase: Any) -> bool:
    return isinstance(phase, dict) and str(
        phase.get("status") or ""
    ).casefold() in {"accepted", "completed"}


def _request_context(
    state: dict[str, Any],
    submission_phases: tuple[str, ...],
) -> dict[str, Any]:
    phases = state.get("phases")
    phases = phases if isinstance(phases, dict) else {}
    config = state.get("config")
    config = config if isinstance(config, dict) else {}
    options = config.get("options")
    options = options if isinstance(options, dict) else {}
    incomplete = [
        phase_id for phase_id, phase in phases.items() if not _accepted(phase)
    ]
    missing = [
        phase_id for phase_id in submission_phases
        if not _accepted(phases.get(phase_id))
    ]
    mode = "executed" if options.get("run_experiment") is True else str(
        options.get("non_experiment_evidence_mode") or "design_only"
    ).casefold()
    return {
        "phases": phases,
        "options": options,
        "selected_phase_ids": list(phases),
        "incomplete_selected": incomplete,
        "missing_submission_phases": missing,
        "execution_completed": bool(phases) and not incomplete,
        "evidence_mode": mode,
        "assurance": str(config.get("assurance") or "draft").casefold(),
    }


def _request_blockers(
    context: dict[str, Any],
    asset_plan: dict[str, Any],
    paper_build: dict[str, Any],
    review_state: dict[str, Any],
    empirical_modes: set[str],
) -> list[str]:
    mode = context["evidence_mode"]
    blockers: list[str] = []
    declared = {
        "scientific asset plan": str(asset_plan.get("evidence_mode") or "").casefold(),
        "paper build": str(paper_build.get("evidence_mode") or "").casefold(),
        "review state": str(review_state.get("evidence_mode") or "").casefold(),
    }
    for source, declared_mode in declared.items():
        if not declared_mode:
            blockers.append(f"{source} does not declare an evidence mode")
        elif declared_mode != mode:
            blockers.append(
                f"{source} evidence mode {declared_mode} does not match requested mode {mode}"
            )
    if context["incomplete_selected"]:
        blockers.append(
            "selected workflow phases are not accepted: "
            + ", ".join(context["incomplete_selected"])
        )
    if context["missing_submission_phases"]:
        blockers.append(
            "submission workflow phases are missing or unaccepted: "
            + ", ".join(context["missing_submission_phases"])
        )
    if mode not in empirical_modes:
        blockers.append(f"evidence mode {mode or 'unspecified'} is not submission-eligible")
    if context["assurance"] not in {"conference-ready", "submission"}:
        blockers.append("the run did not use conference-ready or submission assurance")
    if asset_plan.get("submission_eligible") is not True:
        blockers.append("scientific asset plan is not marked submission-eligible")
    if paper_build.get("submission_eligible") is not True:
        blockers.append("paper build is not marked submission-eligible")
    if review_state.get("publication_ready") is not True:
        blockers.append("independent review did not mark the manuscript publication-ready")
    return blockers


def _figure_attestation(root: Path) -> tuple[list[str], dict[str, Any]]:
    from .figure_artifacts import figure_artifact_registry

    valid, issues, manifest = figure_artifact_registry.validate(root / "figures")
    blockers = [f"scientific figure bundle: {issue}" for issue in issues]
    return blockers, {
        "valid": valid,
        "manifest_valid": valid,
        "issue_count": len(issues),
        "figure_count": len(manifest.get("figures") or []),
        "paper_ready_count": sum(
            1 for item in manifest.get("figures") or []
            if isinstance(item, dict) and item.get("paper_ready") is True
        ),
    }


def _review_and_audit(
    service: Any,
    root: Path,
    state: dict[str, Any],
    mode: str,
    review_state: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any], dict[str, Any]]:
    run_id = str(state.get("run_id") or "")
    review_issues, review = service._review_issues(
        root, review_state, run_id=run_id, evidence_mode=mode
    )
    review.update({
        "valid": review_state.get("publication_ready") is True and not review_issues,
        "issue_count": len(review_issues),
        "publication_ready": review_state.get("publication_ready") is True,
    })
    audit_issues, _entries, audit = service._audit_issues(
        root,
        run_id=run_id,
        evidence_mode=mode,
        executor_model=str(review.get("executor_model") or ""),
    )
    blockers = [*review_issues, *audit_issues, *(audit.get("blocking_issues") or [])]
    advisories = list(audit.get("advisories") or [])
    audit.update({
        "valid": audit.get("accepted") is True,
        "issue_count": len(audit_issues) + len(audit.get("blocking_issues") or []),
    })
    return blockers, advisories, review, audit


def _artifact_checks(
    service: Any,
    root: Path,
    state: dict[str, Any],
    context: dict[str, Any],
    paper_build: dict[str, Any],
    review_state: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    blockers, figures = _figure_attestation(root)
    paper_issues, paper = service._paper_build_issues(root, paper_build)
    paper.update({"valid": not paper_issues, "issue_count": len(paper_issues)})
    blockers.extend(paper_issues)
    review_blockers, advisories, review, audit = _review_and_audit(
        service, root, state, context["evidence_mode"], review_state
    )
    blockers.extend(review_blockers)
    return blockers, advisories, {
        "figures": figures,
        "paper": paper,
        "review": review,
        "audit": audit,
    }


def _evidence_checks(
    root: Path,
    mode: str,
    empirical_modes: set[str],
) -> tuple[list[str], dict[str, Any]]:
    if mode not in empirical_modes or mode == "synthetic_preview":
        return [], {}
    valid, issues, details = scientific_evidence_service.validate_executed_metrics(root)
    return (
        [] if valid else [f"scientific evidence: {issue}" for issue in issues],
        details,
    )


def _classification(
    context: dict[str, Any],
    blockers: list[str],
    simulation: dict[str, Any],
) -> tuple[bool, str, str]:
    execution_completed = context["execution_completed"]
    mode = context["evidence_mode"]
    if (context["options"].get("delivery_goal") == "reviewable_draft" and execution_completed
            and not context["missing_submission_phases"] and "ppt" in context["selected_phase_ids"]):
        if context.get("draft_integrity_valid") is True:
            return False, "reviewable_draft_ready", "Reviewable scientific draft complete; submission not approved"
        return False, "evidence_blocked", "Draft delivery blocked by current artifact integrity checks"
    ready = execution_completed and is_complete_evidence_mode(mode) and not blockers
    if ready:
        return True, "submission_ready", "Submission candidate ready"
    if execution_completed and not context["missing_submission_phases"]:
        if mode in {"design_only", "planned", "execution_pending"}:
            return False, "protocol_ready", "Research protocol draft ready"
        if mode == "synthetic_preview" and simulation.get("valid") is True:
            return False, "synthetic_preview_ready", "Deterministic benchmark manuscript ready"
        return False, "evidence_blocked", "Workflow complete; submission evidence blocked"
    if execution_completed:
        return False, "partial_workflow_complete", "Selected workflow phases complete"
    return False, "incomplete", "Workflow incomplete"


def assess_workflow_readiness(
    service: Any,
    project_path: str | Path,
    run_state: dict[str, Any] | None,
    *,
    persist: bool,
    submission_phases: tuple[str, ...],
    empirical_modes: set[str],
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    state = run_state if isinstance(run_state, dict) else {}
    context = _request_context(state, submission_phases)
    asset_plan = _read_json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
    paper_build = _read_json(root / "paper" / "PAPER_BUILD.json")
    review_state = _read_json(root / "review-stage" / "REVIEW_STATE.json")
    blockers = _request_blockers(
        context, asset_plan, paper_build, review_state, empirical_modes
    )
    simulation: dict[str, Any] = {"applicable": False, "valid": True, "issue_count": 0}
    if context["evidence_mode"] == "synthetic_preview":
        simulation_issues, simulation = service._simulation_package_issues(root)
        simulation["applicable"] = True
        blockers.extend(f"simulation package: {issue}" for issue in simulation_issues)
    artifact_blockers, advisories, attestations = _artifact_checks(
        service, root, state, context, paper_build, review_state
    )
    blockers.extend(artifact_blockers)
    evidence_blockers, evidence_details = _evidence_checks(
        root, context["evidence_mode"], empirical_modes
    )
    blockers.extend(evidence_blockers)
    if context["options"].get("delivery_goal") == "reviewable_draft" and context["execution_completed"]:
        from .draft_readiness import draft_delivery_integrity
        draft = draft_delivery_integrity(root, state, context, attestations, simulation, review_state)
        attestations["draft_integrity"] = draft
        context["draft_integrity_valid"] = draft["valid"]
        blockers.extend(draft["issues"])
    blockers = list(dict.fromkeys(blockers))
    ready, completion_class, label = _classification(context, blockers, simulation)
    report = _report(
        service, root, state, context, blockers, advisories, attestations,
        simulation, evidence_details, ready, completion_class, label,
    )
    if persist:
        atomic_write_json(root / service.report_path, report)
    return report


def _report(
    service: Any,
    root: Path,
    state: dict[str, Any],
    context: dict[str, Any],
    blockers: list[str],
    advisories: list[str],
    attestations: dict[str, Any],
    simulation: dict[str, Any],
    evidence_details: dict[str, Any],
    ready: bool,
    completion_class: str,
    label: str,
) -> dict[str, Any]:
    pdf = root / "paper" / "main.pdf"
    return {
        "schema": service.schema_version,
        "run_id": str(state.get("run_id") or ""),
        "execution_completed": context["execution_completed"],
        "submission_ready": ready,
        "delivery_goal": context["options"].get("delivery_goal", "submission_candidate"),
        "publication_ready": ready,
        "completion_class": completion_class,
        "label": label,
        "evidence_mode": context["evidence_mode"],
        "assurance": context["assurance"],
        "selected_phase_ids": context["selected_phase_ids"],
        "missing_submission_phases": context["missing_submission_phases"],
        "submission_blockers": blockers,
        "submission_advisories": list(dict.fromkeys(advisories)),
        "evidence_details": evidence_details,
        "attestations": {**attestations, "simulation": simulation},
        "paper_pdf": "paper/main.pdf" if pdf.is_file() and pdf.stat().st_size > 0 else "",
        "readiness_input_sha256": service.input_fingerprint(root, state),
        "evaluated_at": time.time(),
    }
