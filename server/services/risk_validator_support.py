"""Focused reusable facts for node risk stage validators."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .risk_artifact_support import _json, _relative, _sha256
from .risk_constants import (
    CONDITIONAL_SUPPORT_RE, CURRENT_METHOD_RE, NEGATED_SUPPORT_RE,
    PENDING_RE, PLACEHOLDER_RE, PROSPECTIVE_RE,
    SUPPORTED_RE,
)

def _declared_research_direction(root: Path, options: dict[str, Any]) -> str:
    for key in ("research_direction", "direction"):
        value = str(options.get(key) or "").strip()
        if value:
            return value
    contract, _ = _json(root / ".merak" / "RESEARCH_WORKFLOW_CONTRACT.json")
    if isinstance(contract, dict) and str(contract.get("direction") or "").strip():
        return str(contract["direction"]).strip()
    memory, _ = _json(root / ".merak" / "memory.json")
    if isinstance(memory, dict):
        return str(memory.get("research_direction") or "").strip()
    return ""


def _semantic_anchor_terms(value: str) -> set[str]:
    stop = {
        "a", "an", "and", "for", "in", "of", "on", "the", "to", "with",
        "analysis", "approach", "data", "dataset", "deep", "error",
        "foundation", "framework", "learning", "method", "methods", "model",
        "models", "neural", "performance", "research", "study", "system", "task",
        "方法", "模型", "研究", "系统", "任务",
    }
    lowered = str(value or "").casefold()
    terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{1,}", lowered)
        if token not in stop
    }
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        if chunk not in stop:
            terms.add(chunk)
        terms.update(
            chunk[index:index + 2]
            for index in range(len(chunk) - 1)
            if chunk[index:index + 2] not in stop
        )
    return terms


def _direction_has_semantic_overlap(
    root: Path,
    options: dict[str, Any],
    artifact_text: str,
) -> tuple[bool, str]:
    direction = _declared_research_direction(root, options)
    direction_terms = _semantic_anchor_terms(direction)
    if not direction or not direction_terms:
        return True, direction
    artifact_terms = _semantic_anchor_terms(artifact_text)
    return bool(direction_terms & artifact_terms), direction


def _simulation_manifest_semantic_hash(payload: dict[str, Any]) -> str:
    """Hash only scientific simulation-manifest fields.

    Kept as a lazy import to avoid coupling service import order; this helper
    also makes unsupported raw-byte bindings explicit.
    """
    from .paper_artifacts import simulation_manifest_semantic_hash

    return simulation_manifest_semantic_hash(payload)


def _newest_mtime(paths: list[Path]) -> float:
    values: list[float] = []
    for path in paths:
        try:
            if path.is_file():
                values.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(values, default=0.0)


def _artifact_files(path: Path, suffixes: set[str] | None = None) -> list[Path]:
    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        candidates = [item for item in path.rglob("*") if item.is_file()]
    else:
        return []
    if suffixes is None:
        return sorted(candidates)
    normalized = {item.casefold() for item in suffixes}
    return sorted(item for item in candidates if item.suffix.casefold() in normalized)


def _result_data_files(root: Path, *, include_planned: bool = False) -> list[Path]:
    results = root / "experiments" / "results"
    files = _artifact_files(results, {".csv", ".tsv", ".json", ".npz"})
    ignored_names = {
        "analysis_build.json",
        "planned_result_manifest.json",
        "figure_manifest.json",
        "source_repairs.json",
    }
    selected: list[Path] = []
    for path in files:
        relative = _relative(root, path).casefold()
        if path.name.casefold() in ignored_names:
            continue
        if any(
            marker in path.stem.casefold()
            for marker in (
                "execution_status",
                "exp_run_status",
                "deployment_status",
                "code_check",
                "readiness",
                "tracker",
                "manifest",
                "schema",
            )
        ):
            continue
        if not include_planned and any(
            marker in relative for marker in ("/templates/", "planned_", "placeholder", "not_evidence")
        ):
            continue
        selected.append(path)
    return selected


def _executed_result_data_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Return owned evidence tables and deterministic aggregates.

    Failed attempts and unowned historical outputs must not make a completed
    analysis stale. Canonical aggregates remain auditable, but only immutable
    runtime-owned sources participate in the analysis freshness check because
    aggregates are created for the downstream figure stage.
    """
    from .execution_provenance import execution_provenance_service

    proven_relatives = execution_provenance_service.proven_result_sources(
        root,
        suffixes={".csv", ".tsv", ".json", ".npz"},
    )
    proven_paths: list[Path] = []
    aggregate_paths = _artifact_files(
        root / "experiments" / "results" / "aggregates",
        {".csv", ".tsv", ".json", ".npz"},
    )
    ignored_markers = {
        "prediction",
        "per_sample",
        "sample_level",
        "provenance",
        "resolved_config",
    }
    for relative in sorted(proven_relatives):
        path = (root / relative).resolve()
        try:
            path.relative_to((root / "experiments" / "results").resolve())
        except ValueError:
            continue
        if (
            path.is_file()
            and path.suffix.casefold() in {".csv", ".tsv", ".json", ".npz"}
            and not any(marker in path.stem.casefold() for marker in ignored_markers)
        ):
            proven_paths.append(path)
    all_paths = sorted(set(proven_paths) | set(aggregate_paths))
    return all_paths, sorted(set(proven_paths))


