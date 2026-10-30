"""Compiled PDF snapshots and bounded native-vision review packets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ..utils.atomic_write import atomic_write_json
from .review_models import ReviewState


ReviewProgress = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ReviewSnapshotRequest:
    """Complete immutable input for one compiled review snapshot."""

    project_path: str
    paper_path: str
    round_number: int
    original: bool
    reason: str
    on_progress: Optional[ReviewProgress]

    def __post_init__(self) -> None:
        if not self.project_path.strip() or not self.paper_path.strip():
            raise ValueError("Review snapshot paths must be non-empty")
        if self.round_number < 0:
            raise ValueError("Review snapshot round_number must be non-negative")
        if not self.reason.strip():
            raise ValueError("Review snapshot reason must be non-empty")


class ReviewVisualsMixin:
    @staticmethod
    def _project_relative(root: Path, path: str | Path) -> str:
        resolved = Path(path).expanduser().resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return resolved.as_posix()

    @staticmethod
    def _visual_bundle_sha256(root: Path, paths: list[str | Path]) -> str:
        digest = hashlib.sha256()
        inspected = 0
        for raw_path in paths:
            path = _resolved_file(root, raw_path)
            if path is None:
                continue
            try:
                identity = path.relative_to(root).as_posix()
            except ValueError:
                identity = path.as_posix()
            digest.update(identity.encode("utf-8", errors="replace"))
            digest.update(b"::")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            digest.update(b"\n")
            inspected += 1
        return digest.hexdigest() if inspected else ""

    @staticmethod
    def _visual_content_sha256(root: Path, paths: list[str | Path]) -> str:
        digest = hashlib.sha256()
        inspected = 0
        for raw_path in paths:
            path = _resolved_file(root, raw_path)
            if path is None:
                continue
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            digest.update(b"\n")
            inspected += 1
        return digest.hexdigest() if inspected else ""

    @staticmethod
    def _pdf_snapshot_for_source(
        state: ReviewState, project_path: str | Path, *,
        round_number: int, source_sha256: str,
    ) -> dict[str, Any] | None:
        root = Path(project_path).expanduser().resolve()
        for record in reversed(state.pdf_snapshots):
            try:
                record_round = int(record.get("round") or 0)
            except (TypeError, ValueError):
                continue
            if (
                record_round != int(round_number)
                or str(record.get("source_bundle_sha256") or "") != source_sha256
            ):
                continue
            snapshot = _resolved_path(root, record.get("snapshot_path"))
            report = _resolved_path(root, record.get("layout_report_path"))
            if (
                snapshot.is_file() and snapshot.stat().st_size > 0
                and snapshot.read_bytes()[:5] == b"%PDF-" and report.is_file()
            ):
                return record
        return None

    async def _compile_review_snapshot(
        self, state: ReviewState, request: ReviewSnapshotRequest,
    ) -> dict[str, Any]:
        from ..services.paper_compiler import paper_compiler
        from ..services.paper_print_repair import compile_print_verified_paper
        from .review_snapshot_reuse import preserve_reviewed_snapshot

        root = Path(request.project_path).expanduser().resolve()
        paper = _validated_paper(root, request.paper_path)
        if request.on_progress:
            label = "original" if request.original else f"round {request.round_number}"
            await request.on_progress(f"Compiling {label} review PDF snapshot...")
        record = preserve_reviewed_snapshot(state, request, paper)
        if record is None:
            if paper != root / "paper/main.tex":
                raise RuntimeError("Managed review requires the canonical paper/main.tex print producer")
            compile_result = await compile_print_verified_paper(paper_compiler, root)
            compiled_pdf = _validated_compile_result(paper, compile_result)
            snapshot = _copy_round_snapshot(paper, compiled_pdf, request.round_number, request.original)
            report_path, layout = await _inspect_snapshot(root, snapshot, compile_result, paper_compiler)
            record = self._snapshot_record(root, snapshot, compiled_pdf, report_path, layout,
                compile_result, request.round_number, request.original, request.reason)
        state.pdf_snapshots = [
            item for item in state.pdf_snapshots
            if int(item.get("round") or 0) != int(request.round_number)
        ]
        state.pdf_snapshots.append(record)
        state.pdf_snapshots.sort(key=lambda item: int(item.get("round") or 0))
        self._save_state(state, request.project_path)
        return record

    def _snapshot_record(
        self, root: Path, snapshot: Path, compiled_pdf: Path,
        report_path: Path, layout: dict[str, Any], compile_result: Any,
        round_number: int, original: bool, reason: str,
    ) -> dict[str, Any]:
        from .review_audit import review_source_bundle

        source_hash, _ = review_source_bundle(root)
        pages = [item for item in layout.get("pages", []) if isinstance(item, dict)]
        previews = [
            *list(layout.get("rendered_page_previews", []) or []),
            *list(layout.get("contact_sheet_paths", []) or []),
        ]
        return {
            "round": int(round_number),
            "kind": "original" if original else "review_round",
            "reason": reason, "compiled_at": time.time(),
            "current_pdf_path": self._project_relative(root, compiled_pdf),
            "snapshot_path": self._project_relative(root, snapshot),
            "pdf_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "visual_bundle_sha256": self._visual_bundle_sha256(root, previews),
            "visual_content_sha256": self._visual_content_sha256(root, previews),
            "source_bundle_sha256": source_hash,
            "pages": int(layout.get("page_count") or compile_result.pages or 0),
            "warning_count": len(compile_result.warnings),
            "layout_finding_count": sum(
                len(item.get("possible_layout_findings") or []) for item in pages
            ),
            "layout_renderer": str(layout.get("renderer") or ""),
            "layout_report_path": self._project_relative(root, report_path),
            "page_preview_paths": [
                self._project_relative(root, path)
                for path in layout.get("rendered_page_previews", [])
            ],
            "contact_sheet_paths": [
                self._project_relative(root, path)
                for path in layout.get("contact_sheet_paths", [])
            ],
        }

    @staticmethod
    def _layout_report_payload(
        project_path: str | Path, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        report_path = _resolved_path(root, snapshot.get("layout_report_path"))
        try:
            layout = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"document_findings": [
                "layout report could not be read; inspect the PDF directly"
            ]}
        return layout if isinstance(layout, dict) else {}

    @classmethod
    def _native_review_image_paths(
        cls, project_path: str | Path, snapshot: dict[str, Any], *,
        limit: int = 8,
    ) -> list[str]:
        root = Path(project_path).expanduser().resolve()
        layout = cls._layout_report_payload(root, snapshot)
        previews = list(snapshot.get("page_preview_paths") or [])
        selected: list[str] = []
        maximum = max(1, int(limit))
        for raw_path in snapshot.get("contact_sheet_paths") or []:
            _add_review_image(root, raw_path, selected, maximum)
        priority_pages = _priority_pages(layout, len(previews), snapshot)
        for page_number in priority_pages:
            _add_review_image(root, previews[page_number - 1], selected, maximum)
        return selected

    @classmethod
    def _pdf_review_context(
        cls, project_path: str, snapshot: dict[str, Any], *,
        review_images: Optional[list[str]] = None,
    ) -> str:
        layout = cls._layout_report_payload(project_path, snapshot)
        if review_images is None:
            review_images = cls._native_review_image_paths(project_path, snapshot)
        evidence = _review_evidence(snapshot, layout, review_images)
        return (
            "\n\n## Mandatory Current-PDF Visual Review\n"
            "The PDF below was freshly compiled from the current sources and "
            "hash-frozen before this review. Open the PDF and rendered page/contact "
            "sheet images when your interface supports them. Independently inspect "
            "figure legibility and grayscale distinction, caption alignment, table "
            "formatting, orphan headings/page breaks, float placement, clipping, "
            "overlap, whitespace, and cross-figure visual consistency. The extracted "
            "geometry report is evidence to cross-check, not a substitute for visual "
            "judgment. Contact sheets cover every rendered page; the attached "
            "high-resolution pages are a deterministic risk-focused subset. Open "
            "additional pages from the recorded layout report when needed. Do not "
            "discuss earlier rounds; judge only this artifact.\n"
            + json.dumps(evidence, ensure_ascii=False, indent=2)
            + "\nYour JSON response MUST include a non-empty visual_review object "
            "with pdf_path, figure_quality, caption_alignment, page_layout, "
            "table_formatting, and visual_consistency."
        )


def _resolved_path(root: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _resolved_file(root: Path, raw_path: Any) -> Path | None:
    path = _resolved_path(root, raw_path)
    return path if path.is_file() and path.stat().st_size > 0 else None


def _validated_paper(root: Path, paper_path: str) -> Path:
    paper = Path(paper_path).expanduser()
    paper = (paper if paper.is_absolute() else root / paper).resolve()
    try:
        paper.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Managed review paper is outside the project: {paper}") from exc
    if not paper.is_file():
        raise RuntimeError(f"Managed review paper source is missing: {paper}")
    return paper


def _validated_compile_result(paper: Path, result: Any) -> Path:
    if not result.success:
        diagnostics = "; ".join(
            f"{item.file}:{item.line}: {item.message}" for item in result.errors[:8]
        ) or result.log_output[-1200:] or "unknown LaTeX failure"
        raise RuntimeError(
            "Managed review requires a fresh compiled PDF before semantic or visual "
            f"scoring; compilation failed: {diagnostics}"
        )
    compiled = Path(result.pdf_path or paper.with_suffix(".pdf")).expanduser().resolve()
    if (
        not compiled.is_file() or compiled.stat().st_size <= 0
        or compiled.read_bytes()[:5] != b"%PDF-"
    ):
        raise RuntimeError(
            "Managed review compilation reported success but produced no valid PDF"
        )
    return compiled


def _copy_round_snapshot(
    paper: Path, compiled_pdf: Path, round_number: int, original: bool
) -> Path:
    name = (
        f"{paper.stem}_round0_original.pdf" if original
        else f"{paper.stem}_round{round_number}.pdf"
    )
    snapshot = paper.parent / name
    shutil.copy2(compiled_pdf, snapshot)
    return snapshot


async def _inspect_snapshot(
    root: Path, snapshot: Path, compile_result: Any, compiler: Any
) -> tuple[Path, dict[str, Any]]:
    preview_dir = root / "review-stage" / "pdf-previews" / snapshot.stem
    layout = await asyncio.to_thread(
        compiler.inspect_pdf_for_review, snapshot, preview_dir=preview_dir
    )
    layout["compile_warnings"] = [
        {"file": item.file, "line": item.line, "message": item.message}
        for item in compile_result.warnings
    ]
    report_path = root / "review-stage" / "pdf-layout" / f"{snapshot.stem}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, layout)
    return report_path, layout


def _add_review_image(
    root: Path, raw_path: Any, selected: list[str], maximum: int
) -> None:
    if len(selected) >= maximum or not str(raw_path or "").strip():
        return
    path = _resolved_path(root, raw_path)
    try:
        relative = path.relative_to(root).as_posix()
    except (OSError, ValueError):
        return
    if path.is_file() and path.stat().st_size > 0 and relative not in selected:
        selected.append(relative)


def _priority_pages(
    layout: dict[str, Any], preview_count: int, snapshot: dict[str, Any]
) -> list[int]:
    records = [item for item in layout.get("pages") or [] if isinstance(item, dict)]
    by_page = {
        int(item.get("page") or index + 1): item
        for index, item in enumerate(records)
        if str(item.get("page") or index + 1).isdigit()
    }
    page_count = max(preview_count, int(layout.get("page_count") or snapshot.get("pages") or 0))
    priority: list[int] = []
    for predicate in (
        lambda item: bool(item.get("possible_layout_findings")),
        lambda item: int(item.get("image_instances") or 0) > 0,
    ):
        for number, record in sorted(by_page.items()):
            if predicate(record) and 1 <= number <= preview_count and number not in priority:
                priority.append(number)
    for number in (1, max(1, page_count // 2), page_count, *range(1, preview_count + 1)):
        if 1 <= number <= preview_count and number not in priority:
            priority.append(number)
    return priority


def _review_evidence(
    snapshot: dict[str, Any], layout: dict[str, Any], images: list[str]
) -> dict[str, Any]:
    fields = (
        "page", "width_pt", "height_pt", "visible_text_chars", "text_blocks",
        "image_instances", "drawing_objects", "minimum_font_pt", "median_font_pt",
        "content_margins_pt", "possible_layout_findings",
    )
    pages = [
        {key: page[key] for key in fields if key in page}
        for page in layout.get("pages") or [] if isinstance(page, dict)
    ]
    return {
        "current_pdf": snapshot.get("current_pdf_path"),
        "immutable_round_snapshot": snapshot.get("snapshot_path"),
        "pdf_sha256": snapshot.get("pdf_sha256"),
        "page_count": snapshot.get("pages"),
        "compile_warning_count": snapshot.get("warning_count"),
        "layout_report": snapshot.get("layout_report_path"),
        "contact_sheets": snapshot.get("contact_sheet_paths"),
        "rendered_page_preview_count": len(snapshot.get("page_preview_paths") or []),
        "native_image_attachments": images,
        "rendered_layout_evidence": {
            "renderer": layout.get("renderer"),
            "page_count": layout.get("page_count"),
            "page_size_consistent": layout.get("page_size_consistent"),
            "document_findings": layout.get("document_findings") or [],
            "pages": pages,
        },
    }
