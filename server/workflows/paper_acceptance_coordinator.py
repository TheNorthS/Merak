"""Coordinate deterministic paper acceptance checks without mutating research content."""

from __future__ import annotations

from typing import Any
from .paper_acceptance_context import PaperGateComplete, PaperGateContext
from .paper_acceptance_checks_1 import (
    initialize_paths,
    initialize_paper_root,
    initialize_main_path,
    initialize_problems,
    initialize_warnings,
    initialize_staged_report,
    initialize_staged_findings,
    initialize_staged_targets,
    validate_staged_draft,
    require_main_document,
    locate_asset_plan,
    initialize_asset_plan,
    load_asset_plan,
    read_evidence_mode,
    read_submission_eligibility,
    load_manuscript_profile,
    require_manuscript_profile,
    validate_complete_evidence_mode,
    validate_experiment_request,
    locate_table_manifest,
    initialize_table_artifacts,
    initialize_table_entries,
    table_manifest_missing,
    table_manifest_load_1,
    table_manifest_load_2,
    table_manifest_load_3,
    table_manifest_load_4,
    table_manifest_load_5,
    table_manifest_load_6,
    table_manifest_load_7,
    table_manifest_load_8,
    validate_empirical_table_manifest,
    validate_simulation_table_manifest,
    require_table_entries,
    initialize_source_map,
    initialize_source_queue,
    collect_reachable_sources,
    read_main_source,
    combine_sources,
    expand_main_source,
    compile_admin_language_rule,
    initialize_admin_hits,
    find_admin_language,
    reject_admin_language,
    collect_contract_ids,
)
from .paper_acceptance_checks_2 import (
    find_exposed_contract_ids,
    reject_exposed_contract_ids,
    strip_comments,
    normalize_visible_prose,
    find_visible_code_artifacts,
    reject_visible_code_artifacts,
    detect_forbidden_simulation_label,
    reject_forbidden_simulation_label,
    validate_simulation_disclosure,
    find_watermarks,
    reject_watermarks,
    validate_latex_shell,
    validate_draft_language,
    find_title,
    validate_title,
    find_abstract,
    normalize_abstract,
    validate_abstract,
    validate_document_length,
    count_main_words,
    fallback_main_words,
    read_word_range,
    validate_word_range,
    locate_selected_contract,
    initialize_selected_contract,
    load_selected_contract,
    validate_selected_title,
    validate_selected_mechanisms,
    count_sections,
    collect_figure_blocks,
    collect_table_blocks,
    collect_labels,
    locate_figure_manifest,
    load_figure_manifest,
    initialize_manifest_outputs,
    collect_manifest_outputs,
    initialize_figure_graphics,
    map_figure_graphics,
    select_included_tables,
    canonicalize_table_roles,
    find_missing_table_roles,
    reject_missing_table_roles,
    select_figure_assets,
    initialize_structural_assets,
    synthetic_asset_manifest,
    synthetic_asset_rows,
)
from .paper_acceptance_checks_3 import (
    synthetic_asset_sources,
    collect_existing_figure_keys,
    merge_structural_assets,
    collect_figure_roles,
    canonicalize_figure_roles,
    read_required_figure_roles,
    find_missing_figure_roles,
    reject_missing_figure_roles,
    validate_empirical_asset_contract,
    validate_section_count,
    read_minimum_figures,
    read_minimum_tables,
    validate_figure_count,
    validate_table_count,
    validate_figure_labels,
    validate_table_labels,
    remove_float_blocks,
    compile_reference_pattern,
    find_reference_commands,
    collect_referenced_labels,
    count_references,
    validate_reference_count,
    compile_discussion_terms,
    initialize_declared_labels,
    collect_declared_labels,
    validate_asset_discussion,
    collect_graphic_paths,
    initialize_resolved_graphics,
    resolve_graphics,
    validate_distinct_graphics,
    parse_citations,
    locate_bibliographies,
    initialize_bibliography_keys,
    collect_bibliography_keys,
    read_bibliography_requirement,
    read_citation_requirement,
    validate_bibliography_count,
    validate_citation_count,
    find_unknown_citations,
    reject_unknown_citations,
    run_figure_gate,
    propagate_figure_gate,
    validate_innovation,
    validate_page_budget,
    reject_problems,
    collect_gate_artifacts,
    collect_optional_artifacts,
    accept_paper,
)


def _run_source_checks(ctx: PaperGateContext) -> None:
    initialize_paths(ctx)
    initialize_paper_root(ctx)
    initialize_main_path(ctx)
    initialize_problems(ctx)
    initialize_warnings(ctx)
    initialize_staged_report(ctx)
    initialize_staged_findings(ctx)
    initialize_staged_targets(ctx)
    validate_staged_draft(ctx)
    require_main_document(ctx)
    locate_asset_plan(ctx)
    initialize_asset_plan(ctx)
    load_asset_plan(ctx)
    read_evidence_mode(ctx)
    read_submission_eligibility(ctx)
    load_manuscript_profile(ctx)
    require_manuscript_profile(ctx)
    validate_complete_evidence_mode(ctx)
    validate_experiment_request(ctx)
    locate_table_manifest(ctx)
    initialize_table_artifacts(ctx)
    initialize_table_entries(ctx)
    table_manifest_missing(ctx)
    table_manifest_load_1(ctx)
    table_manifest_load_2(ctx)
    table_manifest_load_3(ctx)
    table_manifest_load_4(ctx)
    table_manifest_load_5(ctx)
    table_manifest_load_6(ctx)
    table_manifest_load_7(ctx)
    table_manifest_load_8(ctx)
    validate_empirical_table_manifest(ctx)
    validate_simulation_table_manifest(ctx)
    require_table_entries(ctx)
    initialize_source_map(ctx)
    initialize_source_queue(ctx)
    collect_reachable_sources(ctx)
    read_main_source(ctx)
    combine_sources(ctx)
    expand_main_source(ctx)
    compile_admin_language_rule(ctx)
    initialize_admin_hits(ctx)
    find_admin_language(ctx)
    reject_admin_language(ctx)
    collect_contract_ids(ctx)
    find_exposed_contract_ids(ctx)


