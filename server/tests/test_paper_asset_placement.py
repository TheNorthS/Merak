"""Selected scientific assets appear once, beside their owner section, never in a tail dump."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.latex_bundle import latex_source_bundle
from server.services.paper_asset_placement import section_asset_placements
from server.services.paper_complete_validation import _included_fragments
from server.services.paper_manuscript_assembly import _manuscript_inputs


def _write(root: Path, relative: str, text: str = "source") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _figure(label: str, graphic: str) -> str:
    return ("\\begin{figure}[t]\n\\centering\n"
            f"\\includegraphics[width=\\linewidth]{{{graphic}}}\n"
            f"\\caption{{Scientific explanation.}}\\label{{{label}}}\n\\end{{figure}}\n")


def _table(label: str) -> str:
    return "\\begin{table}\n\\caption{Scientific contrasts}\n" + f"\\label{{{label}}}\nA & 1\\\\\n\\end{{table}}\n"


def _fixture(root: Path):
    specs = [SimpleNamespace(id=name, filename=f"{index:02}_{name}.tex") for index, name in enumerate(
        ("introduction", "related_work", "method", "experiments", "results", "discussion", "limitations", "conclusion"), 1)]
    section_files = [(Path(spec.filename).stem, _write(root, f"paper/sections/{spec.filename}", f"\\section{{{spec.id}}}\n"))
                     for spec in specs]
    abstract = _write(root, "paper/sections/00_abstract.tex", "Scientific abstract")
    figure_records = []
    for identity, role, label in (("method_architecture", "method", "fig:method-architecture"),
                                  ("evaluation_design", "evaluation_design", "fig:evaluation-design"),
                                  ("result", "result", "fig:result")):
        graphic = _write(root, f"figures/diagrams/{identity}.pdf", "%PDF-scientific-fixture")
        figure_records.append({"id": identity, "output_path": graphic.relative_to(root).as_posix(),
                               "metadata": {"label": label, "scientific_role": role, "paper_selected": True,
                                            "manuscript_eligible": True}})
    _write(root, "figures/FIGURE_MANIFEST.json", json.dumps({"schema": 1, "figures": figure_records}))
    _write(root, "figures/SCIENTIFIC_ASSET_PLAN.json", json.dumps({"assets": [
        {"id": item["id"], "kind": "figure", "manuscript_eligible": True} for item in figure_records]}))
    for identity, group, label in (("method_architecture", "method", "fig:method-architecture"),
                                    ("evaluation_design", "evaluation", "fig:evaluation-design"),
                                    ("result", "result", "fig:result")):
        _write(root, f"paper/generated_{group}_figures.tex", _figure(label, f"../figures/diagrams/{identity}.pdf"))
    _write(root, "paper/tables/TABLE_MANIFEST.json", '{"schema":3,"tables":[]}')
    paths = {"root": root, "paper": root / "paper", "sections": root / "paper/sections"}
    return paths, specs, [("00_abstract", abstract), *section_files]


def _records(root: Path, tables: list[dict]) -> None:
    _write(root, "paper/tables/TABLE_MANIFEST.json", json.dumps({"schema": 3, "tables": tables}))


def test_existing_inline_label_and_graphic_prevent_duplicate_generated_method_and_evaluation(tmp_path):
    paths, specs, sections = _fixture(tmp_path)
    method = paths["sections"] / "03_method.tex"
    evaluation = paths["sections"] / "04_experiments.tex"
    method.write_text(_figure("fig:method-architecture", "../figures/diagrams/method_architecture.pdf"))
    evaluation.write_text(_figure("fig:evaluation-design", "../figures/diagrams/evaluation_design.pdf"))
    before = {path: path.read_bytes() for _name, path in sections}
    source_before = {path: path.read_bytes() for path in paths["paper"].glob("generated_*_figures.tex")}
    inputs = _manuscript_inputs(paths, sections)
    assert "assembly_method_figures" not in inputs and "assembly_experiments_figures" not in inputs
    assert inputs.index("assembly_results_figures") > inputs.index("sections/05_results")
    assert inputs.index("assembly_results_figures") < inputs.index("sections/06_discussion")
    assert all(path.read_bytes() == content for path, content in before.items())
    assert all(path.read_bytes() == content for path, content in source_before.items())
    fragments = _included_fragments(paths, tuple(specs))
    assert "fig:method-architecture" not in fragments and "fig:evaluation-design" not in fragments
    assert "fig:result" in fragments


def test_true_missing_selected_assets_are_placed_after_each_related_section_not_conclusion(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    inputs = _manuscript_inputs(paths, sections)
    for stage, index, following in (("method", "03_method", "04_experiments"),
                                   ("experiments", "04_experiments", "05_results"),
                                   ("results", "05_results", "06_discussion")):
        assert inputs.index(f"sections/{index}") < inputs.index(f"assembly_{stage}_figures") < inputs.index(f"sections/{following}")
    assert inputs.endswith("\\input{sections/08_conclusion}")


def test_partial_generated_bundle_projects_only_the_unembedded_selected_block(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    manifest_path = tmp_path / "figures/FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    other = copy.deepcopy(manifest["figures"][0])
    other["id"] = "mechanism"
    other["metadata"]["label"] = "fig:mechanism"
    other["output_path"] = "figures/diagrams/mechanism.pdf"
    _write(tmp_path, other["output_path"], "%PDF-scientific-fixture")
    manifest["figures"].append(other)
    manifest_path.write_text(json.dumps(manifest))
    plan_path = tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json"
    plan = json.loads(plan_path.read_text());plan["assets"].append({"id": "mechanism", "kind": "figure"})
    plan_path.write_text(json.dumps(plan))
    first = _figure("fig:method-architecture", "../figures/diagrams/method_architecture.pdf")
    second = _figure("fig:mechanism", "../figures/diagrams/mechanism.pdf")
    generated = _write(tmp_path, "paper/generated_method_figures.tex", first + second)
    (paths["sections"] / "03_method.tex").write_text(first)
    before = generated.read_bytes()
    _manuscript_inputs(paths, sections)
    fragment = (paths["paper"] / "assembly_method_figures.tex").read_text()
    assert "fig:mechanism" in fragment and "fig:method-architecture" not in fragment
    assert generated.read_bytes() == before


def test_recursive_owned_inputs_and_graphicspath_recognize_real_embedded_assets(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    block = "\\graphicspath{{../figures/diagrams/}}\n" + _figure("fig:method-architecture", "method_architecture")
    _write(tmp_path, "paper/owned/method_visual.tex", block + "\\input{owned/method_visual}")
    (paths["sections"] / "03_method.tex").write_text("\\input{owned/method_visual}")
    placements = section_asset_placements(tmp_path, sections[1:])
    assert not any(item.stage == "method" for item in placements)


def test_main_preamble_canonical_graphicspath_resolves_bare_registered_pdf(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    (paths["sections"] / "03_method.tex").write_text(_figure("fig:method-architecture", "method_architecture.pdf"))
    assert not any(item.stage == "method" for item in section_asset_placements(tmp_path, sections[1:]))


@pytest.mark.parametrize("mode", ["bare_ref", "comment", "wrong_graphic", "bare_label"])
def test_references_comments_or_mismatched_labels_cannot_hide_a_missing_canonical_figure(tmp_path, mode):
    paths, _specs, sections = _fixture(tmp_path)
    method = paths["sections"] / "03_method.tex"
    if mode == "bare_ref":
        method.write_text("Figure~\\ref{fig:method-architecture} explains the method.")
    elif mode == "comment":
        method.write_text("% " + _figure("fig:method-architecture", "../figures/diagrams/method_architecture.pdf").replace("\n", "\n% "))
    elif mode == "wrong_graphic":
        method.write_text(_figure("fig:method-architecture", "../figures/diagrams/result.pdf"))
    else:
        method.write_text("\\label{fig:method-architecture}")
    if mode in {"wrong_graphic", "bare_label"}:
        with pytest.raises(ValueError, match="not bound"):
            section_asset_placements(tmp_path, sections[1:])
    else:
        assert any(item.stage == "method" for item in section_asset_placements(tmp_path, sections[1:]))


def test_absent_true_selected_producer_block_remains_blocking(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    (paths["paper"] / "generated_evaluation_figures.tex").unlink()
    with pytest.raises(ValueError, match="Missing selected figure fig:evaluation-design"):
        section_asset_placements(tmp_path, sections[1:])


def test_duplicate_selected_inline_labels_are_not_silently_deduplicated(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    block = _figure("fig:method-architecture", "../figures/diagrams/method_architecture.pdf")
    (paths["sections"] / "03_method.tex").write_text(block + block)
    with pytest.raises(ValueError, match="duplicated"):
        section_asset_placements(tmp_path, sections[1:])


def test_selected_table_portfolio_places_real_method_and_design_tables_and_skips_unregistered_notes(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/study_design.tex", "Unregistered pure design-record prose.")
    _write(tmp_path, "paper/tables/method_components.tex", _table("tab:method-components"))
    _write(tmp_path, "paper/tables/selected_design.tex", _table("tab:registered-design"))
    _records(tmp_path, [{"label": "tab:method-components", "scientific_role": "method_components",
                        "latex_path": "paper/tables/method_components.tex", "paper_selected": True},
                       {"label": "tab:registered-design", "scientific_role": "study_design",
                        "latex_path": "paper/tables/selected_design.tex", "paper_selected": True}])
    inputs = _manuscript_inputs(paths, sections)
    assert "tables/study_design" not in inputs
    assert inputs.index("tables/method_components") < inputs.index("sections/04_experiments")
    assert inputs.index("sections/04_experiments") < inputs.index("tables/selected_design") < inputs.index("sections/05_results")


def test_unselected_table_or_figure_is_not_added_but_author_used_source_is_preserved(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/unselected.tex", _table("tab:unselected"))
    _records(tmp_path, [{"label": "tab:unselected", "scientific_role": "study_design",
                        "latex_path": "paper/tables/unselected.tex", "paper_selected": False}])
    method = paths["sections"] / "03_method.tex"
    method.write_text("\\input{tables/unselected}\nTable~\\ref{tab:unselected} was authored.")
    before = method.read_bytes()
    inputs = _manuscript_inputs(paths, sections)
    assert "tables/unselected" not in inputs
    assert method.read_bytes() == before


def test_selected_table_cannot_be_plain_prose_or_a_stale_label_alias(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/selected.tex", "A note with \\label{tab:registered} but no scientific table.")
    _records(tmp_path, [{"label": "tab:registered", "scientific_role": "result", "latex_path": "paper/tables/selected.tex"}])
    with pytest.raises(ValueError, match="scientific float inventory"):
        section_asset_placements(tmp_path, sections[1:])


def test_shared_selected_table_file_is_included_once_before_discussion(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/results.tex", _table("tab:primary") + _table("tab:ablation"))
    _records(tmp_path, [{"label": label, "scientific_role": role, "latex_path": "paper/tables/results.tex"}
                       for label, role in (("tab:primary", "result"), ("tab:ablation", "ablation"))])
    inputs = _manuscript_inputs(paths, sections)
    assert inputs.count("\\input{tables/results}") == 1
    assert inputs.index("tables/results") < inputs.index("sections/06_discussion")


def test_current_producer_numbered_table_panels_keep_one_selected_source_include(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/panels.tex", _table("tab:primary") + _table("tab:primary-panel-2"))
    _records(tmp_path, [{"label": label, "scientific_role": "result", "latex_path": "paper/tables/panels.tex"}
                       for label in ("tab:primary", "tab:primary-panel-2")])
    assert _manuscript_inputs(paths, sections).count("\\input{tables/panels}") == 1


@pytest.mark.parametrize("other", ["tab:primary-panel-2", "tab:primary-panel-3", "tab:primary-alias", "tab:different"])
def test_unregistered_or_gapped_table_panel_labels_are_not_canonical_aliases(tmp_path, other):
    paths, _specs, sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/panels.tex", _table("tab:primary") + _table(other))
    _records(tmp_path, [{"label": "tab:primary", "scientific_role": "result", "latex_path": "paper/tables/panels.tex"}])
    with pytest.raises(ValueError, match="exact source-bound"):
        section_asset_placements(tmp_path, sections[1:])


def test_assembly_fragments_are_stable_and_graphics_reachable_from_main(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    first = _manuscript_inputs(paths, sections)
    fragment = paths["paper"] / "assembly_method_figures.tex"
    before, stat = fragment.read_bytes(), fragment.stat().st_mtime_ns
    assert _manuscript_inputs(paths, sections) == first
    assert fragment.read_bytes() == before and fragment.stat().st_mtime_ns == stat
    _write(tmp_path, "paper/main.tex", "\\documentclass{article}\\begin{document}\n" + first + "\n\\end{document}")
    _sha, reachable = latex_source_bundle(paths["paper"])
    assert tmp_path / "figures/diagrams/method_architecture.pdf" in reachable
    assert tmp_path / "figures/diagrams/evaluation_design.pdf" in reachable


def test_changed_canonical_pixels_change_the_assembly_input_fingerprint_without_rewriting_authorship(tmp_path):
    paths, _specs, sections = _fixture(tmp_path)
    before = {path: path.read_bytes() for _name, path in sections}
    first = next(item for item in section_asset_placements(tmp_path, sections[1:]) if item.stage == "method")
    (tmp_path / "figures/diagrams/method_architecture.pdf").write_bytes(b"%PDF-current repaired pixels")
    second = next(item for item in section_asset_placements(tmp_path, sections[1:]) if item.stage == "method")
    assert first.source_sha256 != second.source_sha256
    assert first.text != second.text
    assert all(path.read_bytes() == content for path, content in before.items())
