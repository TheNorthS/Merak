"""Apply and revoke only environment overrides owned by user configuration."""
import os
import threading

from .settings_models import ModelConfig

ENVIRONMENT_FIELDS = {
    "exa_api_key": "EXA_API_KEY", "serpapi_api_key": "SERPAPI_KEY",
    "epo_ops_key": "EPO_OPS_KEY", "epo_ops_secret": "EPO_OPS_SECRET",
    "gpt_image_api_key": "GPT_IMAGE_API_KEY", "gpt_image_base_url": "GPT_IMAGE_BASE_URL",
    "vastai_api_key": "VASTAI_API_KEY", "modal_token_id": "MODAL_TOKEN_ID",
    "modal_token_secret": "MODAL_TOKEN_SECRET", "zotero_api_key": "ZOTERO_API_KEY",
    "zotero_user_id": "ZOTERO_USER_ID", "obsidian_vault_path": "OBSIDIAN_VAULT_PATH",
}
_owned: dict[str, tuple[str | None, str]] = {}
_lock = threading.Lock()


def apply_integration_environment(config: ModelConfig) -> None:
    """Empty user values remove the override and restore any preexisting system value."""
    with _lock:
        for field, variable in ENVIRONMENT_FIELDS.items():
            value = getattr(config, field)
            if value:
                original = _owned.get(variable, (os.environ.get(variable), ""))[0]
                os.environ[variable] = value
                _owned[variable] = (original, value)
            elif variable in _owned:
                original, previous = _owned.pop(variable)
                if os.environ.get(variable) != previous:
                    continue
                if original is None:
                    os.environ.pop(variable, None)
                else:
                    os.environ[variable] = original
