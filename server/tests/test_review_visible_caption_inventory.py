"""Review inputs distinguish actual caption commands from non-rendered source metadata."""

from server.services.paper_review_source_inventory import consistency_source_inventory


def test_caption_inventory_excludes_provenance_comments_and_unreachable_previous_projection(tmp_path):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(r"\input{current}")
    (paper / "current.tex").write_text(
        "\\begin{table}\n% MERAK_PRIMARY_MATRIX_CAPTION: old confidence interval title\n"
        "\\caption{Two-sided 95\\% scenario intervals.}\\label{tab:current}\n\\end{table}")
    (paper / "old.tex").write_text(r"\begin{table}\caption{Old confidence intervals}\label{tab:old}\end{table}")
    inventory = consistency_source_inventory(tmp_path)
    assert "Two-sided 95\\% scenario intervals." in inventory
    assert "old confidence interval title" not in inventory
    assert "Old confidence intervals" not in inventory and "tab:old" not in inventory
    assert "are not rendered" in inventory
