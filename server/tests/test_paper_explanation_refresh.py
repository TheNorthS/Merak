"""Interpretation changes preserve candidate prose but invalidate all prior acceptance."""

import json
from types import SimpleNamespace

import pytest

from server.services.paper_explanation_refresh import can_reconcile_explanation_update
from server.services.paper_drafting import PaperDraftingService
from server.tests._staged_paper_drafting_support import seed_project


def _ready(root):
    seed_project(root)
    service = PaperDraftingService()
    service.prepare(root, {})
    paths = service.paths(root)
    state = json.loads(paths["state"].read_text())
    for stage, record in state["stages"].items():
        record.update(status="completed", attempts=3, review_passed=True)
        for target in service.stage_outputs(paths, stage):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"Existing authored candidate for {stage}.")
    paths["state"].write_text(json.dumps(state))
    target = paths["sections"] / "05_results.tex"
    target.write_text("Authored bounded results remain available for independent review.")
    paths["cross_review"].write_text("# Checks Performed\nChecked.\n# Final Consistency Verdict\nPASS\n")
    return service, paths, state, target


def test_analysis_only_update_keeps_authors_but_archives_old_verdict(tmp_path):
    service, paths, before, target = _ready(tmp_path)
    content = target.read_bytes()
    source = tmp_path / "experiments/results/analysis.md"
    source.write_text(source.read_text() + "\nCorrected complete-row range explanation.\n")
    service.prepare(tmp_path, {})
    state = json.loads(paths["state"].read_text())
    assert target.read_bytes() == content
    assert state["explanation_refresh_requires_model_review"] is True
    assert all(record["status"] == "pending" and not record["review_passed"] for record in state["stages"].values())
    assert not paths["cross_review"].exists()
    assert list((paths["paper"] / "revisions").rglob("CROSS_SECTION_REVIEW.md"))


def test_interrupted_directed_repair_keeps_complete_candidates_but_not_absent_sections(tmp_path):
    service, paths, previous, target = _ready(tmp_path)
    previous["stages"]["results"].update(status="running", review_passed=False)
    inputs = {**previous["authoring_inputs"], "experiments/results/analysis.md": "corrected-explanation"}
    assert can_reconcile_explanation_update(paths, previous, inputs, previous["authoring_options"], 3)
    target.unlink()
    assert not can_reconcile_explanation_update(paths, previous, inputs, previous["authoring_options"], 3)


@pytest.mark.parametrize("changed", ["ideas/SELECTED_IDEA.json", "experiments/RUN_SPEC.json", "experiments/METHOD_CONTRACT.json"])
def test_changed_science_cannot_use_explanation_only_reconciliation(tmp_path, changed):
    _service, paths, previous, _target = _ready(tmp_path)
    inputs = dict(previous["authoring_inputs"])
    inputs[changed] = "different"
    assert not can_reconcile_explanation_update(paths, previous, inputs, previous["authoring_options"], 3)


@pytest.mark.asyncio
async def test_fresh_model_requirement_cannot_be_satisfied_by_local_cache(tmp_path):
    from server.services.paper_draft_coordinator import DraftCoordinator

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"explanation_refresh_requires_model_review": True}))
    coordinator = SimpleNamespace(paths={"state": path})
    assert await DraftCoordinator._revalidate_without_invocation(coordinator, SimpleNamespace(stage_id="consistency")) is False


@pytest.mark.parametrize('changed', ['experiments/METHOD_CONTRACT.json', 'experiments/RUN_SPEC.json'])
def test_upstream_scientific_change_preserves_candidates_and_revokes_acceptance(tmp_path, changed):
    service, paths, _previous, target = _ready(tmp_path)
    original = {path: path.read_bytes() for stage in _previous['stages'] if stage != 'consistency'
                for path in service.stage_outputs(paths, stage) if path.is_file()}
    source = tmp_path / changed
    payload = json.loads(source.read_text())
    payload['current_design_note'] = 'Changed upstream input requires independent reassessment'
    source.write_text(json.dumps(payload))
    service.prepare(tmp_path, {})
    state = json.loads(paths['state'].read_text())
    assert all(path.read_bytes() == raw for path, raw in original.items())
    assert state['explanation_refresh_requires_model_review'] is True
    assert all(record['status'] == 'pending' and not record['review_passed'] for record in state['stages'].values())
    assert not paths['cross_review'].exists()
    assert list((paths['paper'] / 'revisions').rglob(target.name))


def test_partial_manuscript_is_never_deleted_by_upstream_refresh(tmp_path):
    service, paths, _previous, target = _ready(tmp_path)
    (paths['sections'] / '03_method.tex').unlink()
    before = target.read_bytes()
    source = tmp_path / 'NARRATIVE_REPORT.md'
    source.write_text('Updated source interpretation')
    service.prepare(tmp_path, {})
    assert target.read_bytes() == before
    assert not (paths['sections'] / '03_method.tex').exists()
    state = json.loads(paths['state'].read_text())
    assert state['explanation_refresh_requires_model_review'] is True
    assert state['stages']['results']['attempts'] == 1
