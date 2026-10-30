"""Consumers must preserve model plans and never generate replacements on resume."""

import json

import pytest

from server.services.paper_plan import paper_plan_service
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun


def test_narrative_input_building_preserves_authored_plan(tmp_path, monkeypatch):
    path = tmp_path / "paper/PAPER_PLAN.md"
    path.parent.mkdir()
    original = "# Model-authored plan\nSpecific reviewer-approved reasoning.\n"
    path.write_text(original)
    monkeypatch.setattr(paper_plan_service, "ensure", lambda *args, **kwargs: pytest.fail("Input construction must not author a paper plan"))
    WorkflowEngine()._input_narrative("fixture", {}, WorkflowRun(project_path=str(tmp_path)))
    assert path.read_text() == original


@pytest.mark.asyncio
async def test_figure_preparation_refuses_missing_plan_before_producing_assets(tmp_path, monkeypatch):
    from server.contracts.preparation import PreparationContractError

    monkeypatch.setattr(paper_plan_service, "ensure", lambda *args, **kwargs: pytest.fail("No replacement plan"))
    with pytest.raises(PreparationContractError, match="paper plan"):
        await WorkflowEngine()._ensure_figure_artifacts(WorkflowRun(project_path=str(tmp_path)), "", "fixture")
    assert not (tmp_path / "paper/PAPER_PLAN.md").exists()
    assert not (tmp_path / "figures").exists()


def test_later_figure_artifacts_do_not_retroactively_invalidate_paper_plan(tmp_path, monkeypatch):
    import server.services.paper_plan_evidence as evidence

    monkeypatch.setattr(evidence, "verified_simulation_plan_evidence", lambda *args: False)
    path = tmp_path / "paper/PAPER_PLAN.md"
    path.parent.mkdir()
    path.write_text("# Paper plan\nOne-sentence contribution\nClaims-evidence\nSection plan\nFigure plan\nEvidence gap\n" + "Scientific detail. " * 100)
    paper_plan_service.record_existing(tmp_path)
    assert paper_plan_service.is_current(tmp_path)
    (tmp_path / "figures").mkdir()
    for name in ("SCIENTIFIC_ASSET_PLAN.json", "FIGURE_MANIFEST.json"):
        (tmp_path / "figures" / name).write_text(json.dumps({"later": name}))
    assert paper_plan_service.is_current(tmp_path)


def test_render_only_manifest_changes_keep_plan_identity_but_scientific_changes_do_not(tmp_path):
    path = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    path.parent.mkdir(parents=True)
    payload = {"schema": 11, "primary_metric": "auroc", "metric_direction": "maximize",
               "data_files": [{"path": "results.csv", "sha256": "a" * 64}],
               "figure_files": [{"source_sha256": "old", "output_sha256": {"png": "old"}}]}
    path.write_text(json.dumps(payload))
    before = paper_plan_service._source_hash(tmp_path, [path])
    payload["figure_files"][0]["output_sha256"]["png"] = "new-render"
    path.write_text(json.dumps(payload))
    assert paper_plan_service._source_hash(tmp_path, [path]) == before
    for key, replacement in (("primary_metric", "balanced_accuracy"), ("metric_direction", "minimize"),
                             ("data_files", [{"path": "results.csv", "sha256": "b" * 64}])):
        changed = {**payload, key: replacement}
        path.write_text(json.dumps(changed))
        assert paper_plan_service._source_hash(tmp_path, [path]) != before
