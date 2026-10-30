"""Explicitly authorized, isolated real-model verification of remaining nodes.

The original project is read-only. Existing scientific inputs are copied and
hash-preserved; authorized narrative/figure revalidation and the five remaining
paper/review/audit/compile/slides nodes may run. No application
lifespan, recovery watchdog, experiment scheduler or remote host is started.
Model calls are real and potentially billable. Acceptance gates are untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
REMAINING_NODES = ("narrative", "figure", "paper", "review", "audit", "compile", "ppt")


def validate_offline_receipt(path: Path) -> dict:
    from scripts.verify_offline_suite import verification_code_sha256
    receipt = json.loads(path.read_text(encoding="utf-8"))
    current_inventory = {path.name for path in (REPOSITORY / "server/tests").glob("test_*.py")}
    current_count = len(current_inventory)
    selected = receipt.get("selected_test_files")
    inventory_complete = (isinstance(selected, list) and all(isinstance(name, str) for name in selected)
                          and len(selected) == len(set(selected)) and set(selected) == current_inventory)
    if (receipt.get("pytest_exit_code") != 0 or receipt.get("excluded_test_files") or receipt.get("start_after") or receipt.get("stop_at")
            or receipt.get("test_files") != current_count or receipt.get("code_unchanged") is not True
            or receipt.get("code_sha256") != verification_code_sha256()
            or not inventory_complete or receipt.get("shard_count", 1) != 1 or receipt.get("shard_index", 0) != 0
            or receipt.get("network_allowed") is not False or receipt.get("shared_mutations_allowed") is not False):
        raise ValueError("Real-model verification requires a passing, current, complete offline suite receipt")
    suites = ET.parse(receipt["report_path"]).getroot().findall("testsuite")
    if not suites or any(int(suite.get("failures", "0")) or int(suite.get("errors", "0")) for suite in suites):
        raise ValueError("Offline JUnit report contains failures or errors")
    actual_tests = sum(int(suite.get("tests", "0")) for suite in suites)
    skipped = sum(int(suite.get("skipped", "0")) for suite in suites)
    if actual_tests <= skipped or actual_tests < current_count:
        raise ValueError("Offline report contains no meaningful complete test inventory")
    return {"receipt_path": str(path.resolve()), "code_sha256": receipt["code_sha256"],
            "test_files": current_count, "tests": actual_tests, "skipped": skipped}


def protected_inputs(root: Path) -> dict[str, str]:
    paths = [path for name in ("ideas", "literature", "experiments")
             for path in (root / name).rglob("*") if path.is_file()]
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def install_write_guard(root: Path) -> None:
    from scripts.verify_offline_suite import _write_path, canonical_io_path

    def check(value):
        _write_path(value, root)
        if isinstance(value, (str, bytes, os.PathLike)):
            target = canonical_io_path(value)
            if any(target.is_relative_to(root / name) for name in ("ideas", "literature", "experiments")):
                raise PermissionError("Live verification cannot mutate frozen scientific inputs")

    def audit(event, arguments):
        if event == "open":
            value, mode, flags = arguments
            if (isinstance(mode, str) and any(item in mode for item in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            ):
                check(value)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            check(arguments[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            for value in arguments[:2]:
                check(value)
        elif event == "subprocess.Popen":
            executable, _arguments, cwd, _environment = arguments
            from scripts.live_snapshot_compilation import validate_spawn_scope
            validate_spawn_scope(root, executable, _arguments, cwd)
    sys.addaudithook(audit)


def reject_scientific_execution(*_args, **_kwargs):
    raise RuntimeError("Live verification prohibits training, experiments and new simulation data")


async def suppress_notification(**_kwargs):
    return {"delivered": False, "reason": "external notifications disabled for isolated verification"}


async def run_remaining(root: Path, run_id: str) -> dict:
    from scripts.live_snapshot_safety import blocked_snapshot_tools, check_snapshot_session
    from scripts.live_snapshot_compilation import restricted_snapshot_compilation
    from server.agent.engine import agent_engine
    from server.workflows.engine import WorkflowEngine
    from server.workflows.run_state import RunState
    from server.utils.atomic_write import atomic_write_json

    host = WorkflowEngine()
    original_execute, original_tool = host.execute, agent_engine._execute_tool
    blocked = []

    async def selected_execution(**options):
        scope = dict(options.get("pipeline_options") or {})
        if (not set(options.get("node_ids") or []).issubset(REMAINING_NODES)
                or Path(str(options.get("project_path") or "")).resolve() != root
                or scope.get("run_experiment") is True or scope.get("resume_run_id") != run_id):
            raise RuntimeError("Remaining-node verification cannot restart upstream research or experiments")
        return await original_execute(**options)

    async def guarded_tool(session, tool_call, on_event=None):
        check_snapshot_session(session, root)
        return await original_tool(session, tool_call, on_event)

    async def progress(event, data):
        if event in {"node_started", "node_accepted", "node_failed", "node_revision_gate", "workflow_completed", "workflow_failed"}:
            payload = {"event": event, "node_id": data.get("node_id"), "time": time.time(),
                       "accepted": data.get("accepted"), "reason": data.get("reason")}
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            atomic_write_json(root / ".merak/LIVE_VERIFICATION_PROGRESS.json", payload)

    with ExitStack() as stack:
        stack.enter_context(patch.object(host, "execute", selected_execution))
        stack.enter_context(patch.object(host, "_execute_managed_experiment", reject_scientific_execution))
        stack.enter_context(patch.object(agent_engine, "_execute_tool", guarded_tool))
        stack.enter_context(blocked_snapshot_tools(agent_engine, root, blocked))
        stack.enter_context(restricted_snapshot_compilation(root))
        for target in ("server.services.experiment_placeholders.experiment_placeholder_service.ensure",
                       "server.services.simulation_benchmark.build_simulation_benchmark",
                       "server.services.experiment_runner.experiment_scheduler.submit_experiment"):
            stack.enter_context(patch(target, reject_scientific_execution))
        for name in ("workflow_completed", "workflow_failed"):
            stack.enter_context(patch(f"server.services.notification.notification_service.{name}", suppress_notification))
        try:
            await host.resume_persisted_run(run_id, str(root), node_ids=list(REMAINING_NODES),
                                           pipeline_options={"enable_overleaf_sync": False, "human_checkpoint": False},
                                           resume_source="explicit", on_event=progress)
            task = host._running_tasks.get(run_id)
            if task is None:
                raise RuntimeError("No live verification worker was created")
            await task
        finally:
            await host.shutdown()
    state = RunState(str(root), run_id).load() or {}
    phases = {node: phase.get("status") for node, phase in (state.get("phases") or {}).items()}
    return {"status": state.get("status"), "phases": phases, "completion": state.get("completion") or {},
            "blocked_operations": blocked, "accepted": bool(state.get("status") == "completed"
                                                           and all(phases.get(node) == "accepted" for node in REMAINING_NODES))}


async def prepare_and_run(root: Path, original: Path, run_id: str, offline_report: Path) -> dict:
    from scripts.verify_figure_snapshot import SnapshotEngine, snapshot_run, verify as verify_figures
    from scripts.live_snapshot_copy import relocate_specialist_plan_same_run
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    from scripts.live_snapshot_revalidation import revalidate_upstream_acceptance
    from server.agent import init_models_from_config, model_router
    from server.agent.tools import register_all_tools
    from server.services.skill_registry import skill_registry

    specialist = relocate_specialist_plan_same_run(root, original, run_id)
    prepared_run, prepared_config = snapshot_run(root, run_id)
    # Refresh only derived rendering/portfolio metadata before freezing the
    # copied scientific inputs. Real resume remains unable to alter that freeze.
    await SnapshotEngine()._refresh_simulation_renderer_before_revalidation(
        prepared_run, str(prepared_config.get("direction") or ""),
    )
    figure_gate = await verify_figures(root, "", run_id, original_project=original)
    if not figure_gate["accepted"]:
        raise RuntimeError("Copied figure prerequisite did not pass its complete real acceptance gate")
    upstream = revalidate_upstream_acceptance(SnapshotEngine(), root, original, run_id)
    before = protected_inputs(root)
    validate_offline_receipt(offline_report)
    config = load_current_model_config_readonly(REPOSITORY)
    init_models_from_config(config)
    if not model_router._providers:
        raise RuntimeError("No configured model provider is available for authorized real verification")
    skill_registry.scan_directory(str(REPOSITORY / "merak-skills"))
    register_all_tools()
    install_write_guard(root)
    validate_offline_receipt(offline_report)
    result = await run_remaining(root, run_id)
    result.update({"scientific_inputs_unchanged": before == protected_inputs(root),
                   "figure_prerequisite_accepted": True, "source_specialist_snapshot": specialist,
                   "upstream_readonly_revalidation": upstream,
                   "real_model_execution": True, "training_authorized": False, "original_workflow_resumed": False})
    result["accepted"] = result["accepted"] and result["scientific_inputs_unchanged"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--offline-report", type=Path, required=True)
    parser.add_argument("--allow-real-models", action="store_true", required=True)
    parser.add_argument("--allow-narrative-revalidation", action="store_true", required=True)
    options = parser.parse_args()
    offline = validate_offline_receipt(options.offline_report)
    original = options.project.resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="live-verification-106-", dir=REPOSITORY)).resolve()
    os.chdir(root)
    os.environ.update({"MERAK_SKILLS_PATH": str(REPOSITORY / "merak-skills"),
                       "MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY": "1", "PYTHONDONTWRITEBYTECODE": "1",
                       "TEMP": str(root), "TMP": str(root), "MPLCONFIGDIR": str(root / "matplotlib"),
                       "openout_any": "p", "shell_escape": "f"})
    os.environ.pop("MERAK_ELECTRON_API_PORT", None)
    tempfile.tempdir = str(root)
    from scripts.verify_paper_preparation_snapshot import files
    from scripts.live_snapshot_copy import additional_input_files, safe_selected_input_files
    from scripts.verify_figure_snapshot import hashes
    from server.utils.atomic_write import atomic_write_json

    selected = safe_selected_input_files(original, [*files(original), *additional_input_files(original, options.run_id)])
    before = hashes(selected, original)
    for source in selected:
        target = root / source.relative_to(original)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(json.dumps({"snapshot_path": str(root), "authorized_real_models": True, "training": False}), flush=True)
    try:
        result = asyncio.run(prepare_and_run(root, original, options.run_id, Path(offline["receipt_path"])))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        result = {"accepted": False, "issues": [f"{type(error).__name__}: {error}"]}
    result.update({"snapshot_path": str(root), "original_inputs_unchanged": before == hashes(selected, original),
                   "offline_verification": offline})
    result["accepted"] = result["accepted"] and result["original_inputs_unchanged"]
    atomic_write_json(root / ".merak/LIVE_VERIFICATION_REPORT.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
