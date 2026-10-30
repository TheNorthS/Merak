"""Pure resolution of revision findings into canonical artifact targets."""

from __future__ import annotations

import re
from typing import Any, Iterable


_PATH_KEYS = frozenset({
    "path", "paths", "file", "files", "target", "targets", "target_file",
    "target_files", "artifact", "artifacts", "artifact_path",
    "artifact_paths", "evidence", "report_path", "source_path",
    "output_path", "data_path",
})
_PATH_SUFFIXES = (
    ".bib", ".csv", ".drawio", ".json", ".jsonl", ".md", ".mmd",
    ".pdf", ".png", ".py", ".svg", ".tex", ".toml", ".tsv",
    ".txt", ".yaml", ".yml",
)
_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:[A-Za-z]:/)?(?:[^\s:;,；，()\[\]{}]+/)+"
    r"[^\s:;,；，()\[\]{}]+\.(?:bib|csv|drawio|jsonl?|md|mmd|pdf|png|py|svg|tex|toml|tsv|txt|ya?ml))",
    re.IGNORECASE,
)
_ASSET_KEYS = frozenset({
    "asset_id", "asset_ids", "semantic_key", "semantic_keys", "figure_id",
    "figure_ids", "table_id", "table_ids",
})
_MANUSCRIPT_MARKERS = (
    "staged-paper:", "staged paper", "staged manuscript",
    "simulation manuscript", "manuscript quality contract", "manuscript must",
)
_PAPER_LABEL_TARGETS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("title and abstract", "front matter", "front_matter"), (
        "paper/TITLE.txt", "paper/sections/00_abstract.tex",
    )),
    (("abstract",), ("paper/sections/00_abstract.tex",)),
    (("introduction",), ("paper/sections/01_introduction.tex",)),
    (("related work", "related_work"), ("paper/sections/02_related_work.tex",)),
    (("method", "methods"), ("paper/sections/03_method.tex",)),
    (("experimental setup", "experiments"), ("paper/sections/04_experiments.tex",)),
    ((
        "results or evaluation protocol", "evaluation protocol and planned analyses",
        "evaluation protocol", "results",
    ), ("paper/sections/05_results.tex",)),
    (("discussion",), ("paper/sections/06_discussion.tex",)),
    (("limitations",), ("paper/sections/07_limitations.tex",)),
    (("conclusion",), ("paper/sections/08_conclusion.tex",)),
    (("cross-section consistency", "cross section consistency", "consistency"), (
        "paper/CROSS_SECTION_REVIEW.md",
    )),
    (("venue-aware manuscript assembly", "manuscript assembly", "assembly"), (
        "paper/main.tex",
    )),
)


def _walk_values(raw: Any, accepted_keys: frozenset[str]) -> Iterable[Any]:
    if isinstance(raw, dict):
        for key, value in raw.items():
            if str(key).casefold() in accepted_keys:
                yield from _walk_values(value, accepted_keys)
    elif isinstance(raw, (list, tuple, set)):
        for value in raw:
            yield from _walk_values(value, accepted_keys)
    else:
        yield raw


def _canonical_revision_path(candidate: str) -> str:
    clean = candidate.strip(" `\"'").rstrip(".,；，")
    paper_relative = clean.replace("\\", "/")
    if paper_relative.startswith("./"):
        paper_relative = paper_relative[2:]
    if paper_relative.casefold().startswith(("tables/", "sections/")) or (
        paper_relative.casefold() in {"main.tex", "references.bib"}
    ):
        return "paper/" + paper_relative
    return clean


def revision_target_files(*values: Any) -> list[str]:
    """Extract safe canonical artifact paths from heterogeneous findings."""
    found: list[str] = []
    for value in values:
        for raw in _walk_values(value, _PATH_KEYS):
            text = str(raw or "").strip()
            if not text:
                continue
            normalized = text.replace("\\", "/")
            candidates = _PATH_PATTERN.findall(normalized)
            if (
                normalized.casefold().endswith(_PATH_SUFFIXES)
                and not candidates
                and not re.search(r"[；，]", normalized)
            ):
                candidates.append(normalized.strip(" `\"'"))
            for candidate in candidates:
                clean = _canonical_revision_path(candidate)
                comparable = "/" + clean.replace("\\", "/").lstrip("/").casefold()
                if "/.merak/quality/" not in comparable and clean not in found:
                    found.append(clean)
    return found[:40]


