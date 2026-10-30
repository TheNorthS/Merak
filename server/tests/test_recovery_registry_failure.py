"""A failed recovery registration cannot silently claim a project is recoverable."""

from pathlib import Path

import pytest

from server.services.workflow_recovery import WorkflowRecoveryWatchdog


def test_failed_registry_write_is_reported_and_next_observation_retries(tmp_path, monkeypatch):
    registry = tmp_path / 'registry.json'
    watchdog = WorkflowRecoveryWatchdog(registry_path=registry)
    project = tmp_path / 'project'
    project.mkdir()
    calls = []
    from server.services import workflow_recovery
    original = workflow_recovery.atomic_write_json

    def failing(path, value):
        calls.append(path)
        raise OSError('disk write failed')

    monkeypatch.setattr(workflow_recovery, 'atomic_write_json', failing)
    with pytest.raises(OSError, match='disk write failed'):
        watchdog.observe_project(project)
    assert watchdog._project_key(project) not in watchdog._projects
    monkeypatch.setattr(workflow_recovery, 'atomic_write_json', original)
    watchdog.observe_project(project)
    assert registry.is_file()
    assert watchdog._projects[watchdog._project_key(project)] == str(project.resolve())
    assert len(calls) == 1
