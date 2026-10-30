"""Explicit real-model full benchmark validation in a NEW independent project.

No workflow runs merely by importing this script. The CLI requires real-model
consent plus a current complete offline receipt before providers are loaded.
Original projects, all existing numerical CSVs and prospective executable science
remain immutable. Ten new stages (eleven with fresh literature) run genuine gates;
unchanged prior owners may be reused, never stamped as new accepted phases.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from scripts.full_benchmark_scope import (TEN_NODES, PIPELINE_NODES, METHOD_SCENE_GUIDANCE, FROZEN_WORKFLOW_INPUTS, install_benchmark_write_guard,
                                         numerical_fingerprint, scientific_method_identity, tree_hashes,
                                         trusted_publication_table_staging, benchmark_method_tool_scope)
from scripts.full_benchmark_evidence import SOURCE_NODES, archive_source_history, check_source_owners, import_source_owner_evidence
from scripts.verify_live_remaining_snapshot import reject_scientific_execution, suppress_notification, validate_offline_receipt


def selected_nodes(rerun_literature: bool, rerun_source_owners: bool = False) -> tuple[str, ...]:
    if rerun_source_owners:
        return PIPELINE_NODES
    return ("lit", *TEN_NODES) if rerun_literature else TEN_NODES


def copy_independent_project(source: Path, destination: Path) -> None:
    """Copy research artifacts only; do not carry providers, services or active state."""
    from scripts.live_snapshot_resume_validation import validate_copy_boundary

    validate_copy_boundary(source)
    if source == destination or not destination.name.startswith("full-benchmark-verification-"):
        raise ValueError("Full benchmark validation requires a new specifically named independent copy")
    excluded = {"user_settings.json", "active-workflow.json", "workflow_recovery_projects.json", ".env"}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if (relative.parts[0] == ".merak" and "implementation-history" not in relative.parts
                or any(part in {"node_modules", ".git", "recovery-leases", "agent-sessions"} for part in relative.parts)
                or path.name.casefold() in excluded or path.suffix.casefold() in {".db", ".sqlite", ".sqlite3", ".key", ".pem"}):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _pipeline_options(config: dict[str, Any], rerun_literature: bool) -> dict[str, Any]:
    options = dict(config.get("options") or {})
    for key in ("resume_run_id", "specialist_plan_path", "resume_feedback", "reused_search_evidence_run_id"):
        options.pop(key, None)
    options.update({"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
                    "enable_overleaf_sync": False, "human_checkpoint": False, "gpu_target": "none",
                    "ssh_server_id": "", "enable_wandb": False, "enable_meta_opt": False,
                    "wandb": False, "enable_meta_optimization": False,
                    "enable_zotero": False, "enable_obsidian": False, "enable_patent_search": False})
    options["node_inputs"] = {"acceptance_scope": "Bounded fixed simulation benchmark only; no EEG training occurred.",
        "preservation": "Do not change SELECTED_IDEA, EXPERIMENT_PLAN, RUN_SPEC/config/source code, any CSV, or numerical manifest semantics.",
        "claim_scope": "Keep research hypotheses; scientific C1-C3 remain unresolved. Describe fixed table negatives, not measured EEG superiority or mechanism failure.",
        "available_code": "The separate prospective CSFS-v1 implementation is V1 code-ready only, not executed research.",
        "literature_owner_requested": rerun_literature}
    options["node_inputs"]["method_scene_repair"] = METHOD_SCENE_GUIDANCE
    options["node_inputs"]["full_acceptance_brief"] = (REPOSITORY / "scripts/fixtures/full_benchmark_acceptance.md").read_text(encoding="utf-8")
    options.update({"platform_auto_recovery": False, "deterministic_source_repair": False})
    options["input_files"] = list(FROZEN_WORKFLOW_INPUTS)
    return options


def validate_final_outcome(state: dict[str, Any], current_run_id: str, selected: tuple[str, ...], source_gates: dict) -> bool:
    """Every selected phase must be genuinely accepted; dependency proof is separate."""
    phases = state.get("phases") or {}
    if (state.get("run_id") != current_run_id or state.get("status") != "completed"
            or set(phases) != set(selected) or set(source_gates) != set(PIPELINE_NODES) - set(selected)):
        return False
    for identity in selected:
        phase = phases[identity]
        evidence = (phase.get("details") or {}).get("execution_evidence") or {}
        if (phase.get("status") != "accepted" or not phase.get("accepted_at") or not phase.get("verdict_id")
                or not phase.get("reviewer") or evidence.get("accepted") is not True or evidence.get("issues")):
            return False
    return all(gate.get("execution_evidence", {}).get("accepted") is True for gate in source_gates.values())


async def execute_new_benchmark(host: Any, root: Path, config: dict, *, source_gates: dict,
                                rerun_literature: bool, rerun_source_owners: bool = False, on_event: Any = None) -> dict:
    """Use the real fresh execute lifecycle, with no resumptions or synthetic state."""
    from server.workflows.run_state import RunState

    selected = selected_nodes(rerun_literature, rerun_source_owners)
    run_id = await host.execute(node_ids=list(selected), project_path=str(root),
        research_direction=str(config.get("direction") or ""), effort=str(config.get("effort") or "balanced"),
        assurance=str(config.get("assurance") or "draft"), pipeline_options=_pipeline_options(config, rerun_literature), on_event=on_event)
    task = host._running_tasks.get(run_id)
    if task is None:
        raise RuntimeError("The real new benchmark worker was not created")
    await task
    state = RunState(str(root), run_id).load() or {}
    current_run = host._runs.get(run_id)
    if current_run is None:
        raise RuntimeError("New workflow lost its actual current run identity before final validation")
    fresh_gates = {}
    for identity in selected:
        node = next(node for node in current_run.nodes if node.id == identity)
        gate = host._acceptance_gate(node, current_run, str(config.get("assurance") or "draft"), "", require_fresh=False)
        fresh_gates[identity] = {"accepted": gate.get("accepted") is True,
                                 "reason": gate.get("reason"), "summary": gate.get("summary"),
                                 "execution_evidence": (gate.get("details") or {}).get("execution_evidence") or {}}
    gates_current = all(gate["accepted"] and gate["execution_evidence"].get("accepted") is True for gate in fresh_gates.values())
    return {"run_id": run_id, "status": state.get("status"),
            "selected_new_nodes": list(selected), "phases": {name: value.get("status") for name, value in (state.get("phases") or {}).items()},
            "source_owner_reuse": source_gates, "logical_pipeline_nodes": list(PIPELINE_NODES),
            "current_gates": fresh_gates, "completion": state.get("completion") or {},
            "accepted": gates_current and validate_final_outcome(state, run_id, selected, source_gates)}


async def _authorized_run(host: Any, root: Path, config: dict, source_gates: dict,
                          rerun_literature: bool, rerun_source_owners: bool) -> dict:
    from scripts.live_snapshot_compilation import restricted_snapshot_compilation
    from scripts.live_snapshot_safety import blocked_snapshot_tools
    from server.agent.engine import agent_engine
    from server.utils.atomic_write import atomic_write_json

    blocked = []
    method_identity = scientific_method_identity(root)
    async def progress(event, data):
        if scientific_method_identity(root) != method_identity:
            raise PermissionError("Workflow modified frozen method hypotheses outside the authorized scientific scene")
        if event in {"node_started", "node_accepted", "node_failed", "node_dependency_reused", "workflow_completed", "workflow_failed"}:
            payload = {"event": event, "node_id": data.get("node_id"), "dependency_id": data.get("dependency_id"),
                       "source_run_id": data.get("source_run_id"), "accepted": data.get("accepted"), "reason": data.get("reason")}
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            atomic_write_json(root / ".merak/FULL_BENCHMARK_PROGRESS.json", payload)
    with ExitStack() as stack:
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
        try:
            result = await execute_new_benchmark(host, root, config, source_gates=source_gates,
                                                  rerun_literature=rerun_literature,
                                                  rerun_source_owners=rerun_source_owners, on_event=progress)
        finally:
            await host.shutdown()
    return {**result, "blocked_operations": blocked, "accepted": result["accepted"] and not blocked}


async def prepare_and_execute(root: Path, original: Path, source_run_id: str, offline_receipt: Path, *,
                              rerun_literature: bool, rerun_source_owners: bool = False,
                              authority_context: dict | None = None) -> dict:
    """Current whole offline admission and original-owner gates precede provider setup."""
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    from scripts.full_benchmark_engine import FullBenchmarkEngine
    from server.agent import init_models_from_config, model_router
    from server.agent.tools import register_all_tools
    from server.services.skill_registry import skill_registry

    offline = validate_offline_receipt(offline_receipt)
    imported = (archive_source_history(root, original, source_run_id) if rerun_source_owners
                else import_source_owner_evidence(root, original, source_run_id))
    source = json.loads((original / f".merak/runs/{source_run_id}.json").read_text(encoding="utf-8-sig"))
    host = FullBenchmarkEngine()
    if authority_context is None:
        raise ValueError("Full validation requires independently pinned historical benchmark authority")
    from scripts.full_benchmark_preparation import prepare_stage_targets, CurrentBenchmarkPreparation, refresh_current_authority

    prepare_stage_targets(root)
    current_authority = refresh_current_authority(root, authority_context)
    preparation = CurrentBenchmarkPreparation(host, root, current_authority,
        staged_implementation=host._execute_staged_experiment_implementation)
    host._execute_staged_experiment_implementation = preparation.integrate
    host._ensure_planned_result_templates = preparation.ensure
    before = numerical_fingerprint(root)
    models = load_current_model_config_readonly(REPOSITORY)
    install_benchmark_write_guard(root, rerun_literature=rerun_literature or rerun_source_owners,
                                  rerun_source_owners=rerun_source_owners)
    reused = () if rerun_source_owners else ("idea", "novelty") if rerun_literature else SOURCE_NODES
    source_gates = check_source_owners(host, root, source_run_id, reused)
    validate_offline_receipt(offline_receipt)
    init_models_from_config(models)
    if not model_router._providers:
        raise RuntimeError("No configured real model provider is available")
    skill_registry.scan_directory(str(REPOSITORY / "merak-skills"))
    register_all_tools()
    validate_offline_receipt(offline_receipt)
    result = await _authorized_run(host, root, source["config"], source_gates,
                                   rerun_literature or rerun_source_owners, rerun_source_owners)
    unchanged = before == numerical_fingerprint(root)
    return {**result, "offline_verification": offline, "source_evidence": imported,
            "raw_numerical_and_semantic_bundle_unchanged": unchanged, "training_authorized": False,
            "real_model_execution": True, "original_workflow_resumed": False,
            "accepted": result["accepted"] and unchanged}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--offline-report", type=Path, required=True)
    parser.add_argument("--frozen-reference", type=Path, required=True)
    parser.add_argument("--historical-inputs-sha256", required=True)
    parser.add_argument("--benchmark-inventory-sha256", required=True)
    parser.add_argument("--allow-real-models", action="store_true", required=True)
    parser.add_argument("--rerun-literature", action="store_true")
    parser.add_argument("--rerun-source-owners", action="store_true",
                        help="Execute all 13 genuine owners; source reports may be repaired but accepted hypotheses remain frozen")
    options = parser.parse_args()
    offline = validate_offline_receipt(options.offline_report)
    source, original = options.source.resolve(strict=True), options.original.resolve(strict=True)
    if source.parent != REPOSITORY or not source.name.startswith("protocol-implementation-") or source == original:
        raise ValueError("Source must be the independent protocol implementation copy, never the original research project")
    source_before, original_before = tree_hashes(source), tree_hashes(original)
    reference = options.frozen_reference.resolve(strict=True)
    reference_before = tree_hashes(reference)
    root = Path(tempfile.mkdtemp(prefix="full-benchmark-verification-", dir=REPOSITORY)).resolve()
    copy_independent_project(source, root)
    authority_context = _authority_context(options, original, reference)
    numerical_before = numerical_fingerprint(root)
    os.chdir(root)
    os.environ.update({"PYTHONDONTWRITEBYTECODE": "1", "MERAK_SKILLS_PATH": str(REPOSITORY / "merak-skills"),
        "MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY": "1", "MPLCONFIGDIR": str(root / ".mpl-cache"),
        "TEMP": str(root), "TMP": str(root), "openout_any": "p", "shell_escape": "f"})
    os.environ.pop("MERAK_ELECTRON_API_PORT", None)
    tempfile.tempdir = str(root)
    try:
        result = asyncio.run(prepare_and_execute(root, original, options.source_run_id, Path(offline["receipt_path"]),
                                                rerun_literature=options.rerun_literature,
                                                rerun_source_owners=options.rerun_source_owners,
                                                authority_context=authority_context))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        result = {"accepted": False, "issues": [f"{type(error).__name__}: {error}"]}
    originals_unchanged = (source_before == tree_hashes(source) and original_before == tree_hashes(original)
                          and reference_before == tree_hashes(reference))
    numerical_unchanged = numerical_before == numerical_fingerprint(root)
    result.update({"snapshot_path": str(root), "originals_unchanged": originals_unchanged,
                   "raw_numerical_and_semantic_bundle_unchanged": numerical_unchanged})
    result["accepted"] = result["accepted"] and originals_unchanged and numerical_unchanged
    from server.utils.atomic_write import atomic_write_json

    print(json.dumps(result, ensure_ascii=False), flush=True)
    atomic_write_json(root / "FULL_BENCHMARK_REPORT.json", result)
    return 0 if result["accepted"] else 1


def _authority_context(options, original: Path, reference: Path) -> dict:
    from server.services.frozen_benchmark_authority import historical_inputs_digest, benchmark_inventory_digest

    config = json.loads((original / f".merak/runs/{options.source_run_id}.json").read_text(encoding="utf-8-sig"))["config"]
    saved = config["options"]
    settings = {"direction": config["direction"], "evidence_mode": "synthetic_preview",
        "target_venue": str(saved.get("target_venue") or ""), "research_family": str(saved.get("research_family") or ""),
        "study_archetype": str(saved.get("study_archetype") or "")}
    if (historical_inputs_digest(original, settings) != options.historical_inputs_sha256
            or benchmark_inventory_digest(reference) != options.benchmark_inventory_sha256):
        raise ValueError("Original benchmark owners differ from their independently observed pins")
    return {"schema": 1, "historical_inputs_root": str(original), "frozen_reference_root": str(reference),
        "historical_inputs_pin": options.historical_inputs_sha256, "benchmark_inventory_pin": options.benchmark_inventory_sha256,
        "settings": settings, "prospective_inventory_pin": ""}


if __name__ == "__main__":
    raise SystemExit(main())
