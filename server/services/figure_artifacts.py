"""Persistent figure assets, previews, and paper-facing manifest utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


from .figure_artifact_support import (
    PAPER_READY_EXTENSIONS as PAPER_READY_EXTENSIONS,
    EDITABLE_EXTENSIONS as EDITABLE_EXTENSIONS,
    ADMINISTRATIVE_FIGURE_PREFIXES as ADMINISTRATIVE_FIGURE_PREFIXES,
    GENERIC_DIAGRAM_SIGNATURES as GENERIC_DIAGRAM_SIGNATURES,
    SEMANTIC_STOPWORDS as SEMANTIC_STOPWORDS,
    SEMANTIC_TOKEN_ALIASES as SEMANTIC_TOKEN_ALIASES,
    SEMANTIC_PHRASE_ALIASES as SEMANTIC_PHRASE_ALIASES,
    SCIENTIFIC_METADATA_FIELDS as SCIENTIFIC_METADATA_FIELDS,
    MANUSCRIPT_FIGURE_ROLES as MANUSCRIPT_FIGURE_ROLES,
    INTERNAL_FIGURE_ROLES as INTERNAL_FIGURE_ROLES,
    NON_SUBMISSION_EVIDENCE_STATUSES as NON_SUBMISSION_EVIDENCE_STATUSES,
    _sha256 as _sha256,
    _sha256_tree as _sha256_tree,
    _font as _font,
    _short_label as _short_label,
    _semantic_tokens as _semantic_tokens,
    _longest_false_run as _longest_false_run,
    _manifest_mutation as _manifest_mutation,
)
from .figure_raster_quality import FigureRasterQualityMixin
from .figure_diagram_text import FigureDiagramTextMixin
from .figure_artifact_queries import FigureArtifactQueryMixin
from .figure_artifact_lifecycle import FigureArtifactLifecycleMixin


class FigureArtifactRegistry(
    FigureArtifactQueryMixin,
    FigureArtifactLifecycleMixin,
    FigureRasterQualityMixin,
    FigureDiagramTextMixin,
):
    """Records every generated figure and provides dependency-free previews."""

    @classmethod
    @_manifest_mutation
    def reconcile(cls, path: str | Path) -> dict[str, Any]:
        from .figure_manifest_repository import reconcile_manifest

        return reconcile_manifest(cls, path)

    @classmethod
    def validate(
        cls,
        path: str | Path,
    ) -> tuple[bool, list[str], dict[str, Any]]:
        from .figure_manifest_repository import validate_manifest

        return validate_manifest(cls, path)

    @classmethod
    @_manifest_mutation
    def record(
        cls,
        *,
        output_dir: str | Path,
        figure_type: str,
        description: str,
        output_path: Optional[str] = None,
        source_path: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[Path, dict[str, Any]]:
        from .figure_manifest_repository import record_manifest_entry

        return record_manifest_entry(
            cls,
            output_dir=output_dir,
            figure_type=figure_type,
            description=description,
            output_path=output_path,
            source_path=source_path,
            metadata=metadata,
        )


figure_artifact_registry = FigureArtifactRegistry()
