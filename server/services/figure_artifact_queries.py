"""Paths, queries, and delegated figure-artifact policies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional


from ..utils.atomic_write import atomic_write_text
from .figure_artifact_support import (
    ADMINISTRATIVE_FIGURE_PREFIXES,
    INTERNAL_FIGURE_ROLES,
    MANUSCRIPT_FIGURE_ROLES,
    NON_SUBMISSION_EVIDENCE_STATUSES,
    PAPER_READY_EXTENSIONS,
)


class FigureArtifactQueryMixin:
    @staticmethod
    def _is_scientific_figure(description: str) -> bool:
        normalized = " ".join(str(description or "").lower().split())
        return not any(normalized.startswith(prefix) for prefix in ADMINISTRATIVE_FIGURE_PREFIXES)

    @staticmethod
    def _is_manuscript_asset(metadata: dict[str, Any]) -> bool:
        role = str(metadata.get("scientific_role") or "").strip().casefold()
        evidence_status = str(
            metadata.get("evidence_status") or "artifact"
        ).strip().casefold()
        if metadata.get("manuscript_eligible") is False:
            return False
        if (
            role in INTERNAL_FIGURE_ROLES
            or evidence_status in NON_SUBMISSION_EVIDENCE_STATUSES
        ):
            return False
        return role in MANUSCRIPT_FIGURE_ROLES

    @staticmethod
    def semantic_key(description: str, metadata: Optional[dict[str, Any]] = None) -> str:
        metadata = dict(metadata or {})
        explicit = str(metadata.get("semantic_key") or "").strip().lower()
        if explicit:
            return re.sub(r"[^a-z0-9]+", "_", explicit).strip("_")[:96]
        words = re.findall(r"[a-z0-9]+", str(description or "").lower())
        if words:
            return "_".join(words[:14])[:96]
        role = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(metadata.get("scientific_role") or "research_figure").lower(),
        ).strip("_")
        return role or "research_figure"
    @staticmethod
    def figures_root(path: str | Path) -> Path:
        candidate = Path(path).expanduser().resolve()
        for current in (candidate, *candidate.parents):
            if current.name.lower() == "figures":
                return current
        return candidate

    @classmethod
    def project_root(cls, path: str | Path) -> Path:
        figures = cls.figures_root(path)
        return figures.parent if figures.name.lower() == "figures" else figures.parent

    @classmethod
    def manifest_path(cls, path: str | Path) -> Path:
        return cls.figures_root(path) / "FIGURE_MANIFEST.json"

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        manifest_path = cls.manifest_path(path)
        if not manifest_path.exists():
            return {"schema": 1, "updated_at": None, "figures": []}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            if strict:
                raise RuntimeError(
                    f"Figure manifest is unreadable and will not be overwritten: {manifest_path}"
                ) from exc
            return {
                "schema": 1,
                "updated_at": None,
                "figures": [],
                "_load_error": f"{type(exc).__name__}: {exc}",
            }
        if not isinstance(payload, dict):
            if strict:
                raise RuntimeError(
                    f"Figure manifest root must be an object: {manifest_path}"
                )
            return {
                "schema": 1,
                "updated_at": None,
                "figures": [],
                "_load_error": "manifest root is not an object",
            }
        if not isinstance(payload.get("figures", []), list):
            if strict:
                raise RuntimeError(
                    f"Figure manifest figures must be a list: {manifest_path}"
                )
            return {
                "schema": 1,
                "updated_at": payload.get("updated_at"),
                "figures": [],
                "_load_error": "manifest figures is not a list",
            }
        payload.setdefault("schema", 1)
        payload.setdefault("figures", [])
        return payload


    @staticmethod
    def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
        lines = [
            "# Figure Manifest",
            "",
            "| ID | Type | Paper-ready output | Editable source | Caption |",
            "|---|---|---|---|---|",
        ]
        for item in payload.get("figures", []):
            lines.append(
                "| {id} | {type} | {output} | {source} | {caption} |".format(
                    id=item.get("id", ""),
                    type=item.get("type", ""),
                    output=item.get("output_path") or "missing",
                    source=item.get("source_path") or "none",
                    caption=str(item.get("caption", "")).replace("|", "\\|"),
                )
            )
        atomic_write_text(path, "\n".join(lines) + "\n")

    @classmethod
    def paper_ready_entries(cls, path: str | Path) -> list[dict[str, Any]]:
        root = cls.project_root(path)
        entries = []
        for item in cls.load(path).get("figures", []):
            rel = item.get("output_path")
            if not rel:
                continue
            metadata = dict(item.get("metadata") or {})
            if not cls._is_manuscript_asset(metadata):
                continue
            if metadata.get("paper_selected", True) is False:
                continue
            output = (root / rel).resolve()
            if item.get("paper_ready") and output.exists() and output.stat().st_size > 0 and output.suffix.lower() in PAPER_READY_EXTENSIONS:
                entries.append(item)
        return entries

    @staticmethod
    def figurespec_layout_issues_payload(payload: dict[str, Any]) -> list[str]:
        from .figurespec_layout_policy import figurespec_layout_issues_payload

        return figurespec_layout_issues_payload(payload)

    @staticmethod
    def figurespec_layout_issues(source: Path) -> list[str]:
        from .figurespec_layout_policy import figurespec_layout_issues

        return figurespec_layout_issues(source)

    @classmethod
    def repair_evaluation_mermaid(
        cls,
        project_path: str | Path,
        figure_id: str,
    ) -> dict[str, Any]:
        from .mermaid_evaluation_repair import repair_evaluation_mermaid

        return repair_evaluation_mermaid(cls, project_path, figure_id)

    @staticmethod
    def candidate_penalty(issues: Iterable[str]) -> float:
        from .figure_candidate_store import candidate_penalty

        return candidate_penalty(issues)

    @classmethod
    def preserve_best_candidate(
        cls,
        project_path: str | Path,
        figure_id: str,
        issues: Iterable[str],
    ) -> dict[str, Any]:
        from .figure_candidate_store import preserve_best_candidate

        return preserve_best_candidate(project_path, figure_id, issues)

    @staticmethod
    def mermaid_render_text_issues(pdf_path: Path) -> list[str]:
        """Estimate Mermaid label size after fitting the figure to paper width."""
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            return ["mermaid paper PDF is missing for render-text verification"]
        try:
            import fitz

            document = fitz.open(pdf_path)
            spans = [
                span
                for page in document
                for block in page.get_text("dict").get("blocks", [])
                if isinstance(block, dict)
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text") or "").strip()
            ]
            page_width = max(
                (float(page.rect.width) for page in document),
                default=0.0,
            )
            document.close()
        except Exception as exc:
            return [f"mermaid paper PDF text cannot be inspected: {exc}"]
        if not spans or page_width <= 0:
            return ["mermaid paper PDF contains no extractable labels"]
        # ICLR/NeurIPS-style full-width figures have roughly 468--504 pt of
        # usable width.  Use 480 pt as a conservative cross-template estimate.
        paper_scale = min(1.0, 480.0 / page_width)
        projected_sizes = sorted(
            float(span.get("size") or 0.0) * paper_scale
            for span in spans
            if float(span.get("size") or 0.0) > 0
        )
        if not projected_sizes:
            return ["mermaid paper PDF has no measurable text spans"]
        median = projected_sizes[len(projected_sizes) // 2]
        tenth = projected_sizes[max(0, int(len(projected_sizes) * 0.10) - 1)]
        issues: list[str] = []
        if median < 7.0:
            issues.append(
                "mermaid labels project to an unreadable median size at paper "
                f"width ({median:.1f} pt)"
            )
        if tenth < 5.5:
            issues.append(
                "mermaid contains very small labels after paper-width scaling "
                f"({tenth:.1f} pt at the 10th percentile)"
            )
        return issues

    @classmethod
    def scientific_alignment_issues(cls, path: str | Path) -> list[str]:
        from .figure_scientific_alignment import scientific_alignment_issues

        return scientific_alignment_issues(cls, path)

    @staticmethod
    def gemini_protocol_issues(
        item: dict[str, Any],
        root: Path,
    ) -> list[str]:
        from .gemini_figure_audit import gemini_protocol_issues

        return gemini_protocol_issues(item, root)

    @classmethod
    def scientific_quality_issues(cls, path: str | Path) -> list[str]:
        from .figure_scientific_quality import scientific_quality_issues

        return scientific_quality_issues(cls, path)

    @staticmethod
    def render_box_diagram(
        output_path: str | Path,
        *,
        title: str,
        labels: Iterable[str],
        subtitle: str = "",
    ) -> str:
        from .figure_preview_renderers import render_box_diagram

        return render_box_diagram(
            output_path, title=title, labels=labels, subtitle=subtitle,
        )

    @staticmethod
    def render_mermaid_preview(
        code: str,
        output_path: str | Path,
        title: str = "Method workflow",
    ) -> str:
        from .figure_preview_renderers import render_mermaid_preview

        return render_mermaid_preview(code, output_path, title)

    @staticmethod
    def render_drawio_preview(
        xml: str,
        output_path: str | Path,
        title: str = "System architecture",
    ) -> str:
        from .figure_preview_renderers import render_drawio_preview

        return render_drawio_preview(xml, output_path, title)


