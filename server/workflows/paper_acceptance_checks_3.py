"""Check mechanism coverage and final manuscript contract conditions.

The coordinator combines these findings with the other paper checks before
acceptance; a section passing alone cannot certify the entire manuscript."""

# ruff: noqa: F401
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from ..utils.atomic_write import atomic_write_json

from ..services.figure_artifacts import figure_artifact_registry
from ..services.manuscript_language import (
    find_internal_contract_references,
    find_visible_code_artifact_references,
)
from ..services.paper_drafting import (
    citation_keys as parsed_citation_keys,
    reference_keys,
    word_count,
)
from ..services.paper_profile import (
    FIGURE_ROLE_ALIASES,
    TABLE_ROLE_ALIASES,
    canonical_roles,
    paper_profile_service,
)
from ..services.simulation_policy import (
    FORBIDDEN_RENDERED_SIMULATION_LABELS,
    rendered_mode_framing_hits_outside_end_disclosure,
    simulation_disclosure_report,
    strip_latex_comments,
    visible_latex_prose,
    visible_watermark_commands,
)
from .paper_acceptance_context import PaperGateComplete, PaperGateContext
from .paper_acceptance_source import expand_tex_source, resolve_graphic_path


def synthetic_asset_sources(ctx: PaperGateContext) -> None:
    if ctx.evidence_mode == "synthetic_preview":
        verified_synthetic_ids = {
            str(item.get("id") or "") for item in ctx.structural_preview_assets
        }
        missing_verified_ids = sorted(
            ctx.expected_synthetic_ids - verified_synthetic_ids
        )
        if missing_verified_ids:
            expected_by_id = {
                str(item.get("id") or "").strip(): item
                for item in ctx.asset_plan.get("assets", [])
                if isinstance(item, dict)
            }
            not_yet_in_manuscript = []
            invalid_bindings = []
            for asset_id in missing_verified_ids:
                label = str(
                    (expected_by_id.get(asset_id) or {}).get("label") or ""
                ).strip()
                if label and label not in ctx.included_labels:
                    not_yet_in_manuscript.append(asset_id)
                else:
                    invalid_bindings.append(asset_id)
            if invalid_bindings:
                ctx.problems.append(
                    "synthetic benchmark figures have invalid or stale manifest/hash binding: "
                    + ", ".join(invalid_bindings)
                )
            if not_yet_in_manuscript and (ctx.paper_root / "main.tex").is_file():
                ctx.problems.append(
                    "synthetic benchmark figures are valid but not included in the current manuscript: "
                    + ", ".join(not_yet_in_manuscript)
                )


def collect_existing_figure_keys(ctx: PaperGateContext) -> None:
    ctx.existing_figure_keys = {
        (str(item.get("id") or ""), str(item.get("label") or ""))
        for item in ctx.included_figure_assets
    }


def merge_structural_assets(ctx: PaperGateContext) -> None:
    ctx.included_figure_assets.extend(
        (
            item
            for item in ctx.structural_preview_assets
            if (str(item.get("id") or ""), str(item.get("label") or ""))
            not in ctx.existing_figure_keys
        )
    )


def collect_figure_roles(ctx: PaperGateContext) -> None:
    ctx.figure_role_values = [
        str(item.get("scientific_role") or "") for item in ctx.included_figure_assets
    ] + [str(item.get("id") or "") for item in ctx.included_figure_assets]


def canonicalize_figure_roles(ctx: PaperGateContext) -> None:
    ctx.canonical_figure_roles = canonical_roles(
        ctx.figure_role_values, FIGURE_ROLE_ALIASES
    )


def read_required_figure_roles(ctx: PaperGateContext) -> None:
    ctx.required_figure_roles = set(
        ctx.manuscript_profile.get("figure_contract", {}).get("required_roles", [])
    )


def find_missing_figure_roles(ctx: PaperGateContext) -> None:
    ctx.missing_figure_roles = sorted(
        ctx.required_figure_roles - ctx.canonical_figure_roles
    )


