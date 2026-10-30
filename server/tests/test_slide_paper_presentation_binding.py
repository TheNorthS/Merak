"""PPT reuses verified current paper pixels without relabelling canonical science."""

import copy
import hashlib
import json

import pytest

from server.services import paper_derived_figure_rendering, paper_print_projection
from server.services.paper_derived_figure_binding import stable_json_sha256
from server.services.slide_deck_builder import _figure_frame
from server.services.slide_figures import qualified_standard_figures, referenced_ids_from_figures
from server.services.slide_presentation_projection import project_slide_presentations, slide_figure_inventory
from server.services.slide_sources import slide_source_paths


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(root, name, payload):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def _fixture(root, monkeypatch):
    original = _write(root, "figures/raw_plot.pdf", "Frozen original scientific graphic")
    entry = {"id": "registered_plot", "paper_ready": True, "output_path": "figures/raw_plot.pdf",
        "output_sha256": _sha(original), "metadata": {"semantic_key": "registered_plot", "scientific_role": "result",
            "evidence_status": "executed", "paper_selected": True, "scientific_question": "Source-bound comparison"}}
    paths = {kind: f"paper/derived-figures/registered_plot/figure.{kind}" for kind in ("pdf", "svg", "png", "source")}
    for kind, path in paths.items():
        _write(root, path, "Correct current scientific presentation " + kind)
    provenance = "paper/derived-figures/registered_plot/PROVENANCE.json"
    packet = {"asset_id": "registered_plot", "original_path": entry["output_path"],
        "original_entry_sha256": stable_json_sha256(entry), "output_path": paths["pdf"],
        "derived_paths": paths, "derived_sha256": {kind: _sha(root / path) for kind, path in paths.items()},
        "provenance_path": provenance}
    _write(root, provenance, packet)
    _write(root, "paper/main.tex", r"\includegraphics{derived-figures/registered_plot/figure.pdf}")
    _write(root, "paper/derived-figures/PRINT_PROJECTION.json", {"schema": 1, "packets": [packet]})
    _write(root, "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [entry]})
    _write(root, "figures/SCIENTIFIC_ASSET_PLAN.json", {"evidence_mode": "executed"})
    calls = []

    def validate_print(actual):
        calls.append(("complete_print_projection", actual))
        for candidate in json.loads((actual / "paper/derived-figures/PRINT_PROJECTION.json").read_text())["packets"]:
            issues = paper_derived_figure_rendering.validate_derived_figure(actual, candidate)
            if issues:
                return issues
        return []

    def validate_pixels(actual, candidate):
        calls.append(("complete_derived_pixel_proof", actual, candidate["asset_id"]))
        return []

    monkeypatch.setattr(paper_print_projection, "validate_print_projection", validate_print)
    monkeypatch.setattr(paper_derived_figure_rendering, "validate_derived_figure", validate_pixels)
    return entry, packet, calls


def _bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_canonical_qualification_precedes_current_pixel_projection_without_mutation(tmp_path, monkeypatch):
    entry, packet, calls = _fixture(tmp_path, monkeypatch)
    before, original_entry = _bytes(tmp_path), copy.deepcopy(entry)
    selected = qualified_standard_figures(tmp_path, {"figures": [entry]})
    assert len(selected) == 1 and selected[0]["output_path"] == entry["output_path"]
    assert selected[0]["output_sha256"] == entry["output_sha256"] and selected[0]["metadata"] == entry["metadata"]
    binding = selected[0]["slide_presentation"]
    assert binding["output_path"] == packet["output_path"]
    assert binding["canonical_asset_id"] == "registered_plot" and binding["workflow_acceptance_granted"] is False
    assert calls == [("complete_print_projection", tmp_path), ("complete_derived_pixel_proof", tmp_path, "registered_plot")]
    assert _bytes(tmp_path) == before and entry == original_entry
    (tmp_path / entry["output_path"]).write_text("Untrusted changed canonical pixels")
    calls.clear()
    assert qualified_standard_figures(tmp_path, {"figures": [entry]}) == []
    assert not qualified_standard_figures(tmp_path, {"figures": [entry]})


def test_native_fallback_model_inventory_and_reference_gate_use_only_current_presentation(tmp_path, monkeypatch):
    entry, packet, _calls = _fixture(tmp_path, monkeypatch)
    qualified = qualified_standard_figures(tmp_path, {"figures": [entry]})
    frame = _figure_frame("Source-grounded figure", qualified[0])
    assert "../" + packet["output_path"] in frame and "../" + entry["output_path"] not in frame
    assert referenced_ids_from_figures(tmp_path, frame, qualified) == ["registered_plot"]
    assert referenced_ids_from_figures(tmp_path, r"\includegraphics{../figures/raw_plot.pdf}", qualified) == []
    inventory = slide_figure_inventory(tmp_path)
    assert "registered_plot: ../" + packet["output_path"] in inventory
    assert "../figures/raw_plot.pdf" not in inventory
    sources = {path.relative_to(tmp_path).as_posix() for path in slide_source_paths(tmp_path)}
    assert {"paper/derived-figures/PRINT_PROJECTION.json", packet["provenance_path"], *packet["derived_paths"].values()} <= sources


@pytest.mark.parametrize("failure", ["print_closure", "derived_pixels", "forged_pdf", "changed_canonical", "missing_receipt"])
def test_missing_stale_or_forged_current_projection_never_falls_back_to_original(tmp_path, monkeypatch, failure):
    entry, packet, _calls = _fixture(tmp_path, monkeypatch)
    if failure == "print_closure":
        monkeypatch.setattr(paper_print_projection, "validate_print_projection", lambda _root: ["Current paper source closure is stale"])
    elif failure == "derived_pixels":
        monkeypatch.setattr(paper_derived_figure_rendering, "validate_derived_figure", lambda *_args: ["Derived pixel proof is forged"])
    elif failure == "forged_pdf":
        (tmp_path / packet["output_path"]).write_text("Changed derived pixels")
    elif failure == "changed_canonical":
        entry["output_sha256"] = "b" * 64
    elif failure == "missing_receipt":
        (tmp_path / "paper/derived-figures/PRINT_PROJECTION.json").unlink()
    with pytest.raises(ValueError, match="presentation|projection"):
        project_slide_presentations(tmp_path, [entry])


def test_no_paper_projection_keeps_existing_canonical_selection(tmp_path):
    output = _write(tmp_path, "figures/canonical.pdf", "Canonical figure")
    entry = {"id": "method", "paper_ready": True, "output_path": "figures/canonical.pdf",
        "output_sha256": _sha(output), "metadata": {"semantic_key": "method", "evidence_status": "implemented_design"}}
    before = _bytes(tmp_path)
    assert qualified_standard_figures(tmp_path, {"figures": [entry]}) == [entry]
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize('extension', ['.pdf', ''])
def test_graphicspath_binds_current_derived_figure_without_rewriting_tex(tmp_path, monkeypatch, extension):
    entry, _packet, _calls = _fixture(tmp_path, monkeypatch)
    qualified = qualified_standard_figures(tmp_path, {'figures': [entry]})
    text = r'\graphicspath{{../paper/derived-figures/}}\includegraphics[width=.8\textwidth]{registered_plot/figure' + extension + '}'
    before = _bytes(tmp_path)
    assert referenced_ids_from_figures(tmp_path, text, qualified) == ['registered_plot']
    assert _bytes(tmp_path) == before


def test_graphicspath_does_not_bind_a_shadowed_or_commented_qualified_figure(tmp_path, monkeypatch):
    entry, _packet, _calls = _fixture(tmp_path, monkeypatch)
    qualified = qualified_standard_figures(tmp_path, {'figures': [entry]})
    _write(tmp_path, 'slides/registered_plot/figure.pdf', 'Unqualified shadow')
    text = r'\graphicspath{{../paper/derived-figures/}}\includegraphics{registered_plot/figure.pdf}'
    assert referenced_ids_from_figures(tmp_path, text, qualified) == []
    assert referenced_ids_from_figures(tmp_path, '% ' + text, qualified) == []


def test_graphicspath_order_and_declared_extensions_choose_the_actual_file(tmp_path, monkeypatch):
    entry, _packet, _calls = _fixture(tmp_path, monkeypatch)
    qualified = qualified_standard_figures(tmp_path, {'figures': [entry]})
    _write(tmp_path, 'slides/shadow/registered_plot/figure.pdf', 'Unqualified shadow')
    prefix = r'\graphicspath{{shadow/}{../paper/derived-figures/}}'
    assert referenced_ids_from_figures(tmp_path, prefix + r'\includegraphics{registered_plot/figure}', qualified) == []


def test_default_extension_priority_precedes_graphics_search_directory(tmp_path, monkeypatch):
    entry, _packet, _calls = _fixture(tmp_path, monkeypatch)
    qualified = qualified_standard_figures(tmp_path, {'figures': [entry]})
    _write(tmp_path, 'slides/registered_plot/figure.png', 'Different local PNG')
    text = r'\graphicspath{{../paper/derived-figures/}}\includegraphics{registered_plot/figure}'
    assert referenced_ids_from_figures(tmp_path, text, qualified) == ['registered_plot']
    prefix = r'\graphicspath{{../paper/derived-figures/}}\DeclareGraphicsExtensions{.png,.pdf}'
    assert referenced_ids_from_figures(tmp_path, prefix + r'\includegraphics{registered_plot/figure}', qualified) == []


def test_inactive_historical_receipt_is_not_the_current_paper_presentation(tmp_path, monkeypatch):
    entry, _packet, calls = _fixture(tmp_path, monkeypatch)
    (tmp_path / "paper/main.tex").write_text(r"\includegraphics{../figures/raw_plot.pdf}")
    (tmp_path / "paper/derived-figures/PRINT_PROJECTION.json").write_text("Obsolete historical receipt")
    before = _bytes(tmp_path)
    assert project_slide_presentations(tmp_path, [entry]) == [entry]
    assert calls == [] and _bytes(tmp_path) == before


@pytest.mark.asyncio
async def test_real_native_print_projection_drives_slide_paths_and_resigned_wrong_pixels_remain_blocking(tmp_path):
    import fitz
    from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
    from server.services.paper_print_projection import install_print_projection, validate_print_projection
    from server.tests.test_paper_derived_figure_rendering import _entry, _placement

    entry = _entry(tmp_path)
    entry["metadata"].update(evidence_status="executed", scientific_role="result", paper_selected=True)
    _write(tmp_path, "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [entry]})
    _write(tmp_path, "figures/SCIENTIFIC_ASSET_PLAN.json", {"evidence_mode": "executed"})
    original_files = {path: path.read_bytes() for name in ("figures", "experiments")
                      for path in (tmp_path / name).rglob("*") if path.is_file()}
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    install_print_projection(tmp_path, [packet])
    assert validate_derived_figure(tmp_path, packet) == []
    assert validate_print_projection(tmp_path) == []
    before = _bytes(tmp_path)
    qualified = qualified_standard_figures(tmp_path, {"figures": [entry]})
    frame = _figure_frame("Registered comparison", qualified[0])
    assert "../" + packet["output_path"] in frame
    assert referenced_ids_from_figures(tmp_path, frame, qualified) == [entry["id"]]
    assert referenced_ids_from_figures(tmp_path, r"\includegraphics{../" + entry["output_path"] + "}", qualified) == []
    assert _bytes(tmp_path) == before
    assert all(path.read_bytes() == content for path, content in original_files.items())
    path = tmp_path / packet["derived_paths"]["pdf"]
    with fitz.open(path) as document:
        document[0].insert_text((30, 35), "Fabricated endpoint 0.999", fontsize=20)
        forged = document.tobytes()
    path.write_bytes(forged)
    packet["derived_sha256"]["pdf"] = _sha(path)
    _write(tmp_path, packet["provenance_path"], packet)
    receipt = json.loads((tmp_path / "paper/derived-figures/PRINT_PROJECTION.json").read_text())
    receipt["packets"] = [packet]
    _write(tmp_path, "paper/derived-figures/PRINT_PROJECTION.json", receipt)
    tampered = _bytes(tmp_path)
    with pytest.raises(ValueError, match="pixels|source.*projection|presentation is not current"):
        qualified_standard_figures(tmp_path, {"figures": [entry]})
    assert _bytes(tmp_path) == tampered
