"""Integration contracts with local personal libraries and isolated skill files."""

import json

import pytest

from server.services.knowledge_context import selected_personal_context
from server.services.knowledge_sources import KnowledgeSourceService
from server.services.meta_optimize import MetaOptimizeGate
from server.services.skill_registry import skill_registry


def test_unconfigured_search_is_configuration_error_not_scientific_repair(monkeypatch):
    from server.services.literature_capabilities import validate_literature_configuration
    from server.workflows.engine import WorkflowEngine
    from server.services.risk_search_evidence import _transient_failures

    monkeypatch.delenv("EXA_API_KEY", raising=False)
    options = {"research_strategy": {"literature_sources": ["openalex", "web"]}}
    with pytest.raises(ValueError, match="LITERATURE_CONFIGURATION_ERROR"):
        validate_literature_configuration(options)
    assert WorkflowEngine._search_tool_failure_kind(False, "Exa search failed: HTTP 401") == "configuration_error"
    stage = {"attempts": [{"calls": [{"source": "web", "success": False,
        "failure_kind": "configuration_error", "output_preview": "Exa search failed: HTTP 401"}]}]}
    assert _transient_failures(stage, ["web"]) == set()
    validate_literature_configuration({"research_strategy": {"literature_sources": ["openalex"]}})


def test_disabled_sync_and_optimization_are_not_available_to_workflow_agents():
    from server.workflows.engine import WorkflowEngine
    from server.agent.engine import AgentEngine
    from server.agent.session_models import AgentSession
    from server.agent import ToolCall

    assert {"overleaf_sync", "meta_optimize_propose"} <= WorkflowEngine._workflow_disabled_tools({})
    enabled = {"enable_overleaf_sync": True, "enable_meta_optimization": True}
    assert "meta_optimize_propose" not in WorkflowEngine._workflow_disabled_tools(enabled)
    assert "overleaf_sync" in WorkflowEngine._workflow_disabled_tools(enabled)
    call = ToolCall("id", "meta_optimize_propose", {"project_path": "another-project"})
    AgentEngine._inject_runtime_arguments(AgentSession(project_path="actual-project"), call)
    assert call.arguments["project_path"] == "actual-project"


def test_delegated_skill_cannot_reenable_disabled_workflow_integrations(tmp_path):
    from types import SimpleNamespace
    from server.agent.tools.skill_tool import _allowed_tools
    from server.agent.skill_resume import workflow_scope
    from server.workflows.run_state import RunState

    RunState(str(tmp_path), "delegate-scope").start([{"id": "lit"}], {"options": {}})
    token = workflow_scope.set(("delegate-scope", "lit"))
    try:
        loaded = SimpleNamespace(root=tmp_path)
        engine = SimpleNamespace(_tools={name: None for name in ("Read", "overleaf_sync", "meta_optimize_propose")})
        assert _allowed_tools(loaded, engine, list(engine._tools)) == ["Read"]
    finally:
        workflow_scope.reset(token)


def test_domain_planning_skills_do_not_advertise_unrelated_execution_tools():
    from pathlib import Path
    from server.services.skill_registry import parse_skill_md

    root = Path(__file__).resolve().parents[2] / "merak-skills"
    for name in ("domain-experiment-plan", "domain-idea-discovery", "domain-novelty-check"):
        metadata = parse_skill_md(root / name / "SKILL.md")
        assert metadata is not None
        assert {"Read", "Write", "WritePart", "AssembleDocument"} <= set(metadata.allowed_tools)
        assert not {"Bash", "overleaf_sync", "generate_figure", "meta_optimize_propose"} & set(metadata.allowed_tools)


def test_static_implementation_ready_does_not_authorize_missing_scientific_inputs(tmp_path):
    from server.services.scientific_execution_readiness import require_scientific_execution_ready
    from server.services.implementation_readiness_checks import readiness_findings

    payload = {"integration_readiness": "ready", "integration_blockers": [],
        "execution_readiness": "blocked", "execution_prerequisites": [{
            "id": "DATA", "owner": "data", "path": "data/manifest.csv",
            "description": "Audited observations are not provided"}]}
    path = tmp_path / "experiments/RUN_SPEC.json"
    path.parent.mkdir()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert readiness_findings(tmp_path, payload) == []
    with pytest.raises(ValueError, match="Audited observations"):
        require_scientific_execution_ready(tmp_path)
    payload.update(execution_readiness="ready", execution_prerequisites=[])
    path.write_text(json.dumps(payload), encoding="utf-8")
    require_scientific_execution_ready(tmp_path)


@pytest.mark.asyncio
async def test_arxiv_timeout_keeps_structured_retryable_error(monkeypatch):
    import httpx
    from server.agent import remote_errors
    from server.agent.tools import literature_tools
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = httpx.ReadTimeout("no response")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(remote_errors.asyncio, "sleep", AsyncMock())
    with pytest.raises(remote_errors.RemoteTransportError) as captured:
        await literature_tools.arxiv_search("EEG")
    assert captured.value.code == "REMOTE_TIMEOUT"
    assert captured.value.retryable is True
    assert captured.value.status is None
    assert client.get.await_count == 2


def test_disabled_personal_sources_are_not_injected_from_old_files(tmp_path):
    source = KnowledgeSourceService()
    source._write_artifact(tmp_path / "zotero_context.json", "zotero", "topic", [{"title": "private"}], [])
    assert selected_personal_context(tmp_path, {}, ["zotero"]) == ""
    assert selected_personal_context(tmp_path, {"enable_zotero": True}, []) == ""
    assert "private" in selected_personal_context(tmp_path, {"enable_zotero": True}, ["zotero"])


