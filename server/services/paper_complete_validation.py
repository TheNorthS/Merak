"""Cross-section validation for a complete staged manuscript."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Pattern

from .manuscript_text import (
    bib_keys,
    citation_keys,
    read_text,
    reference_keys,
    strip_tex,
    word_count,
)
from .simulation_policy import (
    FORBIDDEN_RENDERED_SIMULATION_LABELS,
    rendered_mode_framing_hits_outside_end_disclosure,
    simulation_disclosure_report,
)


def validate_complete_draft(
    *,
    paths: dict[str, Path],
    specs: Iterable[Any],
    require_main: bool,
    superiority_pattern: Pattern[str],
    section_review: Callable[..., dict[str, Any]],
    front_matter_review: Callable[[dict[str, Path], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    contracts = _read_json(paths["contracts"])
    evidence = dict(contracts.get("evidence") or {})
    profile = _read_json(paths["profile"]) or dict(contracts.get("manuscript_profile") or {})
    mechanisms = [str(item) for item in contracts.get("required_mechanisms", [])
                  if str(item).strip()]
    specs = tuple(specs)
    sections = {spec.id: read_text(paths["sections"] / spec.filename) for spec in specs}
    sections["front_matter"] = read_text(paths["sections"] / "00_abstract.tex")
    issues, reviews = _section_issues(
        paths, specs, sections, evidence, mechanisms,
        section_review, front_matter_review,
    )
    try:
        fragments = _included_fragments(paths, specs)
    except ValueError as error:
        issues.append(f"selected scientific asset assembly failed: {error}")
        fragments = ""
    combined = "\n".join(sections.values()) + fragments
    labels, refs, citations = _reference_issues(paths, combined, issues)
    main_words = _profile_issues(paths, sections, specs, profile, citations, issues)
    _duplicate_paragraph_issues(sections, issues)
    _evidence_boundary_issues(sections, evidence, superiority_pattern, issues)
    if require_main:
        _main_document_issues(paths, specs, evidence, issues)
    from .paper_consistency_findings import complete_consistency_findings

    from .paper_prose_references import checked_asset_prose_references

    findings = complete_consistency_findings(paths, specs, sections, labels, refs, citations, profile,
        prose_refs=checked_asset_prose_references(paths["root"], combined, issues))
    from .paper_model_consistency_findings import model_consistency_findings
    from .manuscript_text import final_consistency_verdict

    findings.extend(model_consistency_findings(paths, specs))
    if final_consistency_verdict(read_text(paths["cross_review"])) == "FAIL":
        issues.append("cross-section reviewer recorded FAIL")
    return {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "section_reviews": reviews,
        "front_matter": reviews["front_matter"],
        "citation_keys": sorted(citations),
        "labels": sorted(labels),
        "references": sorted(refs),
        "evidence_mode": evidence.get("mode", "design_only"),
        "submission_eligible": bool(evidence.get("submission_eligible")),
        "main_text_words": main_words,
        "manuscript_profile": profile,
        "findings": findings,
        "target_files": sorted({target for item in findings for target in item["target_files"]}),
    }


def _read_json(path: Path) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _section_issues(
    paths: dict[str, Path], specs: tuple[Any, ...], sections: dict[str, str],
    evidence: dict[str, Any], mechanisms: list[str],
    section_review: Callable[..., dict[str, Any]],
    front_review: Callable[[dict[str, Path], dict[str, Any]], dict[str, Any]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    issues: list[str] = []
    reviews: dict[str, dict[str, Any]] = {}
    for spec in specs:
        review = section_review(
            paths["root"], spec, evidence, mechanisms if spec.id == "method" else []
        )
        reviews[spec.id] = review
        issues.extend(f"{spec.id}: {item}" for item in review["issues"])
    front = front_review(paths, evidence)
    reviews["front_matter"] = front
    issues.extend(f"front_matter: {item}" for item in front["issues"])
    return issues, reviews


def _included_fragments(paths: dict[str, Path], specs: tuple[Any, ...]) -> str:
    from .latex_bundle import _reachable_sources, _tex_text
    from .paper_asset_placement import section_asset_placements

    authored = [(Path(spec.filename).stem, paths["sections"] / spec.filename) for spec in specs]
    primary = {path.resolve() for _name, path in authored}
    sources = {source for _name, path in authored for source in
               _reachable_sources(path, paths["paper"].resolve(), paths["root"].resolve())}
    fragments = [_tex_text(path) for path in sorted(sources - primary)]
    fragments.extend(item.text for item in section_asset_placements(paths["root"], authored))
    return "\n" + "\n".join(fragments) if fragments else ""


def _reference_issues(
    paths: dict[str, Path], combined: str, issues: list[str]
) -> tuple[set[str], set[str], set[str]]:
    labels = set(re.findall(r"\\label\{([^}]+)\}", combined))
    refs = reference_keys(combined)
    if refs - labels:
        issues.append("undefined references: " + ", ".join(sorted(refs - labels)))
    from .paper_prose_references import checked_asset_prose_references

    prose_refs = checked_asset_prose_references(paths.get("root", paths["paper"].parent), combined, issues)
    unreferenced = sorted(
        label for label in labels
        if label.startswith(("fig:", "tab:")) and label not in prose_refs
        and not (label.casefold().endswith("-continued")
                 and label[:-len("-continued")] in prose_refs)
    )
    if unreferenced:
        issues.append(
            "scientific assets included but never referenced in prose: "
            + ", ".join(unreferenced)
        )
    citations = citation_keys(combined)
    unknown = sorted(citations - bib_keys(paths["paper"] / "references.bib"))
    if unknown:
        issues.append("unknown citation keys: " + ", ".join(unknown))
    return labels, refs, citations


def _profile_issues(
    paths: dict[str, Path], sections: dict[str, str], specs: tuple[Any, ...],
    profile: dict[str, Any], citations: set[str], issues: list[str],
) -> int:
    words = sum(word_count(sections.get(spec.id, "")) for spec in specs)
    word_range = list(profile.get("main_text_words") or [])
    if len(word_range) == 2:
        minimum, maximum = int(word_range[0]), int(word_range[1])
        if words < minimum:
            issues.append(
                f"main text is too thin for the selected profile ({words} words; minimum {minimum})"
            )
        if words > maximum:
            issues.append(
                f"main text is too verbose for the selected profile ({words} words; maximum {maximum})"
            )
    bibliography = bib_keys(paths["paper"] / "references.bib")
    minimum_bib = int(profile.get("minimum_unique_bibliography_entries") or 0)
    minimum_citations = int(profile.get("minimum_unique_citations") or 0)
    if len(bibliography) < minimum_bib:
        issues.append(
            f"verified bibliography is too small for the selected profile ({len(bibliography)} entries; minimum {minimum_bib})"
        )
    if len(citations) < minimum_citations:
        issues.append(
            f"manuscript literature coverage is too narrow for the selected profile ({len(citations)} unique citations; minimum {minimum_citations})"
        )
    return words


def _duplicate_paragraph_issues(
    sections: dict[str, str], issues: list[str]
) -> None:
    paragraphs: list[tuple[str, set[str]]] = []
    for section_id, text in sections.items():
        for paragraph in re.split(r"\n\s*\n", strip_tex(text)):
            tokens = set(" ".join(paragraph.casefold().split()).split())
            if len(tokens) >= 30:
                paragraphs.append((section_id, tokens))
    for index, (left_id, left) in enumerate(paragraphs):
        for right_id, right in paragraphs[index + 1:]:
            union = left | right
            if left_id != right_id and union and len(left & right) / len(union) >= 0.82:
                issues.append(f"near-duplicate paragraph across {left_id} and {right_id}")
                break


def _evidence_boundary_issues(
    sections: dict[str, str], evidence: dict[str, Any],
    superiority: Pattern[str], issues: list[str],
) -> None:
    if evidence.get("submission_eligible") or evidence.get("mode") == "synthetic_preview":
        return
    for section_id in ("front_matter", "results", "discussion", "conclusion"):
        if superiority.search(sections.get(section_id, "")):
            issues.append(f"{section_id} claims superiority without eligible evidence")


def _main_document_issues(
    paths: dict[str, Path], specs: tuple[Any, ...],
    evidence: dict[str, Any], issues: list[str],
) -> None:
    main = read_text(paths["main"])
    if "\\documentclass" not in main or "\\end{document}" not in main:
        issues.append("main.tex is missing or incomplete")
    expected = {"sections/00_abstract", *(f"sections/{Path(spec.filename).stem}" for spec in specs)}
    actual = set(re.findall(r"\\input\{([^}]+)\}", main))
    if 'derived-figures/tex/' in main:
        from .paper_print_projection import original_print_inputs
        try:
            actual.update(original_print_inputs(paths['root']))
        except ValueError as error:
            issues.append(str(error))
    if expected - actual:
        from .paper_appendix_assembly import original_assembly_inputs
        if (paths["paper"] / "assembly-layout/PLACEMENT.json").is_file():
            try:
                actual.update(original_assembly_inputs(paths["root"]))
            except (ValueError, OSError) as error:
                issues.append(str(error))
    if expected - actual:
        issues.append("main.tex omits sections: " + ", ".join(sorted(expected - actual)))
    if evidence.get("mode") != "synthetic_preview":
        return
    if any(marker.casefold() in main.casefold() for marker in FORBIDDEN_RENDERED_SIMULATION_LABELS):
        issues.append("main.tex contains a forbidden simulation warning or preview label")
    disclosure = simulation_disclosure_report(main)
    if (disclosure.get("count") != 1 or disclosure.get("end_matter_count") != 1
            or disclosure.get("outside_end_matter_count") != 0):
        issues.append(
            "main.tex must contain exactly one simulation disclosure after the Conclusion and before the bibliography"
        )
    framing = rendered_mode_framing_hits_outside_end_disclosure(main)
    if framing:
        issues.append(
            "main.tex exposes simulation or evidence-mode framing outside the final disclosure: "
            + ", ".join(framing[:6])
        )
