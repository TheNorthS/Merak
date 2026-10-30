"""Installed recovery and connection receipts survive cwd changes and restarts."""

from pathlib import Path

from server.config import settings
from server.services.connection_verification import ConnectionVerificationStore
from server.services.workflow_recovery import WorkflowRecoveryWatchdog


def test_restart_recovers_registry_from_user_data_instead_of_install_directory(tmp_path, monkeypatch):
    data = tmp_path / "user-data"
    install = tmp_path / "application"
    install.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.chdir(install)
    first = WorkflowRecoveryWatchdog()
    first.observe_project(tmp_path / "research")
    monkeypatch.chdir(tmp_path)
    restarted = WorkflowRecoveryWatchdog()
    restarted._load_registry()
    assert list(restarted._projects.values()) == [str((tmp_path / "research").resolve())]
    assert restarted.registry_path.is_relative_to(data)
    assert list(install.iterdir()) == []


def test_connection_receipt_survives_new_cwd_and_never_creates_database_there(tmp_path, monkeypatch):
    data = tmp_path / "user-data"
    monkeypatch.setattr(settings, "data_dir", str(data))
    fingerprint_input = {"model": "fixture", "api_key": "not-a-real-key"}
    store = ConnectionVerificationStore()
    store.record("model", "fixture", fingerprint_input, True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert ConnectionVerificationStore().is_verified("model", "fixture", fingerprint_input)
    assert not Path("merak_ide.db").exists()
    assert not ConnectionVerificationStore().is_verified("model", "fixture", {"model": "changed"})
