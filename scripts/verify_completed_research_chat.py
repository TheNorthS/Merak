"""Validate a real Chat proposal while preserving a completed live run unchanged."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME))


async def verify(args) -> dict:
    from scripts.verify_research_workflow_live import initialize_providers, verify_runtime
    from server.agent import ModelRole
    from server.agent.engine import agent_engine
    from server.agent.session_persistence import restore_session
    from server.api.chat_support import _apply_chat_scope, _chat_system_prompt, _chat_tools_for_mode, CHAT_MODE_PROMPTS
    from server.utils.atomic_write import atomic_write_json

    root = args.project.resolve()
    if not root.is_relative_to(args.settings_root.resolve() / "output"):
        raise ValueError("Chat validation requires the authorized output project")
    source_id = verify_runtime()
    state_path = root / f".merak/runs/{args.run_id}.json"
    before_bytes = state_path.read_bytes()
    before_state = json.loads(before_bytes)
    if (before_state.get("status") != "completed" or len(before_state.get("phases", {})) != 13
            or any(phase.get("status") != "accepted" for phase in before_state["phases"].values())):
        raise ValueError("Chat continuation verification requires a genuinely completed 13-node run")
    paper = root / "paper/sections/01_introduction.tex"
    original = paper.read_text(encoding="utf-8")
    initialize_providers(args.settings_root, args.model_transport)
    session = agent_engine.create_session(system_prompt=_chat_system_prompt("edit"), role=ModelRole.EXECUTOR)
    _apply_chat_scope(session, str(root))
    session.provider_override = "openai-api"
    receipt_dir = root / ".merak/completed-chat-verification" / session.id
    receipt_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_json(receipt_dir / "before-run.json", before_state)
    (receipt_dir / "before-introduction.tex").write_text(original, encoding="utf-8")

    async def event(value):
        with (receipt_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": value.type, "data": value.data}, ensure_ascii=False, default=str) + "\n")

    await agent_engine.run(session.id, CHAT_MODE_PROMPTS["edit"] + "\nRead paper/sections/01_introduction.tex. "
        "Propose exactly one Edit that improves one prose sentence for clarity. Preserve all scientific claims, "
        "numbers, citations and LaTeX structure. Do not edit other files. The reviewed proposal will be applied "
        "as part of this authorized lifecycle validation.", on_event=event, tools=_chat_tools_for_mode("edit"))
    if paper.read_text(encoding="utf-8") != original or len(session.pending_changes) != 1:
        raise AssertionError("Chat must stage exactly one change without editing the source")
    change_id, change = next(iter(session.pending_changes.items()))
    if Path(change.path).resolve() != paper.resolve() or change.before != original or change.action != "edit":
        raise AssertionError("Chat proposal escaped the authorized introduction edit")
    agent_engine._sessions.pop(session.id)
    restored = restore_session(agent_engine._sessions, session.id, str(root))
    if restored is None or change_id not in restored.pending_changes:
        raise AssertionError("Real proposal did not survive session restoration")
    applied = await agent_engine.resolve_pending_change(session.id, change_id, True)
    impact = applied.get("impact", {})
    accepted = (applied["status"] == "applied" and state_path.read_bytes() == before_bytes
        and args.run_id in impact.get("completed_runs", [])
        and not impact.get("affected_runs") and impact.get("workflow_restart_required") is False)
    result = {"accepted": accepted, "real_model": True, "run_state_is_fixture": False,
        "run_id": args.run_id, "session_id": session.id, "change_id": change_id, "source_id": source_id,
        "runtime_unchanged": verify_runtime() == source_id, "training_executed": False,
        "completed_run_bytes_unchanged": state_path.read_bytes() == before_bytes,
        "scheduled_nodes": [],
        "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(paper.read_bytes()).hexdigest(), "impact": applied.get("impact")}
    atomic_write_json(receipt_dir / "verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-model", action="store_true", required=True)
    parser.add_argument("--settings-root", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-transport", choices=("stream", "non_stream"), default="non_stream")
    result = asyncio.run(verify(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["accepted"] else 1)
