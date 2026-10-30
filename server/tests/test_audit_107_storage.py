"""Persistent settings paths, public projections and production dependency contracts."""
import json
from pathlib import Path
import tomllib
import sqlite3

from sqlalchemy import create_engine
from server.models.models import UserSetting

from server.api import settings as settings_api
from server.config import settings, Settings
from server.services.settings_models import ModelConfig, UserSettings
from server.services.settings_visibility import public_model_config


def test_settings_survive_working_directory_changes(tmp_path, monkeypatch):
    durable = tmp_path / "volume"
    monkeypatch.setattr(settings, "data_dir", str(durable))
    monkeypatch.setattr(settings_api, "CONFIG_FILE", durable / "user_settings.json")
    original = UserSettings(models=ModelConfig(exa_api_key="synthetic-storage-fixture"))
    settings_api.save_settings(original)
    elsewhere = tmp_path / "new-container"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    restored = settings_api.load_settings()
    assert restored.models.exa_api_key == original.models.exa_api_key
    assert not (elsewhere / "merak_ide.db").exists()
    assert (durable / "merak_ide.db").exists()
    assert "synthetic-storage-fixture" not in public_model_config(restored.models).model_dump_json()


def test_settings_save_after_application_creates_schema(tmp_path, monkeypatch):
    """A clean installed app creates ORM tables before the first settings save."""
    database = tmp_path / "merak_ide.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    UserSetting.__table__.create(engine)
    engine.dispose()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings_api, "CONFIG_FILE", tmp_path / "user_settings.json")
    config = UserSettings(models=ModelConfig(openai_api_key="fixture-key", openai_model="first"))
    settings_api.save_settings(config)
    config.models.openai_model = "second"
    settings_api.save_settings(config)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT value, updated_at FROM user_settings WHERE key = ?",
            ("models.openai_model",),
        ).fetchone()
    assert row is not None and row[0] == "second" and row[1]
    settings_api.CONFIG_FILE.unlink()
    assert settings_api.load_settings().models.openai_api_key == "fixture-key"


def test_production_dependencies_and_persistent_settings_mount_are_declared():
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(item.startswith("asyncpg") for item in project["project"]["optional-dependencies"]["production"])
    dockerfile = (root / "docker/Dockerfile.server").read_text(encoding="utf-8")
    compose = (root / "docker/docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in dockerfile
    assert "MERAK_IDE_DATA_DIR=/app/data" in compose and "app_data:/app/data" in compose


def test_weak_signing_secrets_are_not_used_or_echoed():
    import pytest
    from pydantic import ValidationError
    weak = "fixture-short"
    assert Settings(_env_file=None, debug=True, jwt_secret_key=weak).jwt_secret_key != weak
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, debug=False, jwt_secret_key=weak)
    assert weak not in str(error.value)
