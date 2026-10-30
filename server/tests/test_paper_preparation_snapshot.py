"""Actual paper preparation reaches the bounded model edge without execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_paper_preparation_snapshot import FirstAuthoringBoundary, verify
from server.tests._staged_paper_drafting_support import seed_project
from server.workflows.run_state import RunState


def _fixture(root: Path, *, long_labels: bool = False) -> None:
    seed_project(root)
    root.joinpath("paper/tables/TABLE_MANIFEST.json").write_text(
        json.dumps({"schema": 3, "tables": []}), encoding="utf8",
    )
    selected_path = root / "ideas/SELECTED_IDEA.json"
    selected = json.loads(selected_path.read_text())
    mechanisms = []
    for index, name in enumerate(("Topology-conditioned encoding", "Restricted prediction readout"), 1):
        description = (
            "The scientifically declared task-facing representation excludes source-specific state from the prediction head. "
            "Matched held-out comparisons retain independent units and uncertainty rather than treating the observation count as replication."
            if long_labels else "Preserve the declared topology transformation."
        )
        evaluation = (
            "Compare full and restricted paths under the same independent units, random seed sets, optimization opportunities and held-out sources, "
            "retaining uncertainty for every registered comparison without converting a conditional improvement into a universal claim."
            if long_labels else "Matched held-out comparison."
        )
        mechanisms.append({"id": f"M{index}", "required": True, "name": name,
                           "description": description, "publication_name": name,
                           "publication_description": description, "publication_evaluation": evaluation})
    selected.update({"schema": 2, "mechanisms": mechanisms,
                     "publication": {"language": "en", "title": selected["title"],
                                     "method_name": "Topology-aware planner",
                                     "contribution_type": "system_architecture",
                                     "comparator_names": ["Matched reference"]}})
    selected_path.write_text(json.dumps(selected), encoding="utf8")
    source = root / "experiments/src/train.py"
    source.parent.mkdir()
    source.write_text("def declared_algorithm():\n    return 'fixture-static-only'\n")
    root.joinpath("experiments/results/registered.csv").write_text("condition,value\nFixed fixture,0.5\n")
    state = RunState(str(root), "fixture-paper-preparation")
    state.start([{"id": "paper", "name": "Paper", "skill": "/paper-write"}], {
        "direction": "Source-bound topology study", "assurance": "draft", "effort": "balanced",
        "options": {"run_experiment": False, "non_experiment_evidence_mode": "design_only",
                    "target_venue": "ICLR", "target_pages": 11},
    })


@pytest.mark.parametrize("long_labels", [False, True])
@pytest.mark.asyncio
async def test_actual_preparation_reaches_first_model_boundary_without_running_it(tmp_path, long_labels):
    _fixture(tmp_path, long_labels=long_labels)
    result = await verify(tmp_path, "fixture-paper-preparation")
    assert result["ready_for_authoring"], result["issues"]
    assert result["paper_accepted"] is False
    assert result["first_model_boundary_reached"] is True
    assert result["invocation_contract_present"] is True
    assert result["scientific_freeze_passed"] is True
    assert result["tables"]["accepted"] is True
    assert result["source_contracts_and_numeric_data_unchanged"] is True
    assert result["model_invoked"] is False
    assert result["manuscript_compiled"] is False
    assert result["live_workflow_resumed"] is False
    assert result["copied_source_run_and_trace_unchanged"] is True
    assert result["figure_assets_unchanged"] is True
    assert result["source_run_id"] != result["verification_run_id"]
    if long_labels:
        assert result["tables"]["source_bound_full_text_notes"] >= 4


def test_first_model_boundary_is_not_swallowed_by_provider_retry() -> None:
    assert not issubclass(FirstAuthoringBoundary, Exception)
    assert issubclass(FirstAuthoringBoundary, BaseException)
