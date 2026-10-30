"""Local validators for bounded manuscript stages."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Pattern

from .manuscript_language import (
    find_internal_contract_references,
    find_visible_code_artifact_references,
)
from .manuscript_text import citation_keys, read_text, word_count
from .simulation_policy import rendered_mode_framing_hits, visible_latex_prose


def invocation_contract(stage_id: str, output_paths: Iterable[Path]) -> str:
    targets = list(output_paths)
    outputs = "\n".join(f"- {path}" for path in targets)
    existing = "\n".join(f"- {path}" for path in targets if path.exists()) or "- (none)"
    missing = "\n".join(f"- {path}" for path in targets if not path.exists()) or "- (none)"
    return f"""Current stage: {stage_id}
Permitted write targets:
{outputs}

Targets that already exist and may be read before editing:
{existing}

Targets that do not exist yet:
{missing}

Read other artifacts as evidence, but write only the targets above. Do not
initialize, clean, back up, or regenerate the whole paper. Do not invoke
another skill or agent. Do not call Read on a target listed as not existing
before its first Write; create it directly, then re-read it. Finish by
re-reading every target that you changed. A prose answer without the required
file write is incomplete."""


def validate_blueprint(path: Path) -> dict[str, Any]:
    text = read_text(path)
    headings = (
        "research question", "closest-work gap", "one-sentence contribution",
        "mechanism logic", "claims and required evidence",
        "alternative explanations", "section narrative", "evidence boundary",
    )
    lower = text.casefold()
    issues = [
        f"blueprint missing heading: {heading}" for heading in headings
        if heading not in lower
    ]
    markdown_headings = [
        re.sub(r"\s+", " ", match.group(1).strip()).casefold()
        for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    ]
    for heading in headings:
        occurrences = markdown_headings.count(heading)
        if occurrences > 1:
            issues.append(
                f"blueprint duplicates heading: {heading} ({occurrences} occurrences)"
            )
    words = word_count(text)
    if words < 700:
        issues.append(f"blueprint too shallow ({words} words; minimum 700)")
    return {"passed": not issues, "issues": issues, "words": words}


def validate_front_matter(
    paths: dict[str, Path], evidence: dict[str, Any], *,
    admin_pattern: Pattern[str], superiority_pattern: Pattern[str],
) -> dict[str, Any]:
    title = " ".join(read_text(paths["title"]).split())
    abstract = read_text(paths["sections"] / "00_abstract.tex")
    words = word_count(abstract)
    issues = _front_matter_content_issues(
        title, abstract, words, evidence, superiority_pattern
    )
    from .manuscript_math_syntax import math_delimiter_issues
    issues.extend(math_delimiter_issues(abstract))
    combined = title + "\n" + abstract
    if admin_pattern.search(visible_latex_prose(combined)) or find_internal_contract_references(combined):
        issues.append("front matter exposes workflow or contract metadata")
    code_artifacts = find_visible_code_artifact_references(combined)
    if code_artifacts:
        issues.append(
            "front matter exposes implementation symbols or artifact paths: "
            + ", ".join(code_artifacts[:6])
        )
    if evidence.get("mode") == "synthetic_preview":
        hits = rendered_mode_framing_hits(combined)
        if hits:
            issues.append(
                "front matter repeats simulation, preview, draft, or evidence-mode "
                "framing reserved for the end disclosure: " + ", ".join(hits[:6])
            )
    return {"passed": not issues, "issues": issues, "words": words, "title": title}


def _front_matter_content_issues(
    title: str, abstract: str, words: int, evidence: dict[str, Any],
    superiority_pattern: Pattern[str],
) -> list[str]:
    issues: list[str] = []
    if not 12 <= len(title) <= 180:
        issues.append("title must be specific and 12--180 characters")
    if title.casefold() in {"paper title", "untitled", "selected idea"}:
        issues.append("title is generic")
    if not 150 <= words <= 250:
        issues.append(f"abstract has {words} words; required range is 150--250")
    if citation_keys(abstract):
        issues.append("abstract must not contain citations")
    eligible = evidence.get("submission_eligible")
    simulation = evidence.get("mode") == "synthetic_preview"
    if not eligible and not simulation and superiority_pattern.search(abstract):
        issues.append("abstract claims superiority without eligible evidence")
    if not eligible and not simulation and not re.search(
        r"\b(?:protocol|preregister|pre-register|planned evaluation|study design)\b",
        abstract, flags=re.IGNORECASE,
    ):
        issues.append("non-empirical abstract does not disclose protocol/draft status")
    return issues
