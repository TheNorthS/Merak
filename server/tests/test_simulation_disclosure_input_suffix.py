"""The exact conclusion input retains its disclosure boundary after PRINT projection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from scripts.live_snapshot_compilation import restricted_snapshot_compilation
from server.services import paper_print_projection as projection
from server.services.paper_complete_validation import _main_document_issues
from server.services.paper_compiler import paper_compiler
from server.services.risk_stage_paper import _rule_1
from server.services.simulation_policy import (
    SIMULATION_END_DISCLOSURE,
    SIMULATION_END_DISCLOSURE_TITLE,
    simulation_disclosure_report,
)
from server.workflows.paper_acceptance_checks_2 import validate_simulation_disclosure


def _disclosure() -> str:
    return f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n{SIMULATION_END_DISCLOSURE}\n"


def _assert_boundary(text: str, *, valid: bool) -> None:
    report = simulation_disclosure_report(text)
    accepted = (report["count"], report["end_matter_count"], report["outside_end_matter_count"]) == (1, 1, 0)
    assert accepted is valid, report
    context = SimpleNamespace(evidence_mode="synthetic_preview", expanded_main=text, problems=[])
    validate_simulation_disclosure(context)
    assert any("exactly one final disclosure" in issue for issue in context.problems) is not valid


@pytest.mark.parametrize("suffix", ["", ".tex"])
def test_exact_conclusion_input_with_or_without_tex_suffix_has_one_final_disclosure(suffix):
    text = f"\\input{{sections/08_conclusion{suffix}}}\n" + _disclosure() + r"\bibliography{references}"
    _assert_boundary(text, valid=True)


@pytest.mark.parametrize("reference", [
    "sections/08_conclusion.tex.tex", "sections/08_conclusion.pdf", "sections/08_conclusion-extra.tex",
    "sections/08_conclusions.tex", "other/08_conclusion.tex", "xsections/08_conclusion.tex",
    "derived-figures/tex/sections/08_conclusion.tex",
])
def test_noncanonical_conclusion_input_cannot_supply_the_final_disclosure_boundary(reference):
    _assert_boundary(f"\\input{{{reference}}}\n" + _disclosure() + r"\bibliography{references}", valid=False)


@pytest.mark.parametrize("case", ["repeated", "before_conclusion", "after_bibliography", "commented_conclusion"])
def test_tex_suffix_does_not_relax_disclosure_count_position_or_comment_rules(case):
    conclusion = "\\input{sections/08_conclusion.tex}\n"
    disclosure, bibliography = _disclosure(), "\\bibliography{references}\n"
    text = {
        "repeated": conclusion + disclosure + disclosure + bibliography,
        "before_conclusion": disclosure + conclusion + bibliography,
        "after_bibliography": conclusion + bibliography + disclosure,
        "commented_conclusion": "% " + conclusion + disclosure + bibliography,
    }[case]
    _assert_boundary(text, valid=False)


def _persistent_bytes(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for directory in ("figures", "experiments")
            for path in (root / directory).rglob("*") if path.is_file()}


def _assert_native_disclosure_consumers(root: Path) -> None:
    main = root / "paper/main.tex"
    issues: list[str] = []
    _main_document_issues({"root": root, "main": main}, (), {"mode": "synthetic_preview"}, issues)
    assert issues == []
    findings = _rule_1({"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}, root)["findings"]
    assert not any(item["id"] == "PAPER-SIM-001" for item in findings), findings


@pytest.mark.asyncio
async def test_real_print_normalization_native_compile_and_all_disclosure_consumers_keep_exact_boundary(tmp_path):
    import fitz
    from server.services.latex_bundle import _reachable_sources, _tex_text
    from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
    from server.tests.test_paper_derived_figure_rendering import _placement
    from server.tests.test_paper_figurespec_source import _native

    assert shutil.which("latexmk"), "This local integration requires the configured native TeX compiler"
    entry = await _native(tmp_path)
    paper = tmp_path / "paper"
    (paper / "sections").mkdir()
    abstract = paper / "sections/00_abstract.tex"
    abstract.write_text("Registered fixed-source abstract.\n", encoding="utf-8")
    conclusion = paper / "sections/08_conclusion.tex"
    conclusion.write_text("\\section{Conclusion}\nRegistered bounded conclusion.\n", encoding="utf-8")
    section = paper / "sections/04_experiments.tex"
    section.write_text(r"\section{Evaluation}\begin{figure}[h]\centering"
        + r"\includegraphics[width=.94\textwidth]{../" + entry["output_path"]
        + r"}\caption{Registered scientific comparison}\label{fig:registered-method}\end{figure}" + "\n", encoding="utf-8")
    main = paper / "main.tex"
    main.write_text("\\documentclass{article}\\usepackage{graphicx}\n\\textwidth 396bp"
        + "\\hyphenpenalty=10000\\exhyphenpenalty=10000\\begin{document}\n"
        + "\\begin{abstract}\\input{sections/00_abstract}\\end{abstract}\n"
        + "\\input{sections/04_experiments}\n\\input{sections/08_conclusion}\n" + _disclosure()
        + "\\begin{thebibliography}{1}\\bibitem{fixed}Registered source.\\end{thebibliography}\n\\end{document}\n",
        encoding="utf-8")
    canonical = {path: path.read_bytes() for path in (abstract, conclusion, section, main)}
    preserved = _persistent_bytes(tmp_path)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert validate_derived_figure(tmp_path, packet) == []
    projection.install_print_projection(tmp_path, [packet])
    assert projection.validate_print_projection(tmp_path) == []
    projected = main.read_text(encoding="utf-8")
    assert r"\input{sections/08_conclusion.tex}" in projected
    _assert_boundary(projected, valid=True)
    _assert_native_disclosure_consumers(tmp_path)
    receipt = json.loads((tmp_path / projection.RECEIPT).read_text(encoding="utf-8"))
    backup = tmp_path / receipt["original_main_path"]
    assert backup.read_bytes() == canonical[main]
    source_text = {tmp_path / row["path"]: (backup.read_text(encoding="utf-8-sig") if row["path"] == "paper/main.tex"
                   else (tmp_path / row["path"]).read_text(encoding="utf-8-sig")) for row in receipt["source_context"]}
    assert all(hashlib.sha256(source_text[tmp_path / row["path"]].encode()).hexdigest() == row["sha256"]
               for row in receipt["source_context"])
    assert projection._transform_sources(tmp_path, source_text,
        {tmp_path / packet["original_path"]: tmp_path / packet["output_path"]}, [packet])[main] == projected
    sources = {path: _tex_text(path) for path in _reachable_sources(main, paper, tmp_path) if path.suffix == ".tex"}
    from server.workflows.paper_acceptance_source import expand_tex_source
    _assert_boundary(expand_tex_source(main, sources, paper, set()), valid=True)
    with restricted_snapshot_compilation(tmp_path):
        result = await paper_compiler.compile(str(paper), "main.tex", clean=True)
    assert result.success, result.log_output
    with fitz.open(result.pdf_path) as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert text.count(SIMULATION_END_DISCLOSURE_TITLE) == 1
    assert text.count(SIMULATION_END_DISCLOSURE) == 1
    assert text.index("Registered bounded conclusion.") < text.index(SIMULATION_END_DISCLOSURE_TITLE) < text.index("Registered source.")
    assert all(path.read_bytes() == content for path, content in preserved.items())
    assert all(path.read_bytes() == canonical[path] for path in (abstract, conclusion, section))