def reject_missing_figure_roles(ctx: PaperGateContext) -> None:
    if ctx.missing_figure_roles:
        ctx.problems.append(
            "paper is missing core scientific figure roles: "
            + ", ".join(ctx.missing_figure_roles)
        )


def validate_empirical_asset_contract(ctx: PaperGateContext) -> None:
    if ctx.manuscript_profile.get("publication_track") in {"empirical_submission", "simulation_draft"}:
        empirical_roles = {
            "main_comparison",
            "robustness_or_error_analysis",
            "calibration_or_efficiency",
        }
        for role in sorted(empirical_roles & ctx.canonical_figure_roles):
            matching = [
                item
                for item in ctx.included_figure_assets
                if role
                in canonical_roles(
                    [str(item.get("scientific_role") or ""), str(item.get("id") or "")],
                    FIGURE_ROLE_ALIASES,
                )
            ]
            if not any(
                (
                    item.get("evidence_status") == "executed"
                    and str(item.get("provenance_kind") or "").strip()
                    or (
                        ctx.evidence_mode == "synthetic_preview"
                        and item.get("evidence_status") == "synthetic_preview"
                        and (
                            item.get("provenance_kind")
                            == "deterministic_simulation_preview"
                        )
                    )
                    for item in matching
                )
            ):
                ctx.problems.append(
                    f"core empirical figure role {role} lacks executed provenance"
                )
    elif (
        ctx.manuscript_profile.get("publication_track") == "empirical_structure_preview"
    ):
        preview_roles = {
            "main_comparison",
            "robustness_or_error_analysis",
            "calibration_or_efficiency",
        }
        for role in sorted(preview_roles & ctx.canonical_figure_roles):
            matching = [
                item
                for item in ctx.included_figure_assets
                if role
                in canonical_roles(
                    [str(item.get("scientific_role") or ""), str(item.get("id") or "")],
                    FIGURE_ROLE_ALIASES,
                )
            ]
            if not matching or not all(
                (
                    item.get("evidence_status") == "synthetic_preview"
                    for item in matching
                )
            ):
                ctx.problems.append(
                    f"preview figure role {role} is not isolated as synthetic_preview"
                )


def validate_section_count(ctx: PaperGateContext) -> None:
    if ctx.section_count < 5:
        ctx.problems.append(
            f"need at least 5 top-level sections, found {ctx.section_count}"
        )


def read_minimum_figures(ctx: PaperGateContext) -> None:
    ctx.minimum_figures = int(
        ctx.manuscript_profile.get("figure_contract", {}).get(
            "minimum_distinct_graphics", 1
        )
    )


def read_minimum_tables(ctx: PaperGateContext) -> None:
    ctx.minimum_tables = int(
        ctx.manuscript_profile.get("table_contract", {}).get("minimum_tables", 2)
    )


def validate_figure_count(ctx: PaperGateContext) -> None:
    if len(ctx.figure_blocks) < ctx.minimum_figures:
        ctx.problems.append(
            f"need at least {ctx.minimum_figures} scientific figure environments for the selected profile, found {len(ctx.figure_blocks)}"
        )


def validate_table_count(ctx: PaperGateContext) -> None:
    if len(ctx.table_blocks) < ctx.minimum_tables:
        ctx.problems.append(
            f"need at least {ctx.minimum_tables} scientific table environments for the selected profile, found {len(ctx.table_blocks)}"
        )


def validate_figure_labels(ctx: PaperGateContext) -> None:
    for index, block in enumerate(ctx.figure_blocks, start=1):
        if not re.search("\\\\caption(?:\\s*\\[[^\\]]*\\])?\\s*\\{", block):
            ctx.problems.append(f"figure {index} has no caption")
        if not re.search("\\\\label\\{fig:[^}]+\\}", block):
            ctx.problems.append(f"figure {index} has no fig: label")


