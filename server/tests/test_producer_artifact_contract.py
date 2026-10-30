"""Pure producer-path checks; no workflow, provider or experiment execution."""

import json
from pathlib import Path

import pytest

from server.agent import ToolCall
from server.agent.session_models import AgentSession
from server.agent.tool_policy import ToolPolicyMixin
from server.services.artifact_contract import (
    artifact_write_error,
    declared_skill_outputs,
    declared_skill_artifact_contracts,
    validate_skill_artifact_contract_content,
    render_artifact_contract,
)
from server.services.project_scaffold import (
    WORKFLOW_ARTIFACT_CONTRACT,
    get_workflow_artifact_contract,
)
from server.services.skill_registry import parse_skill_md
from server.workflows.engine import WorkflowEngine


@pytest.mark.parametrize("relative", [
    "idea-stage/IDEA_REPORT.md", "refine-logs/EXPERIMENT_PLAN.md",
    "results/analysis.md", "ideas/IDEA_CANDIDATES.md", "EXPERIMENT_RESULTS.md",
    "main.tex", "main.pdf", "NOVELTY_REPORT.md", "PAPER_PLAN.md",
    "paper/NARRATIVE_REPORT.md", "misc/NARRATIVE_REPORT.md",
    "experiments/refinement/EXPERIMENT_PLAN.md",
])
def test_incompatible_write_is_rejected_before_mutation(tmp_path: Path, relative: str) -> None:
    session = AgentSession(project_path=str(tmp_path), tool_policy="workflow_artifacts")
    call = ToolCall(id="write-test", name="Write", arguments={"path": relative, "content": "data"})
    rejected = ToolPolicyMixin()._normalize_artifact_argument(session, call, "path")
    assert rejected is not None and rejected.success is False
    assert "ARTIFACT_CONTRACT_ERROR" in rejected.output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("relative", [
    "ideas/ideas.md", "ideas/COMPACT_IDEA_CANDIDATES.md", "ideas/FINAL_PROPOSAL.md",
    "ideas/novelty_report.md", "ideas/SELECTED_IDEA.json",
    "experiments/EXPERIMENT_PLAN.md", "experiments/EXPERIMENT_TRACKER.md",
    "experiments/refinement/round_1.md", "experiments/results/analysis.md",
    "NARRATIVE_REPORT.md", "paper/PAPER_PLAN.md", "paper/main.tex",
    "paper/revisions/round1/main.tex", "slides/main.tex", "paper/references.bib",
])
def test_current_outputs_are_allowed_without_creating_files(tmp_path: Path, relative: str) -> None:
    assert artifact_write_error(tmp_path, tmp_path / relative) == ""
    session = AgentSession(project_path=str(tmp_path), tool_policy="workflow_artifacts")
    call = ToolCall(id="write-test", name="Write", arguments={"path": relative, "content": "data"})
    assert ToolPolicyMixin()._normalize_artifact_argument(session, call, "path") is None
    assert call.arguments["path"] == str((tmp_path / relative).resolve())
    assert list(tmp_path.iterdir()) == []


def test_declared_research_input_remains_readable_and_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "idea-stage/IDEA_REPORT.md"
    source.parent.mkdir()
    source.write_text("user input", encoding="utf-8")
    session = AgentSession(project_path=str(tmp_path), tool_policy="workflow_artifacts")
    call = ToolCall(id="read-test", name="Read", arguments={"path": str(source)})
    assert ToolPolicyMixin()._normalize_artifact_argument(session, call, "path") is None
    assert source.read_text(encoding="utf-8") == "user input"
    assert not (tmp_path / "ideas/ideas.md").exists()


def test_all_gate_contracts_are_current_only(tmp_path: Path) -> None:
    assert not hasattr(WorkflowEngine, "_canonicalize_node_artifacts")
    for node_id, raw in WORKFLOW_ARTIFACT_CONTRACT.items():
        assert "aliases" not in raw
        resolved = get_workflow_artifact_contract(tmp_path, node_id)
        assert set(resolved) == {"primary", "required"}
        prompt = render_artifact_contract(tmp_path, node_id)
        assert all(path in prompt for path in resolved["required"])


def test_skill_output_metadata_is_explicit_not_prose_inference(tmp_path: Path) -> None:
    source = tmp_path / "test-skill/SKILL.md"
    source.parent.mkdir()
    source.write_text(
        '---\nname: test-skill\nartifact-outputs: ["ideas/ideas.md"]\n---\n'
        'Write "not-a-path" in the output prose.\n', encoding="utf-8",
    )
    metadata = parse_skill_md(source)
    assert metadata is not None and metadata.output_files == ["ideas/ideas.md"]
    assert declared_skill_outputs("name: test-skill") == []


@pytest.mark.parametrize("values", [
    "not-json", '{}', '[1]', '["../outside.md"]', '["C:/outside.md"]',
    '["idea-stage/IDEA_REPORT.md"]', '["PAPER_PLAN.md"]',
])
def test_invalid_output_declaration_is_rejected(values: str) -> None:
    with pytest.raises(ValueError):
        declared_skill_outputs("artifact-outputs: " + values)


def test_versioned_skill_contract_must_match_runtime_schema() -> None:
    frontmatter = (
        'artifact-outputs: ["ideas/SELECTED_IDEA.json"]\n'
        'artifact-contracts: {"ideas/SELECTED_IDEA.json": 2}'
    )
    assert declared_skill_artifact_contracts(frontmatter) == {
        "ideas/SELECTED_IDEA.json": 2,
    }
    validate_skill_artifact_contract_content(
        "---\n" + frontmatter + "\n---\n\nWrite the current contract."
    )


def test_versioned_skill_contract_rejects_schema_drift() -> None:
    with pytest.raises(ValueError, match="schema mismatch"):
        validate_skill_artifact_contract_content(
            '---\nartifact-outputs: ["ideas/SELECTED_IDEA.json"]\n'
            'artifact-contracts: {"ideas/SELECTED_IDEA.json": 1}\n---\n'
        )


def test_fixed_skill_outputs_match_acceptance_contracts() -> None:
    repository = Path(__file__).resolve().parents[2]
    owners = {
        "domain-idea-discovery": "idea", "domain-novelty-check": "novelty",
        "research-lit": "lit", "paper-compile": "compile", "paper-talk": "ppt",
    }
    for skill, node in owners.items():
        source = repository / "merak-skills" / skill / "SKILL.md"
        metadata = parse_skill_md(source)
        assert metadata is not None
        assert set(WORKFLOW_ARTIFACT_CONTRACT[node]["required"]) <= set(metadata.output_files)
    assert json.dumps(WORKFLOW_ARTIFACT_CONTRACT).find('"aliases"') == -1
