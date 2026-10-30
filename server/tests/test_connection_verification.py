import asyncio
from types import SimpleNamespace

from server.agent import ModelRole, model_router
from server.services.connection_verification import ConnectionVerificationStore
from server.api import settings as settings_api
from server.api.settings import (
    ModelConfig,
    UserSettings,
    _is_transient_connection_error,
    integration_is_configured,
    model_verification_payload,
)


def test_success_is_bound_to_exact_configuration(tmp_path):
    store = ConnectionVerificationStore(tmp_path / "verification.db")
    original = {"host": "gpu.example.org", "port": 22, "secret": "one"}

    recorded = store.record("ssh", "lab", original, True, "connected")

    assert recorded["verified"] is True
    assert recorded["tested"] is True
    assert store.is_verified("ssh", "lab", original) is True

    changed = store.status("ssh", "lab", {**original, "secret": "two"})
    assert changed["verified"] is False
    assert changed["tested"] is False
    assert changed["stale"] is True
    assert changed["message"] == "配置已变更，需要重新测试"


def test_failed_test_is_persisted_but_not_selectable(tmp_path):
    store = ConnectionVerificationStore(tmp_path / "verification.db")
    payload = {"base_url": "https://example.invalid/v1", "model": "test"}

    status = store.record("model", "openai-api", payload, False, "timeout")

    assert status["tested"] is True
    assert status["verified"] is False
    assert status["stale"] is False
    assert status["message"] == "timeout"


def test_fingerprint_is_order_independent_and_does_not_store_payload(tmp_path):
    store = ConnectionVerificationStore(tmp_path / "verification.db")
    left = {"api_key": "top-secret", "model": "m"}
    right = {"model": "m", "api_key": "top-secret"}

    assert store.fingerprint(left) == store.fingerprint(right)
    store.record("model", "provider", left, True)

    raw_database = (tmp_path / "verification.db").read_bytes()
    assert b"top-secret" not in raw_database

def test_default_model_names_do_not_count_as_configured_integrations():
    config = ModelConfig()

    assert integration_is_configured(config, "gemini") is False
    assert integration_is_configured(config, "gpt_image") is False
    assert integration_is_configured(config, "vastai") is False
    assert integration_is_configured(config, "modal") is False

def test_only_transient_model_connection_errors_are_retried():
    assert _is_transient_connection_error(RuntimeError("503 Service temporarily unavailable")) is True
    assert _is_transient_connection_error(TimeoutError("timed out")) is True
    assert _is_transient_connection_error(RuntimeError("401 invalid API key")) is False


def test_independent_reviewer_status_uses_api_route_and_provider_verification(
    tmp_path,
    monkeypatch,
):
    store = ConnectionVerificationStore(tmp_path / "verification.db")
    monkeypatch.setattr(settings_api, "connection_verification_store", store)
    config = ModelConfig(
        openai_api_key="reviewer-key",
        openai_model="reviewer-a",
        anthropic_api_key="executor-key",
        anthropic_model="executor-a",
    )
    monkeypatch.setattr(
        settings_api,
        "load_settings",
        lambda: UserSettings(models=config),
    )
    monkeypatch.setattr(
        model_router,
        "_providers",
        {
            "claude-api": SimpleNamespace(
                name="anthropic/executor-a",
                model="executor-a",
            ),
            "openai-api": SimpleNamespace(
                name="openai/reviewer-a",
                model="reviewer-a",
            ),
        },
    )
    monkeypatch.setattr(
        model_router,
        "_strategy",
        {
            ModelRole.EXECUTOR: "claude-api",
            ModelRole.REVIEWER: "openai-api",
        },
    )

    before = settings_api._independent_reviewer_status()
    assert before["configured"] is True
    assert before["provider"] == "openai-api"
    assert before["model"] == "openai/reviewer-a"
    assert before["executor_model"] == "anthropic/executor-a"
    assert before["isolated"] is True
    assert before["verified"] is False
    assert before["ready"] is False

    store.record(
        "model",
        "openai-api",
        model_verification_payload(config, "openai-api"),
        True,
        "connected",
    )
    after = settings_api._independent_reviewer_status()

    assert after["verified"] is True
    assert after["ready"] is True


def test_independent_reviewer_test_reuses_model_api_probe(
    tmp_path,
    monkeypatch,
):
    store = ConnectionVerificationStore(tmp_path / "verification.db")
    monkeypatch.setattr(settings_api, "connection_verification_store", store)
    config = ModelConfig(
        openai_api_key="reviewer-key",
        openai_model="reviewer-a",
        anthropic_api_key="executor-key",
        anthropic_model="executor-a",
    )
    monkeypatch.setattr(
        settings_api,
        "load_settings",
        lambda: UserSettings(models=config),
    )
    monkeypatch.setattr(
        model_router,
        "_providers",
        {
            "claude-api": SimpleNamespace(
                name="anthropic/executor-a",
                model="executor-a",
            ),
            "openai-api": SimpleNamespace(
                name="openai/reviewer-a",
                model="reviewer-a",
            ),
        },
    )
    monkeypatch.setattr(
        model_router,
        "_strategy",
        {
            ModelRole.EXECUTOR: "claude-api",
            ModelRole.REVIEWER: "openai-api",
        },
    )
    tested: list[str] = []

    async def fake_model_probe(provider: str):
        tested.append(provider)
        verification = store.record(
            "model",
            provider,
            model_verification_payload(config, provider),
            True,
            "connected",
        )
        return {
            "success": True,
            "model": "openai/reviewer-a",
            "verification": verification,
        }

    monkeypatch.setattr(settings_api, "test_model_connection", fake_model_probe)

    result = asyncio.run(settings_api.test_independent_reviewer_connection())

    assert tested == ["openai-api"]
    assert result["success"] is True
    assert result["status"]["isolated"] is True
    assert result["status"]["ready"] is True


def test_independent_reviewer_test_accepts_executor_model(
    tmp_path,
    monkeypatch,
):
    store = ConnectionVerificationStore(tmp_path / "verification.db")
    monkeypatch.setattr(settings_api, "connection_verification_store", store)
    config = ModelConfig(openai_api_key="shared-key", openai_model="shared-model")
    monkeypatch.setattr(
        settings_api,
        "load_settings",
        lambda: UserSettings(models=config),
    )
    shared_provider = SimpleNamespace(
        name="openai/shared-model",
        model="shared-model",
    )
    monkeypatch.setattr(
        model_router,
        "_providers",
        {"openai-api": shared_provider},
    )
    monkeypatch.setattr(
        model_router,
        "_strategy",
        {
            ModelRole.EXECUTOR: "openai-api",
            ModelRole.REVIEWER: "openai-api",
        },
    )

    tested: list[str] = []

    async def same_model_probe(provider: str):
        tested.append(provider)
        verification = store.record(
            "model",
            provider,
            model_verification_payload(config, provider),
            True,
            "connected",
        )
        return {
            "success": True,
            "model": "openai/shared-model",
            "verification": verification,
        }

    monkeypatch.setattr(settings_api, "test_model_connection", same_model_probe)

    result = asyncio.run(settings_api.test_independent_reviewer_connection())

    assert tested == ["openai-api"]
    assert result["success"] is True
    assert result["status"]["isolated"] is True
    assert result["status"]["session_isolated"] is True
    assert result["status"]["same_model_allowed"] is True
    assert result["status"]["same_model"] is True
    assert result["status"]["ready"] is True
