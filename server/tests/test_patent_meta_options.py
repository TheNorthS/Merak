import json

import pytest

from server.api.settings import ModelConfig, integration_is_configured
from server.services.meta_optimize import MetaOptimizeGate
from server.services.patent_tools import PatentTools
from server.services.skill_orchestrator import SkillOrchestrator


def test_patent_configuration_accepts_serpapi_or_complete_epo_pair():
    assert integration_is_configured(ModelConfig(), "patent") is False
    assert integration_is_configured(ModelConfig(serpapi_api_key="serp"), "patent") is True
    assert integration_is_configured(ModelConfig(epo_ops_key="key"), "patent") is False
    assert integration_is_configured(
        ModelConfig(epo_ops_key="key", epo_ops_secret="secret"), "patent"
    ) is True


@pytest.mark.asyncio
async def test_patent_search_without_provider_fails_instead_of_claiming_zero_results(monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="No patent search API configured"):
        await PatentTools().search_patents("test invention")


def test_skill_orchestrator_selects_patent_and_meta_policies_when_enabled(tmp_path):
    orchestrator = SkillOrchestrator()
    patent = orchestrator.select(
        "novelty", "/novelty-check", str(tmp_path), {"enable_patent_search": True}
    )
    meta = orchestrator.select(
        "audit", "/experiment-audit", str(tmp_path), {"enable_meta_optimization": True}
    )

    assert "patent-novelty-check" in patent.specialists
    assert "prior-art-search" in patent.specialists
    assert "meta-optimize" in meta.specialists


def test_meta_optimization_requires_repetition_and_rejects_stale_approval(tmp_path, monkeypatch):
    skill_path = tmp_path / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    original = "# Demo\n\nKeep human approval and safety checks.\n"
    skill_path.write_text(original, encoding="utf-8")
    gate = MetaOptimizeGate(str(tmp_path / "project"))
    monkeypatch.setattr(gate, "_find_skill_file", lambda _: skill_path)

    first = gate.observe_workflow_failure("demo", "tool schema failure", "run-one")
    second = gate.observe_workflow_failure("demo", "tool schema failure", "run-two")

    assert first["proposed"] is False
    assert first["observations"] == 1
    assert second["proposed"] is True
    state = json.loads((tmp_path / "project" / ".merak" / "meta_optimize" / "mutations.json").read_text(encoding="utf-8"))
    assert state["mutations"][0]["status"] == "pending"

    skill_path.write_text(original + "External update.\n", encoding="utf-8")
    decision = gate.approve_mutation(second["mutation_id"])
    assert decision["success"] is False
    assert "stale" in decision["error"].lower()
    assert "External update" in skill_path.read_text(encoding="utf-8")
