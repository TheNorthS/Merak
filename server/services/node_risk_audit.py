"""Deterministic, stage-specific risk discovery for the research workflow.

The language model owns synthesis and revision.  This service owns cheap facts:
schema validity, provenance, cross-stage contract drift, stale build products, and
evidence-mode contradictions.  Heuristic quality concerns are warnings; only
objective contradictions or unusable artifacts block a stage.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .risk_training_review import training_check_findings as _training_check_findings  # noqa: F401
from .risk_code_reachability import (
    reachable_python_placeholders as _reachable_python_placeholders,  # noqa: F401
)
from .audit_failure_routing import audit_failure_owner as _audit_failure_owner  # noqa: F401

from .research_workflow_contract import NODE_CONTRACTS
from .risk_constants import (
    NODE_RISK_CHECKLIST as NODE_RISK_CHECKLIST,  # noqa: F401
    PENDING_RE as PENDING_RE,  # noqa: F401
    SIMULATION_SCOPE_RE as SIMULATION_SCOPE_RE,  # noqa: F401
    UNCERTAINTY_RE as UNCERTAINTY_RE,  # noqa: F401
)
from .risk_artifact_support import _json
from .risk_validator_support import (
    _has_unbounded_supported_claim as _has_unbounded_supported_claim,  # noqa: F401
    _placeholder_excerpt as _placeholder_excerpt,  # noqa: F401
)
from .run_spec import (
    run_spec_command as resolve_run_spec_command,
)
from .simulation_policy import (
    is_complete_evidence_mode,
)


NODE_ORDER = tuple(NODE_CONTRACTS)
BLOCKING_SEVERITIES = {"blocker"}
KNOWN_AUDIT_VERDICTS = {
    "PASS",
    "WARN",
    "FAIL",
    "NOT_APPLICABLE",
    "BLOCKED",
    "ERROR",
}
RESULT_ANALYSIS_BUILD_SCHEMA = 1
RESULT_ANALYSIS_BUILD_PATH = Path("experiments") / "results" / "ANALYSIS_BUILD.json"


def _workflow_evidence_mode(options: dict[str, Any]) -> str:
    if options.get("run_experiment") is True:
        return "executed"
    return str(options.get("non_experiment_evidence_mode") or "design_only").casefold()


def _has_trusted_empirical_evidence(options: dict[str, Any]) -> bool:
    # Historical name retained for local callers.  This means a complete,
    # provenance-checked manuscript evidence track, which includes the
    # deterministic simulation bundle.
    return is_complete_evidence_mode(_workflow_evidence_mode(options))


def _run_spec_command(
    run_spec: dict[str, Any],
    *,
    run_experiment: bool,
) -> str:
    """Use the shared RUN_SPEC normalization policy for risk analysis."""
    return resolve_run_spec_command(
        run_spec,
        run_experiment=run_experiment,
    )


# This catalog is intentionally domain-neutral. It documents what was actually
# checked at each stage and prevents a newly added workflow node from silently
# inheriting a generic file-exists gate.


class NodeRiskAuditService:
    """Find objective blockers and non-blocking latent risks for every stage."""

    report_dir = Path(".merak") / "quality"
    index_path = Path(".merak") / "NODE_RISK_AUDIT.json"
    _index_update_thread_lock = threading.RLock()
    snapshot_path = Path(".merak") / "WORKFLOW_RISK_SNAPSHOT.json"

    def preflight_node(
        self,
        project_path: str | Path,
        node_id: str,
        options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from .risk_audit_coordinator import preflight_node as operation

        return operation(self, project_path, node_id, options)

    def audit_workflow(
        self,
        project_path: str | Path,
        options: dict[str, Any] | None = None,
        *,
        through_node: str = "",
        persist: bool = True,
    ) -> dict[str, Any]:
        from .risk_audit_coordinator import audit_workflow as operation

        return operation(
            self, project_path, options, through_node=through_node, persist=persist
        )

    def protected_upstream_findings(
        self,
        project_path: str | Path,
        node_id: str,
        options: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from .risk_audit_coordinator import protected_upstream_findings as operation

        return operation(self, project_path, node_id, options)

    def audit_node(
        self,
        project_path: str | Path,
        node_id: str,
        options: dict[str, Any] | None = None,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        from .risk_audit_coordinator import audit_node as operation

        return operation(self, project_path, node_id, options, persist=persist)

    def apply_gate(
        self,
        gate: dict[str, Any],
        project_path: str | Path,
        node_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .risk_audit_coordinator import apply_gate as operation

        return operation(self, gate, project_path, node_id, options)

    def _update_index(self, root: Path, report: dict[str, Any]) -> None:
        from .risk_audit_coordinator import _update_index as operation

        operation(self, root, report)

    @staticmethod
    def _strategy(root: Path, options: dict[str, Any]) -> dict[str, Any]:
        strategy = options.get("research_strategy")
        if isinstance(strategy, dict) and strategy:
            return strategy
        payload, _ = _json(root / ".merak" / "research_strategy.json")
        if isinstance(payload, dict) and isinstance(payload.get("strategy"), dict):
            return payload["strategy"]
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _required_bibliography_count(
        root: Path,
        options: dict[str, Any],
    ) -> int:
        from .paper_profile import paper_profile_service

        workflow_contract, _ = _json(root / ".merak" / "RESEARCH_WORKFLOW_CONTRACT.json")
        workflow_contract = (
            workflow_contract if isinstance(workflow_contract, dict) else {}
        )
        direction = str(
            options.get("research_direction")
            or workflow_contract.get("direction")
            or ""
        )
        return paper_profile_service.bibliography_requirement(
            root,
            options=options,
            direction=direction,
        )

    def _search_evidence_findings(
        self,
        root: Path,
        node_id: str,
        options: dict[str, Any],
    ) -> list[dict[str, Any]]:
        from .risk_search_evidence import search_evidence_findings

        return search_evidence_findings(root, node_id, options, self._strategy)

    def _audit_lit(self, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
        from .risk_stage_lit import audit

        return audit(self, root, options)

    def _audit_idea(self, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
        from .risk_stage_idea import audit

        return audit(self, root, options)

    def _audit_novelty(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_novelty import audit

        return audit(self, root, options)

    def _audit_exp_design(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_exp_design import audit

        return audit(self, root, options)

    def _audit_exp_run(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_exp_run import audit

        return audit(self, root, options)

    def bind_result_analysis_inputs(
        self,
        project_path: str | Path,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .result_analysis_binding import bind_result_analysis_inputs

        return bind_result_analysis_inputs(project_path, options)

    def _audit_results(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_results import audit

        return audit(self, root, options)

    def _audit_figure(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_figure import audit

        return audit(self, root, options)

    def _audit_narrative(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_narrative import audit

        return audit(self, root, options)

    def _audit_paper(self, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
        from .risk_stage_paper import audit

        return audit(self, root, options)

    def _audit_review(
        self, root: Path, options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_review import audit

        return audit(self, root, options)

    def _audit_audit(self, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
        from .risk_stage_audit import audit

        return audit(self, root, options)

    def _audit_compile(
        self, root: Path, _options: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from .risk_stage_compile import audit

        return audit(self, root, _options)

    def _audit_ppt(self, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
        from .risk_stage_ppt import audit

        return audit(self, root, options)

    def _cross_node_findings(
        self,
        root: Path,
        node_id: str,
        options: dict[str, Any],
        *,
        include_upstream: bool = True,
    ) -> list[dict[str, Any]]:
        from .cross_node_consistency import cross_node_findings

        return cross_node_findings(
            self, root, node_id, options, include_upstream=include_upstream
        )


node_risk_audit_service = NodeRiskAuditService()
