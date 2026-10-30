"""Map current PDF geometry findings to editable figure or LaTeX sources."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..services.latex_bundle import latex_source_bundle


MARKERS = (
    "very small text detected",
    "possible overlapping text-block",
    "content approaches the physical page edge",
    "page appears blank or nearly blank",
    "possible orphaned heading",
)


def _report(root: Path, state: dict[str, Any]) -> tuple[dict[str, Any], Path] | None:
    rounds = [item for item in state.get("rounds") or [] if isinstance(item, dict)]
    if not rounds:
        return None
    from .review_audit import review_source_bundle

    source_hash, _ = review_source_bundle(root)
    visual = rounds[-1].get("visual_review")
    visual = visual if isinstance(visual, dict) else {}
    if (
        not source_hash
        or str(state.get("source_bundle_sha256") or "") != source_hash
        or str(visual.get("_source_bundle_sha256") or "") != source_hash
    ):
        return None
    reviewed = str(rounds[-1].get("pdf_snapshot") or "")
    snapshots = [
        item for item in state.get("pdf_snapshots") or [] if isinstance(item, dict)
    ]
    snapshots.sort(
        key=lambda item: (
            int(item.get("round") or 0),
            float(item.get("compiled_at") or 0),
        ),
        reverse=True,
    )
    managed = (root / "review-stage" / "pdf-layout").resolve()
    for snapshot in snapshots:
        if str(snapshot.get("snapshot_path") or "") != reviewed:
            continue
        path = Path(str(snapshot.get("layout_report_path") or ""))
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_relative_to(managed):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and str(payload.get("pdf_sha256") or "")
            == str(snapshot.get("pdf_sha256") or "")
            and str(snapshot.get("source_bundle_sha256") or "") in {"", source_hash}
        ):
            return payload, path
    return None


def _aux_labels(paper: Path) -> dict[int, list[str]]:
    labels, seen, queue = {}, set(), [paper / "main.aux"]
    while queue:
        path = queue.pop(0).resolve()
        if (
            path in seen
            or not path.is_file()
            or not path.is_relative_to(paper.resolve())
        ):
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for match in re.finditer(
            r"\\newlabel\{(?P<label>[^}]+)\}\{\{.*?\}\{(?P<page>\d+)\}",
            text,
        ):
            page, label = int(match.group("page")), match.group("label").strip()
            if label and label not in labels.setdefault(page, []):
                labels[page].append(label)
        for child in re.findall(r"\\@input\s*\{([^}]+)\}", text, re.I):
            candidate = (path.parent / child.replace("\\", "/")).resolve()
            if candidate.is_relative_to(paper.resolve()):
                queue.append(candidate)
    return labels


def _entries(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return [
        dict(item)
        for item in value.get(key) or []
        if isinstance(value, dict) and isinstance(item, dict)
    ]


def _tex_sources(paper: Path) -> list[tuple[Path, str]]:
    try:
        _, paths = latex_source_bundle(paper)
    except (OSError, ValueError):
        return []
    sources = []
    for path in paths:
        if path.suffix.casefold() == ".tex":
            try:
                sources.append(
                    (path, path.read_text(encoding="utf-8-sig", errors="replace")),
                )
            except OSError:
                pass
    return sources


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return ""


def _source_for_label(
    root: Path,
    paper: Path,
    label: str,
    sources: list[tuple[Path, str]],
) -> tuple[str, str]:
    for path, text in sources:
        match = re.search(rf"\\label\{{{re.escape(label)}\}}", text)
        if match is None:
            continue
        starts = list(
            re.finditer(
                r"\\begin\{(figure\*?|table\*?)\}",
                text[: match.start()],
                re.I,
            )
        )
        return _relative(root, path), starts[-1].group(1).casefold() if starts else ""
    return _relative(root, paper / "main.tex"), ""


def _figures_referenced_by_source(
    source: str,
    sources: list[tuple[Path, str]],
    figures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve manifest figures from reachable LaTeX when labels live in TeX.

    Figure manifests do not need to duplicate LaTeX labels. The reachable float
    source is authoritative for label placement, while matching graphic stems
    bind that float back to the editable manifest source.
    """
    text = next(
        (content for path, content in sources if path.as_posix().endswith(source)),
        "",
    )
    references = {
        Path(raw.replace("\\", "/")).stem.casefold()
        for raw in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text)
    }
    if not references:
        return []
    return [
        entry for entry in figures
        if any(
            Path(str(entry.get(key) or "").replace("\\", "/")).stem.casefold()
            in references
            for key in ("output_path", "source_path")
        )
    ]


