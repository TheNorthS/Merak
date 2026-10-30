"""Explicit packaged recovery of a user's interrupted, non-training workflow."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.stability_package_runtime import PackageRuntime, digest, freeze_sources, package_identity, write_json
from scripts.verify_stability_live import collect_events, compact_state, wait_for_run, NODES


def preserve_baseline(project: Path, output: Path, run_id: str) -> dict:
    """Keep a recoverable copy of managed research text and its durable checkpoints."""
    import zipfile
    paths = [path for path in project.rglob("*") if path.is_file()
             and path.suffix.lower() in {".py", ".json", ".jsonl", ".md", ".yaml", ".yml", ".bib", ".tex"}
             and not set(path.relative_to(project).parts).intersection({"data", "checkpoints", ".git", "__pycache__"})]
    manifest = {path.relative_to(project).as_posix(): digest(path) for path in paths}
    with zipfile.ZipFile(output / "before-recovery.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(project).as_posix())
    write_json(output / "before-manifest.json", manifest)
    state = json.loads((project / ".merak/runs" / f"{run_id}.json").read_bytes())
    write_json(output / "before-state.json", state)
    return state


async def recover(args) -> dict:
    project, output = args.project.resolve(), args.output.resolve()
    if not output.is_relative_to(ROOT / "output/stability"):
        raise ValueError("Recovery evidence must stay in a new output/stability directory")
    state = json.loads((project / ".merak/runs" / f"{args.run_id}.json").read_bytes())
    if state.get("status") in {"running", "paused", "completed"}:
        raise ValueError("Only an interrupted workflow may be resumed by this acceptance runner")
    options = state.get("config", {}).get("options", {})
    if options.get("run_experiment") or any(options.get(key) for key in (
        "enable_zotero", "enable_obsidian", "enable_overleaf_sync", "enable_meta_optimization",
    )):
        raise ValueError("This recovery authorization excludes training and external integration mutations")
    output.mkdir(parents=True, exist_ok=False)
    identity = package_identity(args.package.resolve())
    freeze_sources(output)
    before = preserve_baseline(project, output, args.run_id)
    runtime = PackageRuntime(args.package.resolve(), output, args.settings_root.resolve())
    report = {"accepted": False, "identity": identity, "run_id": args.run_id, "project": str(project),
              "real_models": True, "training_executed": False, "started_at": time.time()}
    events = None
    try:
        await runtime.start()
        await runtime.configure_models()
        from scripts.stability_workflow_display import show_project, verify_terminal_display
        await show_project(runtime, project)
        ready = asyncio.Event()
        events = asyncio.create_task(collect_events(runtime, output / "events.jsonl", ready))
        await asyncio.wait_for(ready.wait(), 15)
        await runtime.request("POST", f"/api/workflow/runs/{args.run_id}/resume", json={
            "project_path": str(project), "delivery_goal": "reviewable_draft",
            **({"checkpoint_feedback": args.feedback_file.read_text(encoding="utf-8-sig")}
               if getattr(args, "feedback_file", None) else {}),
        })
        state = await wait_for_run(runtime, project, args.run_id, output, args.hours)
        report["display"] = await verify_terminal_display(runtime, state.get("status"), output)
        write_json(output / "final-state.json", state)
        preserved = {node: state.get("phases", {}).get(node, {}).get("verdict_id") == phase.get("verdict_id")
                     for node, phase in before.get("phases", {}).items() if phase.get("status") == "accepted"}
        phases = compact_state(state)["phases"]
        report.update(compact_state(state), accepted_phases_preserved=preserved,
                      package_unchanged=package_identity(args.package.resolve()) == identity)
        report["accepted"] = (state.get("status") == "completed" and set(phases) == set(NODES)
                              and all(value == "accepted" for value in phases.values())
                              and all(preserved.values()) and report["package_unchanged"] and report["display"]["accepted"])
    except Exception as exc:
        report["error"] = runtime.clean(str(exc))
    finally:
        if events:
            events.cancel()
            await asyncio.gather(events, return_exceptions=True)
        try:
            await runtime.close()
        finally:
            write_json(output / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-model", required=True, action="store_true")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--settings-root", required=True, type=Path)
    parser.add_argument("--package", type=Path, default=ROOT / "release/win-unpacked")
    parser.add_argument("--hours", type=float, default=6)
    parser.add_argument("--feedback-file", type=Path, help="Explicit human continuation instructions")
    result = asyncio.run(recover(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
