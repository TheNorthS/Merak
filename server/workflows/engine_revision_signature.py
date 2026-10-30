"""Compute semantic revision fingerprints from explicit artifact dependencies."""

# ruff: noqa: F403, F405

from .engine_context import *  # noqa: F403, F405
from .engine_snapshot_paths import accepted_snapshot_paths
from ..utils.runtime_source_root import implementation_source_path


def revision_artifact_signature(
    engine: Any, project_path: str, node_id: str,
    options: Optional[dict[str, Any]] = None,
) -> str:
    root = Path(project_path).expanduser().resolve()
    opts = dict(options or {})
    digest = hashlib.sha256()
    digest.update(f"revision-waiting:v{REVISION_GATE_SIGNATURE_VERSION}:{node_id}".encode())
    _bind_validator_sources(digest, node_id)
    paths = list(engine._required_artifacts_for_node(project_path, node_id))
    run = WorkflowRun(project_path=project_path, options=opts)
    paths = accepted_snapshot_paths(engine, run, node_id, {}, paths)
    paths.extend(_extra_paths(engine, root, node_id, opts))
    digest.update(_relevant_options(engine, node_id, opts))
    _bind_paths(engine, digest, root, paths)
    if node_id == "figure":
        from ..services.figure_delegate_budget import (
            figure_producer_code_sha256,
            figure_resume_input_sha256,
        )
        from ..services.figure_revision_progress import (
            figure_draft_progress_signature,
        )

        digest.update(figure_producer_code_sha256().encode("ascii"))
        digest.update(figure_resume_input_sha256(root).encode("ascii"))
        digest.update(figure_draft_progress_signature(root).encode("utf-8"))
    return f"revision:{digest.hexdigest()[:24]}"


def _agent_harness_source_paths(workflows: Path) -> list[Path]:
    return [workflows.parent / "agent" / name for name in (
        "agent_loop.py", "tool_execution.py", "tool_policy.py", "tool_schema.py",
        "tool_harness.py", "tool_deadline.py", "tool_process.py", "tools/tool_registration.py",
        "model_deadlines.py", "model_transport.py", "model_observation.py", "skill_resume.py",
        "openai_stream.py", "remote_errors.py",
        "reviewer_scope.py", "delegate_activity.py", "tools/review_and_domain_tools.py", "tools/skill_tool.py",
    )]


def _node_validator_names(node_id: str) -> set[str]:
    return {
        "exp-design": {
            "method_contract.py", "method_contract_persistence.py", "run_spec.py",
            "experiment_implementation_build.py", "implementation_build_revalidation.py",
            "implementation_stage_validation.py", "implementation_candidate_recovery.py",
            "implementation_audit.py", "implementation_graph.py", "implementation_scopes.py",
            "implementation_capabilities.py",
            "implementation_callbacks.py", "implementation_model_bindings.py", "implementation_check_evidence.py", "implementation_test_evidence.py",
            "experiment_implementation.py", "simulation_render_bundle.py",
            "simulation_artifact_io.py",
        },
        "exp-run": {"execution_provenance.py", "scientific_evidence.py", "run_spec.py"},
        "results": {"scientific_evidence.py", "node_execution_contract.py", "results_execution_policy.py", "simulation_interval_semantics.py",
                    "skill_orchestrator.py", "skill_execution_trace.py", "skill_selection.py",
                    "simulation_asset_profile.py", "node_risk_audit.py"},
        "narrative": {"narrative_prompt.py", "research_delivery_prompt.py"},
        "figure": {
            "figure_artifacts.py", "figure_revision_progress.py",
            "figure_routing.py", "figure_semantic_projection.py", "scientific_plotting.py", "scientific_plot_template.py",
            "scientific_scene_figure.py", "scientific_scene_placement.py", "scientific_scene_labels.py",
            "deterministic_figure_builder.py", "figure_producer_errors.py",
            "figure_producer_fingerprint.py", "scientific_asset_contract.py",
            "figure_execution_policy.py", "figure_execution_evidence.py",
            "node_execution_contract.py", "skill_selection.py",
            "skill_orchestrator.py", "skill_execution_trace.py",
            "simulation_publication_registry.py", "simulation_publication_attestation.py",
            "figure_engine.py", "figure_generation_transaction.py", "figure_result_finalizer.py", "figure_diagram_text.py",
            "figure_scientific_alignment.py", "figure_raster_quality.py",
            "figurespec_backend.py", "figurespec_layout_policy.py",
            "svg_variant_conversion.py", "svg_marker_fallback.py", "figure_svg_sources.py",
            "evaluation_design_svg.py", "evaluation_design_contract.py",
            "evaluation_protocol_projection.py", "evaluation_conditions_projection.py",
            "evaluation_design_content.py",
            "simulation_figure_refresh.py", "simulation_comparison_plots.py",
            "simulation_plot_layout.py", "simulation_plot_layout_refresh.py", "simulation_plot_template.py", "paper_trusted_plot_source.py",
        },
        "paper": {"paper_drafting.py", "paper_artifacts.py", "latex_bundle.py", "manuscript_language.py", "paper_profile.py"},
        "review": {"api_visual_reviewer.py", "latex_bundle.py"},
        "audit": {"latex_bundle.py"},
        "compile": {"paper_compiler.py", "latex_bundle.py"},
        "ppt": {"scientific_slides.py", "latex_bundle.py"},
    }.get(node_id, set())


