"""Same-source paper typography uses temporary scientific fixtures, never a user workflow."""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from server.services.paper_derived_figure_binding import file_sha256, pdf_print_geometry, placement_contract
from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
from server.services.paper_derived_svg_projection import scaled_svg_typography
from server.services.paper_trusted_plot_source import match_trusted_plot, projected_plot_source
from server.services.simulation_comparison_plots import _multitask_matrix_script


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _style():
    return {"fonts": ["DejaVu Sans"], "canvas": {"double_column_inches": 7.2, "target_font_pt": 9,
                                                  "placed_width_inches": 6.5, "minimum_font_pt": 8, "png_dpi": 90}}


def _pdf(path: Path, width: float = 600, fontsize: float = 9):
    import fitz
    document = fitz.open()
    page = document.new_page(width=width, height=200)
    page.insert_text((35, 60), "Registered scientific comparison", fontsize=fontsize)
    document.save(path)
    document.close()


def _entry(root: Path, *, svg: bool = False):
    identity = "evaluation_design" if svg else "synthetic_preview_main_comparison"
    source = root / ("figures/diagrams/evaluation.svg" if svg else "figures/simulated/main.py")
    data = root / "experiments/results/simulated/main_comparison.csv"
    rows = ["row_id,dataset,method,value,ci_low,ci_high,source_run_id,mean_task_rank",
            "r1,Dataset A,Reference,0.61,0.59,0.63,actual-fixture,2",
            "r2,Dataset A,Proposed,0.68,0.66,0.70,actual-fixture,1",
            "r3,Dataset B,Reference,0.55,0.53,0.57,actual-fixture,2",
            "r4,Dataset B,Proposed,0.63,0.60,0.66,actual-fixture,1"]
    _write(data, ("\n".join(rows) + "\n").encode())
    if svg:
        _write(source, b'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="240" viewBox="0 0 1200 240">'
               b'<rect x="10" y="10" width="1180" height="220" fill="white" stroke="black"/>'
               b'<text x="50" y="80" font-size="22">Declared source conditions</text>'
               b'<text x="50" y="160" font-size="22">Frozen evaluation endpoint</text></svg>')
    else:
        code = _multitask_matrix_script(data.relative_to(root).as_posix(), "Balanced accuracy", "main", _style(), "maximize")
        _write(source, code.encode())
    pdf = _write(source.with_suffix(".pdf"), b"temporary PDF fixture")
    _pdf(pdf, 1200 if svg else 600, 22 if svg else 9)
    variants = {kind: source.with_suffix("." + kind) for kind in ("pdf", "svg", "png")}
    if not svg:
        _write(variants["svg"], b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 200"/>')
    _write(variants["png"], b"original hash-only pixel fixture")
    entry = {"id": identity, "source_path": source.relative_to(root).as_posix(), "source_sha256": file_sha256(source),
             "output_path": pdf.relative_to(root).as_posix(), "output_sha256": file_sha256(pdf), "paper_ready": True,
             "metadata": {"semantic_key": identity, "label": "fig:registered-science", "producer_kind": "deterministic",
                          "source_data": [data.relative_to(root).as_posix()],
                          "source_data_sha256": {data.relative_to(root).as_posix(): file_sha256(data)},
                          "rendered_variants": {kind: path.relative_to(root).as_posix() for kind, path in variants.items()},
                          "rendered_variant_sha256": {kind: file_sha256(path) for kind, path in variants.items()}}}
    _write(root / "figures/FIGURE_MANIFEST.json", json.dumps({"schema": 1, "figures": [entry]}).encode())
    _write(root / "paper/main.tex", ("\\documentclass{article}\n\\textwidth 396bp\n\\begin{document}\n"
           f"\\includegraphics[width=0.94\\textwidth]{{../{entry['output_path']}}}\n\\end{{document}}\n").encode())
    return entry


def _placement(root, entry):
    from server.services.publication_print_contract import read_publication_print_contract
    contract = read_publication_print_contract(root, graphic_path=root / entry["output_path"]).to_dict()
    return {**contract["placements"][0], "minimum_font_bp": contract["minimum_font_bp"],
            "target_font_bp": contract["target_font_bp"], "contract_sha256": contract["contract_sha256"],
            "print_contract": contract}


def test_trusted_template_matching_and_typography_keep_computations_and_public_literals(tmp_path):
    entry = _entry(tmp_path)
    original = (tmp_path / entry["source_path"]).read_text()
    name, parameters, _template = match_trusted_plot(original)
    assert name == "multitask_matrix" and parameters["metric"] == "Balanced accuracy"
    projected, _name, _source = projected_plot_source(original, tmp_path, tmp_path / "paper/derived-figures/figure", 1.5)
    tree = ast.parse(projected)
    assert "ci_low" in projected and "ci_high" in projected and "source_run_id" in projected
    assert "Registered scientific" not in projected  # No generic text is inserted into the scientific plot.
    assert len(list(ast.walk(tree))) >= len(list(ast.walk(ast.parse(original)))) - 20


@pytest.mark.parametrize("injection", ["\nimport subprocess\nsubprocess.run(['training'])\n",
                                      "\nopen('experiments/results/changed.csv','w').write('forged')\n",
                                      "\nrows = rows[:1]\n", "\nraise RuntimeError('injected')\n"])
def test_arbitrary_or_changed_source_execution_is_rejected(tmp_path, injection):
    entry = _entry(tmp_path)
    code = (tmp_path / entry["source_path"]).read_text() + injection
    with pytest.raises(ValueError, match="exact current trusted"):
        match_trusted_plot(code)


@pytest.mark.asyncio
async def test_quantitative_variant_retains_every_row_ci_label_and_original_byte(tmp_path):
    entry = _entry(tmp_path)
    originals = {path: path.read_bytes() for directory in ("figures", "experiments")
                 for path in (tmp_path / directory).rglob("*") if path.is_file()}
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert packet["csv_inventory"][0]["rows"] == 4
    assert {"value", "ci_low", "ci_high", "source_run_id"}.issubset(packet["csv_inventory"][0]["fields"])
    assert packet["render_attempts"][-1]["minimum_placed_font_bp"] >= 8
    assert len(packet["render_attempts"]) <= 2
    assert not validate_derived_figure(tmp_path, packet)
    assert all(path.read_bytes() == value for path, value in originals.items())
    import fitz
    with fitz.open(tmp_path / packet["output_path"]) as document:
        text = document[0].get_text()
    assert "Dataset A" in text and "Dataset B" in text and "Reference" in text and "Proposed" in text


@pytest.mark.asyncio
async def test_deterministic_svg_variant_preserves_visible_labels_and_original_source(tmp_path):
    entry = _entry(tmp_path, svg=True)
    original = (tmp_path / entry["source_path"]).read_bytes()
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert (tmp_path / entry["source_path"]).read_bytes() == original
    assert not validate_derived_figure(tmp_path, packet)
    derived = (tmp_path / packet["source_path"]).read_bytes()
    assert b"Declared source conditions" in derived and b"Frozen evaluation endpoint" in derived
    assert packet["render_attempts"][-1]["minimum_placed_font_bp"] >= 8


@pytest.mark.asyncio
async def test_changed_derived_pixels_or_source_are_not_accepted_by_boolean_provenance(tmp_path):
    entry = _entry(tmp_path, svg=True)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    pdf = tmp_path / packet["output_path"]
    pdf.write_bytes(pdf.read_bytes() + b"tampered pixels")
    assert any("variant changed" in issue for issue in validate_derived_figure(tmp_path, packet))


@pytest.mark.asyncio
async def test_updated_source_data_and_unbound_manifest_inputs_block_reuse(tmp_path):
    entry = _entry(tmp_path, svg=True)
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    data = tmp_path / entry["metadata"]["source_data"][0]
    data.write_bytes(data.read_bytes().replace(b"0.61", b"0.99"))
    assert validate_derived_figure(tmp_path, packet)


@pytest.mark.asyncio
async def test_model_owned_artwork_cannot_enter_deterministic_font_redraw(tmp_path):
    entry = _entry(tmp_path, svg=True)
    entry["metadata"]["producer_kind"] = "model"
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [entry]}))
    with pytest.raises(ValueError, match="model-owned"):
        await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert not (tmp_path / "paper/derived-figures").exists()


