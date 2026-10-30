"""Code dependencies for evidence decisions and protocol-readiness consumers."""

from pathlib import Path


_NODES = frozenset({"exp-design", "exp-run", "results", "narrative", "figure", "paper", "review", "audit", "compile", "ppt"})


def scientific_contract_implementation_paths(services_root: Path, node_id: str) -> list[Path]:
    if node_id not in _NODES:
        return []
    return [
        *(services_root / name for name in (
            "scientific_contract_sources.py", "protocol_conformance.py",
            "scientific_matrix_records.py", "scientific_evidence_sources.py", "scientific_numeric_parsing.py",
            "scientific_architecture_projection.py",
            "independent_matrix_audit.py", "independent_matrix_statistics.py",
            "paper_matrix_result_rows.py", "paper_table_projection.py", "paper_submission_tables.py", "scientific_asset_builders.py",
            "evaluation_protocol_projection.py", "evaluation_protocol_validation.py",
            "training_review_policy.py", "execution_matrix.py", "paper_plan_evidence.py", "paper_plan.py", "paper_plan_runtime.py",
            "execution_cell_binding.py",
            "simulation_claim_decisions.py", "simulation_claim_decision_report.py",
            "simulation_claim_evidence.py", "simulation_benchmark.py",
            "scientific_narrative.py", "narrative_rendering.py", "narrative_evidence.py",
            "narrative_source_bindings.py", "experiment_runner.py",
            "implementation_graph.py", "implementation_import_scopes.py", "implementation_scopes.py",
            "implementation_callbacks.py", "implementation_model_bindings.py", "implementation_check_evidence.py", "implementation_test_evidence.py",
            "implementation_readiness_checks.py", "implementation_review_receipt.py", "planning_input_identity.py",
            "evidence_versions.py", "evidence_publication_recovery.py", "search_evidence_snapshot.py",
            "implementation_capabilities.py", "implementation_audit.py", "experiment_implementation.py",
            "publication_labels.py", "simulation_scenario.py", "simulation_table_projection.py",
            "simulation_table_publication.py", "table_panel_reference_contract.py",
            "frozen_benchmark_authority.py", "frozen_benchmark_runtime.py", "planned_result_reuse.py",
            "impl_stage_targets.py", "implementation_blueprint.py", "implementation_stage_validation.py",
            "implementation_dependencies.py", "implementation_build_revalidation.py", "experiment_implementation_build.py",
            "implementation_handoff.py",
        )),
        *(services_root.parent / "workflows" / name for name in (
            "simulation_result_analysis.py", "engine_inputs.py",
            "acceptance_manifest.py", "run_execution_coordinator.py", "revision_loop_phases.py",
            "evidence_producer_gate.py", "evidence_version_request.py", "design_review.py", "owner_revision_transaction.py",
        )),
        *(services_root.parent / "contracts" / name for name in (
            "evaluation.py", "preparation.py", "workflow_nodes.py", "implementation_readiness.py",
            "implementation_evidence.py",
        )),
    ]