def _validator_source_paths(node_id: str) -> list[Path]:
    services = Path(__file__).parents[1] / "services"
    common = {"node_risk_audit.py", "research_quality.py", "paper_plan_asset_links.py", "paper_plan.py", "paper_plan_runtime.py", "paper_plan_delivery.py"}
    names = _node_validator_names(node_id)
    workflows = Path(__file__).parent
    sources = [
        workflows / "engine.py", workflows.parent / "utils/atomic_write.py",
        workflows / "engine_artifacts_a.py",
        workflows / "engine_execution_extra.py",
        workflows.parent / "utils/runtime_source_root.py",
        workflows / "revision_diagnostics.py",
        workflows / "revision_owner_rules.py",
        workflows / "revision_owner_policy.py",
        workflows / "node_execution_completion.py",
        workflows / "node_execution_phases.py",
        workflows / "node_gate_preparation.py",
        workflows / "acceptance_context.py",
        workflows / "acceptance_coordinator.py",
        workflows / "revision_loop_phases.py",
        workflows / "revision_attempt.py",
        workflows / "paper_plan_repair.py",
        workflows / "owner_revision_scope.py",
        workflows / "result_resume_refresh.py",
        workflows / "revision_progress_diagnostics.py",
        workflows / "paper_revision_progress.py",
        workflows / "interruption_checkpoint.py",
        workflows / "primary_session_resume.py",
        workflows / "primary_model_execution.py",
        workflows / "design_review.py", workflows / "owner_revision_transaction.py", workflows / "evidence_version_request.py",
        *_agent_harness_source_paths(workflows),
        workflows.parent / "agent/tool_response_protocol.py",
        workflows.parent / "agent/write_scope.py",
        workflows.parent / "contracts/repairs.py",
        *(services / name for name in sorted(common | names)),
        *_planned_reuse_validator_paths(services, node_id),
    ]
    if node_id in {"review", "audit"}:
        sources.extend(workflows / name for name in (
            "review_audit.py", "draft_delivery.py", "review_acceptance_policy.py", "review_loop.py", "audit_coordinator.py", "audit_layer_checkpoint.py", "audit_protocol.py",
            "audit_layers.py", "audit_result_store.py", "audit_bundle_checks.py", "proof_audit_validation.py",
        ))
    if node_id == "exp-design":
        sources.extend(workflows / name for name in (
            "implementation_reconciliation.py", "implementation_stage_progress.py", "implementation_declared_handoff.py",
            "implementation_review_progress.py",
            "implementation_model_invocation.py",
            "staged_implementation_coordinator.py", "node_gate_preparation.py",
        ))
    if node_id == "figure":
        sources.extend((
            workflows / "simulation_render_refresh.py",
            workflows / "figure_execution_verification.py",
            workflows / "acceptance_pipeline.py",
            workflows / "revision_gate_phases.py",
            services / "simulation_plot_templates/multitask_matrix.py.tmpl",
            services.parents[1] / "merak-skills/figure-spec/scripts/figure_renderer.py",
            services.parents[1] / "merak-skills/figure-spec/scripts/figure_semantic_rendering.py",
        ))
    sources.extend(_owner_validation_sources(services, node_id))
    if node_id == "results":
        sources.extend(_results_validator_paths(workflows))
    return sources


def _owner_validation_sources(services: Path, node_id: str) -> list[Path]:
    from ..services.scientific_contract_sources import scientific_contract_implementation_paths

    paths = [services.parent / "workflows" / name for name in (
        "artifact_snapshot_ownership.py", "engine_snapshot_paths.py",
        "accepted_phase_validation.py", "dependency_reuse.py",
    )]
    paths.extend(services / name for name in (
        "specialist_inputs.py", "specialist_plan.py", "research_specialists.py",
    ))
    paths.extend(scientific_contract_implementation_paths(services, node_id))
    if node_id == "paper":
        from ..services.paper_preparation_sources import paper_preparation_implementation_paths
        return [*paths, *paper_preparation_implementation_paths(services)]
    if node_id == "review":
        from .review_contract_sources import review_contract_implementation_paths
        return [*paths, *review_contract_implementation_paths(services)]
    if node_id == "ppt":
        from ..services.slide_contract_sources import slide_contract_implementation_paths
        return [*paths, *slide_contract_implementation_paths(services)]
    return paths


