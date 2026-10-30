"""Explicit state for one bounded node revision transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import WorkflowNode, WorkflowRun


class RevisionContinue(Exception):
    """Advance to the next gate iteration without consuming another outer cycle."""


class RevisionComplete(Exception):
    def __init__(self, gate_and_result: tuple[dict[str, Any], str]):
        self.gate_and_result = gate_and_result


@dataclass
class RevisionLoopContext:
    host: Any
    node: WorkflowNode
    run: WorkflowRun
    assurance: str
    research_direction: str
    effort: str
    opts: dict[str, Any]
    max_revision_rounds: int
    checkpoint_timeout: float
    initial_result: str
    require_fresh: bool
    no_progress_limit: int
    active_owner_id: Any = None
    consumer_refresh_required: Any = None
    consumer_refresh_upstream_gate: Any = None
    current_finding_ids: Any = None
    current_upstream_blockers: Any = None
    cycle: Any = None
    diagnostics: Any = None
    execution_contract: Any = None
    execution_gate_applied: Any = None
    gate: Any = None
    gate_details: Any = None
    gate_runtime_service: Any = None
    guided_revision: Any = None
    has_repair_targets: Any = None
    last_execution_error: Any = None
    last_finding_ids: Any = None
    last_revision_attempt_round: Any = None
    last_revision_execution_succeeded: Any = None
    last_revision_event_pending: Any = None
    first_gate: Any = None
    persisted_scope: Any = None
    stale_snapshot_findings: Any = None
    waiting_diagnostics: Any = None
    requires_human_decision: Any = None
    last_revision_method: Any = None
    last_revision_owner_id: Any = None
    last_revision_scope_before: Any = None
    last_revision_scope_diagnostics: Any = None
    last_scope_signature: Any = None
    max_transport_failures: Any = None
    new_finding_ids: Any = None
    no_progress_count: Any = None
    owner_last_finding_ids: Any = None
    owner_last_scope_signatures: Any = None
    owner_last_draft_review_signatures: Any = None
    owner_no_progress_counts: Any = None
    owner_rounds: Any = None
    pending_feedback: Any = None
    persisted_gate: Any = None
    persisted_progress: Any = None
    preflight_for_current: Any = None
    preparation_error: Any = None
    preparation_failure_details: Any = None
    raw_owner_rounds: Any = None
    reconciliation: Any = None
    repair_scope: Any = None
    resolved_finding_ids: Any = None
    result: Any = None
    review_reconciliation_failed: Any = None
    review_state_incomplete: Any = None
    review_state_stale: Any = None
    revision_owner: Any = None
    round_number: Any = None
    run_state: Any = None
    saved_revision: Any = None
    scope: Any = None
    scope_signature: Any = None
    draft_review_signature: Any = None
    draft_review_changed: Any = None
    stall_classification: Any = None
    stop_for_deterministic_stage: Any = None
    stop_for_managed_stage: Any = None
    stop_for_no_progress: Any = None
    target_changed: Any = None
    transport_attempt_since_gate: Any = None
    transport_failures: Any = None
    unchanged_revision_event: Any = None
    unscoped_platform_gate: Any = None
