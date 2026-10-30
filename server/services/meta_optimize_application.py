"""Validate and serialize skill mutations before they reach live execution."""

from functools import wraps
from contextlib import nullcontext
from pathlib import Path
import re
import copy

from ..utils.atomic_write import path_lock


def mutation_transaction(method):
    """Reload under the state lock so different gate instances cannot lose updates."""
    @wraps(method)
    def execute(self, *args, **kwargs):
        with path_lock(self._state_file()):
            self._mutations.clear()
            self._load_state()
            identity = args[0] if args else kwargs.get("mutation_id", kwargs.get("skill_name", ""))
            mutation = self._mutations.get(identity)
            skill = mutation.skill_name if mutation else identity
            path = self._find_skill_file(skill)
            with path_lock(path) if path else nullcontext():
                before = path.read_text(encoding="utf-8") if path and path.is_file() else None
                previous = copy.deepcopy(self._mutations)
                try:
                    return method(self, *args, **kwargs)
                except Exception:
                    if before is not None and path.is_file() and path.read_text(encoding="utf-8") != before:
                        from ..utils.atomic_write import atomic_write_text
                        atomic_write_text(path, before)
                        refresh_skill(path)
                    self._mutations = previous
                    raise
    return execute


def valid_skill_identity(skill_name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", skill_name))


def validate_skill_revision(path: Path, original: str, proposed: str) -> None:
    from .artifact_contract import validate_skill_artifact_contract_content

    if not proposed.strip() or proposed == original:
        raise ValueError("A skill revision must contain a substantive change")
    validate_skill_artifact_contract_content(proposed)
    if path.read_text(encoding="utf-8") != original:
        raise ValueError("Mutation is stale because the canonical skill changed")


def refresh_skill(path: Path) -> None:
    from .skill_registry import parse_skill_md, skill_registry

    metadata = parse_skill_md(path)
    if metadata is None:
        raise ValueError("The changed skill cannot be loaded by the runtime")
    skill_registry._skills[metadata.id] = metadata
    skill_registry._build_category_index()
    skill_registry._build_search_index()
