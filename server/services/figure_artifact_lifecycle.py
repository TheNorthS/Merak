"""Curation, reuse, and duplicate pruning for figure artifacts."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Optional

from PIL import Image

from ..utils.atomic_write import atomic_write_json, path_lock
from .figure_artifact_support import (
    NON_SUBMISSION_EVIDENCE_STATUSES,
    _manifest_mutation,
    _sha256,
)


class FigureArtifactLifecycleMixin:
    @classmethod
    @_manifest_mutation
    def curate_to_plan(
        cls,
        path: str | Path,
        allowed_semantic_keys: set[str],
        *,
        evidence_mode: str = "planned",
        planned_assets: Optional[dict[str, dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Keep only planned/contracted assets paper-facing.

        Files are never deleted.  Unplanned MERAK-managed assets remain available in
        the IDE, but are explicitly marked IDE-only so a model cannot accidentally
        turn an administrative or duplicate image into paper evidence.
        """
        figures_root = cls.figures_root(path)
        payload = cls.reconcile(figures_root)
        changed = False
        for item in payload.get("figures", []):
            if not isinstance(item, dict):
                continue
            metadata = dict(item.get("metadata") or {})
            key = str(metadata.get("semantic_key") or "").strip()
            if not key or metadata.get("managed_by") != "merak":
                continue
            # The deterministic asset plan is authoritative for manuscript
            # semantics.  A model may describe an evaluation-design diagram as
            # a "protocol", but that internal role must not silently demote a
            # fully rendered required manuscript asset.  Synchronize the small
            # set of plan-owned fields before deciding paper eligibility.
            planned_asset = (
                (planned_assets or {}).get(key)
                if isinstance(planned_assets, dict)
                else None
            )
            if isinstance(planned_asset, dict):
                for field in (
                    "scientific_role",
                    "publication_role",
                    "manuscript_eligible",
                    "submission_eligible",
                    "evidence_status",
                    "generation_phase",
                    "generation_policy",
                ):
                    if field in planned_asset and metadata.get(field) != planned_asset.get(field):
                        metadata[field] = planned_asset.get(field)
                        changed = True
                if item.get("metadata") != metadata:
                    item["metadata"] = metadata
            selected = key in allowed_semantic_keys
            if not cls._is_manuscript_asset(metadata):
                selected = False
            if (
                str(metadata.get("evidence_status") or "").casefold()
                in NON_SUBMISSION_EVIDENCE_STATUSES
            ):
                selected = False
            if evidence_mode == "executed" and key.startswith("planned_"):
                selected = False
            if metadata.get("paper_selected") is not selected:
                metadata["paper_selected"] = selected
                item["metadata"] = metadata
                item["paper_ready"] = bool(
                    item.get("output_path")
                    and cls._is_scientific_figure(str(item.get("description") or ""))
                    and selected
                )
                changed = True
        if changed:
            payload["updated_at"] = time.time()
            manifest_path = cls.manifest_path(figures_root)
            atomic_write_json(manifest_path, payload)
            cls._write_markdown(figures_root / "FIGURE_MANIFEST.md", payload)
        return payload

    @classmethod
    def repair_previews(cls, path: str | Path) -> list[str]:
        """Re-render source-only or illegible Mermaid/Draw.io previews locally.

        Renderer availability is an infrastructure concern. It must not be sent
        back to the language model as a scientific revision task.
        """
        figures_root = cls.figures_root(path)
        project_root = cls.project_root(figures_root)
        payload = cls.load(figures_root)
        repaired: list[str] = []
        for item in list(payload.get("figures", [])):
            if not isinstance(item, dict):
                continue
            metadata = dict(item.get("metadata") or {})
            if (
                metadata.get("paper_selected") is False
                and not item.get("paper_ready")
            ):
                continue
            source_value = item.get("source_path")
            if not source_value:
                continue
            source = Path(str(source_value))
            source = source if source.is_absolute() else project_root / source
            if not source.is_file() or source.suffix.lower() not in {".mmd", ".mermaid", ".drawio", ".dio"}:
                continue
            output_value = item.get("output_path")
            output = Path(str(output_value)) if output_value else source.with_suffix(".png")
            output = output if output.is_absolute() else project_root / output
            needs_render = not output.is_file() or output.stat().st_size == 0
            if not needs_render:
                try:
                    with Image.open(output) as image:
                        width, height = image.size
                    needs_render = width < 1000 or height < 450 or width / max(1, height) > 4.2
                except OSError:
                    needs_render = True
            if not needs_render:
                needs_render = bool(cls.raster_layout_issues(output))
            if not needs_render:
                continue
            code = source.read_text(encoding="utf-8", errors="replace")
            if source.suffix.lower() in {".mmd", ".mermaid"}:
                cls.render_mermaid_preview(code, output, title=str(item.get("description") or source.stem))
                figure_type = "mermaid"
            else:
                cls.render_drawio_preview(code, output, title=str(item.get("description") or source.stem))
                figure_type = "drawio"
            metadata.update({
                "renderer": "local-semantic-repair",
                "render_status": "rendered",
                "source_faithful": "geometry-labels-edges-and-style" if figure_type == "drawio" else "nodes-and-order",
            })
            cls.record(
                output_dir=source.parent,
                figure_type=figure_type,
                description=str(item.get("description") or source.stem),
                output_path=str(output),
                source_path=str(source),
                metadata=metadata,
            )
            repaired.append(str(output))
        return repaired

    @classmethod
    def find_reusable(
        cls,
        path: str | Path,
        semantic_key: str,
        content_sha256: str,
        *,
        require_output: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Return a complete, hash-current semantic artifact.

        The manifest is read under the same lock used by record/reconcile so a
        concurrent session cannot observe an old entry while its superseded
        files are being replaced. Reuse is read-only: incomplete or
        hash-stale entries are skipped and will be regenerated by the caller.
        """

        with path_lock(cls.manifest_path(path)):
            return cls._find_reusable_locked(
                path,
                semantic_key,
                content_sha256,
                require_output=require_output,
            )

    @classmethod
    def _find_reusable_locked(
        cls,
        path: str | Path,
        semantic_key: str,
        content_sha256: str,
        *,
        require_output: bool = False,
    ) -> Optional[dict[str, Any]]:
        project_root = cls.project_root(path)
        target_key = cls.semantic_key("", {"semantic_key": semantic_key})

        def verified_file(value: Any, expected_hash: Any) -> Optional[Path]:
            if not str(value or "").strip() or not str(expected_hash or "").strip():
                return None
            candidate = Path(str(value)).expanduser()
            candidate = (
                candidate
                if candidate.is_absolute()
                else project_root / candidate
            ).resolve()
            if not candidate.is_file() or candidate.stat().st_size == 0:
                return None
            try:
                return (
                    candidate
                    if _sha256(candidate) == str(expected_hash)
                    else None
                )
            except OSError:
                return None

        for item in reversed(cls.load(path).get("figures", [])):
            metadata = dict(item.get("metadata") or {})
            if cls.semantic_key(str(item.get("description") or ""), metadata) != target_key:
                continue
            if str(metadata.get("content_sha256") or "") != str(content_sha256 or ""):
                continue

            declared_primary = [
                (item.get("output_path"), item.get("output_sha256")),
                (item.get("source_path"), item.get("source_sha256")),
            ]
            existing = [
                candidate
                for value, expected_hash in declared_primary
                if value
                for candidate in [verified_file(value, expected_hash)]
                if candidate is not None
            ]
            if any(value for value, _ in declared_primary) and len(existing) != sum(
                1 for value, _ in declared_primary if value
            ):
                continue

            variants = dict(metadata.get("rendered_variants") or {})
            variant_hashes = dict(metadata.get("rendered_variant_sha256") or {})
            variants_current = all(
                verified_file(value, variant_hashes.get(variant)) is not None
                for variant, value in variants.items()
                if str(value or "").strip()
            )
            if variants and not variants_current:
                continue
            if require_output and verified_file(
                item.get("output_path"),
                item.get("output_sha256"),
            ) is None:
                continue
            if existing:
                return dict(item)
        return None

    @classmethod
    def _delete_managed_assets(
        cls,
        figures_root: Path,
        project_root: Path,
        entries: Iterable[dict[str, Any]],
        keep_paths: set[str],
    ) -> None:
        for item in entries:
            metadata = dict(item.get("metadata") or {})
            managed = metadata.get("managed_by") == "merak"
            for key in ("output_path", "source_path"):
                value = str(item.get(key) or "")
                if not value or value in keep_paths:
                    continue
                candidate = Path(value)
                candidate = candidate if candidate.is_absolute() else project_root / candidate
                try:
                    candidate = candidate.resolve()
                    candidate.relative_to(figures_root)
                except (OSError, ValueError):
                    continue
                # A filename is not proof of ownership. Never delete user files
                # based on a historical naming convention.
                if not managed:
                    continue
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    continue

    @classmethod
    @_manifest_mutation
    def prune_semantic_duplicates(cls, path: str | Path) -> dict[str, Any]:
        """Keep one best artifact per semantic figure and remove MERAK-owned duplicates."""
        figures_root = cls.figures_root(path)
        project_root = cls.project_root(path)
        payload = cls.load(figures_root, strict=True)
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in payload.get("figures", []):
            key = cls.semantic_key(
                str(item.get("description") or ""),
                dict(item.get("metadata") or {}),
            )
            groups.setdefault(key, []).append(item)

        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for entries in groups.values():
            ordered = sorted(
                entries,
                key=lambda item: (
                    bool(item.get("paper_ready")),
                    bool(item.get("editable")),
                    int(item.get("output_bytes") or 0),
                    float(item.get("created_at") or 0),
                ),
                reverse=True,
            )
            kept.append(ordered[0])
            removed.extend(ordered[1:])
        if not removed:
            return payload

        keep_paths = {
            str(item.get(key))
            for item in kept
            for key in ("output_path", "source_path")
            if item.get(key)
        }
        cls._delete_managed_assets(figures_root, project_root, removed, keep_paths)
        payload["figures"] = kept
        payload["updated_at"] = time.time()
        manifest_path = figures_root / "FIGURE_MANIFEST.json"
        atomic_write_json(manifest_path, payload)
        cls._write_markdown(figures_root / "FIGURE_MANIFEST.md", payload)
        return payload
