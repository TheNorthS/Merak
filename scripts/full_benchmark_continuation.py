"""Continue one benchmark through the production resume and acceptance lifecycle.

This runner does not create/copy a run or install accepted phases. Current
accepted owners are revalidated by the normal resume machinery; scientific
execution, foreign writes and external mutations remain prohibited.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from typing import Any
import uuid
from unittest.mock import patch

from scripts.full_benchmark_scope import (
    PIPELINE_NODES, benchmark_method_tool_scope, install_benchmark_write_guard,
    numerical_fingerprint, scientific_method_identity, trusted_publication_table_staging,
)
from scripts.full_benchmark_continuation_scope import frozen_inputs, validate_stopped_run
from scripts.full_benchmark_failure import (
    BenchmarkContinuationFailure, ContinuationObservation, observe_continuation,
)
from scripts.verify_full_benchmark_workflow import _pipeline_options, validate_final_outcome
from scripts.verify_live_remaining_snapshot import (
    reject_scientific_execution, suppress_notification, validate_offline_receipt,
)


def current_pipeline_gates(host: Any, root: Path, run_id: str, state: dict) -> dict:
    """Recheck every current gate without writing any accepted lifecycle state."""
    from server.workflows.models import WorkflowRun

    config = state.get("config") or {}
    run = WorkflowRun(id=run_id, project_path=str(root), nodes=host._get_default_nodes(),
        options=dict(config.get("options") or {}), input_baseline=dict(state.get("input_baseline") or {}))
    gates = {}
    for node in run.nodes:
        gate = host._acceptance_gate(node, run, str(config.get("assurance") or "draft"), "", require_fresh=False)
        gates[node.id] = {"accepted": gate.get("accepted") is True, "reason": gate.get("reason"),
            "summary": gate.get("summary"), "execution_evidence": (gate.get("details") or {}).get("execution_evidence") or {}}
    return gates


async def execute_same_benchmark(host: Any, root: Path, run_id: str, config: dict, *,
                                  checkpoint_feedback: str = "", on_event: Any = None,
                                  observation: ContinuationObservation | None = None) -> dict:
    """Only the exact original copy/run may execute after native revalidation and claims."""
    from server.workflows.run_state import RunState

    original_execute = host.execute

    async def scoped_execute(**arguments):
        options = arguments.get("pipeline_options") or {}
        if (Path(str(arguments.get("project_path") or "")).resolve() != root
                or options.get("resume_run_id") != run_id
                or not set(arguments.get("node_ids") or []).issubset(PIPELINE_NODES)
                or options.get("run_experiment") is not False
                or options.get("non_experiment_evidence_mode") != "synthetic_preview"
                or options.get("platform_auto_recovery") is not False
                or options.get("deterministic_source_repair") is not False):
            raise PermissionError("Benchmark continuation may only resume its exact non-training run")
        if observation is not None:
            observation.execute_entered = True
        return await original_execute(**arguments)

    with patch.object(host, "execute", scoped_execute):
        if observation is not None:
            observation.native_resume_entered = True
        resumed = await host.resume_persisted_run(run_id, str(root), node_ids=list(PIPELINE_NODES),
            research_direction=str(config.get("direction") or ""), effort=str(config.get("effort") or "balanced"),
            assurance=str(config.get("assurance") or "draft"), pipeline_options=_pipeline_options(config, True),
            checkpoint_feedback=checkpoint_feedback, resume_source="explicit", on_event=on_event)
        if resumed != run_id or host._running_tasks.get(run_id) is None:
            raise RuntimeError("Native continuation lost the exact existing benchmark worker identity")
        if observation is not None:
            observation.worker_entered = True
        await host._running_tasks[run_id]
    state = RunState(str(root), run_id).load() or {}
    if run_id not in host._runs:
        raise RuntimeError("Native continuation lost its actual workflow run before final validation")
    gates = current_pipeline_gates(host, root, run_id, state)
    passing = set(gates) == set(PIPELINE_NODES) and all(
        gate["accepted"] and gate["execution_evidence"].get("accepted") is True
        and not gate["execution_evidence"].get("issues") for gate in gates.values())
    return {"run_id": run_id, "status": state.get("status"), "continuation": True,
        "phases": {name: value.get("status") for name, value in (state.get("phases") or {}).items()},
        "logical_pipeline_nodes": list(PIPELINE_NODES), "source_owner_reuse": {},
        "current_gates": gates, "completion": state.get("completion") or {},
        "accepted": passing and validate_final_outcome(state, run_id, PIPELINE_NODES, {})}


async def _authorized_continuation(host: Any, root: Path, run_id: str,
                                    config: dict, checkpoint_feedback: str) -> dict:
    from scripts.live_snapshot_compilation import restricted_snapshot_compilation
    from scripts.live_snapshot_safety import blocked_snapshot_tools
    from scripts.full_benchmark_runtime_records import trusted_benchmark_runtime_records
    from server.agent.engine import agent_engine
    from server.utils.atomic_write import atomic_write_json

    observation = ContinuationObservation()
    blocked = observation.blocked_operations
    method_identity, inputs = scientific_method_identity(root), frozen_inputs(root)

    async def progress(event, data):
        if scientific_method_identity(root) != method_identity or frozen_inputs(root) != inputs:
            raise PermissionError("Benchmark continuation modified frozen science or source inputs")
        if event in {"node_started", "node_accepted", "node_failed", "node_dependency_reused",
                     "node_revision_gate", "workflow_completed", "workflow_failed"}:
            payload = {"event": event, "node_id": data.get("node_id"),
                "accepted": data.get("accepted"), "reason": data.get("reason")}
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            atomic_write_json(root / ".merak/FULL_BENCHMARK_PROGRESS.json", payload)

    with ExitStack() as stack:
        stack.enter_context(trusted_benchmark_runtime_records(root, run_id))
        stack.enter_context(blocked_snapshot_tools(agent_engine, root, blocked))
        stack.enter_context(trusted_publication_table_staging(root))
        stack.enter_context(benchmark_method_tool_scope(agent_engine, root, method_identity))
        stack.enter_context(restricted_snapshot_compilation(root))
        stack.enter_context(patch.object(host, "_execute_managed_experiment", reject_scientific_execution))
        for target in ("server.services.experiment_placeholders.experiment_placeholder_service.ensure",
                       "server.services.simulation_benchmark.build_simulation_benchmark",
                       "server.services.experiment_runner.experiment_scheduler.submit_experiment"):
            stack.enter_context(patch(target, reject_scientific_execution))
        for name in ("workflow_completed", "workflow_failed"):
            stack.enter_context(patch(f"server.services.notification.notification_service.{name}", suppress_notification))
        observation.guards_entered = True
        result = await observe_continuation(
            lambda: execute_same_benchmark(host, root, run_id, config,
                checkpoint_feedback=checkpoint_feedback, on_event=progress, observation=observation),
            host.shutdown, observation)
    return {**result, "blocked_operations": blocked, "accepted": result["accepted"] and not blocked}


async def prepare_continuation(root: Path, run_id: str, offline_receipt: Path,
                                authority_context: dict, identity: dict,
                                checkpoint_feedback: str = "") -> dict:
    """Offline admission precedes every provider; no stage-target or accepted-input resets."""
    from scripts.full_benchmark_engine import FullBenchmarkEngine
    from scripts.full_benchmark_preparation import CurrentBenchmarkPreparation, refresh_current_authority
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    from server.agent import init_models_from_config, model_router
    from server.agent.tools import register_all_tools
    from server.services.skill_registry import skill_registry
    from server.utils.atomic_write import atomic_write_bytes
    from scripts.verify_full_benchmark_workflow import REPOSITORY

    offline = validate_offline_receipt(offline_receipt)
    state = validate_stopped_run(root, run_id)
    if state != identity["state"]:
        raise ValueError("Benchmark state changed after read-only continuation admission")
    before, method_before = numerical_fingerprint(root), scientific_method_identity(root)
    models = load_current_model_config_readonly(REPOSITORY)
    install_benchmark_write_guard(root, rerun_literature=True, rerun_source_owners=True, continuing_run_id=run_id)
    archive = root / f".merak/benchmark-continuations/{run_id}/{uuid.uuid4().hex}/report.previous.json"
    atomic_write_bytes(archive, (root / "FULL_BENCHMARK_REPORT.json").read_bytes())
    host = FullBenchmarkEngine()
    current = refresh_current_authority(root, authority_context)
    preparation = CurrentBenchmarkPreparation(host, root, current,
        staged_implementation=host._execute_staged_experiment_implementation)
    host._execute_staged_experiment_implementation = preparation.integrate
    host._ensure_planned_result_templates = preparation.ensure
    validate_offline_receipt(offline_receipt)
    init_models_from_config(models)
    if not model_router._providers:
        raise RuntimeError("No configured real provider is available for authorized benchmark continuation")
    skill_registry.scan_directory(str(REPOSITORY / "merak-skills"))
    register_all_tools()
    validate_offline_receipt(offline_receipt)
    try:
        result = await _authorized_continuation(host, root, run_id, state["config"], checkpoint_feedback)
    except BenchmarkContinuationFailure as error:
        error.context.update({"previous_report_archive": str(archive.relative_to(root)),
            "continuation_identity": {name: value for name, value in identity.items() if name.endswith("sha256")},
            "prior_blocked_operations_observability": identity.get("prior_blocked_operations_observability", "complete"),
            "interruption_history": dict(identity.get("interruption_history") or {}),
            "natural_failure_history": dict(identity.get("natural_failure_history") or {})})
        raise
    unchanged = before == numerical_fingerprint(root) and method_before == scientific_method_identity(root)
    return {**result, "offline_verification": offline, "source_evidence": identity["previous_report"]["source_evidence"],
        "previous_report_archive": str(archive.relative_to(root)),
        "continuation_identity": {name: value for name, value in identity.items() if name.endswith("sha256")},
        "prior_blocked_operations_observability": identity.get("prior_blocked_operations_observability", "complete"),
        "interruption_history": dict(identity.get("interruption_history") or {}),
        "natural_failure_history": dict(identity.get("natural_failure_history") or {}),
        "raw_numerical_and_semantic_bundle_unchanged": unchanged, "training_authorized": False,
        "real_model_execution": True, "original_workflow_resumed": False, "accepted": result["accepted"] and unchanged}
