"""Candidate-only manuscript sections must use one file view throughout panel validation."""
from pathlib import Path

import pytest

from server.services.paper_candidate_transaction import PaperCandidate
from server.services.table_panel_reference_contract import section_primary_panel_parents
from server.tests.test_table_panel_reference_contract import _bundle, LABEL


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_real_panel_gate_reads_candidate_without_publishing_it(tmp_path, existing, nested):
    _bundle(tmp_path, "original")
    section = tmp_path / "paper/sections/05_results.tex"
    section.parent.mkdir(parents=True, exist_ok=True)
    if existing:
        section.write_text("Canonical text without table inputs", encoding="utf-8")
    before = section.read_bytes() if existing else None
    targets = [section]
    helper = tmp_path / "paper/sections/results_inputs.tex"
    if nested:
        targets.append(helper)
    candidate = PaperCandidate(tmp_path, "results", targets, lambda: "frozen-fixture")
    for path in candidate.files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    candidate.files[section.resolve()].write_text(
        r"\input{results_inputs}" if nested else r"\input{tables/synthetic_preview_results}", encoding="utf-8")
    if nested:
        candidate.files[helper.resolve()].write_text(r"\input{tables/synthetic_preview_results}", encoding="utf-8")
    with candidate:
        parents = section_primary_panel_parents(tmp_path, section)
        assert parents and set(parents.values()) == {LABEL}
    assert (section.read_bytes() if section.exists() else None) == before
    assert not helper.exists()


def test_candidate_without_input_cannot_borrow_old_canonical_table_reference(tmp_path):
    _bundle(tmp_path, "original")
    section = tmp_path / "paper/sections/05_results.tex"
    section.parent.mkdir(parents=True, exist_ok=True)
    section.write_text(r"\input{tables/synthetic_preview_results}", encoding="utf-8")
    candidate = PaperCandidate(tmp_path, "results", [section], lambda: "frozen-fixture")
    candidate.files[section.resolve()].write_text("Candidate has no table input", encoding="utf-8")
    with candidate:
        assert section_primary_panel_parents(tmp_path, section) == {}
