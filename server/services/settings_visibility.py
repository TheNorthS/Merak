"""Public settings projections contain presence markers, never credential bytes."""
from .settings_models import ModelConfig, UserSettings

SECRET_FIELDS = frozenset(name for name in ModelConfig.model_fields if (
    name.endswith(("_api_key", "_secret", "_token_id")) or name == "epo_ops_key"
))
MASK = "********"


def public_model_config(config: ModelConfig) -> ModelConfig:
    return config.model_copy(update={name: MASK if getattr(config, name) else "" for name in SECRET_FIELDS})


def public_settings(settings: UserSettings) -> UserSettings:
    return settings.model_copy(update={"models": public_model_config(settings.models)})
