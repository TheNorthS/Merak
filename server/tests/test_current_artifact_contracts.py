"""Pure regression checks for current-only artifact contracts; no workflow runs."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from server.services.paper_artifacts import (
    TABLE_MANIFEST_SCHEMA,
    bind_table_manifest_hashes,
    build_table_manifest,
)
from server.services.paper_plan import PaperPlanService
from server.services.paper_scientific_freeze import (
    freeze_scientific_inputs,
    rebind_layout_only_derived_inputs,
    validate_scientific_freeze,
)
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.workflows import engine, engine_context, workflow_policy


def test_plan_has_only_one_registered_location(tmp_path: Path) -> None:
    plan = PaperPlanService()
    unregistered = tmp_path / "PAPER_PLAN.md"
    unregistered.write_text("A user-owned root-level document.", encoding="utf-8")

    assert plan.path(tmp_path) == tmp_path / "paper/PAPER_PLAN.md"
    assert plan.is_current(tmp_path) is False
    assert not plan.path(tmp_path).exists()
    assert unregistered.read_text(encoding="utf-8") == "A user-owned root-level document."


def test_table_owner_binds_current_schema_and_validator_does_not_repair(
    tmp_path: Path,
) -> None:
    data = tmp_path / "result.csv"
    latex = tmp_path / "result.tex"
    data.write_text("method,value\nA,1\n", encoding="utf-8")
    latex.write_text("A & 1", encoding="utf-8")
    records = [{"id": "result", "data_path": "result.csv", "latex_path": "result.tex"}]
    payload = build_table_manifest(tmp_path, records)
    assert payload["schema"] == TABLE_MANIFEST_SCHEMA
    assert "data_sha256" not in records[0]
    expected_hash = hashlib.sha256(data.read_bytes()).hexdigest()
    assert payload["tables"][0]["data_sha256"] == expected_hash

    data.write_text("method,value\nA,2\n", encoding="utf-8")
    checked, issues, changed = bind_table_manifest_hashes(tmp_path, payload)
    assert any("data_sha256 does not match" in issue for issue in issues)
    assert checked["tables"][0]["data_sha256"] == expected_hash
    assert changed is False


def test_unregistered_table_schema_is_not_promoted(tmp_path: Path) -> None:
    payload = {"schema": TABLE_MANIFEST_SCHEMA - 1, "tables": []}
    checked, issues, changed = bind_table_manifest_hashes(tmp_path, payload)
    assert "table manifest schema is unsupported" in issues
    assert checked["schema"] == payload["schema"]
    assert changed is False


def test_table_owner_rejects_paths_outside_project(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes project"):
        build_table_manifest(tmp_path, [{
            "id": "unsafe", "data_path": "../outside.csv", "latex_path": "result.tex",
        }])


def test_unsupported_freeze_cannot_be_rebound_or_written(tmp_path: Path) -> None:
    path = tmp_path / "paper/SCIENTIFIC_FREEZE.json"
    path.parent.mkdir()
    original = json.dumps({"schema_version": 1, "inputs": {}, "generation": 1})
    path.write_text(original, encoding="utf-8")

    assert validate_scientific_freeze(tmp_path)["passed"] is False
    with pytest.raises(ValueError, match="Unsupported scientific freeze"):
        freeze_scientific_inputs(tmp_path)
    result = rebind_layout_only_derived_inputs(
        tmp_path, target_files=["paper/tables/result.tex"], before_manifest={},
    )
    assert result["passed"] is False
    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "paper/tables/TABLE_MANIFEST.json").exists()


@pytest.mark.parametrize("schema", [0, SIMULATION_MANIFEST_SCHEMA - 1, SIMULATION_MANIFEST_SCHEMA + 1])
def test_resume_does_not_convert_unsupported_simulation_schema(
    tmp_path: Path, schema: int,
) -> None:
    path = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    path.parent.mkdir(parents=True)
    original = json.dumps({"schema": schema, "renderer_version": 1})
    path.write_text(original, encoding="utf-8")
    run = WorkflowRun(project_path=str(tmp_path), options={
        "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
    })
    with pytest.raises(ValueError, match="Unsupported simulation schema"):
        asyncio.run(WorkflowEngine()._refresh_simulation_renderer_before_revalidation(run, ""))
    assert path.read_text(encoding="utf-8") == original


def test_resume_without_simulation_authorization_never_touches_manifest(tmp_path: Path) -> None:
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": True})
    assert asyncio.run(
        WorkflowEngine()._refresh_simulation_renderer_before_revalidation(run, "")
    ) is False
    assert list(tmp_path.iterdir()) == []


def test_workflow_policies_have_one_definition() -> None:
    assert engine.NODE_RUNTIME_CONTRACT_VERSIONS is workflow_policy.NODE_RUNTIME_CONTRACT_VERSIONS
    assert engine_context.NODE_RUNTIME_CONTRACT_VERSIONS is workflow_policy.NODE_RUNTIME_CONTRACT_VERSIONS
    assert engine.normalize_revision_rounds is workflow_policy.normalize_revision_rounds
    assert engine_context.normalize_revision_rounds is workflow_policy.normalize_revision_rounds


@pytest.mark.parametrize("mode", ["codex-image2", "gpt-image", "gemini", "figurespec", "false"])
def test_workflow_policy_does_not_migrate_removed_user_modes(mode: str) -> None:
    with pytest.raises(ValueError, match="unsupported illustration_mode"):
        workflow_policy.normalize_workflow_illustration_mode(mode)