def _targets(
    root: Path,
    paper: Path,
    label: str,
    figures: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    sources: list[tuple[Path, str]],
) -> tuple[str, list[str], list[str]]:
    source, environment = _source_for_label(root, paper, label, sources)
    if environment.startswith("figure") or label.casefold().startswith(
        ("fig:", "figure:")
    ):
        selected = []
        for entry in figures:
            metadata = (
                entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            )
            if str(entry.get("label") or metadata.get("label") or "") == label:
                selected.append(entry)
        if not selected:
            selected = _figures_referenced_by_source(source, sources, figures)
        paths = [
            _relative(
                root, root / str(item.get("source_path") or item.get("output_path"))
            )
            for item in selected
        ]
        paths = [path for path in paths if path]
        return (
            "figure",
            list(dict.fromkeys([*paths, source])),
            [str(item.get("id")) for item in selected if item.get("id")],
        )
    selected = [item for item in tables if str(item.get("label") or "") == label]
    paths = [
        _relative(root, root / str(item.get("latex_path") or ""))
        for item in selected
        if item.get("latex_path")
    ]
    return (
        "paper",
        list(dict.fromkeys([source or "paper/main.tex", *paths])),
        [str(item.get("id")) for item in selected if item.get("id")],
    )


def _layout_finding(
    page: int,
    issue: str,
    label: str,
    owner: str,
    targets: list[str],
    assets: list[str],
    report: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(
        f"{page}:{issue}:{owner}:{targets}:{assets}".encode(),
    ).hexdigest()[:10]
    token = re.sub("[^A-Za-z0-9]+", "-", label).strip("-").upper()[:48] or "PAGE"
    message = f"PDF page {page} layout: {issue}"
    return {
        "id": f"PDF-LAYOUT-{page}-{owner.upper()}-{token}-{digest}",
        "severity": "blocker",
        "category": "visual_layout",
        "label": label,
        "message": message,
        "plain_message": message,
        "remediation": (
            "Repair typography and spacing in the editable figure source, re-render, "
            "and recompile."
            if owner == "figure"
            else "Repair the implicated LaTeX float or table layout and recompile."
        ),
        "owner_node": owner,
        "target_files": targets,
        "asset_ids": assets,
        "page": page,
        "layout_report_path": report,
    }


def review_layout_revision_findings(
    project_path: str,
    state_data: dict[str, Any],
) -> list[dict[str, Any]]:
    root = Path(project_path).expanduser().resolve()
    selected = _report(root, state_data)
    if selected is None:
        return []
    report, report_path = selected
    pages = [item for item in report.get("pages") or [] if isinstance(item, dict)]
    paper = root / "paper"
    labels = _aux_labels(paper)
    figures = _entries(root / "figures" / "FIGURE_MANIFEST.json", "figures")
    tables = _entries(paper / "tables" / "TABLE_MANIFEST.json", "tables")
    sources = _tex_sources(paper)
    findings = []
    for page in pages:
        number = int(page.get("page") or 0)
        for raw in page.get("possible_layout_findings") or []:
            issue = " ".join(str(raw or "").split())
            if not any(marker in issue.casefold() for marker in MARKERS):
                continue
            for label in labels.get(number) or [""]:
                owner, targets, assets = _targets(
                    root,
                    paper,
                    label,
                    figures,
                    tables,
                    sources,
                )
                findings.append(
                    _layout_finding(
                        number,
                        issue,
                        label,
                        owner,
                        targets,
                        assets,
                        _relative(root, report_path),
                    )
                )
    return findings
