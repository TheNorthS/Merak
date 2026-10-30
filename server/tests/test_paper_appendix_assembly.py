"""Explicit appendix placement retains all original prose, floats and source bindings."""

import json

import pytest

from server.services.paper_appendix_assembly import prepare_appendix_assembly, original_assembly_inputs, planned_appendix_labels


def _project(root):
    paper = root / "paper"
    (paper / "sections").mkdir(parents=True)
    (root / "figures").mkdir()
    (root / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"figures": [
        {"id": "main", "output_path": "figures/main.pdf", "metadata": {"label": "fig:main", "scientific_role": "main_comparison"}},
        {"id": "risk", "output_path": "figures/risk.pdf", "metadata": {"label": "fig:risk", "scientific_role": "calibration"}},
    ]}))
    (paper / "PAPER_PLAN.md").write_text("| ID / exact label | Question | Placement |\n|---|---|---|\n"
        "| `fig:main` | Main endpoint | Section 5 |\n| `fig:risk` | Risk bounds | Appendix A.1 |\n")
    floats = (r"\begin{figure}\includegraphics{../figures/main.pdf}\caption{Main 0.32}\label{fig:main}\end{figure}" + "\n"
        + r"\begin{figure}\includegraphics{../figures/risk.pdf}\caption{Risk 0.129 [0.119, 0.139]}\label{fig:risk}\end{figure}")
    (paper / "figures.tex").write_text(floats)
    (paper / "sections/05_results.tex").write_text(r"\section{Results} See Figure~\ref{fig:risk}. \input{figures}")
    main = "\\documentclass{article}\n\\begin{document}\n\\input{sections/05_results}\n\\bibliography{references}\n\\end{document}\n"
    return paper, main


def test_assembly_moves_only_explicit_floats_and_preserves_authored_inputs(tmp_path):
    paper, main = _project(tmp_path)
    originals = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    rendered = prepare_appendix_assembly(tmp_path, main)
    (paper / "main.tex").write_bytes(rendered.encode())
    assert rendered.index(r"\label{fig:risk}") > rendered.index(r"\bibliography{references}")
    assert "Risk 0.129 [0.119, 0.139]" in rendered
    assert r"\suppressfloats[t]" in rendered and r"\begin{figure}[!htbp]" in rendered
    overlay = (paper / "assembly-layout/paper/figures.tex").read_text()
    assert r"\label{fig:main}" in overlay and r"\label{fig:risk}" not in overlay
    assert original_assembly_inputs(tmp_path) == {"sections/05_results"}
    from server.services.paper_review_source_inventory import consistency_source_inventory
    inventory = consistency_source_inventory(tmp_path)
    assert "fig:risk: 1 definition(s), paper/main.tex" in inventory
    assert "not two independent manuscript copies" in inventory
    assert all(path.read_bytes() == before for path, before in originals.items())
    assert prepare_appendix_assembly(tmp_path, main) == rendered


@pytest.mark.parametrize("changed", ["plan", "source", "overlay", "main"])
def test_stale_or_edited_projection_cannot_certify_section_inclusion(tmp_path, changed):
    paper, main = _project(tmp_path)
    (paper / "main.tex").write_bytes(prepare_appendix_assembly(tmp_path, main).encode())
    target = {"plan": paper / "PAPER_PLAN.md", "source": paper / "figures.tex",
        "overlay": paper / "assembly-layout/paper/figures.tex", "main": paper / "main.tex"}[changed]
    target.write_text(target.read_text().replace("0.32", "0.99") + "\nchanged\n")
    with pytest.raises(ValueError, match="stale|edited|differs"):
        original_assembly_inputs(tmp_path)


def test_conflicting_or_missing_selected_float_is_rejected(tmp_path):
    paper, main = _project(tmp_path)
    plan = paper / "PAPER_PLAN.md"
    plan.write_text(plan.read_text() + "| `fig:risk` | Same risk | Main text |\n")
    with pytest.raises(ValueError, match="conflicting"):
        planned_appendix_labels(tmp_path)
    plan.write_text(plan.read_text().replace("| `fig:risk` | Same risk | Main text |\n", ""))
    (paper / "figures.tex").write_text(r"\begin{figure}\label{fig:main}\end{figure}")
    with pytest.raises(ValueError, match="absent"):
        prepare_appendix_assembly(tmp_path, main)
