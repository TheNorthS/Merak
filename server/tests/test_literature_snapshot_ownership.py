"""Literature proof never depends on a later paper owner's derived profile."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from server.services.workflow_inputs import snapshot_paths
from server.workflows.artifact_snapshot_ownership import owner_snapshot_view
from server.workflows.engine import WorkflowEngine
from server.workflows.engine_snapshot_paths import accepted_snapshot_paths
from server.workflows.models import WorkflowRun
from server.workflows.run_state import RunState


UPSTREAM = ("lit", "idea", "novelty", "exp-design", "exp-run", "results")


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _accepted_upstream(root: Path, *, profile_exists: bool = False):
    artifacts = {node: _write(root, f"fixtures/{node}.md", f"source {node}") for node in UPSTREAM}
    survey = _write(root, "literature/survey.md", "Substantive survey source")
    bibliography = _write(root, "literature/references.bib", "@article{known,title={Verified source}}")
    profile = root / "paper/PAPER_PROFILE.json"
    if profile_exists:
        _write(root, "paper/PAPER_PROFILE.json", '{"minimum_verified_citations":30}')
    run_id = "owned-literature-fixture"
    state = RunState(str(root), run_id)
    host = WorkflowEngine()
    nodes = [node for node in host._get_default_nodes() if node.id in UPSTREAM]
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in nodes], {"options": {}})
    for node in nodes:
        paths = [artifacts[node.id]]
        if node.id == "lit":
            # Exercise an actual persisted erroneous binding without normalizing
            # or rewriting it during the new owner-aware verification.
            paths.extend((survey, bibliography, profile))
        state.set_status(node.id, "done", artifact=str(artifacts[node.id]))
        state.accept(node.id, f"verified:{node.id}", "deterministic:fixture",
                     {"artifact_snapshot": snapshot_paths(root, paths)})
    run = WorkflowRun(id=run_id, project_path=str(root), nodes=nodes)
    return host, run, state, profile, bibliography, survey


@pytest.mark.parametrize("initial_exists", [False, True])
def test_creating_or_revising_paper_profile_preserves_all_six_upstream_acceptances(tmp_path, initial_exists):
    host, run, state, profile, _bibliography, _survey = _accepted_upstream(tmp_path, profile_exists=initial_exists)
    recorded = copy.deepcopy(state.load()["phases"])
    original_snapshot = recorded["lit"]["details"]["artifact_snapshot"]
    assert "paper/PAPER_PROFILE.json" in original_snapshot
    _write(tmp_path, "paper/PAPER_PROFILE.json", '{"minimum_verified_citations":45}')
    assert host._validated_accepted_phase_ids(run, state) == list(UPSTREAM)
    assert state.load()["phases"] == recorded
    assert profile.is_file()


@pytest.mark.parametrize("changed", ["bibliography", "survey"])
def test_real_literature_source_change_still_invalidates_literature_and_its_dependents(tmp_path, changed):
    host, run, state, _profile, bibliography, survey = _accepted_upstream(tmp_path)
    target = bibliography if changed == "bibliography" else survey
    target.write_text("Actual changed scientific source", encoding="utf-8")
    assert host._validated_accepted_phase_ids(run, state) == []
    phases = state.load()["phases"]
    assert all(phases[node]["status"] == "done" for node in UPSTREAM)
    reason = phases["lit"]["details"]["acceptance_invalidations"][-1]["reason"]
    assert target.relative_to(tmp_path).as_posix() in reason
    assert "lit" in phases["idea"]["details"]["acceptance_invalidations"][-1]["reason"]


def test_new_literature_bindings_exclude_profile_even_if_required_paths_reintroduce_it(tmp_path):
    host = WorkflowEngine()
    profile = tmp_path / "paper/PAPER_PROFILE.json"
    bibliography = tmp_path / "literature/references.bib"
    survey = tmp_path / "literature/survey.md"
    run = WorkflowRun(project_path=str(tmp_path))
    paths = accepted_snapshot_paths(host, run, "lit", {}, [survey, bibliography, profile])
    assert profile.resolve() not in paths
    assert bibliography.resolve() in paths and survey.resolve() in paths


def test_paper_profile_is_still_a_real_paper_acceptance_dependency(tmp_path):
    host = WorkflowEngine()
    profile = _write(tmp_path, "paper/PAPER_PROFILE.json", '{"minimum_verified_citations":30}')
    main = _write(tmp_path, "paper/main.tex", "\\documentclass{article}\\begin{document}Study\\end{document}")
    run_id = "paper-profile-owner"
    state = RunState(str(tmp_path), run_id)
    definitions = host._get_default_nodes()
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in definitions], {"options": {}})
    for node in definitions[:definitions.index(next(node for node in definitions if node.id == "paper"))]:
        artifact = _write(tmp_path, f"fixtures/{node.id}.md", f"source {node.id}")
        state.set_status(node.id, "done", artifact=str(artifact))
        state.accept(node.id, f"verified:{node.id}", "deterministic:fixture",
                     {"artifact_snapshot": snapshot_paths(tmp_path, [artifact])})
    run = WorkflowRun(id=run_id, project_path=str(tmp_path), nodes=definitions)
    paths = accepted_snapshot_paths(host, run, "paper", {}, [main])
    assert profile.resolve() in paths
    state.set_status("paper", "done", artifact=str(main))
    state.accept("paper", "verified:paper", "deterministic:fixture",
                 {"artifact_snapshot": snapshot_paths(tmp_path, paths)})
    profile.write_text('{"minimum_verified_citations":45}', encoding="utf-8")
    accepted = host._validated_accepted_phase_ids(run, state)
    assert "paper" not in accepted and "lit" in accepted
    phase = state.load()["phases"]["paper"]
    assert phase["status"] == "done"
    assert "paper/PAPER_PROFILE.json" in phase["details"]["acceptance_invalidations"][-1]["reason"]


@pytest.mark.parametrize("owner", ["idea", "novelty", "narrative", "paper", "review", "audit", "compile", "ppt", ""])
def test_other_owners_never_ignore_a_profile_binding(owner):
    snapshot = {"paper/PAPER_PROFILE.json": {"kind": "file", "sha256": "recorded"}}
    assert owner_snapshot_view(owner, snapshot) is snapshot


@pytest.mark.parametrize("key", ["paper/OTHER_PROFILE.json", "paper/PAPER_PROFILE.json.bak",
                                "fixtures/paper/PAPER_PROFILE.json", "../paper/PAPER_PROFILE.json",
                                "paper\\PAPER_PROFILE.json", "paper/paper_profile.json"])
def test_historical_literature_exclusion_is_an_exact_canonical_key_only(key):
    snapshot = {key: {"kind": "file", "sha256": "recorded"},
                "literature/references.bib": {"kind": "file", "sha256": "retained"}}
    assert owner_snapshot_view("lit", snapshot) == snapshot


@pytest.mark.parametrize("snapshot", [None, [], "malformed", 42])
def test_invalid_snapshot_shape_is_preserved_for_the_strict_validator(snapshot):
    assert owner_snapshot_view("lit", snapshot) is snapshot


def test_profile_only_historical_snapshot_does_not_turn_into_fake_acceptance(tmp_path):
    host = WorkflowEngine()
    snapshot = {"paper/PAPER_PROFILE.json": {"kind": "missing", "sha256": ""}}
    view = owner_snapshot_view("lit", snapshot)
    assert host._artifact_snapshot_issues(str(tmp_path), view) == ["accepted phase has no content-bound artifact snapshot"]


def test_filtered_verification_view_does_not_mutate_persisted_proof():
    snapshot = {"paper/PAPER_PROFILE.json": {"kind": "missing", "sha256": ""},
                "literature/references.bib": {"kind": "file", "sha256": "verified"}}
    before = copy.deepcopy(snapshot)
    assert owner_snapshot_view("lit", snapshot) == {"literature/references.bib": snapshot["literature/references.bib"]}
    assert snapshot == before
