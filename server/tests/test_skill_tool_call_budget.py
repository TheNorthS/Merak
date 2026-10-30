"""Runtime tool limits bound isolated skills without model calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.agent.engine import agent_engine
from server.agent.tools import skill_tool


@pytest.mark.asyncio
async def test_isolated_skill_receives_hard_tool_call_limits(monkeypatch, tmp_path) -> None:
    session = SimpleNamespace(max_iterations=40, tool_call_limits={})
    loaded = SimpleNamespace(root=tmp_path, name="model-svg-figure", lineage=["model-svg-figure"])
    monkeypatch.setattr(skill_tool, "_load_skill", lambda *_args: loaded)
    monkeypatch.setattr(skill_tool, "_system_prompt", lambda *_args: ("fixture", []))
    monkeypatch.setattr(skill_tool, "_allowed_tools", lambda *_args: ["submit_model_svg_draft"])
    monkeypatch.setattr(skill_tool, "_new_trace", lambda *_args: (tmp_path / "trace.json", {}))
    monkeypatch.setattr(agent_engine, "create_session", lambda **_kwargs: session)

    async def traced(*_args):
        assert session.tool_call_limits == {"submit_model_svg_draft": 3}
        assert session.max_iterations == 24
        return "bounded"

    monkeypatch.setattr(skill_tool, "_run_traced", traced)
    assert await skill_tool.invoke_skill(
        "model-svg-figure", max_iterations=24,
        tool_call_limits={"submit_model_svg_draft": 3},
    ) == "bounded"


@pytest.mark.asyncio
async def test_invalid_tool_limit_is_rejected_before_delegate_execution(monkeypatch) -> None:
    session = SimpleNamespace(max_iterations=40, tool_call_limits={})
    loaded = SimpleNamespace(root="fixture-root", name="model-svg-figure", lineage=["model-svg-figure"])
    monkeypatch.setattr(skill_tool, "_load_skill", lambda *_args: loaded)
    monkeypatch.setattr(skill_tool, "_system_prompt", lambda *_args: ("fixture", []))
    monkeypatch.setattr(agent_engine, "create_session", lambda **_kwargs: session)
    with pytest.raises(ValueError, match="positive integer"):
        await skill_tool.invoke_skill(
            "model-svg-figure", tool_call_limits={"submit_model_svg_draft": 0},
        )
