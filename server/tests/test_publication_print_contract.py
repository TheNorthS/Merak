"""Actual reachable TeX widths are resolved in bp or explicitly require measurement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services.publication_print_contract import read_publication_print_contract, UnresolvedPublicationPrintContract


def _project(root: Path, style: str, include: str, options: str = "") -> Path:
    paper = root / "paper"
    paper.mkdir()
    (paper / "venue.sty").write_bytes(style.encode("utf-8"))
    asset = root / "figures/result.pdf"
    asset.parent.mkdir()
    asset.write_bytes(b"%PDF-1.4 finite asset identity fixture, no rendering")
    (paper / "main.tex").write_bytes(("\\documentclass" + options + "{article}\n\\usepackage{venue}\n"
                                        + r"\begin{document}\input{section}\end{document}" + "\n").encode("utf-8"))
    (paper / "section.tex").write_bytes(include.encode("utf-8"))
    return asset


def _figure(width: str, environment: str = "figure") -> str:
    return "\\begin{" + environment + "}\n\\includegraphics[width=" + width + "]{../figures/result.pdf}\n\\end{" + environment + "}"


def test_current_iclr_true_inches_produce_actual_372bp_placement_not_6point5in(tmp_path):
    asset = _project(tmp_path, "\\newif\\ificlrfinal\n\\def\\iclrfinalcopy{\\iclrfinaltrue}\n"
                     "\\textwidth 5.5 true in\n\\textheight 9 true in\n"
                     "\\def\\maketitle{\\ificlrfinal final\\else draft\\fi}\n", _figure(r"0.94\textwidth"))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    contract = read_publication_print_contract(tmp_path, graphic_path=asset).to_dict()
    assert contract["text_width_bp"] == 396 and contract["column_width_bp"] == 396
    assert contract["placements"][0]["width_bp"] == pytest.approx(372.24)
    assert contract["placements"][0]["graphic_relative"] == "figures/result.pdf"
    assert contract["target_font_bp"] == 8.5 and contract["minimum_font_bp"] == 8.0
    assert contract["template_source_sha256"]["paper/venue.sty"] == hashlib.sha256((tmp_path / "paper/venue.sty").read_bytes()).hexdigest()
    assert read_publication_print_contract(tmp_path).to_dict() == contract
    assert before == {path: path.read_bytes() for path in before}


@pytest.mark.parametrize(("dimension", "expected"), [("397.485pt", 396), ("396bp", 396), ("5.5in", 396),
                                                     ("139.7mm", 396), ("13.97cm", 396), ("33.12375pc", 396)])
def test_exact_dimension_units_convert_tex_points_to_pdf_big_points(tmp_path, dimension, expected):
    _project(tmp_path, r"\setlength{\textwidth}{" + dimension + "}", _figure(r"\textwidth"))
    assert read_publication_print_contract(tmp_path).text_width_bp == pytest.approx(expected)


def test_two_column_width_and_full_width_figure_have_distinct_actual_placements(tmp_path):
    _project(tmp_path, r"\setlength{\textwidth}{7in}\setlength{\columnsep}{0.2in}",
             _figure(r"0.9\columnwidth") + _figure(r"0.9\linewidth", "figure*"), "[twocolumn]")
    payload = read_publication_print_contract(tmp_path).to_dict()
    assert payload["text_width_bp"] == 504 and payload["column_width_bp"] == pytest.approx(244.8)
    assert [placement["width_bp"] for placement in payload["placements"]] == pytest.approx([220.32, 453.6])


def test_explicit_geometry_paper_size_is_resolved_without_default_letter_assumption(tmp_path):
    _project(tmp_path, r"\usepackage[margin=1in]{geometry}", _figure(r"0.94\textwidth"), "[a4paper]")
    assert read_publication_print_contract(tmp_path).text_width_bp == pytest.approx(210 * 72 / 25.4 - 144)


def test_reachable_style_order_and_unused_sources_are_hash_bound_correctly(tmp_path):
    _project(tmp_path, "\\textwidth 5in\n", _figure("300bp"))
    (tmp_path / "paper/unused.sty").write_bytes(b"\\textwidth 100in")
    main = tmp_path / "paper/main.tex"
    main.write_bytes(main.read_bytes().replace(b"\\begin{document}", b"\\setlength{\\textwidth}{6in}\n\\begin{document}"))
    payload = read_publication_print_contract(tmp_path).to_dict()
    assert payload["text_width_bp"] == 432 and "paper/unused.sty" not in payload["template_source_sha256"]


@pytest.mark.parametrize("style", [
    "", r"\setlength{\textwidth}{\unknownwidth}", r"\newif\ifwide\ifwide\textwidth 5in\else\textwidth 6in\fi",
    r"\def\applywidth{\textwidth 5in}", r"\textwidth 5in\advance\textwidth by 1in",
    r"\textwidth 5in\mag=1200", r"\textwidth 7in", r"\usepackage[margin=1in]{geometry}",
])
def test_unknown_dynamic_or_underspecified_width_never_silently_guesses(tmp_path, style):
    options = "[twocolumn]" if style == r"\textwidth 7in" else ""
    _project(tmp_path, style, _figure(r"0.94\textwidth"), options)
    with pytest.raises(UnresolvedPublicationPrintContract):
        read_publication_print_contract(tmp_path)


@pytest.mark.parametrize("include", [
    _figure(r"\dynamicwidth"), r"\begin{minipage}{0.5\textwidth}" + _figure(r"\linewidth") + r"\end{minipage}",
    r"\includegraphics[width=0.9\textwidth,height=2in,keepaspectratio]{../figures/result.pdf}",
    r"\includegraphics[scale=0.7]{../figures/result.pdf}", r"\def\graphic{\includegraphics[width=0.9\textwidth]{../figures/result.pdf}}",
])
def test_dynamic_inner_or_height_constrained_placement_requires_controlled_measurement(tmp_path, include):
    _project(tmp_path, r"\textwidth 5.5in", include)
    with pytest.raises(UnresolvedPublicationPrintContract):
        read_publication_print_contract(tmp_path)


def test_template_and_graphic_byte_changes_invalidate_the_print_identity(tmp_path):
    asset = _project(tmp_path, r"\textwidth 5.5in", _figure(r"0.94\textwidth"))
    before = read_publication_print_contract(tmp_path).to_dict()
    asset.write_bytes(asset.read_bytes() + b"changed pixels")
    after = read_publication_print_contract(tmp_path).to_dict()
    assert before["contract_sha256"] != after["contract_sha256"]
    (tmp_path / "paper/venue.sty").write_bytes(b"\\textwidth 5.25in")
    changed = read_publication_print_contract(tmp_path).to_dict()
    assert changed["text_width_bp"] == 378 and changed["contract_sha256"] != after["contract_sha256"]


def test_cross_input_full_width_figure_preserves_parent_column_context(tmp_path):
    _project(tmp_path, r"\textwidth 7in\columnsep 0.2in", r"\includegraphics[width=0.9\linewidth]{../figures/result.pdf}", "[twocolumn]")
    main = tmp_path / "paper/main.tex"
    main.write_bytes(main.read_bytes().replace(b"\\input{section}", b"\\begin{figure*}\\input{section}\\end{figure*}"))
    assert read_publication_print_contract(tmp_path).placements[0]["width_bp"] == pytest.approx(453.6)


def test_cross_input_minipage_cannot_be_mistaken_for_global_linewidth(tmp_path):
    _project(tmp_path, r"\textwidth 5.5in", r"\includegraphics[width=0.9\linewidth]{../figures/result.pdf}")
    main = tmp_path / "paper/main.tex"
    main.write_bytes(main.read_bytes().replace(b"\\input{section}", b"\\begin{minipage}{0.5\\textwidth}\\input{section}\\end{minipage}"))
    with pytest.raises(UnresolvedPublicationPrintContract, match="inner graphic placement"):
        read_publication_print_contract(tmp_path)


def test_unknown_external_class_column_mode_is_not_assumed_single_column(tmp_path):
    _project(tmp_path, r"\textwidth 7in", _figure(r"\linewidth"))
    main = tmp_path / "paper/main.tex"
    main.write_bytes(main.read_bytes().replace(b"{article}", b"{unknownjournal}"))
    with pytest.raises(UnresolvedPublicationPrintContract, match="Unknown class column mode"):
        read_publication_print_contract(tmp_path)


def test_body_width_change_does_not_retroactively_change_earlier_figure_contract(tmp_path):
    _project(tmp_path, r"\textwidth 5.5in", _figure(r"\linewidth") + r"\setlength{\textwidth}{3in}")
    with pytest.raises(UnresolvedPublicationPrintContract, match="width requires controlled"):
        read_publication_print_contract(tmp_path)


def _active_projection(root: Path) -> tuple[dict, Path]:
    from server.services.paper_print_projection import install_print_projection

    paper, sections = root / "paper", root / "paper/sections"
    (sections / "nested").mkdir(parents=True)
    (root / "figures").mkdir()
    (root / "figures/result.pdf").write_bytes(b"%PDF-1.4 original variant identity only")
    (paper / "iclr2026_conference.sty").write_text(
        "\\newif\\ificlrfinal\n\\textwidth 5.5 true in\n"
        "\\def\\maketitle{\\ificlrfinal final\\else draft\\fi}\n", encoding="utf-8")
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{iclr2026_conference}\n"
        "\\graphicspath{{../figures/}}\n\\begin{document}\n"
        "\\input{sections/00_abstract}\n\\input{sections/03_method}\n\\end{document}\n", encoding="utf-8")
    (sections / "00_abstract.tex").write_text("\\begin{abstract}Bound abstract.\\end{abstract}\n", encoding="utf-8")
    (sections / "03_method.tex").write_text(
        "\\section{Method}\n\\input{nested/plot}\n", encoding="utf-8")
    (sections / "nested/plot.tex").write_text(
        "\\begin{figure}\n\\includegraphics[width=0.94\\textwidth]{result}\n\\end{figure}\n", encoding="utf-8")
    original = read_publication_print_contract(root).to_dict()
    variant = paper / "derived-figures/result/figure.pdf"
    variant.parent.mkdir(parents=True)
    variant.write_bytes(b"%PDF-1.4 bound print-only variant identity")
    install_print_projection(root, [{"original_path": "figures/result.pdf",
                                    "output_path": variant.relative_to(root).as_posix()}])
    return original, paper / "derived-figures/ORIGINAL_MAIN.tex"


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_active_exact_original_archive_preserves_chapters_nested_inputs_graphicspath_and_iclr_contract(tmp_path):
    from server.services.paper_derived_figure_binding import _canonical_original_contract, verified_print_placement

    original, archive = _active_projection(tmp_path)
    before = _files(tmp_path)
    raw = read_publication_print_contract(tmp_path, main_tex=archive).to_dict()
    normalized = _canonical_original_contract(raw, archive.relative_to(tmp_path).as_posix())
    assert normalized == original
    assert raw["text_width_bp"] == 396 and raw["placements"][0]["width_bp"] == pytest.approx(372.24)
    assert {"paper/sections/00_abstract.tex", "paper/sections/03_method.tex",
            "paper/sections/nested/plot.tex", "paper/iclr2026_conference.sty"} <= set(raw["template_source_sha256"])
    value = {"width_bp": 372.24, "graphic_relative": "figures/result.pdf", "print_contract": original,
             "contract_sha256": original["contract_sha256"], "minimum_font_bp": 8, "target_font_bp": 8.5}
    assert verified_print_placement(tmp_path, {"output_path": "figures/result.pdf"}, value)["width_bp"] == 372.24
    assert _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["missing_receipt", "wrong_archive_hash", "wrong_archive_path",
                                     "current_main_hash", "inactive_main", "foreign_archive"])
def test_archive_source_root_requires_exact_active_canonical_projection_proof(tmp_path, defect):
    _original, archive = _active_projection(tmp_path)
    receipt_path = tmp_path / "paper/derived-figures/PRINT_PROJECTION.json"
    if defect == "missing_receipt":
        receipt_path.unlink()
    elif defect == "current_main_hash":
        main = tmp_path / "paper/main.tex"
        main.write_bytes(main.read_bytes() + b"\nChanged active entrypoint\n")
    elif defect == "inactive_main":
        (tmp_path / "paper/main.tex").write_bytes(archive.read_bytes())
    elif defect == "foreign_archive":
        alternate = tmp_path / "unrelated/ORIGINAL_MAIN.tex"
        alternate.parent.mkdir()
        alternate.write_bytes(archive.read_bytes())
        archive = alternate
    else:
        receipt = json.loads(receipt_path.read_text())
        receipt["original_main_sha256" if defect.endswith("hash") else "original_main_path"] = (
            "0" * 64 if defect.endswith("hash") else "unrelated/ORIGINAL_MAIN.tex")
        receipt_path.write_text(json.dumps(receipt))
    before = _files(tmp_path)
    with pytest.raises(UnresolvedPublicationPrintContract, match="archive"):
        read_publication_print_contract(tmp_path, main_tex=archive)
    assert _files(tmp_path) == before


def test_archive_storage_sibling_cannot_shadow_or_replace_the_actual_paper_chapter(tmp_path):
    original, archive = _active_projection(tmp_path)
    shadow = archive.parent / "sections/00_abstract.tex"
    shadow.parent.mkdir()
    shadow.write_text("Unrelated archive sibling, not the authored abstract.\n")
    raw = read_publication_print_contract(tmp_path, main_tex=archive).to_dict()
    assert "paper/derived-figures/sections/00_abstract.tex" not in raw["template_source_sha256"]
    assert raw["template_source_sha256"]["paper/sections/00_abstract.tex"] == original["template_source_sha256"]["paper/sections/00_abstract.tex"]
    (tmp_path / "paper/sections/00_abstract.tex").unlink()
    with pytest.raises(UnresolvedPublicationPrintContract, match="sections/00_abstract"):
        read_publication_print_contract(tmp_path, main_tex=archive)


def test_bound_archive_still_refuses_dynamic_macros_in_actual_nested_placements(tmp_path):
    _original, archive = _active_projection(tmp_path)
    nested = tmp_path / "paper/sections/nested/plot.tex"
    nested.write_text(nested.read_text().replace(r"0.94\textwidth", r"\unresolvedwidth"))
    with pytest.raises(UnresolvedPublicationPrintContract, match="Dynamic TeX dimension"):
        read_publication_print_contract(tmp_path, main_tex=archive)