@pytest.mark.parametrize("mutation", [{"width_bp": 0}, {"width_bp": float("nan")}, {"minimum_font_bp": 7},
                                      {"target_font_bp": 7}, {"contract_sha256": "unbound"}])
def test_unmeasured_or_weakened_print_geometry_is_rejected(mutation):
    value = {"width_bp": 372.24, "minimum_font_bp": 8, "target_font_bp": 8.5, "contract_sha256": "c" * 64, **mutation}
    with pytest.raises(ValueError, match="actual print width"):
        placement_contract(value)


@pytest.mark.parametrize("svg", [b'<svg viewBox="0 0 100 100"><script>training()</script></svg>',
                                 b'<svg viewBox="0 0 100 100"><image href="file:///outside"/></svg>',
                                 b'<!DOCTYPE svg><svg viewBox="0 0 100 100"/>'])
def test_svg_projection_never_allows_external_or_executable_content(svg):
    with pytest.raises(ValueError):
        scaled_svg_typography(svg, 1.2)


@pytest.mark.asyncio
async def test_successful_current_packet_is_reused_without_another_render(tmp_path, monkeypatch):
    from server.services import paper_derived_figure_rendering as producer
    entry = _entry(tmp_path, svg=True)
    placement = _placement(tmp_path, entry)
    packet = await derive_paper_figure(tmp_path, entry, placement)
    paths = [tmp_path / relative for relative in packet["derived_paths"].values()]
    before = {path: path.stat().st_mtime_ns for path in paths}
    monkeypatch.setattr(producer, "_render_candidate", lambda *_args: pytest.fail("Current successful input cannot redraw itself"))
    assert await derive_paper_figure(tmp_path, entry, placement) == packet
    assert {path: path.stat().st_mtime_ns for path in paths} == before


