from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from server.services.research_workflow_contract import (
    NODE_CONTRACTS,
    research_workflow_contract_service,
)
from server.services.scientific_assets import scientific_asset_service
from server.workflows.engine import WorkflowEngine, WorkflowRun
from server.tests._planned_publication_fixture import author_publication_fixture


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_contract(root: Path, *, title: str = "Accepted research idea") -> None:
    selected = {
        "status": "accepted",
        "title": title,
        "hypothesis": "The declared mechanism changes a prespecified outcome under a matched test.",
        "claims": [
            {
                "id": "C1",
                "statement": "A long, precise claim that must remain intact across experiment, figure, review, and paper stages.",
            }
        ],
        "mechanisms": [
            {
                "id": "M1",
                "name": "Contract-bound mechanism",
                "description": "The implementation must expose the exact mechanism and its observable consequence.",
                "required": True,
            }
        ],
        "falsification_conditions": [
            "Reject C1 if the matched control achieves the same outcome under the same budget."
        ],
    }
    _write_json(root / "ideas" / "SELECTED_IDEA.json", selected)
    author_publication_fixture(root, method_name=title,
                               comparators=["Matched research control", title])
    (root / "ideas" / "novelty_report.md").write_text(
        "# Novelty\nAccepted research idea.",
        encoding="utf-8",
    )
    (root / "ideas" / "ideas.md").write_text("# Ideas\nAccepted research idea.", encoding="utf-8")
    _write_json(
        root / "experiments" / "METHOD_CONTRACT.json",
        {
            "schema": 2,
            "implementation_checks": [],
            "selected_idea": title,
            "scientific_scene": {"schema": 1, "objects": [
                {"id": "observed_material", "kind": "input", "label": "Registered research observations", "source_path": "experiments/EXPERIMENT_PLAN.md"},
                {"id": "declared_operation", "kind": "operation", "label": "Contract-bound mechanism", "source_path": "ideas/SELECTED_IDEA.json"},
                {"id": "measured_outcome", "kind": "output", "label": "Prespecified outcome", "source_path": "experiments/EXPERIMENT_PLAN.md"},
            ], "relations": [{"from": "observed_material", "to": "declared_operation", "kind": "data"},
                              {"from": "declared_operation", "to": "measured_outcome", "kind": "data"}]},
            "claim_evidence_plan": [
                {
                    "idea_claim_id": "C1",
                    "outcomes": ["Matched primary endpoint"],
                    "failure_conditions": ["Matched control is equivalent"],
                }
            ],
        },
    )
    _write_json(root / "experiments" / "RUN_SPEC.json", {"seeds": [1, 2, 3]})
    (root / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\nMatched comparison and falsification.",
        encoding="utf-8",
    )


def test_contract_covers_every_workflow_node_and_reports_cross_node_drift(
    tmp_path: Path,
) -> None:
    _seed_contract(tmp_path)
    method = json.loads(
        (tmp_path / "experiments" / "METHOD_CONTRACT.json").read_text(encoding="utf-8")
    )
    method["selected_idea"] = "Different easier idea"
    _write_json(tmp_path / "experiments" / "METHOD_CONTRACT.json", method)
    _write_json(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        {"selected_idea": "Accepted research"},
    )

    payload = research_workflow_contract_service.prepare(
        tmp_path,
        "test direction",
        {"run_experiment": False, "gpu_target": "local"},
    )

    expected = {
        "lit", "idea", "novelty", "exp-design", "exp-run", "results",
        "figure", "narrative", "paper", "review", "audit", "compile", "ppt",
    }
    assert set(NODE_CONTRACTS) == expected
    assert set(payload["nodes"]) == expected
    assert any("METHOD_CONTRACT" in issue for issue in payload["cross_node_issues"])
    assert any("SCIENTIFIC_ASSET_PLAN" in issue for issue in payload["cross_node_issues"])
    assert any("GPU target" in issue for issue in payload["cross_node_issues"])
    persisted = json.loads(
        (tmp_path / ".merak" / "RESEARCH_WORKFLOW_CONTRACT.json").read_text(encoding="utf-8")
    )
    assert persisted["nodes"]["figure"]["risks"]
    assert persisted["nodes"]["audit"]["checks"]


