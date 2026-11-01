"""The failed mixed-control cycle must render without losing edges or label text."""
from copy import deepcopy
from pathlib import Path
import json
import re
from xml.etree.ElementTree import fromstring

import pytest

from server.services.figure_engine import _load_figurespec_renderer
from server.services.figure_semantic_projection import project_figure_semantics
from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.services.scientific_scene_labels import projected_public_labels


@pytest.mark.parametrize("reverse", [False, True])
def test_failed_authored_scene_preserves_projection_and_print_readability(reverse):
    asset = json.loads((Path(__file__).parent / "fixtures/mixed_control_scene.json").read_text(encoding="utf-8"))
    if reverse:
        asset["scientific_scene"]["objects"].reverse()
        asset["scientific_scene"]["relations"].reverse()
    before = deepcopy(asset)
    result = compile_scientific_scene_figure(asset)
    assert asset == before
    assert result.profile["layout_strategy"] == "topology-perimeter"
    assert figurespec_layout_issues_payload(result.spec) == []
    projection = project_figure_semantics(asset)
    assert {n["id"] for n in result.spec["nodes"]} == {o["id"] for o in projection["entities_states_transformations"]}
    assert {(e["from"], e["to"], e["scientific_kind"]) for e in result.spec["edges"]} == {
        (e["from"], e["to"], e["kind"]) for e in projection["relations"]}
    svg = fromstring(_load_figurespec_renderer().render_svg(result.spec))
    texts = " ".join("".join(el.itertext()) for el in svg.iter() if el.tag.endswith("text"))
    for label in projected_public_labels(asset).values():
        assert all(word in texts for word in re.findall(r"[A-Za-z-]+", label))
    for node in result.spec["nodes"]:
        smallest_font = node["font_size"] - (3 if node.get("sublabel") else 0)
        assert smallest_font * 468 / result.spec["canvas"]["width"] >= 8


def test_topology_search_does_not_depend_on_domain_names():
    from server.services.scientific_scene_topology_layout import topology_placements
    objects = [{"id": str(i), "kind": "input" if i == 0 else "operation"} for i in range(5)]
    edges = [{"from": str(a), "to": str(b), "kind": "data"} for a,b in [(0,1),(0,2),(1,4),(2,3),(3,4)]]
    placements = topology_placements(objects, edges, {str(i): "Clinical sample preparation" for i in range(5)})
    assert set(next(placements)[0]) == {str(i) for i in range(5)}


def test_new_layout_code_invalidates_architecture_cache(monkeypatch):
    from server.services import scientific_scene_topology_layout as topology
    from server.services.deterministic_figure_builder import _architecture_code_sha256
    renderer = _load_figurespec_renderer()
    before = _architecture_code_sha256(renderer)
    monkeypatch.setattr(topology, "_noncrossing", lambda *args: False)
    assert before != _architecture_code_sha256(renderer)
