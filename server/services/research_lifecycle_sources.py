"""Declare lifecycle implementation dependencies for affected node signatures."""

from pathlib import Path


def lifecycle_source_paths(services: Path, node_id: str) -> list[Path]:
    paths = [services / "research_change_application.py", services / "chat_runtime_revision.py"]
    paths.append(services / "workflow_tool_capabilities.py")
    paths.append(services / "research_edit_context.py")
    paths.append(services.parent / "workflows/run_start_lifecycle.py")
    paths.append(services.parent / "workflows/operator_feedback.py")
    if node_id in {"review", "audit"}:
        paths.extend(services.parent / "workflows" / name for name in (
            "report_revision_plan.py", "report_revision_store.py", "report_revision_impact.py", "report_impact_followup.py", "report_refresh_recovery.py", "report_print_recovery.py",
            "report_revision_execution.py", "report_revision_coordinator.py", "report_revision_transport.py", "draft_audit_routing.py",
            "audit_target_location.py", "audit_target_owner.py"))
        paths.append(services / "specialist_dependency_review.py")
        paths.append(services / "specialist_targeted_repair.py")
        paths.append(services / "citation_source_evidence.py")
    if node_id in {"narrative", "figure", "paper"}:
        paths.extend(services / name for name in ("paper_plan_runtime.py", "paper_plan.py", "narrative_prompt.py"))
    if node_id in {"exp-design", "exp-run"}:
        paths.append(services / "scheduler_authoring_contract.py")
        paths.extend(services / name for name in ('experiment_output_contract.py', 'experiment_output_failure.py'))
    if node_id in {"lit", "novelty"}:
        paths.extend(services / name for name in (
            "knowledge_context.py", "knowledge_sources.py", "literature_capabilities.py", "risk_search_evidence.py",
        ))
        paths.extend((services.parent / "agent/remote_errors.py",
                      services.parent / "agent/tools/literature_tools.py"))
    if node_id == "exp-run":
        paths.append(services / 'experiment_aggregation_validation.py')
        paths.append(services.parent / 'workflows/engine_execution.py')
        paths.append(services / 'accepted_experiment_matrix.py')
        paths.append(services.parent / 'workflows/managed_experiment_repair_execution.py')
        paths.extend(services / name for name in (
            "experiment_runtime_identity.py", "experiment_runtime_lifecycle.py", "experiment_runtime_state.py",
            "experiment_runtime_ssh.py", "experiment_runtime_vast.py", "experiment_runtime_modal.py",
            "experiment_retries.py", "experiment_execution.py",
            "scientific_execution_readiness.py",
            "experiment_attempt_clock.py",
        ))
    if node_id == "compile":
        paths.extend(services / name for name in (
            "overleaf_research_revision.py", "overleaf_sync.py", "overleaf_pull.py", "overleaf_export.py",
            "overleaf_revision_recovery.py",
        ))
    return paths
