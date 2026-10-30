"""Explicit real-model Chat edit verification with durable recovery and real tools."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


async def verify(root: Path) -> dict:
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    from server.agent import ModelRole, init_models_from_config
    from server.agent.engine import agent_engine
    from server.agent.session_persistence import restore_session
    from server.agent.tools import register_all_tools
    from server.api.chat_support import _apply_chat_scope, _chat_system_prompt, _chat_tools_for_mode, CHAT_MODE_PROMPTS
    from server.utils.atomic_write import atomic_write_json

    root.mkdir(parents=True, exist_ok=False)
    paper = root / "paper/sections/introduction.tex"
    paper.parent.mkdir(parents=True)
    original = "\\section{Introduction}\nThis study measures estimation error under controlled missingness.\nThe study has not been executed; no performance improvement is claimed.\n"
    paper.write_text(original, encoding="utf-8")
    run_path = root / ".merak/runs/chat-baseline.json"
    atomic_write_json(run_path, {"run_id": "chat-baseline", "status": "completed",
        "phases": {node: {"status": "accepted", "verdict_id": "fixture", "reviewer": "fixture",
                            "details": {}} for node in ("lit", "exp-run", "paper", "review", "audit", "compile", "ppt")}})
    completed_bytes = run_path.read_bytes()
    init_models_from_config(load_current_model_config_readonly(REPOSITORY))
    register_all_tools()
    session = agent_engine.create_session(system_prompt=_chat_system_prompt("edit"), role=ModelRole.EXECUTOR)
    _apply_chat_scope(session, str(root))
    session.provider_override = "openai-api"
    events = root / "model-events.jsonl"

    async def event(value):
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": value.type, "data": value.data}, ensure_ascii=False, default=str) + "\n")
        if value.type in {"tool_call", "tool_result", "error", "status", "heartbeat"}:
            print(json.dumps({"event": value.type}, ensure_ascii=False), flush=True)

    await agent_engine.run(session.id,
        CHAT_MODE_PROMPTS["edit"] + "\nPlease read paper/sections/introduction.tex and propose exactly one Edit to improve the "
        "first sentence for clarity. Keep the second sentence unchanged and do not add claims. "
        "Use the real Read and Edit tools. I will approve the resulting proposal in this validation.",
        on_event=event, tools=_chat_tools_for_mode("edit"))
    if paper.read_text(encoding="utf-8") != original or len(session.pending_changes) != 1:
        raise AssertionError("Chat must produce one durable proposal without changing the file")
    change_id = next(iter(session.pending_changes))
    agent_engine._sessions.pop(session.id)
    restored = restore_session(agent_engine._sessions, session.id, str(root))
    if restored is None or change_id not in restored.pending_changes:
        raise AssertionError("The real-model proposal was lost across session restoration")
    result = await agent_engine.resolve_pending_change(session.id, change_id, True)
    after = paper.read_text(encoding="utf-8")
    state = json.loads(run_path.read_text())
    accepted = (result["status"] == "applied" and after != original
                and original.splitlines()[2] in after
                and state["phases"]["exp-run"]["status"] == "accepted"
                and state["phases"]["compile"]["status"] == "accepted"
                and run_path.read_bytes() == completed_bytes
                and result.get("impact", {}).get("workflow_restart_required") is False)
    receipt = {"accepted": accepted, "real_model": True, "run_state_is_fixture": True,
               "session_id": session.id, "change_id": change_id,
               "tokens": restored.total_tokens, "usage_unknown_responses": restored.usage_unknown_responses,
               "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
               "after_sha256": hashlib.sha256(after.encode()).hexdigest(), "impact": result.get("impact")}
    atomic_write_json(root / "verification.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-model", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if not root.is_relative_to(REPOSITORY / "output"):
        raise ValueError("Live Chat verification must use a new directory under output/")
    result = asyncio.run(verify(root))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
