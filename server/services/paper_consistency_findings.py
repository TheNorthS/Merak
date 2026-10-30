"""Attribute cross-section defects to their real, bounded manuscript authors.

This read-only policy never invents table labels, citations or scholarly prose.
Available bibliography keys are evidence to inspect, not recommendations to cite.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from .manuscript_text import bib_keys, citation_keys, reference_keys


def _finding(
    category: str, key: str, stage: str, target: str, message: str,
    remediation: str, **details: Any,
) -> dict[str, Any]:
    signature = hashlib.sha256(f"{category}:{key}:{stage}:{target}".encode()).hexdigest()[:12]
    return {
        "id": f"PAPER-CONSISTENCY-{category.upper()}-{signature.upper()}",
        "severity": "blocker", "category": category, "owner_node": "paper", "upstream_node": "paper",
        "stage_id": stage, "target_files": [target], "legal_write_targets": [target],
        "message": f"{message}; revise {target}", "plain_message": message,
        "remediation": remediation, **details,
    }


def _authored_sources(paths: dict[str, Path], specs: Iterable[Any]) -> dict[str, str]:
    return {**{item.id: f"paper/sections/{item.filename}" for item in specs},
            "front_matter": "paper/sections/00_abstract.tex"}


def complete_consistency_findings(
    paths: dict[str, Path], specs: Iterable[Any], sections: dict[str, str],
    labels: set[str], refs: set[str], citations: set[str], profile: dict[str, Any],
    *, prose_refs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return legal author targets for references and substantive literature repair."""
    specs = tuple(specs)
    sources = _authored_sources(paths, specs)
    findings = []
    from .paper_length_findings import length_findings
    findings.extend(length_findings(specs, sections, profile))
    from .paper_table_ownership import registered_table_copy_issues
    for stage, text in sections.items():
        for issue in registered_table_copy_issues(paths["root"], text):
            if stage in sources:
                findings.append(_finding("registered_table_copy", issue, stage, sources[stage], issue,
                    "Repair only the section-authored copy; preserve the canonical registered table and its source data.",
                    validation_issue=issue))
    findings.extend(_unreferenced_asset_findings(paths, specs, labels, refs if prose_refs is None else prose_refs))
    missing = refs - labels
    ref_issue = "undefined references: " + ", ".join(sorted(missing))
    for key in sorted(missing):
        for stage, text in sections.items():
            if stage not in sources or key not in reference_keys(text):
                continue
            findings.append(_finding(
                "undefined_reference", key, stage, sources[stage], f"undefined reference: {key}",
                "Reconcile this section's scientific interpretation with current registered assets and their exact labels; "
                "do not create an unplanned table or label merely to satisfy the reference.",
                reference_key=key, validation_issue=ref_issue, available_asset_labels=sorted(labels),
                evidence_paths=["paper/AUTHORING_ASSET_MANIFEST.json", "paper/tables/TABLE_MANIFEST.json"],
            ))
    bibliography = bib_keys(paths["paper"] / "references.bib")
    unknown = citations - bibliography
    for key in sorted(unknown):
        for stage, text in sections.items():
            if stage in sources and key in citation_keys(text):
                findings.append(_finding(
                    "unknown_citation", key, stage, sources[stage], f"unknown citation key: {key}",
                    "Check the scientific claim against verified literature and replace or remove only unsupported citation usage; never invent a bibliography entry.",
                    citation_key=key, validation_issue="unknown citation keys: " + ", ".join(sorted(unknown)),
                    evidence_paths=["paper/references.bib", "literature/survey.md"],
                ))
    findings.extend(_literature_deficit_findings(sources, bibliography, citations, profile))
    return findings


def _unreferenced_asset_findings(
    paths: dict[str, Path], specs: Iterable[Any], labels: set[str], refs: set[str],
) -> list[dict[str, Any]]:
    from .paper_asset_author_ownership import unreferenced_asset_author

    unreferenced = sorted(label for label in labels if label.startswith(("fig:", "tab:"))
        and label not in refs and not (label.casefold().endswith("-continued")
        and label[:-len("-continued")] in refs))
    aggregate = "scientific assets included but never referenced in prose: " + ", ".join(unreferenced)
    findings = []
    for label in unreferenced:
        stage, target = unreferenced_asset_author(paths["root"], label, specs)
        singular = "scientific asset is included but never referenced in prose: " + label
        findings.append(_finding(
            "unreferenced_asset", label, stage, target, singular,
            "Interpret this existing source-bound scientific asset in this section's prose using its exact "
            "registered reference. Preserve its label, graphic/table, scientific scope and every numerical value; "
            "do not insert a dummy reference, remove the asset, or change a review report to bypass the finding.",
            reference_key=label, validation_issue=aggregate,
            validation_issue_aliases=[singular, "scientific assets included but never referenced in prose: " + label],
            evidence_paths=[target, "figures/FIGURE_MANIFEST.json", "paper/tables/TABLE_MANIFEST.json"],
        ))
    return findings


def _literature_deficit_findings(
    sources: dict[str, str], bibliography: set[str], citations: set[str], profile: dict[str, Any],
) -> list[dict[str, Any]]:
    minimum = int(profile.get("minimum_unique_citations") or 0)
    current = len(citations & bibliography)
    if current >= minimum:
        return []
    stage = "related_work" if "related_work" in sources else "introduction" if "introduction" in sources else ""
    if not stage:
        return []
    issue = f"manuscript literature coverage is too narrow for the selected profile ({len(citations)} unique citations; minimum {minimum})"
    return [_finding(
        "literature_coverage", "verified-unique-citations", stage, sources[stage],
        f"substantive verified literature coverage is insufficient ({current} unique citations; minimum {minimum})",
        "Strengthen the closest-work and assumption-level comparison using only relevant verified sources; "
        "read the source evidence before citing. The unused-key inventory is not a relevance recommendation, "
        "and adding unrelated citations or a cosmetic citation list cannot satisfy scientific authorship.",
        validation_issue=issue, current_verified_citations=current, required_unique_citations=minimum,
        needed_unique_citations=minimum - current,
        available_unused_verified_keys=sorted(bibliography - citations),
        candidate_inventory_is_relevance_recommendation=False,
        evidence_paths=["paper/references.bib", "literature/survey.md"],
    )]


def merge_complete_findings(
    active: list[dict[str, Any]], complete: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Precise author obligations replace only matching generic consistency issues."""
    covered = {value for item in complete for value in _finding_issue_aliases(item)}
    retained = [item for item in active if not (
        item.get("stage_id") == "consistency"
        and any(issue in str(item.get("message") or "") for issue in covered)
    )]
    unique = {str(item.get("id") or ""): item for item in [*retained, *complete]}
    return list(unique.values())


def implicated_consistency_findings(
    targeted: list[str], findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recognize current typed author causes after a gate wrapped their issue text."""
    import re
    explicit = {match.replace('\\', '/').casefold() for issue in targeted
                for match in re.findall(r'(?i)Target artifact:\s*(paper[\\/][A-Za-z0-9_.\\/-]+\.[A-Za-z0-9]+)', issue)}
    return [item for item in findings if isinstance(item, dict)
        and (not explicit or explicit.intersection(str(path).replace('\\', '/').casefold()
                                                   for path in item.get('target_files', []))) and any(
        value in issue
        for issue in targeted for value in _finding_issue_aliases(item)
        if value
    )]


def _finding_issue_aliases(item: dict[str, Any]) -> list[str]:
    return [str(value).strip() for value in (
        item.get("validation_issue"), item.get("message"), item.get("plain_message"),
        *(item.get("validation_issue_aliases") or [])) if str(value or "").strip()]
