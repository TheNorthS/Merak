"""Verify a real sidebar edit leaves its completed workflow immutable."""

import asyncio
import json
from pathlib import Path
import time

from websockets.asyncio.client import connect

from scripts.stability_package_runtime import PackageRuntime, digest, write_json


async def receive(socket, log, runtime: PackageRuntime, wanted: set[str], timeout: float = 300) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(socket.recv(), max(1, deadline - time.monotonic()))
        event = json.loads(raw)
        log.write(runtime.clean(json.dumps(event, ensure_ascii=False)) + "\n")
        log.flush()
        if event.get("type") in {"agent_error", "change_error", "protocol_error"}:
            raise RuntimeError(runtime.clean(str(event)))
        if event.get("type") in wanted:
            return event
    raise RuntimeError("Sidebar revision timed out")


async def verify_sidebar_revision(runtime: PackageRuntime, case: dict, *, project_path: Path | None = None) -> dict:
    project = project_path.resolve() if project_path else runtime.output / "projects" / case["case"]
    evidence = runtime.output / case["case"]
    run_path = project / ".merak/runs" / f"{case['run_id']}.json"
    run_before = digest(run_path)
    files = sorted((project / "paper/sections").glob("*intro*.tex"))
    if not files:
        raise RuntimeError("Completed draft has no introduction section for sidebar verification")
    target = files[0]
    before = digest(target)
    all_runs = {path.name: digest(path) for path in (project / ".merak/runs").glob("*.json")}
    with (evidence / "sidebar-events.jsonl").open("w", encoding="utf-8") as log:
        async with runtime.websocket("/api/chat/ws") as socket:
            await socket.send(json.dumps({"type": "create_session", "project_path": str(project),
                                          "provider": "openai-api", "role": "executor"}))
            session = (await receive(socket, log, runtime, {"session_created"}))["session_id"]
            await socket.send(json.dumps({
                "type": "message", "mode": "edit", "project_path": str(project),
                "content": f"Read {target.relative_to(project).as_posix()} and propose exactly one small Edit "
                           "to improve clarity of one introductory prose sentence. Preserve scientific meaning, "
                           "all numbers, citations and evidence qualifications. Do not change other files or run "
                           "workflow nodes. Use Read and Edit to submit one proposal for approval.",
            }))
            proposal = (await receive(socket, log, runtime, {"agent_change_proposal"}))["data"]
            await receive(socket, log, runtime, {"agent_done"})
            if digest(target) != before or Path(proposal["path"]).resolve() != target.resolve():
                raise RuntimeError("Sidebar proposal modified a file before approval or targeted another file")
            await socket.send(json.dumps({"type": "resolve_change", "session_id": session,
                                          "change_id": proposal["id"], "approved": True}))
            applied = (await receive(socket, log, runtime, {"change_applied"}))["data"]
    await asyncio.sleep(12)  # One normal recovery-watchdog cycle after the local edit.
    status = await runtime.request("GET", f"/api/workflow/run-states/{case['run_id']}",
                                    params={"project_path": str(project)})
    impact = applied.get("impact", {})
    after_runs = {path.name: digest(path) for path in (project / ".merak/runs").glob("*.json")}
    accepted = (applied.get("status") == "applied" and before != digest(target)
                and run_before == digest(run_path) and all_runs == after_runs
                and status.get("status") == "completed" and not status.get("runtime_active")
                and impact.get("workflow_restart_required") is False and impact.get("revision_mode") == "local")
    receipt = {"accepted": accepted, "real_models": True, "entrypoint": "sidebar_chat_websocket",
               "run_id": case["run_id"], "session_id": session, "change_id": proposal["id"],
               "before_sha256": before, "after_sha256": digest(target), "run_unchanged": run_before == digest(run_path),
               "no_new_runs": all_runs == after_runs, "impact": impact}
    write_json(evidence / "sidebar-receipt.json", receipt)
    return receipt
