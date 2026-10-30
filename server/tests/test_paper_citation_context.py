"""Citation guidance measures distinct verified coverage rather than repeated keys."""

from server.services.paper_citation_context import related_work_citation_context


def test_current_gap_counts_verified_union_and_names_unused_inventory(tmp_path):
    paper = tmp_path / "paper"
    (paper / "sections").mkdir(parents=True)
    (paper / "references.bib").write_text("@article{a,title={A}}\n@article{b,title={B}}\n@article{c,title={C}}")
    (paper / "sections/01_introduction.tex").write_text(r"Compared designs \citep{a,b,a,unknown}.")
    (paper / "sections/02_related_work.tex").write_text(r"Earlier assumptions \citep{a}.")
    prompt = related_work_citation_context(tmp_path, 3)
    assert "2/3 distinct verified" in prompt and "1 additional distinct" in prompt
    assert "Already cited keys: a, b" in prompt
    assert "not a relevance recommendation): c" in prompt
    assert "unknown" not in prompt
