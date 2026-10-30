"""Revalidate persisted accepted phases and invalidate their dependent closure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .engine_context import (
    TERMINAL_PHASE_STATES,
    logger,
)
from .models import WorkflowNode, WorkflowRun
from .run_state import RunState
from .artifact_snapshot_ownership import owner_snapshot_view


class AcceptedPhaseHost(Protocol):
    def _get_default_nodes(self) -> list[WorkflowNode]: ...
    def _risk_audit_validator_signature(self, options: dict[str, Any]) -> str: ...
    def _artifact_snapshot_issues(
        self, project_path: str, snapshot: Any
    ) -> list[str]: ...
    def _managed_experiment_acceptance_gate(
        self, run: WorkflowRun, options: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass
class AcceptedPhaseAudit:
    phases: dict[str, dict[str, Any]]
    definitions: dict[str, WorkflowNode]
    accepted: set[str]
    issues: dict[str, list[str]] = field(default_factory=dict)
    risk_refreshes: dict[str, dict[str, Any]] = field(default_factory=dict)


def _managed_run_issues(
    host: AcceptedPhaseHost,
    run: WorkflowRun,
) -> list[str]:
    """Check runtime-owned evidence without rebinding previously accepted files."""
    gate = host._managed_experiment_acceptance_gate(run, run.options)
    if not gate.get("accepted"):
        gate_details = gate.get("details")
        gate_details = gate_details if isinstance(gate_details, dict) else {}
        issues = [
            str(item) for item in gate_details.get("issues", []) if str(item).strip()
        ]
        return issues or [
            str(
                gate.get("summary")
                or gate.get("reason")
                or "managed experiment evidence contract failed"
            )
        ]
    return []


def _risk_cache_issues(
    run: WorkflowRun,
    phase_id: str,
    details: dict[str, Any],
    expected_signature: str,
    audit: AcceptedPhaseAudit,
) -> list[str]:
    cached = (
        details.get("risk_audit_bound")
        and str(details.get("risk_audit_validator_signature") or "")
        == expected_signature
        and isinstance(details.get("node_risk_audit"), dict)
    )
    if not details.get("risk_audit_bound") or cached:
        return []
    try:
        from ..services.node_risk_audit import node_risk_audit_service

        report = node_risk_audit_service.audit_node(
            run.project_path,
            phase_id,
            run.options,
            persist=False,
        )
    except Exception as error:
        return [
            f"accepted phase risk audit could not be rerun: {type(error).__name__}: {error}"
        ]
    blockers = [
        str(item.get("plain_message") or item.get("message") or "")
        for item in report.get("findings", [])
        if item.get("severity") == "blocker"
        and str(item.get("plain_message") or item.get("message") or "").strip()
    ]
    if not blockers:
        audit.risk_refreshes[phase_id] = {
            "node_risk_audit": report,
            "risk_audit_validator_signature": expected_signature,
        }
    return blockers


def _phase_issues(
    host: AcceptedPhaseHost,
    run: WorkflowRun,
    phase_id: str,
    phase: dict[str, Any],
    expected_input_id: str,
    expected_risk_signature: str,
    audit: AcceptedPhaseAudit,
) -> list[str]:
    details = phase.get("details")
    details = details if isinstance(details, dict) else {}
    recorded_input = str(details.get("input_baseline_snapshot_id") or "")
    snapshot = details.get("artifact_snapshot")
    producer_issues = []
    if phase_id == "figure":
        from ..services.deterministic_figure_freshness import deterministic_figure_freshness_issues

        producer_issues = deterministic_figure_freshness_issues(run.project_path)
    if not recorded_input and not snapshot:
        return producer_issues
    # Revalidation must inspect the recorded binding, never replace it with a
    # newly generated snapshot before deciding whether the owner is reusable.
    issues = host._artifact_snapshot_issues(run.project_path, owner_snapshot_view(phase_id, snapshot))
    issues.extend(producer_issues)
    if expected_input_id and recorded_input != expected_input_id:
        issues.append("accepted phase is bound to a different workflow input baseline")
    if (
        not issues
        and phase_id == "exp-run"
        and run.options.get("run_experiment") is True
    ):
        issues.extend(_managed_run_issues(host, run))
    if not issues:
        issues.extend(
            _risk_cache_issues(
                run,
                phase_id,
                details,
                expected_risk_signature,
                audit,
            )
        )
    return issues


def _collect_audit(
    host: AcceptedPhaseHost,
    run: WorkflowRun,
    state: dict[str, Any],
) -> AcceptedPhaseAudit:
    phases = state.get("phases")
    phases = phases if isinstance(phases, dict) else {}
    definitions = {node.id: node for node in host._get_default_nodes()}
    accepted = {
        phase_id
        for phase_id, phase in phases.items()
        if isinstance(phase, dict)
        and str(phase.get("status") or "") in TERMINAL_PHASE_STATES
    }
    audit = AcceptedPhaseAudit(phases, definitions, accepted)
    input_id = str(run.input_baseline.get("snapshot_id") or "")
    signature = host._risk_audit_validator_signature(run.options)
    for phase_id in phases:
        if phase_id not in accepted:
            continue
        issues = _phase_issues(
            host,
            run,
            phase_id,
            phases.get(phase_id, {}),
            input_id,
            signature,
            audit,
        )
        if issues:
            audit.issues[phase_id] = issues
    return audit


def _refresh_valid_details(run_state: RunState, audit: AcceptedPhaseAudit) -> None:
    for phase_id, details in audit.risk_refreshes.items():
        if phase_id not in audit.issues:
            run_state.refresh_accepted_details(
                phase_id,
                details,
                reason="refreshed accepted-phase risk audit cache",
            )


def _invalid_closure(audit: AcceptedPhaseAudit) -> set[str]:
    invalid = set(audit.issues)
    changed = True
    while changed:
        changed = False
        for phase_id in audit.accepted - invalid:
            definition = audit.definitions.get(phase_id)
            if definition is None:
                continue
            invalid_dependencies = [
                item for item in definition.depends_on if item in invalid
            ]
            nonterminal = [
                item
                for item in definition.depends_on
                if item in audit.phases
                and item not in invalid
                and str(audit.phases.get(item, {}).get("status") or "pending")
                not in TERMINAL_PHASE_STATES
            ]
            if not invalid_dependencies and not nonterminal:
                continue
            invalid.add(phase_id)
            audit.issues[phase_id] = [
                *(
                    [
                        "an accepted upstream dependency changed: "
                        + ", ".join(invalid_dependencies)
                    ]
                    if invalid_dependencies
                    else []
                ),
                *(
                    [
                        "an accepted upstream dependency is not terminal: "
                        + ", ".join(nonterminal)
                    ]
                    if nonterminal
                    else []
                ),
            ]
            changed = True
    return invalid


def _changed_snapshot_keys(issues: list[str]) -> list[str]:
    prefixes = (
        "accepted artifact changed:",
        "accepted semantic artifact changed:",
        "accepted semantic artifact missing or invalid:",
    )
    keys = []
    for issue in issues:
        for prefix in prefixes:
            if issue.startswith(prefix):
                key = issue[len(prefix) :].strip()
                if key and key not in keys:
                    keys.append(key)
                break
    return keys


def _journal_invalidation(
    run: WorkflowRun,
    audit: AcceptedPhaseAudit,
    phase_id: str,
    issues: list[str],
    invalid: set[str],
) -> None:
    definition = audit.definitions.get(phase_id)
    dependencies = [
        item
        for item in (definition.depends_on if definition else [])
        if item in invalid
        or (
            item in audit.phases
            and str(audit.phases.get(item, {}).get("status") or "pending")
            not in TERMINAL_PHASE_STATES
        )
    ]
    details = audit.phases.get(phase_id, {}).get("details")
    details = details if isinstance(details, dict) else {}
    owner = str(
        details.get("artifact_owner_id")
        or (details.get("revision") or {}).get("active_owner_id")
        or phase_id
    )
    try:
        from ..services.workflow_event_journal import workflow_event_journal

        workflow_event_journal.record(
            run.project_path,
            run.id,
            "accepted_phase_invalidated",
            {
                "phase_id": phase_id,
                "issues": issues[:12],
                "changed_snapshot_keys": _changed_snapshot_keys(issues),
                "owner": owner,
                "dependency": dependencies,
                "dependency_phase_ids": dependencies,
            },
        )
    except Exception as error:
        logger.warning(
            "accepted phase invalidation journal error",
            phase_id=phase_id,
            error=str(error),
        )


def validated_accepted_phase_ids(
    host: AcceptedPhaseHost,
    run: WorkflowRun,
    run_state: RunState,
) -> list[str]:
    audit = _collect_audit(host, run, run_state.load() or {})
    _refresh_valid_details(run_state, audit)
    invalid = _invalid_closure(audit)
    for phase_id in audit.phases:
        if phase_id not in invalid:
            continue
        issues = list(audit.issues.get(phase_id) or [])
        run_state.invalidate_acceptance(phase_id, "; ".join(issues[:8]))
        _journal_invalidation(run, audit, phase_id, issues, invalid)
    return [
        phase_id
        for phase_id in audit.phases
        if phase_id in audit.accepted and phase_id not in invalid
    ]
