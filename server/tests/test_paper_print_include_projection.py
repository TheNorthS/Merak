"""Paper-only input projection preserves dependencies under the real TeX cwd."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

import pytest

from scripts.live_snapshot_compilation import restricted_snapshot_compilation
from server.services import paper_print_projection as projection
from server.services.latex_bundle import _reachable_sources, _tex_text, latex_source_bundle
from server.services.paper_compiler import paper_compiler
from server.tests.test_paper_print_repair import _fixture


def _files(root):
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _table(paper: Path) -> tuple[Path, Path]:
    directory = paper / "tables"
    directory.mkdir(exist_ok=True)
    table, csv = directory / "method_components.tex", directory / "method_components.csv"
    table.write_text(r"\par Retained table source.\begin{table}[h]\centering"
        r"\caption{Bound inputs}\label{tab:method-components}\begin{tabular}{ll}"
        r"Component & Weight \\ Alpha & 0.125 \\ Beta & 0.875 \\"
        r"\end{tabular}\end{table}" + "\n", encoding="utf-8")
    csv.write_bytes(b"component,weight\nAlpha,0.125\nBeta,0.875\n")
    return table, csv


def _assert_actual_cwd_input_closure(paper: Path) -> set[Path]:
    """Check TeX's execution cwd, without the graph resolver's source-dir fallback."""
    reached, queue = set(), [paper / "main.tex"]
    while queue:
        source = queue.pop()
        if source in reached:
            continue
        assert source.is_file(), source
        reached.add(source)
        for name in re.findall(r"\\(?:input|include|subfile)\s*\{([^}]+)\}", _tex_text(source)):
            target = (paper / name).resolve()
            target = target if target.suffix else target.with_suffix(".tex")
            assert target.is_file(), (source, name)
            queue.append(target)
    return reached


def test_unchanged_section_relative_table_is_relocated_without_editing_authors_or_numeric_rows(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    table, csv = _table(tmp_path / "paper")
    original = section.read_text(encoding="utf-8")
    section.write_text("% Preserve this comment: \\input{../tables/method_components.tex}\n"
        + "Unrelated 95\\% prose.\n" + r"\input{../tables/method_components.tex}" + "\n"
        + original, encoding="utf-8")
    before = _files(tmp_path)
    projection.install_print_projection(tmp_path, [packet])
    projected = tmp_path / "paper/derived-figures/tex/sections/01_results.tex"
    text = projected.read_text(encoding="utf-8")
    assert "% Preserve this comment: \\input{../tables/method_components.tex}" in text
    assert "Unrelated 95\\% prose." in text and r"\input{tables/method_components.tex}" in text
    assert table in _assert_actual_cwd_input_closure(tmp_path / "paper")
    assert table in _reachable_sources(main, tmp_path / "paper", tmp_path)
    receipt = json.loads((tmp_path / projection.RECEIPT).read_text())
    context = {row["path"]: row["sha256"] for row in receipt["source_context"]}
    assert context["paper/tables/method_components.tex"] == hashlib.sha256(
        table.read_text(encoding="utf-8-sig").encode()).hexdigest()
    assert table.read_bytes() == before[table] and csv.read_bytes() == before[csv]
    assert section.read_bytes() == before[section] and projection.validate_print_projection(tmp_path) == []
    first = _files(tmp_path)
    projection.install_print_projection(tmp_path, [packet])
    assert _files(tmp_path) == first


def test_changed_child_and_unchanged_child_use_exact_paper_cwd_targets_with_normal_convergence(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    table, csv = _table(tmp_path / "paper")
    child = tmp_path / "paper/sections/details.tex"
    child.write_text(section.read_text(encoding="utf-8"), encoding="utf-8")
    section.write_text(r"Reviewed parent.\input{details}\input{../tables/method_components.tex}", encoding="utf-8")
    before = _files(tmp_path)
    projection.install_print_projection(tmp_path, [packet])
    projected = tmp_path / "paper/derived-figures/tex/sections/01_results.tex"
    assert r"\input{derived-figures/tex/sections/details.tex}" in projected.read_text()
    assert r"\input{tables/method_components.tex}" in projected.read_text()
    reached = _assert_actual_cwd_input_closure(tmp_path / "paper")
    assert table in reached and len(reached) == 4
    assert all(path.read_bytes() == before[path] for path in (section, child, table, csv))
    assert projection.validate_print_projection(tmp_path) == [] and main in reached


def test_unknown_reference_is_preserved_and_never_guessed_or_dropped(tmp_path, monkeypatch):
    _main, section, packet = _fixture(tmp_path, monkeypatch)
    section.write_text(section.read_text() + r"\input{../tables/missing-authored-input.tex}")
    before = section.read_bytes()
    projection.install_print_projection(tmp_path, [packet])
    projected = tmp_path / "paper/derived-figures/tex/sections/01_results.tex"
    assert r"\input{../tables/missing-authored-input.tex}" in projected.read_text()
    assert section.read_bytes() == before
    assert not (tmp_path / "paper/tables/missing-authored-input.tex").exists()


def test_project_local_external_paper_child_keeps_identity_without_copying_it(tmp_path, monkeypatch):
    _main, section, packet = _fixture(tmp_path, monkeypatch)
    external = tmp_path / "appendix-context.tex"
    external.write_bytes(b"Immutable project-local context.\n")
    section.write_text(section.read_text() + r"\input{../../appendix-context.tex}")
    before = external.read_bytes()
    projection.install_print_projection(tmp_path, [packet])
    projected = tmp_path / "paper/derived-figures/tex/sections/01_results.tex"
    assert r"\input{../appendix-context.tex}" in projected.read_text()
    assert external in _assert_actual_cwd_input_closure(tmp_path / "paper")
    assert external.read_bytes() == before and projection.validate_print_projection(tmp_path) == []
    assert not (tmp_path / "paper/derived-figures/tex/appendix-context.tex").exists()


def test_project_local_external_source_cannot_become_a_paper_owned_derived_copy(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    external = tmp_path / "appendix-context.tex"
    external.write_text(section.read_text())
    section.write_text(r"\input{../../appendix-context.tex}")
    before = _files(tmp_path)
    with pytest.raises(ValueError, match="local paper TeX source"):
        projection.install_print_projection(tmp_path, [packet])
    assert _files(tmp_path) == before and main.read_bytes() == before[main]


def test_forged_relocated_dependency_is_rejected_even_when_output_hash_is_resigned(tmp_path, monkeypatch):
    _main, section, packet = _fixture(tmp_path, monkeypatch)
    _table(tmp_path / "paper")
    section.write_text(section.read_text() + r"\input{../tables/method_components.tex}")
    projection.install_print_projection(tmp_path, [packet])
    projected = tmp_path / "paper/derived-figures/tex/sections/01_results.tex"
    projected.write_text(projected.read_text().replace("tables/method_components.tex", "tables/foreign.tex"))
    receipt = tmp_path / projection.RECEIPT
    payload = json.loads(receipt.read_text())
    row = next(item for item in payload["sources"] if item["original_path"] == "paper/sections/01_results.tex")
    row["output_sha256"] = hashlib.sha256(projected.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(payload))
    assert any("exact graphics-only transform" in issue for issue in projection.validate_print_projection(tmp_path))


@pytest.mark.asyncio
async def test_real_source_bound_projection_and_native_tex_compile_include_exact_table_and_graphic(tmp_path):
    import fitz
    from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
    from server.tests.test_paper_derived_figure_rendering import _placement
    from server.tests.test_paper_figurespec_source import _native

    assert shutil.which("latexmk"), "Native temporary path regression requires the configured local TeX compiler"
    entry = await _native(tmp_path)
    paper = tmp_path / "paper"
    (paper / "sections").mkdir()
    table, csv = _table(paper)
    section = paper / "sections/04_experiments.tex"
    section.write_text(r"Reviewed experiment text.\input{../tables/method_components.tex}" + "\n"
        r"\begin{figure}[h]\centering\includegraphics[width=.94\textwidth]{../" + entry["output_path"]
        + r"}\caption{Bound source graphic}\label{fig:registered-method}\end{figure}", encoding="utf-8")
    (paper / "main.tex").write_text(r"\documentclass{article}\usepackage{graphicx}" + "\n"
        r"\textwidth 396bp\begin{document}\input{sections/04_experiments}\end{document}", encoding="utf-8")
    preserved = {path: path.read_bytes() for path in (section, table, csv)}
    preserved.update({path: path.read_bytes() for folder in ("figures", "experiments")
                      for path in (tmp_path / folder).rglob("*") if path.is_file()})
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert validate_derived_figure(tmp_path, packet) == []
    projection.install_print_projection(tmp_path, [packet])
    assert projection.validate_print_projection(tmp_path) == []
    assert table in _assert_actual_cwd_input_closure(paper)
    digest, bundle = latex_source_bundle(paper)
    assert table in bundle and tmp_path / packet["output_path"] in bundle
    with restricted_snapshot_compilation(tmp_path):
        result = await paper_compiler.compile(str(paper), "main.tex", clean=True)
    assert result.success, result.log_output
    with fitz.open(result.pdf_path) as document:
        text = " ".join(page.get_text() for page in document)
    assert all(value in text for value in ("Retained table source", "Alpha", "0.125", "Beta", "0.875", "Bound source graphic"))
    native = json.loads((tmp_path / entry["source_path"]).read_text())
    assert all(" ".join(node["label"].split()) in " ".join(text.split()) for node in native["nodes"])
    assert all(path.read_bytes() == raw for path, raw in preserved.items())
    assert latex_source_bundle(paper)[0] == digest
