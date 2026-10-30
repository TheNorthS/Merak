"""Pure geometry regressions for containment and complete box extents."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pytest

from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene_figure import ScientificSceneFigureError, compile_scientific_scene_figure
from server.services.scientific_scene_placement import normalize_placement, relation_ranks


@pytest.fixture(scope="module")
def renderer():
    path = Path(__file__).resolve().parents[2] / "merak-skills/figure-spec/scripts/figure_renderer.py"
    spec = importlib.util.spec_from_file_location("figure105_test_renderer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _asset(count: int, relations: list[dict], *, long_labels: bool = False) -> dict:
    labels = [
        "Cross-condition representation with separated nuisance variation",
        "Sensor-informed temporal encoding and semantic fusion",
        "Paired perturbation consistency for stable latent representation",
        "Disentangled acquisition variation under matched observations",
        "Orthogonal residual separation with coordinated alignment",
        "Independent component fusion for structured representation",
        "Bounded intervention invariance across alternate observations",
        "Contrastive semantic alignment under source-preserving controls",
    ]
    return {
        "id": "method_architecture", "scientific_role": "method",
        "scene_contract": {"complexity_budget": {"maximum_primary_objects": 8}},
        "scientific_scene": {
            "schema": 1,
            "objects": [{
                "id": f"object_{index}", "kind": "operation",
                "label": labels[index] if long_labels else f"Semantic component {index + 1}",
                "source_path": "ideas/SELECTED_IDEA.json",
            } for index in range(count)],
            "relations": relations,
        },
    }


def _edge(source: int, target: int, kind: str = "containment") -> dict:
    return {"from": f"object_{source}", "to": f"object_{target}", "kind": kind}


def _assert_preserved(asset: dict, spec: dict) -> None:
    assert figurespec_layout_issues_payload(spec) == []
    assert {item["id"] for item in spec["nodes"]} == {
        item["id"] for item in asset["scientific_scene"]["objects"]
    }
    assert {(item["from"], item["to"], item["scientific_kind"]) for item in spec["edges"]} == {
        (item["from"], item["to"], item["kind"]) for item in asset["scientific_scene"]["relations"]
    }
    assert {item["label"] for item in spec["nodes"]} == {
        item["label"] for item in asset["scientific_scene"]["objects"]
    }
    assert min(item["font_size"] for item in spec["nodes"]) == 20
    assert 20 * 468 / spec["canvas"]["width"] >= 8


@pytest.mark.parametrize("count", range(2, 9))
@pytest.mark.parametrize("long_labels", [False, True])
def test_containment_star_keeps_two_to_eight_authored_objects(count: int, long_labels: bool, renderer) -> None:
    asset = _asset(count, [_edge(0, index) for index in range(1, count)], long_labels=long_labels)
    compilation = compile_scientific_scene_figure(asset)
    _assert_preserved(asset, compilation.spec)
    assert compilation.profile["layout_strategy"] == "containment-composition"
    svg = fromstring(renderer.render_svg(compilation.spec))
    visible = " ".join((item.text or "") for item in svg.iter() if item.tag.endswith("text"))
    assert "..." not in visible
    assert all(item["label"] in visible for item in asset["scientific_scene"]["objects"])
    connectors = [item for item in svg.iter() if item.attrib.get("data-relation-kind") == "containment"]
    assert len(connectors) == count - 1
    assert all("marker-end" not in item.attrib and "marker-start" not in item.attrib for item in connectors)
    diamonds = [item for item in svg.iter() if item.attrib.get("data-relation-marker") == "containment-parent"]
    assert len(diamonds) == count - 1


@pytest.mark.parametrize("count", range(2, 9))
def test_containment_chain_is_ranked_and_remains_inside_canvas(count: int) -> None:
    asset = _asset(count, [_edge(index, index + 1) for index in range(count - 1)], long_labels=True)
    ranks = relation_ranks(asset["scientific_scene"]["objects"], asset["scientific_scene"]["relations"])
    assert ranks == {f"object_{index}": index for index in range(count)}
    _assert_preserved(asset, compile_scientific_scene_figure(asset).spec)


@pytest.mark.parametrize("count", [3, 4, 5, 6, 7, 8])
def test_feedback_cycle_does_not_draw_through_intermediate_components(count: int) -> None:
    edges = [_edge(index, index + 1, "data") for index in range(count - 1)]
    edges.append(_edge(count - 1, 0, "feedback"))
    asset = _asset(count, edges)
    _assert_preserved(asset, compile_scientific_scene_figure(asset).spec)


def test_mixed_hierarchy_with_control_keeps_every_node_and_relation() -> None:
    asset = _asset(5, [_edge(0, 1), _edge(0, 2), _edge(1, 3, "data"), _edge(4, 1, "control")])
    spec = compile_scientific_scene_figure(asset).spec
    _assert_preserved(asset, spec)
    assert next(item for item in spec["nodes"] if item["id"] == "object_4")["height"] == 110
    assert all(item["height"] == 140 for item in spec["nodes"] if item["id"] != "object_4")


def test_nested_containment_branches_keep_the_authored_parentage() -> None:
    asset = _asset(7, [_edge(0, 1), _edge(0, 2), _edge(1, 3), _edge(1, 4), _edge(2, 5), _edge(2, 6)])
    _assert_preserved(asset, compile_scientific_scene_figure(asset).spec)


def test_test105_authored_scene_is_compiled_without_dropping_semantics() -> None:
    labels = ["SSD-LP", "Source-constrained latent factorization", "Restricted task readout",
              "Structured contextual latent prediction", "Tri-axis transfer adjudication"]
    identities = ["planned_method", *(f"declared_mechanism_{index}" for index in range(1, 5))]
    asset = _asset(5, [])
    for item, identity, label in zip(asset["scientific_scene"]["objects"], identities, labels):
        item.update({"id": identity, "label": label})
    asset["scientific_scene"]["relations"] = [
        {"from": identities[0], "to": identity, "kind": "containment"}
        for identity in identities[1:]
    ]
    compilation = compile_scientific_scene_figure(asset)
    _assert_preserved(asset, compilation.spec)
    assert compilation.profile["layout_strategy"] == "containment-composition"


def test_extents_normalization_translates_negative_coordinates_not_just_centers() -> None:
    positions = {"left": (-92, -170, 330), "right": (1072, 510, 245)}
    with pytest.raises(ValueError, match="paper-scale typography"):
        normalize_placement((positions, 980, 340), set(), {}, [])
    bounded, width, height = normalize_placement(
        ({"left": (-92, -170, 260), "right": (208, 170, 245)}, 980, 340), set(), {}, [],
    )
    assert width == 980
    assert all(x - box / 2 >= 64 and x + box / 2 <= width - 64 for x, _, box in bounded.values())
    assert all(y - 70 >= 64 and y + 70 <= height - 64 for _, y, _ in bounded.values())


def test_true_overbudget_scene_does_not_drop_objects_to_pass() -> None:
    asset = _asset(8, [_edge(0, index) for index in range(1, 8)])
    asset["scene_contract"]["complexity_budget"]["maximum_primary_objects"] = 7
    with pytest.raises(ScientificSceneFigureError, match="split the authored figure portfolio"):
        compile_scientific_scene_figure(asset)


def test_unreadable_labels_remain_blocking_instead_of_font_shrinking() -> None:
    asset = _asset(5, [_edge(0, index) for index in range(1, 5)])
    asset["scientific_scene"]["objects"][1]["label"] = "Source-grounded " * 8
    with pytest.raises(ScientificSceneFigureError, match="label is too long"):
        compile_scientific_scene_figure(asset)


def test_true_text_overflow_raises_instead_of_ellipsis(renderer) -> None:
    asset = _asset(2, [_edge(0, 1)], long_labels=True)
    spec = compile_scientific_scene_figure(asset).spec
    spec["nodes"][0]["height"] = 30
    with pytest.raises(ValueError, match="complete label"):
        renderer.render_svg(spec)


def test_data_and_causal_edges_keep_arrowheads(renderer) -> None:
    asset = _asset(3, [_edge(0, 1, "data"), _edge(1, 2, "causal")])
    svg = fromstring(renderer.render_svg(compile_scientific_scene_figure(asset).spec))
    connectors = [item for item in svg.iter() if item.attrib.get("data-relation-kind") in {"data", "causal"}]
    assert len(connectors) == 2
    assert all("marker-end" in item.attrib and "marker-start" not in item.attrib for item in connectors)


def test_containment_diamonds_survive_the_pdf_conversion_boundary(renderer) -> None:
    from server.services.svg_variant_conversion import _converter_svg

    asset = _asset(5, [_edge(0, index) for index in range(1, 5)])
    source = renderer.render_svg(compile_scientific_scene_figure(asset).spec).encode()
    converted = fromstring(_converter_svg(source))
    diamonds = [item for item in converted.iter() if item.attrib.get("data-relation-marker") == "containment-parent"]
    assert len(diamonds) == 4
    assert all(item.tag.endswith("polygon") for item in diamonds)