def _run_asset_checks(ctx: PaperGateContext) -> None:
    reject_exposed_contract_ids(ctx)
    strip_comments(ctx)
    normalize_visible_prose(ctx)
    find_visible_code_artifacts(ctx)
    reject_visible_code_artifacts(ctx)
    detect_forbidden_simulation_label(ctx)
    reject_forbidden_simulation_label(ctx)
    validate_simulation_disclosure(ctx)
    find_watermarks(ctx)
    reject_watermarks(ctx)
    validate_latex_shell(ctx)
    validate_draft_language(ctx)
    find_title(ctx)
    validate_title(ctx)
    find_abstract(ctx)
    normalize_abstract(ctx)
    validate_abstract(ctx)
    validate_document_length(ctx)
    count_main_words(ctx)
    fallback_main_words(ctx)
    read_word_range(ctx)
    validate_word_range(ctx)
    locate_selected_contract(ctx)
    initialize_selected_contract(ctx)
    load_selected_contract(ctx)
    validate_selected_title(ctx)
    validate_selected_mechanisms(ctx)
    count_sections(ctx)
    collect_figure_blocks(ctx)
    collect_table_blocks(ctx)
    collect_labels(ctx)
    locate_figure_manifest(ctx)
    load_figure_manifest(ctx)
    initialize_manifest_outputs(ctx)
    collect_manifest_outputs(ctx)
    initialize_figure_graphics(ctx)
    map_figure_graphics(ctx)
    select_included_tables(ctx)
    canonicalize_table_roles(ctx)
    find_missing_table_roles(ctx)
    reject_missing_table_roles(ctx)
    select_figure_assets(ctx)
    initialize_structural_assets(ctx)
    synthetic_asset_manifest(ctx)
    synthetic_asset_rows(ctx)
    synthetic_asset_sources(ctx)


def _run_submission_checks(ctx: PaperGateContext) -> None:
    from ..services.publication_table_policy import publication_table_issues

    table_paths = [
        str(item.get("latex_path")) for item in (ctx.included_table_entries or [])
        if isinstance(item, dict) and str(item.get("latex_path") or "").strip()
    ]
    table_issues = publication_table_issues(ctx.paper_root, table_paths)
    ctx.problems.extend(table_issues)
    from ..services.paper_presentation_findings import publication_table_findings
    ctx.staged_findings.extend(publication_table_findings(table_issues))
    if ctx.require_page_budget:
        from ..services.paper_pdf_quality import validate_persisted_pdf_quality
        ctx.problems.extend(validate_persisted_pdf_quality(ctx.root))
    collect_existing_figure_keys(ctx)
    merge_structural_assets(ctx)
    collect_figure_roles(ctx)
    canonicalize_figure_roles(ctx)
    read_required_figure_roles(ctx)
    find_missing_figure_roles(ctx)
    reject_missing_figure_roles(ctx)
    validate_empirical_asset_contract(ctx)
    validate_section_count(ctx)
    read_minimum_figures(ctx)
    read_minimum_tables(ctx)
    validate_figure_count(ctx)
    validate_table_count(ctx)
    validate_figure_labels(ctx)
    validate_table_labels(ctx)
    remove_float_blocks(ctx)
    compile_reference_pattern(ctx)
    find_reference_commands(ctx)
    collect_referenced_labels(ctx)
    count_references(ctx)
    validate_reference_count(ctx)
    compile_discussion_terms(ctx)
    initialize_declared_labels(ctx)
    collect_declared_labels(ctx)
    validate_asset_discussion(ctx)
    collect_graphic_paths(ctx)
    initialize_resolved_graphics(ctx)
    resolve_graphics(ctx)
    validate_distinct_graphics(ctx)
    parse_citations(ctx)
    locate_bibliographies(ctx)
    initialize_bibliography_keys(ctx)
    collect_bibliography_keys(ctx)
    read_bibliography_requirement(ctx)
    read_citation_requirement(ctx)
    validate_bibliography_count(ctx)
    validate_citation_count(ctx)
    find_unknown_citations(ctx)
    reject_unknown_citations(ctx)
    run_figure_gate(ctx)
    propagate_figure_gate(ctx)
    validate_innovation(ctx)
    validate_page_budget(ctx)
    reject_problems(ctx)
    collect_gate_artifacts(ctx)
    collect_optional_artifacts(ctx)
    accept_paper(ctx)


def paper_acceptance_gate(
    host: Any,
    project_path: str,
    *,
    require_innovation: bool = False,
    require_page_budget: bool = False,
    require_staged: bool = False,
    paper_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = PaperGateContext(
        host,
        project_path,
        require_innovation,
        require_page_budget,
        require_staged,
        dict(paper_options or {}),
    )
    try:
        from ..services.paper_pixel_validation_cache import pixel_validation_scope
        with pixel_validation_scope():
            _run_source_checks(ctx)
            _run_asset_checks(ctx)
            _run_submission_checks(ctx)
    except PaperGateComplete as completed:
        return completed.gate
    raise RuntimeError("Paper acceptance checks completed without a verdict")
