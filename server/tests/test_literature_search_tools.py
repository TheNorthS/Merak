from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from server.agent.engine import agent_engine
from server.agent.tools import invoke_skill, openalex_search, pubmed_search
from server.services.skill_registry import skill_registry


class _Response:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _Client:
    responses: list[_Response] = []

    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url: str, params: dict | None = None):
        self.calls.append((url, dict(params or {})))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_openalex_search_parses_structured_metadata(monkeypatch) -> None:
    _Client.responses = [_Response({
        "results": [{
            "display_name": "A Reliable Study",
            "publication_year": 2025,
            "cited_by_count": 17,
            "doi": "https://doi.org/10.1000/example",
            "primary_location": {"source": {"display_name": "Journal of Tests"}},
            "authorships": [
                {"author": {"display_name": "Ada Researcher"}},
                {"author": {"display_name": "Bo Scientist"}},
            ],
        }],
    })]
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    output = await openalex_search("reliable study", max_results=100)

    assert "A Reliable Study" in output
    assert "Journal of Tests" in output
    assert "cited_by=17" in output
    assert "Ada Researcher" in output
    assert "10.1000/example" in output


@pytest.mark.asyncio
async def test_pubmed_search_parses_search_and_summary_responses(monkeypatch) -> None:
    _Client.responses = [
        _Response({"esearchresult": {"idlist": ["12345"]}}),
        _Response({"result": {
            "12345": {
                "title": "Clinical Validation Study",
                "fulljournalname": "Clinical Methods",
                "pubdate": "2024 Dec",
                "authors": [{"name": "Lin A"}, {"name": "Singh B"}],
                "articleids": [{"idtype": "doi", "value": "10.1000/clinical"}],
            },
        }}),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    output = await pubmed_search("clinical validation", max_results=5)

    assert "PMID:12345" in output
    assert "Clinical Validation Study" in output
    assert "Clinical Methods" in output
    assert "Lin A" in output
    assert "10.1000/clinical" in output


@pytest.mark.asyncio
async def test_invoke_skill_accepts_sync_event_callback_and_writes_trace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path(__file__).parents[2]
    skill_registry.scan_directory(root / "merak-skills")
    session = SimpleNamespace(id="skill-session", max_iterations=40)
    monkeypatch.setattr(agent_engine, "create_session", lambda **_kwargs: session)
    observed: list[str] = []

    async def fake_run(*, on_event=None, **_kwargs):
        if on_event:
            await on_event(SimpleNamespace(
                type="status",
                data={"provider": "test-provider", "model": "test-model"},
            ))
        return "completed artifact work"

    monkeypatch.setattr(agent_engine, "run", fake_run)

    def on_event(event) -> None:
        observed.append(event.type)

    result = await invoke_skill(
        "domain-methodology",
        "Write the requested contract.",
        project_path=str(tmp_path),
        on_event=on_event,
        allowed_tools_override=[],
        max_iterations=4,
    )

    traces = list((tmp_path / ".merak" / "skill-invocations").glob(
        "*_domain-methodology.json"
    ))
    assert result == "completed artifact work"
    assert observed == ["status"]
    assert len(traces) == 1
    payload = json.loads(traces[0].read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["policy_loaded"] is True
    assert payload["session_id"] == "skill-session"
    assert payload["skill_bytes"] > 500
    assert payload["model_provider"] == "test-provider"
    assert payload["model_name"] == "test-model"
