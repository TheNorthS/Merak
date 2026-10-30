"""Typed mutable facts for the deterministic paper acceptance transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class PaperGateHost(Protocol):
    def _paper_has_unfinished_draft_language(
        self, text: str, evidence_mode: str
    ) -> bool: ...
    def _figure_acceptance_gate(self, project_path: str) -> dict[str, Any]: ...
    def _verdict_id(self, node_id: str, artifacts: list[Any]) -> str: ...


class PaperGateComplete(Exception):
    def __init__(self, gate: dict[str, Any]):
        self.gate = gate


@dataclass
class PaperGateContext:
    host: PaperGateHost
    project_path: str
    require_innovation: bool
    require_page_budget: bool
    require_staged: bool
    paper_options: dict[str, Any]
    abstract_match: Any = None
    abstract_text: Any = None
    administrative_hits: Any = None
    administrative_language: Any = None
    artifacts: Any = None
    asset_plan: Any = None
    asset_plan_path: Any = None
    bib_paths: Any = None
    bibliography_keys: Any = None
    canonical_figure_roles: Any = None
    canonical_table_roles: Any = None
    citation_keys: Any = None
    combined: Any = None
    contract_ids: Any = None
    declared_labels: Any = None
    discussion_terms: Any = None
    evidence_mode: Any = None
    existing_figure_keys: Any = None
    expanded_main: Any = None
    expected_synthetic_ids: Any = None
    exposed_ids: Any = None
    figure_blocks: Any = None
    figure_gate: Any = None
    figure_graphics_by_label: Any = None
    figure_role_values: Any = None
    include_paths: Any = None
    included_figure_assets: Any = None
    included_labels: Any = None
    included_table_entries: Any = None
    included_table_roles: Any = None
    forbidden_simulation_label_present: Any = None
    main_path: Any = None
    main_text: Any = None
    main_text_words: Any = None
    method_source: Any = None
    manifest: Any = None
    manifest_outputs: Any = None
    manifest_path: Any = None
    manuscript_profile: Any = None
    minimum_figures: Any = None
    minimum_tables: Any = None
    missing_figure_roles: Any = None
    missing_included_table_roles: Any = None
    normalized_manuscript: Any = None
    paper_root: Any = None
    problems: Any = None
    prose_only: Any = None
    queue: Any = None
    ref_count: Any = None
    reference_command_re: Any = None
    reference_matches: Any = None
    referenced_labels: Any = None
    required_bibliography: Any = None
    required_citations: Any = None
    required_figure_roles: Any = None
    required_table_roles: Any = None
    resolved_graphics: Any = None
    root: Any = None
    scientific_table_roles: Any = None
    section_count: Any = None
    selected_contract: Any = None
    selected_contract_path: Any = None
    source_text: Any = None
    staged_findings: Any = None
    staged_report: Any = None
    staged_target_files: Any = None
    structural_preview_assets: Any = None
    submission_eligible: Any = None
    table_artifacts: Any = None
    table_blocks: Any = None
    table_entries: Any = None
    table_ids: Any = None
    table_manifest: Any = None
    table_manifest_path: Any = None
    table_role_values: Any = None
    title_match: Any = None
    unknown_citations: Any = None
    visible_code_artifacts: Any = None
    visible_manuscript: Any = None
    warnings: Any = None
    watermark_commands: Any = None
    word_range: Any = None
