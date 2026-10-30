"""Verify current results-node production and acceptance in a fresh isolated copy.

Existing source data and original execution traces are immutable. Only local
derived analysis executes; workflows, models, scientific jobs and simulation
data generation are forbidden. Specialist evidence is explicitly relocated in
a separate verification plan without modifying its original invocation bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from scripts.verify_figure_snapshot import SnapshotEngine, hashes, snapshot_run
from scripts.verify_paper_preparation_snapshot import files as prior_files
from server.services.skill_execution_trace import stage_execution_evidence
from server.services.research_specialists import research_specialist_service
from server.workflows.run_execution_context import RunExecutionContext
from server.workflows.run_execution_node import run_planned_results
from server.workflows.run_execution_execute import persist_node_acceptance, refresh_node_audits
from server.workflows.revision_loop_context import RevisionComplete, RevisionLoopContext
from server.workflows.revision_loop_phases import initialize_revision, initialize_progress
from server.workflows.revision_gate_phases import (
    persist_gate_inputs, build_current_gate, record_runtime_gate, verify_runtime_execution,
    normalize_gate_outcome, complete_accepted_gate,
)
from server.workflows.run_state import RunState


def files(project: Path) -> list[Path]:
    selected = prior_files(project)
    for directory in ("experiments/specialists", ".merak/skill-invocations", "experiments/results"):
        selected.extend(path for path in (project / directory).rglob("*") if path.is_file()
                        and path.suffix.casefold() in {".md", ".json", ".jsonl", ".csv", ".yaml", ".py"})
    return sorted(set(selected))


def _forbidden(*_args, **_kwargs):
    raise RuntimeError("Model, workflow execution, training, simulation generation and manuscript compilation are prohibited")


def original_project_changes(before: dict[str, str], after: dict[str, str]) -> dict:
    """Compare the complete selected inventories, including newly written files."""
    changed = sorted(path for path in before.keys() & after.keys() if before[path] != after[path])
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    return {"original_project_unchanged": not (changed or added or removed),
            "original_changed_files": changed, "original_added_files": added,
            "original_removed_files": removed}


def original_runtime_mismatch(root: Path, run_id: str) -> dict:
    path = root / f".merak/runs/{run_id}.skills.json"
    payload = json.loads(path.read_text(encoding="utf8"))
    stage = payload.get("stages", {}).get("results") or {}
    evidence = stage_execution_evidence(stage, run_id)
    return {"declared_runtime": stage.get("runtime_service"),
            "completed_runtime_services": sorted({item.get("runtime_service") for item in stage.get("runtime_invocations") or []
                                                   if item.get("status") == "completed"}),
            "declared_runtime_verified": bool(evidence.get("runtime_execution_verified"))}


def relocate_specialist_plan(root: Path, original: Path, source_run_id: str, verification_run_id: str) -> dict:
    source = root / f".merak/runs/{source_run_id}.specialists.json"
    payload = json.loads(source.read_text(encoding="utf8"))
    clone = copy.deepcopy(payload)
    clone["run_id"] = verification_run_id
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    relocated = []
    for entry in clone.get("subnodes") or []:
        value = str(entry.get("invocation_trace") or "")
        if not value:
            continue
        path = Path(value).resolve()
        relative = path.relative_to(original.resolve())
        copied = root / relative
        if not copied.is_file():
            raise ValueError("Copied specialist invocation trace is missing")
        entry["invocation_trace"] = str(copied)
        relocated.append({"id": entry.get("id"), "source_trace_sha256": hashlib.sha256(copied.read_bytes()).hexdigest()})
    clone["snapshot_provenance"] = {"source_run_id": source_run_id, "source_plan_sha256": source_hash,
                                    "new_model_session_claimed": False}
    path = root / f".merak/runs/{verification_run_id}.specialists.json"
    path.write_text(json.dumps(clone, ensure_ascii=False), encoding="utf8")
    return {"metadata_relocated_for_snapshot": True, "new_model_session_claimed": False,
            "source_plan_preserved": hashlib.sha256(source.read_bytes()).hexdigest() == source_hash,
            "relocated_evidence_count": len(relocated)}


async def validate_current_node(host, run, config: dict, execution: RunExecutionContext) -> dict:
    ctx = RevisionLoopContext(host, execution.node, run, str(config.get("assurance") or "draft"),
                              str(config.get("direction") or ""), "balanced", run.options,
                              1, 1, execution.result, False, 2)
    await initialize_revision(ctx)
    await initialize_progress(ctx)
    await persist_gate_inputs(ctx)
    ctx.preparation_error = ""
    await build_current_gate(ctx)
    await record_runtime_gate(ctx)
    await verify_runtime_execution(ctx)
    await normalize_gate_outcome(ctx)
    if ctx.gate.get("accepted"):
        try:
            await complete_accepted_gate(ctx)
        except RevisionComplete:
            pass
        execution.gate = ctx.gate
        execution.run_state = ctx.run_state
        await persist_node_acceptance(execution)
        await refresh_node_audits(execution)
    return ctx.gate


async def verify(root: Path, original: Path, run_id: str) -> dict:
    host = SnapshotEngine()
    run, config = snapshot_run(root, run_id)
    source_run_id = run.id
    baseline = original_runtime_mismatch(root, source_run_id)
    run.id = "results-node-snapshot"
    specialist_clone = relocate_specialist_plan(root, original, source_run_id, run.id)
    source_trace_files = [path for path in (root / ".merak/skill-invocations").glob("*.json")]
    source_trace_files.extend(root / f".merak/runs/{source_run_id}{suffix}" for suffix in (".json", ".skills.json", ".specialists.json"))
    original_trace_hashes = hashes(source_trace_files, root)
    protected = [path for directory in ("ideas", "experiments/src", "experiments/configs")
                 for path in (root / directory).rglob("*") if path.is_file()]
    protected.extend(path for path in (root / "experiments/results").rglob("*.csv") if path.is_file())
    protected.extend(root / value for value in ("experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json") if (root / value).is_file())
    before = hashes(protected, root)
    node = next(node for node in run.nodes if node.id == "results")
    state = RunState(str(root), run.id)
    state.start([{"id": node.id, "name": node.name, "skill": node.skill}], {"options": run.options})
    execution = RunExecutionContext(host, run, str(config.get("direction") or ""), "balanced",
                                    str(config.get("assurance") or "draft"), run.options, run_state=state, node=node)
    with ExitStack() as stack:
        for target in ("server.agent.tools.invoke_skill", "server.agent.engine.agent_engine.run",
                       "server.agent.model_transport.ModelTransportMixin._chat_with_progress",
                       "server.services.simulation_benchmark.build_simulation_benchmark",
                       "server.services.experiment_placeholders.experiment_placeholder_service.ensure"):
            stack.enter_context(patch(target, _forbidden))
        await run_planned_results(execution)
        execution.result = await host._prepare_node_for_gate(node, run, execution.result,
                                                            execution.research_direction, execution.assurance, run.options)
        gate = await validate_current_node(host, run, config, execution)
    specialist_gate = research_specialist_service.gate_node(root, run.id, "results")
    phase = (state.load() or {}).get("phases", {}).get("results", {})
    details = gate.get("details") or {}
    return {"accepted": bool(gate.get("accepted")), "issues": details.get("issues") or ([] if gate.get("accepted") else [gate.get("summary")]),
            "source_run_id": source_run_id, "verification_run_id": run.id, "original_trace_baseline": baseline,
            "current_execution": details.get("execution_evidence") or {}, "specialist_evidence_accepted": bool(specialist_gate.get("accepted")),
            "specialist_snapshot": specialist_clone, "persisted_results_status": phase.get("status"),
            "source_contracts_and_numeric_data_unchanged": before == hashes([root / value for value in before], root),
            "original_execution_evidence_unchanged": original_trace_hashes == hashes(source_trace_files, root),
            "model_invoked": False, "scientific_execution_performed": False, "workflow_resumed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    options = parser.parse_args()
    project = options.project.resolve(strict=True)
    selected = files(project)
    before = hashes(selected, project)
    with tempfile.TemporaryDirectory(prefix="results-node-snapshot-", dir=REPOSITORY) as directory:
        root = Path(directory)
        for source in selected:
            target = root / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        try:
            result = asyncio.run(verify(root, project, options.run_id))
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            result = {"accepted": False, "issues": [f"{type(error).__name__}: {error}"]}
    after = hashes(files(project), project)
    result.update(original_project_changes(before, after))
    result["original_project_check_scope"] = "selected original project hashes compared only during this snapshot verification window"
    if not result["original_project_unchanged"]:
        result.setdefault("issues", []).append("Original project changed during the verification window; stop concurrent writers and verify again")
    result["accepted"] = result["accepted"] and result["original_project_unchanged"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
