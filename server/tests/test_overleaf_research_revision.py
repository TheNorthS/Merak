"""Local publication merge tests; no network, remote repository or credentials."""

import json

import pytest

from server.services.overleaf_models import OverleafProject
from server.services.overleaf_sync import OverleafSync
from server.utils.atomic_write import atomic_write_json


@pytest.fixture
def sync_project(tmp_path):
    root = tmp_path / "research"
    (root / "paper").mkdir(parents=True)
    (root / "paper/main.tex").write_text("original", encoding="utf-8")
    service = OverleafSync(db_path=tmp_path / "links.sqlite", encryption_secret="local-test")
    project = OverleafProject(project_id="test-project", local_path=str(root / "paper"),
                              repo_path=str(tmp_path / "repository"))
    service._materialize_export(project)
    return service, project, root, tmp_path / "repository"


def test_pull_cannot_overwrite_local_edit_made_during_network_operation(sync_project):
    service, project, root, repository = sync_project
    (repository / "paper/main.tex").write_text("remote", encoding="utf-8")
    (root / "paper/main.tex").write_text("concurrent", encoding="utf-8")
    with pytest.raises(RuntimeError, match="local publication changed"):
        service._apply_export(project)
    assert (root / "paper/main.tex").read_text() == "concurrent"


def test_remote_paper_change_preserves_completed_version_before_import(sync_project):
    service, project, root, repository = sync_project
    run_file = root / ".merak/runs/accepted.json"
    atomic_write_json(run_file, {"run_id": "accepted", "status": "completed", "phases": {
        node: {"status": "accepted", "verdict_id": "prior", "details": {}}
        for node in ("lit", "exp-run", "paper", "review", "compile")}})
    before_run = run_file.read_bytes()
    (repository / "paper/main.tex").write_text("remote", encoding="utf-8")
    service._apply_export(project)
    state = json.loads(run_file.read_text())
    assert (root / "paper/main.tex").read_text() == "remote"
    assert state["phases"]["compile"]["status"] == "accepted"
    assert state["phases"]["exp-run"]["status"] == "accepted"
    assert run_file.read_bytes() == before_run
    revision = json.loads(next((root/'.merak/local-revisions').glob('*.json')).read_bytes())
    assert json.loads((root/revision['change_receipt']).read_bytes())['status'] == 'applied'
    baseline = root/'.merak/completed-versions/accepted/artifacts/paper/main.tex'
    assert baseline.read_text() == 'original'
    assert project.last_imported_files == ["paper/main.tex"]
    service._apply_export(project)
    assert project.last_imported_files == []


def test_failed_merge_restores_local_files(sync_project, monkeypatch):
    service, project, root, repository = sync_project
    (repository / "paper/main.tex").write_text("remote", encoding="utf-8")
    copy = service._copy_research_tree
    calls = 0

    def failing_copy(source, destination, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk failure")
        copy(source, destination, **kwargs)

    monkeypatch.setattr(service, "_copy_research_tree", failing_copy)
    with pytest.raises(OSError, match="disk failure"):
        service._apply_export(project)
    assert (root / "paper/main.tex").read_text() == "original"
    receipts = list((root / ".merak/overleaf-revisions").glob("*/revision.json"))
    assert json.loads(receipts[0].read_text())["status"] == "rolled_back"


@pytest.mark.parametrize("later_edit", [False, True])
def test_restart_recovers_interrupted_import_but_preserves_later_edits(sync_project, monkeypatch, later_edit):
    from server.services import overleaf_research_revision as revisions

    service, project, root, repository = sync_project
    (repository / "paper/main.tex").write_text("remote", encoding="utf-8")
    writer = revisions.atomic_write_json
    def interrupt_commit(path, value):
        if value.get("status") == "applied":
            raise OSError("process stopped before commit receipt")
        return writer(path, value)
    monkeypatch.setattr(revisions, "atomic_write_json", interrupt_commit)
    with pytest.raises(OSError, match="before commit"):
        service._apply_export(project)
    assert (root / "paper/main.tex").read_text() == "remote"
    if later_edit:
        (root / "paper/main.tex").write_text("later edit", encoding="utf-8")
        with pytest.raises(ValueError, match="explicit reconciliation"):
            service._materialize_export(project)
        assert (root / "paper/main.tex").read_text() == "later edit"
    else:
        service._materialize_export(project)
        assert (root / "paper/main.tex").read_text() == "original"
        receipt = next((root / ".merak/overleaf-revisions").glob("*/revision.json"))
        assert json.loads(receipt.read_text())["recovered_after_restart"]
