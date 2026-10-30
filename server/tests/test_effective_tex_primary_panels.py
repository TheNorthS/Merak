"""Expanded manuscript panels retain exact visible science after comment removal."""

from __future__ import annotations

import re

import pytest

from server.services.latex_bundle import _tex_text
from server.services.paper_complete_validation import _included_fragments, _reference_issues
from server.services.paper_drafting import SECTION_SPECS
from server.services.paper_prose_references import asset_prose_reference_keys
from server.services.paper_table_source_labels import selected_table_source_records
from server.services.simulation_policy import strip_latex_comments
from server.services.simulation_table_projection_binding import CANONICAL_TABLE
from server.services.table_panel_reference_contract import source_bound_primary_panel_parents
from server.tests.test_paper_results_panel_references import _section
from server.tests.test_table_panel_reference_contract import LABEL, _files


RESULT_SPEC = next(spec for spec in SECTION_SPECS if spec.id == "results")


def _expanded(root, route="derived"):
    _path, prose = _section(root, route)
    paths = {"root": root, "paper": root / "paper", "sections": root / "paper/sections"}
    fragments = _included_fragments(paths, (RESULT_SPEC,))
    return paths, prose + fragments


@pytest.mark.parametrize("route", ["original", "derived"])
def test_real_complete_fragment_expansion_accepts_exact_comment_stripped_producer_panels_readonly(tmp_path, route):
    paths, combined = _expanded(tmp_path, route)
    before = _files(tmp_path)
    source = (tmp_path / CANONICAL_TABLE).read_text(encoding="utf-8")
    assert "% MERAK_PRIMARY_MATRIX_CAPTION:" in source
    assert "% MERAK_PRIMARY_MATRIX_CAPTION:" not in combined
    assert r"95\%" in source and r"95\%" in combined
    blocks = re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", combined, re.DOTALL)
    expected = {f"{LABEL}-panel-{number}": LABEL for number in range(2, 9)}
    assert source_bound_primary_panel_parents(tmp_path, blocks) == expected
    references = asset_prose_reference_keys(tmp_path, combined)
    assert set(expected) <= references and LABEL in references
    issues = []
    _reference_issues(paths, combined, issues)
    assert not issues and _files(tmp_path) == before


def test_effective_tex_only_ignores_nonvisible_comments_preserving_escaped_percent_and_all_other_characters(tmp_path):
    _paths, combined = _expanded(tmp_path)
    before = _files(tmp_path)
    blocks = re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", combined, re.DOTALL)
    marked = [block.replace(r"\centering", r"\centering% Additional nonvisible local comment") for block in blocks]
    expected = {f"{LABEL}-panel-{number}": LABEL for number in range(2, 9)}
    assert source_bound_primary_panel_parents(tmp_path, marked) == expected
    canonical = selected_table_source_records((tmp_path / CANONICAL_TABLE).read_text(encoding="utf-8"))
    effective = selected_table_source_records(_tex_text(tmp_path / CANONICAL_TABLE))
    assert canonical[LABEL]["source"] != effective[LABEL]["source"]
    assert canonical[LABEL]["caption"] == effective[LABEL]["caption"]
    assert strip_latex_comments(r"95\% CI % nonvisible") == r"95\% CI "
    assert _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["number", "interval", "caption", "label", "missing_panel",
    "foreign_panel", "scientific_operation", "visible_space"])
def test_effective_expanded_panel_content_mutations_remain_blocking_and_do_not_modify_sources(tmp_path, defect):
    _paths, combined = _expanded(tmp_path)
    before = _files(tmp_path)
    if defect == "number": changed = combined.replace("0.005 [0.001, 0.009]", "0.006 [0.001, 0.009]", 1)
    elif defect == "interval": changed = combined.replace("0.005 [0.001, 0.009]", "0.005 [0.002, 0.009]", 1)
    elif defect == "caption": changed = combined.replace("Matched primary comparison.", "Unverified superiority.", 1)
    elif defect == "label": changed = combined.replace(r"\label{" + LABEL + "}", r"\label{tab:foreign-primary}", 1)
    elif defect == "missing_panel":
        records = selected_table_source_records(combined)
        changed = combined.replace(records[LABEL + "-panel-2"]["source"], "", 1)
    elif defect == "foreign_panel":
        changed = combined.replace(r"\label{" + LABEL + "-panel-2}", r"\label{tab:foreign-panel-2}", 1)
    elif defect == "scientific_operation": changed = combined.replace(r"\small", r"\tiny", 1)
    else: changed = combined.replace(r"\centering", r"\centering ", 1)
    assert changed != combined
    blocks = re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", changed, re.DOTALL)
    with pytest.raises(ValueError, match="Primary table panel"):
        source_bound_primary_panel_parents(tmp_path, blocks)
    assert _files(tmp_path) == before


def test_stripping_comments_from_canonical_source_without_current_hash_proof_remains_rejected(tmp_path):
    _paths, _combined = _expanded(tmp_path)
    path = tmp_path / CANONICAL_TABLE
    path.write_text(_tex_text(path), encoding="utf-8")
    before = _files(tmp_path)
    blocks = re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", path.read_text(encoding="utf-8"), re.DOTALL)
    with pytest.raises(ValueError):
        source_bound_primary_panel_parents(tmp_path, blocks)
    assert _files(tmp_path) == before