def revision_asset_ids(*values: Any) -> list[str]:
    """Extract stable semantic figure and table identifiers."""
    found: list[str] = []
    pattern = re.compile(
        r"(?:not rendered|required scientific (?:figure|table)|semantic (?:asset|key))\s*:\s*"
        r"([A-Za-z][A-Za-z0-9_-]{2,80})",
        re.IGNORECASE,
    )
    for value in values:
        for raw in _walk_values(value, _ASSET_KEYS):
            text = str(raw or "").strip()
            candidates = pattern.findall(text)
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,80}", text):
                candidates.append(text)
            for candidate in candidates:
                if candidate not in found:
                    found.append(candidate)
    return found[:30]


def stable_revision_finding_text(value: Any) -> str:
    """Remove transport and run churn before deriving a finding identity."""
    text = " ".join(str(value or "").split()).casefold()
    substitutions = (
        (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", "<uuid>"),
        (r"\b(?:sha(?:-?256)?\s*[:=]?\s*)?[0-9a-f]{40,64}\b", "<digest>"),
        (r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b", "<timestamp>"),
        (r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b", "<time>"),
        (r"\b(?:round|revision|attempt|cycle)\s*[-#:]?\s*\d+\b", "<iteration>"),
        (r"(?<=_)round\d+(?=\.)", "round<n>"),
        (r"\b(?:updated_at|evaluated_at|created_at|generated_at)\s*[:=]\s*[^,;]+", "<volatile-time-field>"),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _asset_reference_targets(text: str) -> list[str]:
    if not any(marker in text for marker in (
        "never referenced in prose", "referenced but not interpreted in prose",
    )):
        return []
    targets: list[str] = []
    for label in re.findall(r"\b(?:fig|tab):[a-z0-9][a-z0-9:._-]*", text):
        if any(token in label for token in ("method", "architecture", "component")):
            candidate = "paper/sections/03_method.tex"
        elif any(token in label for token in ("evaluation-design", "study-design", "protocol")):
            candidate = "paper/sections/04_experiments.tex"
        elif any(token in label for token in (
            "result", "claim-evidence", "comparison", "ablation", "training",
            "robust", "error", "calibrat", "efficien", "trade-off", "tradeoff",
            "preview",
        )):
            candidate = "paper/sections/05_results.tex"
        else:
            continue
        if candidate not in targets:
            targets.append(candidate)
    return targets or [
        "paper/sections/03_method.tex", "paper/sections/04_experiments.tex",
        "paper/sections/05_results.tex", "paper/sections/06_discussion.tex",
    ]


def _paper_stage_scope(text: str) -> str:
    staged = re.search(r"staged-paper\s*:\s*", text)
    if staged:
        return text[staged.end():]
    marker = re.search("|".join(re.escape(item) for item in _MANUSCRIPT_MARKERS), text)
    return text[marker.end():] if marker else text


def _labeled_paper_targets(scope: str) -> list[str]:
    target_by_label = {
        label: targets
        for labels, targets in _PAPER_LABEL_TARGETS
        for label in labels
    }
    labels = "|".join(re.escape(label) for label in sorted(target_by_label, key=len, reverse=True))
    failure = r"(?:has|have|is|are|lacks?|omits?|fails?|failed|must|needs?|requires?|contains?|does|do|should|cannot)\b"
    matcher = re.compile(
        rf"(?:^|[;:])\s*(?P<label>{labels})(?=\s*(?::|[-\u2013\u2014]|{failure}))",
        re.IGNORECASE,
    )
    targets: list[str] = []
    for match in matcher.finditer(scope):
        for target in target_by_label[match.group("label").casefold()]:
            if target not in targets:
                targets.append(target)
    return targets


def paper_revision_fallback_targets(message: Any) -> list[str]:
    """Recover paper targets from a flattened manuscript failure."""
    text = " ".join(str(message or "").split()).casefold()
    if not text or not any(marker in text for marker in _MANUSCRIPT_MARKERS):
        return []
    asset_targets = _asset_reference_targets(text)
    if asset_targets:
        return asset_targets
    scope = _paper_stage_scope(text)
    targets = _labeled_paper_targets(scope)
    if re.search(r"\bmethods?\s*(?:/|and)\s*experimental setup\b", scope):
        targets.extend(target for target in (
            "paper/sections/03_method.tex", "paper/sections/04_experiments.tex",
        ) if target not in targets)
    if not targets and "benchmark provenance" in scope:
        targets = ["paper/sections/03_method.tex", "paper/sections/04_experiments.tex"]
    return targets or ["paper/main.tex"]