def test_unchanged_personal_context_preserves_accepted_hash(tmp_path):
    source = KnowledgeSourceService()
    path = tmp_path / "obsidian_context.json"
    source._write_artifact(path, "obsidian", "topic", [{"path": "note.md", "snippets": ["text"]}], [])
    original = path.read_bytes()
    source._write_artifact(path, "obsidian", "topic", [{"path": "note.md", "snippets": ["text"]}], [])
    assert path.read_bytes() == original
    source._write_artifact(path, "obsidian", "topic", [{"path": "note.md", "snippets": ["changed"]}], [])
    assert path.read_bytes() != original


@pytest.mark.parametrize("status", ["scaffold_only", "implementation_in_progress", "implemented"])
def test_design_example_preserves_runtime_status_for_authored_writer_payload(tmp_path, status):
    from server.services.scientific_scene import method_scene_authoring_example
    from server.contracts.writers import versioned_artifact_write_error

    target = tmp_path / "experiments/METHOD_CONTRACT.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"schema": 2, "status": status}), encoding="utf-8")
    example = {"schema": 2, "status": "implementation_in_progress", "implementation_checks": []}
    if status == "implemented":
        example["implementation_checks"] = [{"id": "I1", "description": "Existing implementation", "evidence": [{"path": "experiments/src/model.py"}]}]
    content, _ = method_scene_authoring_example(json.dumps(example), str(target))
    assert json.loads(content)["status"] == status
    authored = json.loads(content)
    for item, label in zip(authored["scientific_scene"]["objects"],
                           ["Sensor observations", "Temporal encoding", "Forecast error"]):
        item["label"] = label
    content = json.dumps(authored)
    assert versioned_artifact_write_error(tmp_path, target, content, model_authored=True) == ""


@pytest.fixture
def skill_gate(tmp_path, monkeypatch):
    path = tmp_path / "skills/lifecycle-test/SKILL.md"
    path.parent.mkdir(parents=True)
    original = "---\nname: lifecycle-test\ndescription: Original policy\nallowed-tools: Read\n---\n# Policy\nKeep safety and human approval.\n"
    path.write_text(original, encoding="utf-8")
    gate = MetaOptimizeGate(str(tmp_path / "project"))
    monkeypatch.setattr(gate, "_find_skill_file", lambda _: path if path.is_file() else None)
    monkeypatch.setattr(skill_registry, "_skills", dict(skill_registry._skills))
    monkeypatch.setattr(skill_registry, "_by_category", dict(skill_registry._by_category))
    monkeypatch.setattr(skill_registry, "_search_index", dict(skill_registry._search_index))
    return gate, path, original


def test_missing_canonical_skill_never_reports_applied(skill_gate):
    gate, path, original = skill_gate
    proposal = gate.propose_mutation("lifecycle-test", original, original + "\nCheck inputs.", "change")
    assert proposal["accepted"]
    path.unlink()
    assert gate.approve_mutation(proposal["mutation_id"])["success"] is False
    assert gate.list_mutations()[0]["status"] == "pending"


def test_approved_skill_refreshes_runtime_metadata_and_rolls_back(skill_gate):
    gate, path, original = skill_gate
    changed = original.replace("Original policy", "Updated policy").replace("allowed-tools: Read", "allowed-tools: Read, Grep")
    proposal = gate.propose_mutation("lifecycle-test", original, changed, "change")
    assert gate.approve_mutation(proposal["mutation_id"])["success"]
    assert "Grep" in skill_registry.get_skill("lifecycle-test").allowed_tools
    assert gate.reject_mutation(proposal["mutation_id"])["success"] is False
    assert gate.rollback_mutation(proposal["mutation_id"])["success"]
    assert path.read_text(encoding="utf-8") == original
    assert skill_registry.get_skill("lifecycle-test").allowed_tools == ["Read"]


def test_duplicate_skill_proposal_preserves_rejection(skill_gate):
    gate, _, original = skill_gate
    proposal = gate.propose_mutation("lifecycle-test", original, original + "\nCheck inputs.", "change")
    gate.reject_mutation(proposal["mutation_id"])
    repeated = gate.propose_mutation("lifecycle-test", original, original + "\nCheck inputs.", "change")
    assert not repeated["accepted"]
    assert gate.list_mutations()[0]["status"] == "rejected"


def test_skill_mutations_reload_before_merging_other_instance(skill_gate):
    gate, path, original = skill_gate
    other = MetaOptimizeGate(str(gate._base_path.parents[1]))
    other._find_skill_file = lambda _: path
    gate.propose_mutation("lifecycle-test", original, original + "\nCheck inputs.", "first")
    other.propose_mutation("lifecycle-test", original, original + "\nCheck outputs.", "second")
    records = json.loads(gate._state_file().read_text())["mutations"]
    assert len(records) == 2


def test_skill_application_rolls_back_if_state_persistence_fails(skill_gate, monkeypatch):
    gate, path, original = skill_gate
    proposal = gate.propose_mutation("lifecycle-test", original, original + "\nCheck inputs.", "change")
    def fail_save():
        raise OSError("disk write failed")
    monkeypatch.setattr(gate, "_save_state", fail_save)
    with pytest.raises(OSError, match="disk write failed"):
        gate.approve_mutation(proposal["mutation_id"])
    assert path.read_text(encoding="utf-8") == original
    assert gate.list_mutations()[0]["status"] == "pending"