@pytest.mark.asyncio
async def test_exact_actual_print_width_cannot_be_replaced_by_selfsigned_geometry(tmp_path):
    entry = _entry(tmp_path, svg=True)
    value = _placement(tmp_path, entry)
    value["width_bp"] = 600
    value["contract_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="actual current template"):
        await derive_paper_figure(tmp_path, entry, value)


@pytest.mark.asyncio
async def test_unchanged_two_attempt_geometry_failure_is_not_automatically_redrawn(tmp_path, monkeypatch):
    from server.services import paper_derived_figure_rendering as producer
    entry = _entry(tmp_path, svg=True)
    value = _placement(tmp_path, entry)
    actual_geometry = producer.pdf_print_geometry
    calls = []

    def collisions(path, placement):
        geometry = actual_geometry(path, placement)
        if "derived-figures" in path.parts:
            geometry["text_geometry_findings"] = [{"kind": "text_collision", "labels": ["fixture one", "fixture two"]}]
            calls.append(path)
        return geometry

    monkeypatch.setattr(producer, "pdf_print_geometry", collisions)
    with pytest.raises(producer.PaperFigureProjectionError) as first:
        await derive_paper_figure(tmp_path, entry, value)
    assert len(first.value.render_attempts) == 2 and len(calls) == 2
    monkeypatch.setattr(producer, "_render_candidate", lambda *_args: pytest.fail("Unchanged failed producer input cannot redraw"))
    with pytest.raises(producer.PaperFigureProjectionError) as second:
        await derive_paper_figure(tmp_path, entry, value)
    assert len(second.value.render_attempts) == 2 and len(calls) == 2


def test_canonical_evaluation_reflow_preserves_each_visible_word_and_scientific_group():
    import xml.etree.ElementTree as ET
    from server.services.paper_evaluation_svg_layout import reflow_evaluation_svg
    raw = (b'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="300" viewBox="0 0 1200 300">'
           b'<rect width="1200" height="300" fill="white"/>'
           b'<g id="eval_group_split"><rect x="20" y="20" width="400" height="100"/>'
           b'<text x="38" y="60" font-size="22">One declared independent source condition and matched scientific control</text></g>'
           b'<g id="eval_matched_comparisons"><text x="40" y="160" font-size="22">Matched comparison</text></g>'
           b'<g id="eval_publication_labels"><text x="40" y="230" font-size="22">Frozen endpoint</text></g></svg>')
    original, projected = ET.fromstring(raw), ET.fromstring(reflow_evaluation_svg(raw, 1.4))
    text = lambda root: [" ".join("".join(item.itertext()).split()) for item in root.iter() if item.tag.endswith("}text")]
    assert text(projected) == text(original)
    assert {item.get("id") for item in projected.iter()} == {item.get("id") for item in original.iter()}
    assert float(projected.get("height")) > float(original.get("height"))


def test_evaluation_same_baseline_heading_keeps_a_visible_gap_before_body():
    import fitz
    import xml.etree.ElementTree as ET
    from server.services.paper_evaluation_svg_layout import reflow_evaluation_svg
    raw = (b'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="300" viewBox="0 0 1200 300">'
           b'<g id="eval_group_split"/><g id="eval_matched_comparisons"/>'
           b'<g id="eval_publication_labels"><rect x="28" y="50" width="1136" height="180"/>'
           b'<text x="48" y="100" font-size="22" font-weight="700">Primary endpoint</text>'
           b'<text x="258" y="100" font-size="22">The joint scientific mechanism preserves each registered contrast</text>'
           b'</g></svg>')
    root = ET.fromstring(reflow_evaluation_svg(raw, 1.4))
    texts = [item for item in root.iter() if item.tag.endswith("}text")]
    title, body = texts
    right = float(title.get("x")) + fitz.get_text_length(title.text, fontname="hebo", fontsize=float(title.get("font-size")))
    assert float(body.get("x")) - right >= 17.99
    assert " ".join("".join(body.itertext()).split()) == "The joint scientific mechanism preserves each registered contrast"


def test_data_mutation_or_truncation_in_a_current_trusted_plot_remains_rejected(tmp_path):
    entry = _entry(tmp_path)
    code = (tmp_path / entry["source_path"]).read_text()
    mutations = []
    truncated = ast.parse(code)
    rows = next(node for node in ast.walk(truncated) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "rows" for target in node.targets))
    rows.value = ast.Subscript(rows.value, ast.Slice(upper=ast.Constant(2)), ast.Load())
    mutations.append(ast.unparse(ast.fix_missing_locations(truncated)))
    altered = ast.parse(code)
    limits = [node for node in ast.walk(altered) if isinstance(node, ast.Constant) and node.value == "ci_low"]
    assert limits
    for node in limits:
        node.value = "value"
    mutations.append(ast.unparse(altered))
    for changed in mutations:
        assert ast.dump(ast.parse(changed)) != ast.dump(ast.parse(code))
        with pytest.raises(ValueError, match="exact current trusted"):
            match_trusted_plot(changed)