def validate_table_labels(ctx: PaperGateContext) -> None:
    for index, block in enumerate(ctx.table_blocks, start=1):
        if not re.search("\\\\caption(?:\\s*\\[[^\\]]*\\])?\\s*\\{", block):
            ctx.problems.append(f"table {index} has no caption")
        if not re.search("\\\\label\\{tab:[^}]+\\}", block):
            ctx.problems.append(f"table {index} has no tab: label")


def remove_float_blocks(ctx: PaperGateContext) -> None:
    from ..services.paper_prose_references import scientific_prose_text

    ctx.prose_only = scientific_prose_text(ctx.expanded_main)


def compile_reference_pattern(ctx: PaperGateContext) -> None:
    ctx.reference_command_re = re.compile(
        "\\\\crefrange\\*?(?:\\s*\\[[^\\]]*\\])?\\s*\\{[^{}]+\\}\\s*\\{[^{}]+\\}|\\\\(?:ref|cref|autoref)\\*?(?:\\s*\\[[^\\]]*\\])?\\s*\\{[^{}]+\\}",
        re.IGNORECASE,
    )


def find_reference_commands(ctx: PaperGateContext) -> None:
    ctx.reference_matches = list(ctx.reference_command_re.finditer(ctx.prose_only))


def collect_referenced_labels(ctx: PaperGateContext) -> None:
    ctx.referenced_labels = {
        label
        for match in ctx.reference_matches
        for label in reference_keys(match.group(0))
    }


def count_references(ctx: PaperGateContext) -> None:
    ctx.ref_count = len(ctx.referenced_labels)


def validate_reference_count(ctx: PaperGateContext) -> None:
    if ctx.ref_count < 2:
        ctx.problems.append(
            f"need at least 2 in-text figure/table references, found {ctx.ref_count}"
        )


def compile_discussion_terms(ctx: PaperGateContext) -> None:
    ctx.discussion_terms = re.compile(
        "(?:show|report|indicat|demonstrat|compar\\w*|illustrat|visualiz|depict|define|specif|bind|summari|expose|record|register|control|describ|organize|reveal|follow|trace|map|route|identif|interpret|evaluate|assess|measure|quantif|represent|correspond|track|plot|axis|curve|give|present|provide|calibrat|coverage|uncertainty|展示|报告|表明|说明|比较|定义|规定|绑定|揭示|总结)",
        re.IGNORECASE,
    )


def initialize_declared_labels(ctx: PaperGateContext) -> None:
    ctx.declared_labels: list[str] = []


def collect_declared_labels(ctx: PaperGateContext) -> None:
    for block in [*ctx.figure_blocks, *ctx.table_blocks]:
        match = re.search("\\\\label\\{((?:fig|tab):[^}]+)\\}", block)
        if match:
            ctx.declared_labels.append(match.group(1))


def validate_asset_discussion(ctx: PaperGateContext) -> None:
    from ..services.table_panel_reference_contract import source_bound_primary_panel_parents

    try:
        panel_parents = source_bound_primary_panel_parents(ctx.root, ctx.table_blocks or [])
    except ValueError as error:
        ctx.problems.append(str(error))
        panel_parents = {}
    for label in ctx.declared_labels:
        reference = next(
            (
                match
                for match in ctx.reference_matches
                if label in reference_keys(match.group(0))
            ),
            None,
        )
        if not reference and label in panel_parents:
            reference = next(
                (match for match in ctx.reference_matches
                 if panel_parents[label] in reference_keys(match.group(0))),
                None,
            )
        if not reference and label.casefold().endswith("-continued"):
            parent_label = label[: -len("-continued")]
            reference = next(
                (
                    match
                    for match in ctx.reference_matches
                    if parent_label in reference_keys(match.group(0))
                ),
                None,
            )
        if not reference:
            ctx.problems.append(
                f"scientific asset is included but never referenced in prose: {label}"
            )
            continue
        paragraph_start = ctx.prose_only.rfind("\n\n", 0, reference.start())
        paragraph_end = ctx.prose_only.find("\n\n", reference.end())
        paragraph_start = 0 if paragraph_start < 0 else paragraph_start + 2
        paragraph_end = len(ctx.prose_only) if paragraph_end < 0 else paragraph_end
        window = ctx.prose_only[paragraph_start:paragraph_end]
        if len(window) > 1800:
            window = ctx.prose_only[
                max(0, reference.start() - 650) : min(
                    len(ctx.prose_only), reference.end() + 650
                )
            ]
        if not ctx.discussion_terms.search(window):
            ctx.problems.append(
                f"scientific asset is referenced but not interpreted in prose: {label}; add a nearby sentence explaining what the asset shows, measures, compares, or implies"
            )


