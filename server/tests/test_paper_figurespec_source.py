"""Native temporary FigureSpec provenance, never models or accepted user state."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.services.deterministic_figure_builder import ensure_evaluation_design
from server.services.figure_artifacts import figure_artifact_registry
from server.services.paper_derived_figure_binding import bound_original_inputs, file_sha256, pdf_print_geometry
from server.services.paper_derived_figure_rendering import derive_paper_figure, validate_derived_figure
from server.services.paper_figurespec_source import figurespec_svg_source
from server.tests.test_deterministic_architecture_integration import _Host
from server.tests._figure_workflow_support import _seed_project
from server.tests.test_paper_derived_figure_rendering import _placement


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def _native(root: Path) -> dict:
    """The real local native producer records all source pins and four variants."""
    from server.services.scientific_assets import scientific_asset_service
    from server.services.figure_spec_repository import persist_figure_specs

    _seed_project(root)
    plan = scientific_asset_service.build_plan(root, experiment_requested=False)
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    scientific = list(method["source_data"])
    for index in range(13 - len(scientific)):
        path = root / f"experiments/registered-source-{index:02}.txt"
        path.write_text(f"Explicit local immutable source {index}; never executed.\n", encoding="utf-8")
        scientific.append(path.relative_to(root).as_posix())
    method["source_data"] = scientific
    _json(root / "figures/SCIENTIFIC_ASSET_PLAN.json", plan)
    spec = next(item for item in persist_figure_specs(root, plan) if item["id"] == "method_architecture")
    await ensure_evaluation_design(_Host(), object(), root / "figures", [spec], plan, set(), figure_artifact_registry)
    entry = figure_artifact_registry.load(root / "figures", strict=True)["figures"][0]
    paper = root / "paper/main.tex"
    paper.parent.mkdir(exist_ok=True)
    paper.write_text(r"\documentclass{article}" + "\n" + r"\textwidth 396bp\begin{document}"
        + r"\begin{figure*}\includegraphics[width=.94\textwidth]{../" + entry["output_path"]
        + r"}\caption{Registered scientific method}\label{fig:registered-method}\end{figure*}\end{document}", encoding="utf-8")
    return entry


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.asyncio
async def test_native_four_variants_and_thirteen_sources_resolve_without_any_rebinding(tmp_path):
    entry = await _native(tmp_path)
    before = _files(tmp_path)
    metadata = entry["metadata"]
    assert set(metadata["rendered_variants"]) == {"json", "svg", "pdf", "png"}
    assert metadata.get("source_data_sha256") is None and len(metadata["source_bindings"]) == 13
    bound, inventory = bound_original_inputs(tmp_path, entry)
    svg, expected, payload = figurespec_svg_source(tmp_path, entry)
    assert svg.read_bytes() == expected and payload == json.loads((tmp_path / entry["source_path"]).read_text())
    assert set(metadata["rendered_variants"].values()).issubset(bound)
    assert set(metadata["source_data"]).issubset(bound) and inventory == []
    assert _files(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["missing_json", "extra_variant", "missing_hash", "json_path", "source_hash",
    "missing_binding", "duplicate_binding", "bad_binding", "changed_source", "changed_svg", "changed_json",
    "fake_svg_resigned", "fake_json_resigned", "producer_hash", "backend", "renderer", "mapping", "foreign_entry"])
async def test_untrusted_native_source_cannot_enter_paper_projection_or_modify_evidence(tmp_path, defect):
    entry = await _native(tmp_path)
    changed = copy.deepcopy(entry)
    metadata = changed["metadata"]
    variants, hashes = metadata["rendered_variants"], metadata["rendered_variant_sha256"]
    if defect == "missing_json":
        variants.pop("json")
        hashes.pop("json")
    elif defect == "extra_variant":
        variants["unknown"] = variants["svg"]
        hashes["unknown"] = hashes["svg"]
    elif defect == "missing_hash": hashes.pop("svg")
    elif defect == "json_path": variants["json"] = variants["svg"]
    elif defect == "source_hash": metadata["source_bindings"][0]["sha256"] = "0" * 64
    elif defect == "missing_binding": metadata["source_bindings"].pop()
    elif defect == "duplicate_binding": metadata["source_bindings"][-1] = metadata["source_bindings"][0]
    elif defect == "bad_binding": metadata["source_bindings"][0]["status"] = "missing"
    elif defect == "changed_source": (tmp_path / metadata["source_data"][0]).write_text("Changed scientific source")
    elif defect in {"changed_svg", "fake_svg_resigned"}:
        import xml.etree.ElementTree as ET

        path = tmp_path / variants["svg"]
        tree = ET.fromstring(path.read_bytes())
        next(node for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "text").text = "Fabricated scientific label"
        path.write_bytes(ET.tostring(tree, encoding="utf-8"))
        if defect == "fake_svg_resigned": hashes["svg"] = file_sha256(path)
    elif defect in {"changed_json", "fake_json_resigned"}:
        path = tmp_path / changed["source_path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["nodes"][0]["label"] = "Fabricated scientific object"
        _json(path, payload)
        if defect == "fake_json_resigned": changed["source_sha256"] = hashes["json"] = file_sha256(path)
    elif defect == "producer_hash": metadata["producer_input_sha256"] = "0" * 64
    elif defect == "backend": metadata["recommended_backend"] = "unknown"
    elif defect == "renderer": metadata["renderer"] = "unknown"
    elif defect == "mapping": metadata["element_mappings"][0]["source_path"] = metadata["source_data"][1]
    else: changed["id"] = "foreign-canonical-source"
    if defect != "foreign_entry":
        _json(tmp_path / "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [changed]})
    before = _files(tmp_path)
    with pytest.raises(ValueError):
        figurespec_svg_source(tmp_path, changed)
    assert _files(tmp_path) == before
    assert not (tmp_path / "paper/derived-figures").exists()


@pytest.mark.asyncio
async def test_native_paper_projection_keeps_canonical_json_identity_and_rejects_resigned_wrong_pixels(tmp_path):
    import fitz
    from server.services import paper_print_projection

    entry = await _native(tmp_path)
    before = {p: p.read_bytes() for folder in ("figures", "experiments")
              for p in (tmp_path / folder).rglob("*") if p.is_file()}
    packet = await derive_paper_figure(tmp_path, entry, _placement(tmp_path, entry))
    assert packet["source"] == entry["source_path"] and packet["source"].endswith(".json")
    assert packet["source_path"].endswith(".svg") and len(packet["original_inputs_sha256"]) >= 17
    assert validate_derived_figure(tmp_path, packet) == []
    measured = pdf_print_geometry(tmp_path / packet["output_path"], packet["print_placement"])
    assert measured["minimum_placed_font_bp"] >= 8.5 and measured["text_geometry_findings"] == []
    native = json.loads((tmp_path / entry["source_path"]).read_text(encoding="utf-8"))
    svg_text = (tmp_path / packet["source_path"]).read_text(encoding="utf-8")
    for node in native["nodes"]:
        assert all(word in svg_text for word in node["label"].split())
    paper_print_projection.install_print_projection(tmp_path, [packet])
    assert paper_print_projection.validate_print_projection(tmp_path) == []
    assert all(p.read_bytes() == raw for p, raw in before.items())
    output = tmp_path / packet["output_path"]
    with fitz.open(output) as document:
        document[0].insert_text((40, 50), "Forged 0.999", fontsize=40)
        changed = document.tobytes()
    output.write_bytes(changed)
    packet["derived_sha256"]["pdf"] = file_sha256(output)
    _json(tmp_path / packet["provenance_path"], packet)
    assert any("pixels" in issue for issue in validate_derived_figure(tmp_path, packet))
    assert all(p.read_bytes() == raw for p, raw in before.items())
