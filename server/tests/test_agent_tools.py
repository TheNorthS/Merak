from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from server.agent import tools as agent_tools
from server.agent.tools.file_tools import FILE_READ_MAX_CHARS


def test_spawn_agent_uses_current_agent_package(monkeypatch) -> None:
    session = SimpleNamespace(id="child-session")

    monkeypatch.setattr(
        agent_tools.agent_engine,
        "create_session",
        lambda **_kwargs: session,
    )

    async def fake_run(**kwargs):
        assert kwargs["session_id"] == session.id
        return "child result"

    monkeypatch.setattr(agent_tools.agent_engine, "run", fake_run)

    result = asyncio.run(agent_tools.spawn_agent("inspect the artifact"))
    assert result == "child result"


def test_figure_manifest_returns_json_for_empty_project(tmp_path) -> None:
    result = asyncio.run(agent_tools.figure_manifest(str(tmp_path)))
    payload = json.loads(result)

    assert payload["schema"] == 1
    assert payload["figures"] == []


def test_file_read_uses_one_based_inclusive_line_numbers(tmp_path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("first\nsecond\nthird\nfourth\nfifth\nsixth\n", encoding="utf-8")

    first = asyncio.run(agent_tools.file_read(str(artifact), start_line=1, end_line=1))
    first_five = asyncio.run(agent_tools.file_read(str(artifact), start_line=1, end_line=5))

    assert first == "first"
    assert first_five == "first\nsecond\nthird\nfourth\nfifth"


def test_file_read_without_range_returns_entire_file(tmp_path) -> None:
    artifact = tmp_path / "artifact.txt"
    content = "first\nsecond\n"
    artifact.write_text(content, encoding="utf-8")

    assert asyncio.run(agent_tools.file_read(str(artifact))) == content


def test_file_read_caps_large_outputs_without_loading_them_into_context(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "predictions.jsonl"
    artifact.write_text(
        "x" * (FILE_READ_MAX_CHARS + 5000),
        encoding="utf-8",
    )

    content = asyncio.run(agent_tools.file_read(str(artifact)))

    assert "MERAK Read truncated this file" in content
    assert "Use start_line/end_line" in content
    assert len(content) < FILE_READ_MAX_CHARS + 500


def test_file_read_caps_large_requested_line_range(tmp_path: Path) -> None:
    artifact = tmp_path / "large.csv"
    artifact.write_text(
        "\n".join("row-" + ("x" * 500) for _ in range(1000)),
        encoding="utf-8",
    )

    content = asyncio.run(
        agent_tools.file_read(str(artifact), start_line=1, end_line=1000)
    )

    assert "MERAK Read truncated this file" in content
    assert len(content) < FILE_READ_MAX_CHARS + 500


def test_cross_model_review_accepts_file_path_only_and_keeps_trace_in_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "paper" / "main.tex"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("\\section{A cold review target}", encoding="utf-8")
    (tmp_path / ".merak").mkdir()
    session = SimpleNamespace(id="review-thread", max_iterations=50, project_path=".")
    captured: dict = {}

    monkeypatch.setattr(agent_tools.agent_engine, "create_session", lambda **_kwargs: session)

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return "Overall Score: 8/10"

    monkeypatch.setattr(agent_tools.agent_engine, "run", fake_run)
    result = asyncio.run(
        agent_tools.cross_model_review(
            file_path=str(artifact),
            project_path=str(tmp_path),
        )
    )

    assert result.startswith("[thread:review-thread]")
    assert "A cold review target" in captured["user_message"]
    assert captured["tools"] == ["Read", "Glob", "Grep"]
    assert session.project_path == str(tmp_path.resolve()) and session.allowed_write_paths == []
    traces = list((tmp_path / ".merak" / "traces" / "cross_model_review").glob("*/input.txt"))
    assert traces
    assert "A cold review target" in traces[0].read_text(encoding="utf-8")


def test_cross_model_review_accepts_current_prompt_field(tmp_path: Path, monkeypatch) -> None:
    session = SimpleNamespace(id="prompt-thread", max_iterations=50, project_path=".")
    captured: dict = {}
    monkeypatch.setattr(agent_tools.agent_engine, "create_session", lambda **_kwargs: session)

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return "review"

    monkeypatch.setattr(agent_tools.agent_engine, "run", fake_run)
    result = asyncio.run(
        agent_tools.cross_model_review(
            prompt="Review this artifact",
            project_path=str(tmp_path),
        )
    )

    assert result.startswith("[thread:prompt-thread]")
    assert captured["user_message"] == "Review this artifact"


def test_cross_model_review_rejects_empty_request() -> None:
    with pytest.raises(ValueError, match="requires one of"):
        asyncio.run(agent_tools.cross_model_review())