def collect_graphic_paths(ctx: PaperGateContext) -> None:
    ctx.include_paths = re.findall(
        "\\\\includegraphics\\*?(?:\\[[^\\]]*\\])?\\{([^}]+)\\}", ctx.combined
    )


def initialize_resolved_graphics(ctx: PaperGateContext) -> None:
    ctx.resolved_graphics: list[Path] = []


def resolve_graphics(ctx: PaperGateContext) -> None:
    for raw_path in ctx.include_paths:
        resolved = resolve_graphic_path(
            raw_path, ctx.paper_root, ctx.root, ctx.manifest_outputs
        )
        if resolved:
            ctx.resolved_graphics.append(resolved)
        else:
            ctx.problems.append(f"unresolved includegraphics path: {raw_path}")


def validate_distinct_graphics(ctx: PaperGateContext) -> None:
    if len(set(ctx.resolved_graphics)) < ctx.minimum_figures:
        ctx.problems.append(
            f"need at least {ctx.minimum_figures} distinct existing graphics for the selected profile, found {len(set(ctx.resolved_graphics))}"
        )


def parse_citations(ctx: PaperGateContext) -> None:
    ctx.citation_keys = parsed_citation_keys(ctx.combined)


def locate_bibliographies(ctx: PaperGateContext) -> None:
    ctx.bib_paths = [
        ctx.paper_root / "references.bib",
        ctx.root / "literature" / "references.bib",
    ]


def initialize_bibliography_keys(ctx: PaperGateContext) -> None:
    ctx.bibliography_keys: set[str] = set()


def collect_bibliography_keys(ctx: PaperGateContext) -> None:
    for bib_path in ctx.bib_paths:
        if bib_path.exists():
            ctx.bibliography_keys.update(
                (
                    key.strip()
                    for key in re.findall(
                        "(?m)^\\s*@[a-zA-Z]+\\s*\\{\\s*([^,\\s]+)",
                        bib_path.read_text(encoding="utf-8", errors="replace"),
                    )
                    if key.strip()
                )
            )


def read_bibliography_requirement(ctx: PaperGateContext) -> None:
    ctx.required_bibliography = int(
        ctx.manuscript_profile.get("minimum_unique_bibliography_entries") or 0
    )


def read_citation_requirement(ctx: PaperGateContext) -> None:
    ctx.required_citations = int(
        ctx.manuscript_profile.get("minimum_unique_citations") or 0
    )


def validate_bibliography_count(ctx: PaperGateContext) -> None:
    if len(ctx.bibliography_keys) < ctx.required_bibliography:
        ctx.problems.append(
            f"need at least {ctx.required_bibliography} verified bibliography entries for the selected profile, found {len(ctx.bibliography_keys)}"
        )


def validate_citation_count(ctx: PaperGateContext) -> None:
    if len(ctx.citation_keys) < ctx.required_citations:
        ctx.problems.append(
            f"need at least {ctx.required_citations} distinct citation keys, found {len(ctx.citation_keys)}"
        )


def find_unknown_citations(ctx: PaperGateContext) -> None:
    ctx.unknown_citations = sorted(ctx.citation_keys - ctx.bibliography_keys)


