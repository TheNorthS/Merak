"""Settings saves survive partial persistence failures and preserve transport."""

import json
import os
import sqlite3

import pytest

from server.api import settings as api
from server.config import settings
from server.services.settings_models import ModelConfig, UserSettings
from server.services import settings_repository as repository


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(api, "CONFIG_FILE", tmp_path / "user_settings.json")
    return tmp_path


@pytest.mark.asyncio
async def test_model_settings_roundtrip_preserves_transport_and_masked_secret(storage, monkeypatch):
    api.save_settings(UserSettings(models=ModelConfig(openai_api_key="fixture-secret")))
    applied = []
    monkeypatch.setattr(api, "apply_model_config", applied.append)
    await api.update_model_config(ModelConfig(
        openai_api_key="****", openai_model="fixture-model", openai_transport="non_stream",
    ))
    restored = api.load_settings().models
    assert restored.openai_transport == "non_stream"
    assert restored.openai_api_key == "fixture-secret"
    assert applied[0] == restored


def test_unrelated_database_write_cannot_resurrect_old_settings(storage, monkeypatch):
    api.save_settings(UserSettings(models=ModelConfig(openai_model="old")))
    database = storage / "merak_ide.db"
    original_connect = sqlite3.connect

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as failure:
        failure.setattr(sqlite3, "connect", locked)
        api.save_settings(UserSettings(models=ModelConfig(openai_model="new")))
    with original_connect(database) as connection:
        connection.execute("CREATE TABLE unrelated_events (value TEXT)")
        connection.execute("INSERT INTO unrelated_events VALUES ('heartbeat')")
    future = api.CONFIG_FILE.stat().st_mtime + 10
    os.utime(database, (future, future))
    assert api.load_settings().models.openai_model == "new"


def test_new_db_snapshot_wins_even_if_json_mtime_is_in_future(storage, monkeypatch):
    api.save_settings(UserSettings(models=ModelConfig(openai_model="old")))
    old_json = api.CONFIG_FILE.read_bytes()
    api.save_settings(UserSettings(models=ModelConfig(openai_model="new")))
    api.CONFIG_FILE.write_bytes(old_json)
    future = (storage / "merak_ide.db").stat().st_mtime + 10
    os.utime(api.CONFIG_FILE, (future, future))
    assert api.load_settings().models.openai_model == "new"


def test_invalid_new_snapshot_falls_back_without_disclosing_secret(storage, capsys):
    api.save_settings(UserSettings(models=ModelConfig(openai_model="valid")))
    payload = json.loads(api.CONFIG_FILE.read_text(encoding="utf-8"))
    payload["models"]["openai_api_key"] = ["private-invalid-value"]
    api.CONFIG_FILE.write_text(json.dumps(payload), encoding="utf-8")
    assert api.load_settings().models.openai_model == "valid"
    captured = capsys.readouterr()
    assert "private-invalid-value" not in captured.out + captured.err


def test_both_writes_failing_never_report_saved_or_replace_previous(storage, monkeypatch):
    api.save_settings(UserSettings(models=ModelConfig(openai_model="previous")))

    def fail(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as failure:
        failure.setattr(repository, "write_database", fail)
        failure.setattr(repository, "atomic_write_json", fail)
        with pytest.raises(RuntimeError, match="could not be persisted"):
            api.save_settings(UserSettings(models=ModelConfig(openai_model="unsaved")))
    assert api.load_settings().models.openai_model == "previous"


def test_json_failure_and_backward_clock_leave_new_db_settings_recoverable(storage, monkeypatch):
    api.save_settings(UserSettings(models=ModelConfig(openai_model="previous")))

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(repository, "atomic_write_json", fail)
    monkeypatch.setattr(repository.time, "time_ns", lambda: 1)
    api.save_settings(UserSettings(models=ModelConfig(openai_model="durable")))
    assert api.load_settings().models.openai_model == "durable"
    from scripts.live_snapshot_safety import load_current_model_config_readonly
    assert load_current_model_config_readonly(storage).openai_model == "durable"
