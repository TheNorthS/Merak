"""Explicit real-model acceptance through the packaged application's public API."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.stability_package_runtime import PackageRuntime, digest, freeze_sources, package_identity, write_json

NODES = ["lit", "idea", "novelty", "exp-design", "exp-run", "results", "narrative", "figure",
         "paper", "review", "audit", "compile", "ppt"]
CASES = {
    "eeg": "Self-supervised EEG representation learning under missing channels: investigate whether "
           "channel-aware masking improves the planned robustness of compact representations. Focus on one "
           "testable mechanism, a conventional baseline and a matched ablation. Deliver a reviewable research "
           "draft with explicitly labelled synthetic previews; no real EEG training or clinical claims.",
    "timeseries": "Distribution shift detection in multivariate sensor time series: investigate robust "
                  "window normalization for distinguishing missingness from genuine drift. Focus on a compact "
                  "controlled comparison with one baseline and one ablation. Deliver a reviewable draft with "
                  "explicitly labelled synthetic previews; no real-world deployment or trained-model claims.",
    "graph": "Calibration of graph classifiers under edge sparsity: investigate degree-aware confidence "
             "calibration with a conventional baseline and a matched ablation. Keep the mechanism and "
             "evaluation plan focused. Deliver a reviewable research draft with explicitly labelled "
             "synthetic previews; no real graph-model training or empirical superiority claims.",
}


async def collect_events(runtime: PackageRuntime, path: Path, ready: asyncio.Event):
    """Exercise the same global event socket as the renderer; HTTP remains authoritative."""
    async with runtime.websocket("/ws/workflow") as socket:
        await socket.send(json.dumps({"type": "ping"}))
        with path.open("a", encoding="utf-8") as handle:
            async for raw in socket:
                event = json.loads(raw)
                handle.write(runtime.clean(json.dumps({"received_at": time.time(), **event}, ensure_ascii=False)) + "\n")
                handle.flush()
                if event.get("type") == "pong":
                    ready.set()


def compact_state(state: dict) -> dict:
    return {"status": state.get("status"), "current_node": state.get("current_node"),
            "runtime_active": state.get("runtime_active"),
            "phases": {key: value.get("status") for key, value in state.get("phases", {}).items()}}


async def wait_for_run(runtime: PackageRuntime, project: Path, run_id: str, case_dir: Path, hours: float) -> dict:
    started = time.monotonic()
    deadline = started + hours * 3600
    previous = None
    inactive_since = None
    last_notice = 0
    while time.monotonic() < deadline:
        state = await runtime.request("GET", f"/api/workflow/run-states/{run_id}",
                                      params={"project_path": str(project)})
        summary = compact_state(state)
        if summary != previous or time.monotonic() - last_notice >= 60:
            notice = {"run_id": run_id, "elapsed_seconds": round(time.monotonic() - started), **summary}
            write_json(case_dir / "progress.json", notice)
            print(json.dumps(notice, ensure_ascii=False), flush=True)
            previous, last_notice = summary, time.monotonic()
        if not state.get("runtime_active") and state.get("status") not in {"running", "paused"}:
            inactive_since = inactive_since or time.monotonic()
            if state.get("status") == "completed" or time.monotonic() - inactive_since > 25:
                return state
        else:
            inactive_since = None
        if (runtime.output / "cancel.request").exists():
            await runtime.request("POST", f"/api/workflow/runs/{run_id}/cancel",
                                  json={"project_path": str(project), "kill_experiment": False})
            raise RuntimeError("Acceptance stopped by operator; durable run remains resumable")
        await asyncio.sleep(5)
    await runtime.request("POST", f"/api/workflow/runs/{run_id}/cancel",
                          json={"project_path": str(project), "kill_experiment": False})
    raise RuntimeError("Acceptance time budget reached; run cancelled with resumable checkpoint")


async def run_case(runtime: PackageRuntime, name: str, hours: float) -> dict:
    case_dir = runtime.output / name
    case_dir.mkdir()
    project = runtime.output / "projects" / name
    request = {"node_ids": NODES, "project_path": str(project), "research_direction": CASES[name],
               "delivery_goal": "reviewable_draft", "assurance": "draft", "effort": "balanced",
               "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
               "research_family": "machine_learning", "study_archetype": "algorithm_benchmark",
               "literature_sources": ["arxiv", "openalex"], "literature_max_papers": 20,
               "target_venue": "ICLR", "human_checkpoint": False, "auto_proceed": True}
    write_json(case_dir / "request.json", request)
    await runtime.request("POST", "/api/projects/scaffold", json={
        "path": str(project), "name": f"Merak acceptance {name}", "venue": "ICLR",
        "direction": CASES[name], "mode": "create",
    })
    from scripts.stability_workflow_display import show_project, verify_terminal_display
    await show_project(runtime, project)
    ready = asyncio.Event()
    events = asyncio.create_task(collect_events(runtime, case_dir / "events.jsonl", ready))
    try:
        await asyncio.wait_for(ready.wait(), 15)
        started = await runtime.request("POST", "/api/workflow/run", json=request)
        run_id = started["run_id"]
        write_json(case_dir / "started.json", {"run_id": run_id, "started_at": time.time()})
        state = await wait_for_run(runtime, project, run_id, case_dir, hours)
        if events.done():
            events.result()
        write_json(case_dir / "final-state.json", state)
        display = await verify_terminal_display(runtime, state.get("status"), case_dir)
        phases = compact_state(state)["phases"]
        accepted = state.get("status") == "completed" and set(phases) == set(NODES)
        accepted = accepted and all(value == "accepted" for value in phases.values()) and display["accepted"]
        output_files = {path.relative_to(project).as_posix(): digest(path)
                        for directory in ("paper", "slides") for path in (project / directory).rglob("*")
                        if path.is_file() and path.suffix.lower() in {".pdf", ".pptx"}}
        accepted = accepted and "paper/main.pdf" in output_files and "slides/main.pdf" in output_files
        receipt = {"accepted": accepted, "run_id": run_id, "case": name, "real_models": True,
                   "entrypoint": "packaged_http_api", "websocket_connected": ready.is_set(),
                   "training_executed": False, "evidence_mode": "synthetic_preview",
                   "delivery_goal": "reviewable_draft", "outputs": output_files, **compact_state(state)}
        write_json(case_dir / "receipt.json", receipt)
        return receipt
    finally:
        events.cancel()
        await asyncio.gather(events, return_exceptions=True)


async def verify(args) -> dict:
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "output/stability"):
        raise ValueError("Acceptance output must be a new directory under output/stability")
    output.mkdir(parents=True, exist_ok=False)
    identity = package_identity(args.package.resolve())
    sources = freeze_sources(output)
    write_json(output / "candidate.json", identity)
    runtime = PackageRuntime(args.package.resolve(), output, args.settings_root.resolve())
    report = {"accepted": False, "identity": identity, "cases": [],
              "external_services": "skipped_by_user", "required_consecutive_runs": 3}
    try:
        await runtime.start()
        await runtime.configure_models()
        for name in CASES:
            receipt = await run_case(runtime, name, args.hours_per_case)
            report["cases"].append(receipt)
            write_json(output / "report.json", report)
            if not receipt["accepted"]:
                break
        if len(report["cases"]) == 3 and all(case["accepted"] for case in report["cases"]):
            from scripts.stability_sidebar_revision import verify_sidebar_revision
            report["sidebar_revision"] = await verify_sidebar_revision(runtime, report["cases"][0])
        report["package_unchanged"] = package_identity(args.package.resolve()) == identity
        from scripts.export_source import source_files
        report["sources_unchanged"] = sources == {
            path.relative_to(ROOT).as_posix(): digest(path) for path in source_files()
        }
        report["accepted"] = (len(report["cases"]) == 3 and all(case["accepted"] for case in report["cases"])
                              and report["package_unchanged"] and report["sources_unchanged"]
                              and report.get("sidebar_revision", {}).get("accepted") is True)
    except (RuntimeError, OSError, ValueError, TimeoutError, httpx.HTTPError) as exc:
        report["error"] = runtime.clean(str(exc))
    finally:
        await runtime.close()
        write_json(output / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-model", required=True, action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--settings-root", required=True, type=Path)
    parser.add_argument("--package", type=Path, default=ROOT / "release/win-unpacked")
    parser.add_argument("--hours-per-case", type=float, default=6)
    args = parser.parse_args()
    result = asyncio.run(verify(args))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