def reject_unknown_citations(ctx: PaperGateContext) -> None:
    if ctx.unknown_citations:
        ctx.problems.append(
            "manuscript cites unknown bibliography keys: "
            + ", ".join(ctx.unknown_citations[:12])
        )


def run_figure_gate(ctx: PaperGateContext) -> None:
    ctx.figure_gate = ctx.host._figure_acceptance_gate(ctx.project_path)


def propagate_figure_gate(ctx: PaperGateContext) -> None:
    if not ctx.figure_gate.get("accepted"):
        ctx.problems.append(
            f"figure manifest is not valid: {ctx.figure_gate.get('summary', '')}"
        )


def validate_innovation(ctx: PaperGateContext) -> None:
    if ctx.require_innovation:
        from ..services.research_intake import research_intake_service

        context_ok, context_issues, _ = research_intake_service.validate_context(
            ctx.project_path
        )
        brief_ok, brief_issues = research_intake_service.validate_innovation_brief(
            ctx.project_path
        )
        if not context_ok:
            ctx.problems.extend(context_issues)
        if not brief_ok:
            ctx.problems.extend(brief_issues)
        lower_paper = ctx.combined.lower()
        if not any(
            (
                term in lower_paper
                for term in (
                    "delta from the reference",
                    "novelty delta",
                    "相对参考工作",
                    "创新增量",
                )
            )
        ):
            ctx.problems.append("paper has no explicit delta from the reference work")
        if not any(
            (
                term in lower_paper
                for term in ("reference baseline", "baseline reproduction", "基线复现")
            )
        ):
            ctx.problems.append(
                "paper has no reference-baseline reproduction section or status"
            )
        baseline_metrics = (
            ctx.root / "experiments" / "results" / "reference_baseline" / "metrics.json"
        )
        proposed_metrics = (
            ctx.root / "experiments" / "results" / "proposed_method" / "metrics.json"
        )
        if not baseline_metrics.exists() or not proposed_metrics.exists():
            conclusion_blocks = re.findall(
                "\\\\begin\\{abstract\\}.*?\\\\end\\{abstract\\}|\\\\section\\*?\\{Conclusion\\}.*?(?=\\\\section|\\\\end\\{document\\})",
                ctx.combined,
                flags=re.IGNORECASE | re.DOTALL,
            )
            conclusion_text = "\n".join(conclusion_blocks)
            if re.search(
                "\\b(?:outperform(?:s|ed)?|superior|state-of-the-art|significantly improves?)\\b|(?:优于|显著提升|达到最先进)",
                conclusion_text,
                flags=re.IGNORECASE,
            ):
                ctx.problems.append(
                    "paper claims superiority without executed reference and proposed metric artifacts"
                )


def validate_page_budget(ctx: PaperGateContext) -> None:
    if ctx.require_page_budget:
        from ..services.paper_budget import paper_budget_service

        budget = paper_budget_service.load(ctx.project_path)
        if budget:
            build_path = ctx.paper_root / "PAPER_BUILD.json"
            if not build_path.exists():
                ctx.warnings.append(
                    "paper page target could not be checked because PAPER_BUILD.json is missing"
                )
            else:
                try:
                    build = json.loads(build_path.read_text(encoding="utf-8"))
                    actual_pages = int(build.get("compile", {}).get("pages") or 0)
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    actual_pages = 0
                if not budget.contains(actual_pages):
                    ctx.warnings.append(
                        f"compiled page count {actual_pages} is outside the preferred range {budget.minimum_pages}-{budget.maximum_pages}; page count is a soft target"
                    )