def _planned_reuse_validator_paths(services: Path, node_id: str) -> list[Path]:
    paths = []
    if node_id in {"exp-design", "exp-run", "results", "figure", "narrative", "paper", "review", "audit", "compile", "ppt"}:
        paths.extend(services / name for name in ("planned_result_reuse.py", "simulation_figure_portfolio.py",
                                                   "simulation_paper_projection.py", "simulation_render_bundle.py",
                                                   "simulation_publication_registry.py", "planned_simulation_bindings.py"))
    if node_id in {"paper", "review", "audit", "compile", "ppt"}:
        paths.extend(services / name for name in ("latex_compile_execution.py", "local_compile_process.py", "windows_compile_job.py"))
    return paths


def _results_validator_paths(workflows: Path) -> list[Path]:
    return [workflows / name for name in ("results_runtime_execution.py", "run_execution_node.py",
                                          "revision_execution.py", "node_gate_preparation.py",
                                          "engine_artifacts_a.py", "engine_execution.py", "engine_inputs.py",
                                          "simulation_result_analysis.py", "simulation_report_contract.py",
                                          "acceptance_pipeline.py", "revision_gate_phases.py")]


def _bind_validator_sources(digest: Any, node_id: str) -> None:
    for path in _validator_source_paths(node_id):
        digest.update(path.name.encode())
        try:
            digest.update(hashlib.sha256(implementation_source_path(path).read_bytes()).digest())
        except OSError:
            digest.update(b"<validator-unavailable>")


def _extra_paths(
    engine: Any, root: Path, node_id: str, opts: dict[str, Any],
) -> list[Path]:
    paths = []
    sources = set(dict(opts.get("research_strategy") or {}).get("literature_sources", []))
    if node_id == "lit":
        if opts.get("enable_zotero") and "zotero" in sources:
            paths.append(root / "literature/zotero_context.json")
        if opts.get("enable_obsidian") and "obsidian" in sources:
            paths.append(root / "literature/obsidian_context.json")
    if node_id == "novelty" and opts.get("enable_patent_search"):
        paths.append(root / "ideas/patent_prior_art.json")
    if node_id == "exp-run" and opts.get("run_experiment") is True:
        paths.extend(_runtime_manifest_paths(engine, root))
    return paths


def _runtime_manifest_paths(engine: Any, root: Path) -> list[Path]:
    paths = []
    runtime = root / ".merak/experiments"
    if not runtime.is_dir():
        return paths
    for manifest_path in sorted(runtime.glob("*/run.json")):
        paths.append(manifest_path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        maps = [manifest.get("result_artifacts")]
        attempt = int(manifest.get("current_attempt") or 0)
        maps.extend(item.get("result_artifacts") for item in manifest.get("attempts") or []
                    if isinstance(item, dict) and int(item.get("attempt") or 0) == attempt)
        for mapping in maps:
            for raw in mapping if isinstance(mapping, dict) else {}:
                candidate = engine._project_artifact_reference(root, raw)
                if candidate and candidate.is_file() and candidate.stat().st_size <= MANAGED_EXPERIMENT_DIRECT_HASH_LIMIT_BYTES:
                    paths.append(candidate)
    return paths


def _relevant_options(engine: Any, node_id: str, opts: dict[str, Any]) -> bytes:
    evidence = {"run_experiment", "non_experiment_evidence_mode"}
    keys = {
        "lit": {"enable_zotero", "enable_obsidian", "research_strategy", "research_direction"},
        "idea": {"research_direction"},
        "novelty": {"enable_patent_search", "research_strategy", "research_direction"},
        "exp-design": evidence | {"_training_check"},
        "exp-run": evidence | {"_training_check", "gpu_target", "ssh_server_id"},
        "results": evidence, "figure": evidence,
        "narrative": evidence | {"target_venue"}, "paper": evidence | {"target_venue"},
        "review": evidence | {"delivery_goal"}, "audit": evidence | {"delivery_goal"},
        "compile": evidence | {"delivery_goal"}, "ppt": evidence | {"delivery_goal"},
    }.get(node_id, set())
    relevant = {key: opts.get(key) for key in sorted(keys) if key in opts}
    return json.dumps(engine._stable_revision_json(relevant), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")).encode()


def _bind_paths(
    engine: Any, digest: Any, root: Path, paths: list[Path],
) -> None:
    unique = {str(Path(raw).expanduser().resolve()).casefold(): Path(raw).expanduser().resolve()
              for raw in paths}.values()
    for path in sorted(unique, key=lambda item: item.as_posix().casefold()):
        if path.is_file():
            _add_file(engine, digest, root, path)
        elif path.is_dir():
            files = sorted(item for item in path.rglob("*") if item.is_file() and "__pycache__" not in item.parts)
            for item in files[:2000]:
                _add_file(engine, digest, root, item)
            if len(files) > 2000:
                digest.update(b"<directory-scan-truncated>")
        else:
            digest.update(_relative_identity(root, path).encode(errors="replace"))
            digest.update(b"<missing>")


def _add_file(engine: Any, digest: Any, root: Path, path: Path) -> None:
    digest.update(_relative_identity(root, path).encode(errors="replace"))
    digest.update(hashlib.sha256(engine._revision_file_bytes(path)).digest())


def _relative_identity(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