def _result_analysis_source_hashes(
    root: Path,
    paths: Iterable[Path],
) -> dict[str, str]:
    """Hash only immutable, runtime-owned inputs used by result analysis."""
    hashes: dict[str, str] = {}
    for path in sorted(set(paths), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        relative = _relative(root, path)
        digest = _sha256(path)
        if relative and digest:
            hashes[relative] = digest
    return hashes


def _hash_mapping_digest(values: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _placeholder_excerpt(text: str) -> str:
    for match in PLACEHOLDER_RE.finditer(text):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 160)
        context = text[start:end]
        if re.search(r"(?:placeholder|占位符)", match.group(0), re.IGNORECASE) and re.search(
            r"(?:not\s+evidence|demo\s+values?|must\s+not|should\s+not|"
            r"不得|不应|不选作|不能.*证据|演示值|占位图|"
            r"planning\s+(?:visualization|figure|asset)|synthetic\s+preview|"
            r"not\s+for\s+submission|仅供(?:规划|预览)|不用于投稿)",
            context,
            re.IGNORECASE,
        ):
            continue
        # A bounded limitation may explicitly enumerate evidence that remains
        # to be supplied. That is substantive scientific prose, not an
        # unfilled authoring template. Keep the exception local to the
        # matched sentence/nearby clause so a real TODO elsewhere is reported.
        if re.search(r"待补充(?:项|的证据|的测量)?", match.group(0), re.IGNORECASE) and re.search(
            r"(?:限制|局限|边界|证据缺口|外部有效性|不能|不得|若|如果|"
            r"limitation|boundary|evidence\s+gap|external\s+validity|"
            r"cannot|must\s+not|if\s+(?:these|those|the))",
            context,
            re.IGNORECASE,
        ):
            continue
        return " ".join(context.split())[:180]
    return ""


def _candidate_sections(text: str) -> list[tuple[str, str]]:
    heading_re = re.compile(r"(?im)^(#{2,4})\s+(.+?)\s*$")
    candidate_re = re.compile(
        r"(?i)^(?:idea|candidate|proposal|候选(?:\s*idea)?|方案)\s*(?:#?\d+|[A-Z]\d*)?\b"
        r"|^\d+\s*[.：:]\s*(?:idea|candidate|proposal|候选|方案)\b"
    )
    matches = [
        match for match in heading_re.finditer(text)
        if candidate_re.search(match.group(2).strip())
    ]
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(2).strip(), text[match.end():end].strip()))
    return sections


def _latex_graphics(text: str) -> list[str]:
    return [
        " ".join(item.split())
        for item in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text)
        if item.strip()
    ]