def reject_problems(ctx: PaperGateContext) -> None:
    if ctx.problems:
        raise PaperGateComplete(
            {
                "accepted": False,
                "reason": "paper quality contract failed",
                "summary": "; ".join(ctx.problems[:12]),
                "details": {
                    "issues": ctx.problems,
                    "review_findings": ctx.staged_findings,
                    "target_files": ctx.staged_target_files,
                    "failed_stage": str(ctx.staged_report.get("active_stage") or ""),
                    "semantic_no_progress": bool(
                        ctx.staged_report.get("semantic_no_progress")
                    ),
                    "sections": ctx.section_count,
                    "figures": len(ctx.figure_blocks),
                    "tables": len(ctx.table_blocks),
                    "graphics": [str(path) for path in ctx.resolved_graphics],
                    "citations": len(ctx.citation_keys),
                    "bibliography_entries": len(ctx.bibliography_keys),
                    "main_text_words": ctx.main_text_words,
                    "figure_roles": sorted(ctx.canonical_figure_roles),
                    "structural_preview_figures": [
                        str(item.get("id") or "")
                        for item in ctx.structural_preview_assets
                    ],
                    "table_roles": sorted(ctx.included_table_roles),
                    "manuscript_profile": ctx.manuscript_profile,
                    "warnings": ctx.warnings,
                    "sources": [str(path) for path in ctx.source_text],
                    "staged_drafting": ctx.staged_report,
                },
            }
        )


def collect_gate_artifacts(ctx: PaperGateContext) -> None:
    ctx.artifacts = [
        ctx.main_path,
        ctx.manifest_path,
        ctx.asset_plan_path,
        ctx.table_manifest_path,
        *ctx.table_artifacts,
        *ctx.source_text.keys(),
        *set(ctx.resolved_graphics),
    ]


def collect_optional_artifacts(ctx: PaperGateContext) -> None:
    for optional_artifact in (
        ctx.paper_root / "PAPER_PLAN.md",
        ctx.paper_root / "PAPER_BUDGET.json",
        ctx.paper_root / "PAPER_PLAN.json",
        ctx.paper_root / "PAPER_BUILD.json",
        ctx.paper_root / "PAPER_STYLE_PROFILE.json",
        ctx.paper_root / "PAPER_PROFILE.json",
        ctx.paper_root / "SECTION_CONTRACTS.json",
        ctx.paper_root / "SECTION_REVIEWS.json",
        ctx.paper_root / "DRAFT_STATE.json",
        ctx.paper_root / "CROSS_SECTION_REVIEW.md",
    ):
        if optional_artifact.exists():
            ctx.artifacts.append(optional_artifact)


def accept_paper(ctx: PaperGateContext) -> None:
    raise PaperGateComplete(
        {
            "accepted": True,
            "verdict_id": ctx.host._verdict_id("artifact:paper-quality", ctx.artifacts),
            "reviewer": "deterministic:paper-quality",
            "summary": f"Verified complete paper with {ctx.section_count} sections, {len(ctx.figure_blocks)} figures, {len(ctx.table_blocks)} tables, and {len(ctx.citation_keys)} citation keys.",
            "details": {
                "issues": [],
                "sources": [str(path) for path in ctx.source_text],
                "graphics": [str(path) for path in ctx.resolved_graphics],
                "sections": ctx.section_count,
                "figures": len(ctx.figure_blocks),
                "tables": len(ctx.table_blocks),
                "citations": len(ctx.citation_keys),
                "bibliography_entries": len(ctx.bibliography_keys),
                "main_text_words": ctx.main_text_words,
                "figure_roles": sorted(ctx.canonical_figure_roles),
                "structural_preview_figures": [
                    str(item.get("id") or "") for item in ctx.structural_preview_assets
                ],
                "table_roles": sorted(ctx.included_table_roles),
                "manuscript_profile": ctx.manuscript_profile,
                "warnings": ctx.warnings,
                "evidence_mode": ctx.evidence_mode,
                "submission_eligible": ctx.submission_eligible,
                "staged_drafting": ctx.staged_report,
                "manuscript_class": "synthetic_preview"
                if ctx.evidence_mode == "synthetic_preview"
                else "submission_candidate"
                if ctx.submission_eligible
                else "scientific_draft",
            },
        }
    )
