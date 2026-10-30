"""Contract-grounded Beamer fallback for a research workflow."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from ..utils.atomic_write import (
    atomic_write_json,
    atomic_write_text,
    path_lock,
)
from .slide_figures import (
    SYNTHETIC_SLIDE_FIGURES as SYNTHETIC_PREVIEW_SLIDE_FIGURES,
    SYNTHETIC_SLIDE_FIGURE_IDS as SYNTHETIC_PREVIEW_SLIDE_FIGURE_IDS,
    deck_figures,
    qualified_standard_figures,
    qualified_synthetic_figures,
    referenced_figure_ids as resolve_referenced_figure_ids,
    referenced_ids_from_figures,
    standard_figure_entries,
)
from .slide_text import compact as _compact
from .slide_text import items as _items
from .slide_sources import slide_source_hash, slide_source_paths
from .slide_deck_builder import ensure_slide_deck


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _owned_json(path: Path, *, label: str) -> dict[str, Any]:
    """Read mutable slide coordination state without erasing corruption."""
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"{label} is empty or not a regular file: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig", errors="strict")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable or corrupt: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} root must be a JSON object: {path}")
    return value


def _update_plan(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    with path_lock(path):
        payload = _owned_json(path, label="Slide plan")
        payload.update(updates)
        atomic_write_json(path, payload)
        return payload


def _bind_existing_deck(
    project_path: str | Path,
    generator: str,
    figure_resolver: Callable[[str | Path, str, dict[str, Any]], list[str]],
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    main = root / "slides" / "main.tex"
    plan_path = root / "slides" / "SLIDE_PLAN.json"
    if not main.is_file() or main.stat().st_size == 0:
        return {
            "generated": False, "bound": False,
            "path": str(main), "plan_path": "",
        }
    sources = slide_source_paths(root)
    source_hash = slide_source_hash(root, sources)
    assets = _json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
    manifest = _json(root / "figures" / "FIGURE_MANIFEST.json")
    source_text = main.read_text(encoding="utf-8-sig", errors="replace")
    plan = _update_plan(plan_path, {
        "schema": 1,
        "bound_at": time.time(),
        "generator": generator,
        "platform_managed": True,
        "evidence_mode": str(assets.get("evidence_mode") or "planned"),
        "source_bundle_sha256": source_hash,
        "sources": [
            source.relative_to(root).as_posix()
            if source.is_relative_to(root) else source.as_posix()
            for source in sources
        ],
        "tex_sha256": hashlib.sha256(main.read_bytes()).hexdigest(),
        "selected_figures": figure_resolver(root, source_text, manifest),
    })
    return {
        "generated": False, "bound": True,
        "path": str(main), "plan_path": str(plan_path),
        "evidence_mode": plan["evidence_mode"],
    }


class ScientificSlideService:
    @staticmethod
    def _standard_figures(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return standard_figure_entries(manifest)

    @classmethod
    def qualified_standard_figures(
        cls,
        project_path: str | Path,
        manifest: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        root = Path(project_path).expanduser().resolve()
        figure_manifest = manifest if isinstance(manifest, dict) else _json(
            root / "figures" / "FIGURE_MANIFEST.json"
        )
        return qualified_standard_figures(root, figure_manifest)

    @classmethod
    def qualified_synthetic_figures(
        cls,
        project_path: str | Path,
        manifest: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        root = Path(project_path).expanduser().resolve()
        figure_manifest = manifest if isinstance(manifest, dict) else _json(
            root / "figures" / "FIGURE_MANIFEST.json"
        )
        return qualified_synthetic_figures(root, figure_manifest)

    @classmethod
    def _deck_figures(
        cls,
        root: Path,
        assets: dict[str, Any],
        manifest: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return deck_figures(root, assets, manifest)

    @classmethod
    def referenced_figure_ids(
        cls,
        project_path: str | Path,
        tex_text: str,
        manifest: dict[str, Any] | None = None,
    ) -> list[str]:
        root = Path(project_path).expanduser().resolve()
        figure_manifest = manifest if isinstance(manifest, dict) else _json(
            root / "figures" / "FIGURE_MANIFEST.json"
        )
        assets = _json(root / "figures" / "SCIENTIFIC_ASSET_PLAN.json")
        return resolve_referenced_figure_ids(root, tex_text, assets, figure_manifest)
    @staticmethod
    def _source_paths(root: Path) -> list[Path]:
        return slide_source_paths(root)

    @staticmethod
    def _source_hash(root: Path, sources: list[Path]) -> str:
        return slide_source_hash(root, sources)

    def source_bundle(self, project_path: str | Path) -> tuple[str, list[Path]]:
        root = Path(project_path).expanduser().resolve()
        sources = self._source_paths(root)
        return self._source_hash(root, sources), sources
    def bind_existing(
        self,
        project_path: str | Path,
        *,
        generator: str = "model:paper-talk",
    ) -> dict[str, Any]:
        return _bind_existing_deck(
            project_path, generator, self.referenced_figure_ids
        )

    def refresh_plan_binding(self, project_path: str | Path) -> bool:
        """Refresh TeX-derived bindings after a deterministic source repair.

        The upstream research bundle must already match the plan. This prevents a
        compiler package repair from making the plan look stale without masking
        genuine paper, method, result, or figure drift.
        """
        root = Path(project_path).expanduser().resolve()
        main = root / "slides" / "main.tex"
        plan_path = root / "slides" / "SLIDE_PLAN.json"
        plan = _owned_json(plan_path, label="Slide plan")
        if not main.is_file() or not plan:
            return False
        source_hash, sources = self.source_bundle(root)
        if str(plan.get("source_bundle_sha256") or "") != source_hash:
            return False
        source_text = main.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )
        manifest = _json(root / "figures" / "FIGURE_MANIFEST.json")
        plan = _update_plan(plan_path, {
            "source_bundle_sha256": source_hash,
            "sources": [
                source.relative_to(root).as_posix()
                if source.is_relative_to(root)
                else source.as_posix()
                for source in sources
            ],
            "tex_sha256": hashlib.sha256(main.read_bytes()).hexdigest(),
            "selected_figures": self.referenced_figure_ids(
                root,
                source_text,
                manifest,
            ),
            "binding_refreshed_at": time.time(),
        })
        return True

    def ensure(
        self,
        project_path: str | Path,
        research_direction: str = "",
        *,
        force: bool = False,
        bind_existing: bool = False,
    ) -> dict[str, Any]:
        return ensure_slide_deck(
            self,
            project_path,
            research_direction,
            force=force,
            bind_existing=bind_existing,
            figure_titles=SYNTHETIC_PREVIEW_SLIDE_FIGURES,
        )


scientific_slide_service = ScientificSlideService()