def _latex_graphic_exists(
    document_dir: Path,
    source_path: Path,
    raw_graphic: str,
    latex_text: str,
) -> bool:
    """Resolve graphics with LaTeX's main-document and graphicspath semantics."""
    search_roots: list[Path] = []

    def add_root(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in search_roots:
            search_roots.append(resolved)

    add_root(document_dir)
    add_root(source_path.parent)
    for block in re.findall(
        r"\\graphicspath\s*\{((?:\{[^{}]*\}\s*)+)\}",
        latex_text,
        flags=re.IGNORECASE,
    ):
        for raw_root in re.findall(r"\{([^{}]*)\}", block):
            if raw_root.strip():
                add_root(document_dir / raw_root.strip())

    raw_path = Path(raw_graphic.strip())
    candidates = [raw_path] if raw_path.is_absolute() else [
        root / raw_path for root in search_roots
    ]
    for candidate in candidates:
        alternatives = [candidate] if candidate.suffix else [
            candidate,
            *(candidate.with_suffix(suffix) for suffix in (".pdf", ".png", ".jpg", ".jpeg")),
        ]
        if any(item.is_file() and item.stat().st_size > 0 for item in alternatives):
            return True
    return False


def _load_csv_columns(path: Path) -> tuple[list[str], int]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
    except (OSError, UnicodeError, csv.Error):
        return [], 0
    return [str(item).strip() for item in header], rows


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _ids(records: Any, key: str = "id") -> list[str]:
    return [str(item.get(key) or "").strip() for item in _dict_list(records) if item.get(key)]


def _bib_entries(text: str) -> list[dict[str, str]]:
    starts = list(re.finditer(r"(?m)^\s*@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,", text))
    entries: list[dict[str, str]] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        body = text[match.start():end]
        field_boundary = r"(?:^|,)\s*"
        year_match = re.search(
            field_boundary + r"year\s*=\s*[\{\"]?\s*(\d{4})",
            body,
            re.IGNORECASE | re.MULTILINE,
        )
        title_match = re.search(
            field_boundary
            + r"title\s*=\s*[\{\"]\s*(.+?)\s*[\}\"]\s*(?:,|$)",
            body,
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        author_match = re.search(
            field_boundary
            + r"author\s*=\s*[\{\"]\s*(.+?)\s*[\}\"]\s*(?:,|$)",
            body,
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )
        entries.append({
            "type": match.group(1).lower(),
            "key": match.group(2).strip(),
            "year": year_match.group(1) if year_match else "",
            "title": " ".join(title_match.group(1).split()) if title_match else "",
            "author": " ".join(author_match.group(1).split()) if author_match else "",
            "traceable": "1" if re.search(
                field_boundary + r"(?:doi|url|eprint|arxiv|isbn)\s*=",
                body,
                re.IGNORECASE | re.MULTILINE,
            ) else "0",
        })
    return entries


def _citation_keys(text: str) -> set[str]:
    from .manuscript_text import citation_keys
    keys = citation_keys(text)
    for raw in re.findall(r"\[@([^\]]+)\]", text):
        keys.update(item.strip().lstrip("@") for item in raw.split(";") if item.strip())
    return keys


def _retained_reference_mentions(
    text: str,
    known_keys: Iterable[str],
) -> set[str]:
    """Count canonical citations plus explicit Markdown mentions of known keys."""
    known = {str(item).strip() for item in known_keys if str(item).strip()}
    mentions = _citation_keys(text)
    for raw in re.findall(r"`([^`\r\n]+)`", text):
        for token in re.split(r"[\s,;]+", raw):
            candidate = token.strip().lstrip("@")
            if candidate in known:
                mentions.add(candidate)
    return mentions


def _inline_bibliography_keys(text: str) -> set[str]:
    return {
        raw.strip()
        for raw in re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", text)
        if raw.strip()
    }


def _unbounded_supported_claims(
    text: str,
    *,
    current_method_only: bool = False,
) -> list[dict[str, Any]]:
    """Locate empirical support claims that lack negation or a local boundary."""
    hits: list[dict[str, Any]] = []
    for paragraph_match in re.finditer(r"(?:^|\n\s*\n)(.*?)(?=\n\s*\n|$)", text, re.DOTALL):
        paragraph = paragraph_match.group(1)
        paragraph_offset = paragraph_match.start(1)
        for match in SUPPORTED_RE.finditer(paragraph):
            left_boundaries = [
                paragraph.rfind(marker, 0, match.start())
                for marker in (".", "!", "?", "\n")
            ]
            sentence_start = max(left_boundaries) + 1
            right_boundaries = [
                index
                for marker in (".", "!", "?", "\n")
                if (index := paragraph.find(marker, match.end())) >= 0
            ]
            sentence_end = min(right_boundaries) + 1 if right_boundaries else len(paragraph)
            context = paragraph[sentence_start:sentence_end]
            relative_match_start = max(0, match.start() - sentence_start)
            conditional_prefix = context[:relative_match_start]
            if NEGATED_SUPPORT_RE.search(context):
                continue
            if CONDITIONAL_SUPPORT_RE.search(conditional_prefix):
                continue
            if PENDING_RE.search(paragraph) and PROSPECTIVE_RE.search(context):
                continue
            if current_method_only and not CURRENT_METHOD_RE.search(paragraph):
                continue
            hits.append({
                "match": match.group(0),
                "start": paragraph_offset + match.start(),
                "end": paragraph_offset + match.end(),
                "context": " ".join(context.split()),
            })
    return hits


def _has_unbounded_supported_claim(
    text: str,
    *,
    current_method_only: bool = False,
) -> bool:
    """Find a non-negated empirical claim without a local prospective boundary."""
    return bool(
        _unbounded_supported_claims(
            text,
            current_method_only=current_method_only,
        )
    )