def test_node_prompt_keeps_full_claim_mechanism_and_stage_risks(tmp_path: Path) -> None:
    _seed_contract(tmp_path)

    prompt = research_workflow_contract_service.prompt(
        tmp_path,
        "figure",
        "test direction",
        {"run_experiment": False},
    )

    assert "Accepted research idea" in prompt
    assert "A long, precise claim that must remain intact" in prompt
    assert "Contract-bound mechanism" in prompt
    assert "generic workflow art" in prompt
    assert "Evidence mode: design_only" in prompt


def test_node_prompt_preserves_non_experiment_evidence_modes(tmp_path: Path) -> None:
    _seed_contract(tmp_path)

    for mode in (
        "synthetic_preview",
        "existing_results",
        "secondary_analysis",
        "design_only",
    ):
        prompt = research_workflow_contract_service.prompt(
            tmp_path,
            "results",
            "test direction",
            {
                "run_experiment": False,
                "non_experiment_evidence_mode": mode,
            },
        )
        assert f"Evidence mode: {mode}" in prompt


def test_scientific_asset_plan_does_not_truncate_frozen_contract(tmp_path: Path) -> None:
    title = "T" * 180
    _seed_contract(tmp_path, title=title)
    selected_path = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    selected["claims"][0]["statement"] = "C" * 420
    selected["claims"][0]["publication_statement"] = "C" * 420
    selected["mechanisms"][0]["description"] = "M" * 620
    selected["mechanisms"][0]["publication_description"] = "M" * 620
    selected_path.write_text(json.dumps(selected), encoding="utf-8")

    plan = scientific_asset_service.build_plan(tmp_path, experiment_requested=False)

    assert plan["selected_idea"] == title
    assert plan["claims"][0]["statement"] == "C" * 420
    assert plan["mechanisms"][0]["description"] == "M" * 620


def test_default_graph_requires_novelty_before_design_and_audit_before_compile() -> None:
    nodes = {node.id: node for node in WorkflowEngine()._get_default_nodes()}

    assert nodes["exp-design"].depends_on == ["novelty"]
    assert nodes["figure"].depends_on == ["narrative"]
    assert nodes["paper"].depends_on == ["figure"]
    assert nodes["paper"].skill == "/paper-write"
    assert nodes["compile"].depends_on == ["audit"]


def test_synthetic_preview_placeholder_disclosure_is_not_unfinished_draft() -> None:
    engine = WorkflowEngine()

    assert engine._paper_has_unfinished_draft_language(
        "This figure is placeholder content and is NOT FOR SUBMISSION.",
        "synthetic_preview",
    ) is False
    assert engine._paper_has_unfinished_draft_language(
        "TODO: insert figure",
        "synthetic_preview",
    ) is True
    assert engine._paper_has_unfinished_draft_language(
        "This section contains placeholder content.",
        "design_only",
    ) is True


def test_paper_mechanism_check_accepts_substantive_paraphrase() -> None:
    engine = WorkflowEngine()

    assert engine._paper_covers_mechanism(
        "Leave-montage/device falsification and leakage probes",
        (
            "We use leave-montage and leave-device evaluation with leakage "
            "probes as a falsification test."
        ),
    ) is True
    assert engine._paper_covers_mechanism(
        "Conditional masked prediction",
        "We train a generic convolutional classifier.",
    ) is False
    assert engine._paper_covers_mechanism(
        "跨域表征解耦机制",
        (
            "The method learns acquisition-invariant representations and uses "
            "a nuisance-factor intervention under dataset-held-out evaluation."
        ),
        [
            "acquisition-invariant representation",
            "nuisance-factor intervention",
            "dataset-held-out evaluation",
        ],
    ) is True


def test_exp_design_fallback_never_overwrites_existing_project_code(tmp_path: Path) -> None:
    _seed_contract(tmp_path)
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    source.parent.mkdir(parents=True, exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("PROJECT_SPECIFIC_TRAINING = True\n", encoding="utf-8")
    config.write_text("model:\n  name: project_specific\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(source, (old, old))
    os.utime(config, (old, old))
    run = WorkflowRun(
        id="preserve-code",
        project_path=str(tmp_path),
        created_at=time.time(),
        options={"run_experiment": False, "research_quality_mode": "rigorous"},
    )

    asyncio.run(
        WorkflowEngine()._ensure_exp_design_artifacts(
            run,
            "Existing implementation should be preserved.",
            "test direction",
        )
    )

    assert source.read_text(encoding="utf-8") == "PROJECT_SPECIFIC_TRAINING = True\n"
    assert config.read_text(encoding="utf-8") == "model:\n  name: project_specific\n"
