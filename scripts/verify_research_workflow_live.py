"""Run an explicitly authorized full workflow using a frozen production runtime.

External account integrations and scientific training are disabled. Synthetic
preview generation is part of the requested workflow; its results never become
executed empirical evidence. No producer, model or acceptance gate is mocked.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))


def verify_runtime() -> str:
    payload = json.loads((RUNTIME / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    for relative, digest in payload["files"].items():
        if hashlib.sha256((RUNTIME / relative).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen validation source changed: {relative}")
    return payload["source_id"]


def initialize_providers(settings_root: Path, transport: str = "") -> None:
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    from server.agent import init_models_from_config
    from server.agent.tools import register_all_tools
    from server.services.skill_registry import skill_registry
    from server.services.notification import NotifyConfig, notification_service
    from server.services.integration_environment import apply_integration_environment

    config = load_current_model_config_readonly(settings_root)
    if transport:
        config = config.model_copy(update={"openai_transport": transport})
    init_models_from_config(config)
    apply_integration_environment(config)
    skill_registry.scan_directory(RUNTIME / "merak-skills")
    register_all_tools()
    notification_service._config = NotifyConfig()


def prepare_inputs(root: Path, source: Path) -> dict:
    from server.contracts.workflow_nodes import WORKFLOW_NODES
    from server.services.project_scaffold import scaffold_project

    saved = json.loads(source.read_text(encoding="utf-8-sig"))
    config = saved["config"]
    scaffold_project(root, name="Research lifecycle validation", direction=config["direction"], mode="create")
    options = {key: value for key, value in config["options"].items()
               if not key.startswith("_") and key not in {
                   "resume_run_id", "specialist_plan_path", "research_profile", "selected_node_ids"}}
    options.update(run_experiment=False, gpu_target="none", ssh_server_id="",
                   enable_overleaf_sync=False, overleaf_project_id="", enable_zotero=False,
                   enable_obsidian=False, enable_meta_optimization=False, wandb=False,
                   platform_auto_recovery=False, human_checkpoint=False,
                   staged_experiment_implementation=True, non_experiment_evidence_mode="synthetic_preview")
    return {"direction": config["direction"], "effort": config["effort"], "assurance": config["assurance"],
            "node_ids": [node["id"] for node in WORKFLOW_NODES], "options": options,
            "source_config_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


async def execute(args) -> dict:
    from server.utils.atomic_write import atomic_write_json
    from server.workflows.engine import WorkflowEngine
    from server.workflows.run_state import RunState

    source_id = verify_runtime()
    root = args.project.resolve()
    inputs_path = root / ".merak/live-verification-inputs.json"
    if args.resume:
        inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    else:
        inputs = prepare_inputs(root, args.source_run)
        atomic_write_json(inputs_path, inputs)
    if args.delivery_goal:
        before = inputs["options"].get("delivery_goal", "submission_candidate")
        inputs["options"]["delivery_goal"] = args.delivery_goal
        atomic_write_json(root / f".merak/live-delivery-selection-{int(time.time())}.json",
            {"previous": before, "selected": args.delivery_goal, "reason": "explicit researcher delivery choice"})
        atomic_write_json(inputs_path, inputs)
    if args.literature_sources:
        previous = list(inputs["options"]["research_strategy"]["literature_sources"])
        selected = args.literature_sources.split(",")
        if not set(selected) <= {"arxiv", "semantic_scholar", "openalex", "pubmed", "web"}:
            raise ValueError("Unknown literature source override")
        inputs["options"]["research_strategy"]["literature_sources"] = selected
        atomic_write_json(root / f".merak/live-source-selection-{int(time.time())}.json",
                          {"previous": previous, "selected": selected, "reason": args.source_reason})
        atomic_write_json(inputs_path, inputs)
    initialize_providers(args.settings_root, args.model_transport)
    host = WorkflowEngine()
    start = time.time()
    events_path = root / ".merak/live-verification-events.jsonl"

    async def event(kind, data):
        value = {"type": kind, **data}
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        if kind not in {"agent_text", "agent_thinking", "node_stream", "node_agent_event"}:
            print(json.dumps(value, ensure_ascii=False, default=str)[:1400], flush=True)

    if args.resume:
        run_id = await host.resume_persisted_run(project_path=str(root), run_id=args.resume,
            on_event=event, pipeline_options=inputs["options"], checkpoint_feedback=args.feedback)
    else:
        run_id = await host.execute(node_ids=inputs["node_ids"], project_path=str(root),
            research_direction=inputs["direction"], effort=inputs["effort"], assurance=inputs["assurance"],
            pipeline_options=inputs["options"], on_event=event)
    atomic_write_json(root / ".merak/live-verification-active.json", {"run_id": run_id, "source_id": source_id})
    task = host._running_tasks[run_id]
    while not task.done():
        if args.max_seconds and time.time() - start >= args.max_seconds:
            await host.cancel_run(run_id)
            break
        if (root / ".merak/live-verification-cancel.request").is_file():
            await host.cancel_run(run_id)
            break
        await asyncio.wait({task}, timeout=2)
    if not task.cancelled():
        await task
    state = RunState(str(root), run_id).load() or {}
    phases = {key: value.get("status") for key, value in state.get("phases", {}).items()}
    result = {"run_id": run_id, "source_id": source_id, "runtime_unchanged": verify_runtime() == source_id,
              "status": state.get("status"), "phases": phases, "seconds": time.time() - start,
              "accepted": state.get("status") == "completed" and len(phases) == 13
                          and all(value == "accepted" for value in phases.values()),
              "real_models": True, "model_transport_override": args.model_transport,
              "training_executed": False, "external_integrations_verified": False}
    atomic_write_json(root / f".merak/live-verification-{run_id}-{int(start)}.json", result)
    return result


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-model", action="store_true", required=True)
    parser.add_argument("--settings-root", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--resume", default="")
    parser.add_argument("--literature-sources", default="")
    parser.add_argument("--source-reason", default="")
    parser.add_argument("--feedback", default="")
    parser.add_argument("--model-transport", choices=("stream", "non_stream"), default="")
    parser.add_argument("--delivery-goal", choices=("submission_candidate", "reviewable_draft"), default="")
    parser.add_argument("--max-seconds", type=int, default=3600)
    parser.add_argument("--allow-existing-project", action="store_true")
    args = parser.parse_args()
    if args.allow_existing_project and not args.resume:
        raise ValueError('Existing-project authorization is only for an explicit resume')
    if not args.allow_existing_project and not args.project.resolve().is_relative_to(args.settings_root.resolve() / "output"):
        raise ValueError("Validation project must remain under the workspace output directory")
    os.chdir(RUNTIME)
    result = asyncio.run(execute(args))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
