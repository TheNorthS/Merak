"""Place local settings durability copies under the configured persistent directory."""
from pathlib import Path

from ..config import settings


def settings_storage_path(name: str) -> Path:
    return Path(settings.data_dir).expanduser().resolve() / name
