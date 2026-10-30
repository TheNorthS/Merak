"""Non-compatible visual-blueprint contract for publication SVGs."""

import xml.etree.ElementTree as ET
from pathlib import Path

from server.agent.tools.tool_registration import (
    MECHANISM_IR_TOOL_SCHEMA,
    VISUAL_BLUEPRINT_TOOL_SCHEMA,
)
from server.services.rich_svg_blueprint import (
    FLOW_KIND_VALUES,
    MIN_BLUEPRINT_PRIMITIVES,
    MIN_BLUEPRINT_VISUAL_FORMS,
    STORYBOARD_FLOW_KIND_DEFAULTS,
    VISUAL_FORM_VALUES,
    blueprint_minimums,
    blueprint_svg_issues,
    validate_visual_blueprint,
)
from server.services.scientific_asset_builders import _mechanism_detail_asset


def _blueprint() -> dict:
    primitives = [
        {"id": name, "visual_form": form, "public_label": name.replace("_", " ").title(),
         "role": role, "annotations": [], "scientific_meaning": meaning}
        for name, form, role, meaning in (
            ("input_signal", "signal", "source", "Observed scientific input"),
            ("encoded_state", "tensor", "focal_process", "Learned intermediate state"),
            ("interaction", "matrix", "interaction", "Pairwise mechanism interaction"),
            ("secondary_branch", "graph", "interaction", "Complementary scientific relation"),
            ("operative_rule", "equation", "synthesis", "Formal mechanism relation"),
            ("output_state", "distribution", "output", "Resulting scientific output"),
        )
    ]
    return {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_level": "mechanism_detail",
        "figure_label": "Shared interaction mechanism",
        "focal_message": "A shared state is transformed by an explicit interaction rule",
        "primitives": primitives,
        "reading_order": [item["id"] for item in primitives],
        "flows": [
            {"from": primitives[index]["id"], "to": primitives[index + 1]["id"], "kind": "causal"}
            for index in range(len(primitives) - 1)
        ],
        "formal_relation": "output = rule(interaction(encoded(input)))",
    }


def test_blueprint_requires_domain_native_visual_variety() -> None:
    blueprint, issues = validate_visual_blueprint(_blueprint())
    assert not issues
    assert blueprint["narrative_level"] == "mechanism_detail"
    assert "primitives" in VISUAL_BLUEPRINT_TOOL_SCHEMA["required"]


def test_tool_schemas_share_runtime_visual_and_flow_enums() -> None:
    blueprint_properties = VISUAL_BLUEPRINT_TOOL_SCHEMA["properties"]
    primitive_schema = blueprint_properties["primitives"]
    flow_schema = blueprint_properties["flows"]
    mechanism_properties = MECHANISM_IR_TOOL_SCHEMA["properties"]

    assert primitive_schema["minItems"] == 1
    assert MIN_BLUEPRINT_PRIMITIVES == 4
    assert tuple(
        primitive_schema["items"]["properties"]["visual_form"]["enum"]
    ) == VISUAL_FORM_VALUES
    assert tuple(flow_schema["items"]["properties"]["kind"]["enum"]) == (
        FLOW_KIND_VALUES
    )
    assert tuple(
        mechanism_properties["primitives"]["items"]["properties"]
        ["visual_form"]["enum"]
    ) == VISUAL_FORM_VALUES
    assert tuple(
        mechanism_properties["flows"]["items"]["properties"]["kind"]["enum"]
    ) == FLOW_KIND_VALUES


def test_test99_aliases_are_rejected_with_actionable_canonical_values() -> None:
    invalid_forms = {
        "signal_trace", "token_grid", "comparison_node", "waveform",
        "diamond", "bar_chart", "arrow",
    }
    invalid_flows = {"main", "feedback", "side_output"}
    primitive_enum = set(
        VISUAL_BLUEPRINT_TOOL_SCHEMA["properties"]["primitives"]["items"]
        ["properties"]["visual_form"]["enum"]
    )
    flow_enum = set(
        VISUAL_BLUEPRINT_TOOL_SCHEMA["properties"]["flows"]["items"]
        ["properties"]["kind"]["enum"]
    )
    assert invalid_forms.isdisjoint(primitive_enum)
    assert invalid_flows.isdisjoint(flow_enum)

    value = _blueprint()
    value["primitives"][0]["visual_form"] = "waveform"
    value["flows"][0]["kind"] = "main"
    _normalized, issues = validate_visual_blueprint(value)
    message = "; ".join(issues)
    assert "unsupported visual forms: waveform" in message
    assert "accepted visual_form values: " + ", ".join(VISUAL_FORM_VALUES) in message
    assert "unsupported kind 'main'" in message
    assert "accepted flow kind values: " + ", ".join(FLOW_KIND_VALUES) in message


def test_four_primitive_blueprint_matches_schema_minimum() -> None:
    value = _blueprint()
    value["primitives"] = [
        value["primitives"][index] for index in (0, 1, 2, 5)
    ]
    identities = [item["id"] for item in value["primitives"]]
    value["reading_order"] = identities
    value["flows"] = [
        {"from": identities[index], "to": identities[index + 1], "kind": "causal"}
        for index in range(len(identities) - 1)
    ]

    _normalized, issues = validate_visual_blueprint(value)

    assert issues == []


def test_source_scoped_two_object_scene_uses_one_edge_minimum() -> None:
    spec = {
        "scientific_role": "method",
        "scientific_scene": {
            "objects": [
                {"id": "input", "kind": "input", "label": "Input"},
                {"id": "method", "kind": "operation", "label": "Method"},
            ],
            "relations": [{"from": "input", "to": "method", "kind": "data"}],
        },
    }
    value = {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_level": "method_overview",
        "figure_label": "Compact method",
        "focal_message": "Input is transformed by the method",
        "primitives": [
            {"id": "input", "visual_form": "signal", "public_label": "Input",
             "role": "source", "annotations": [], "scientific_meaning": "Input"},
            {"id": "method", "visual_form": "algorithm", "public_label": "Method",
             "role": "focal_process", "annotations": [], "scientific_meaning": "Method"},
        ],
        "reading_order": ["input", "method"],
        "flows": [{"from": "input", "to": "method", "kind": "data"}],
    }
    assert blueprint_minimums(spec).flows == 1
    _normalized, issues = validate_visual_blueprint(value, source_spec=spec)
    assert issues == []


def test_legacy_blueprint_keeps_four_object_floor_without_source_spec() -> None:
    value = _blueprint()
    value["primitives"] = value["primitives"][:3]
    value["reading_order"] = [item["id"] for item in value["primitives"]]
    value["flows"] = [
        {"from": value["primitives"][index]["id"],
         "to": value["primitives"][index + 1]["id"], "kind": "causal"}
        for index in range(2)
    ]
    _normalized, issues = validate_visual_blueprint(value)
    assert any("at least 4 identified" in issue for issue in issues)


def test_structural_scene_does_not_require_invented_directed_flow() -> None:
    spec = {
        "scientific_role": "method",
        "scientific_scene": {
            "objects": [
                {"id": "whole", "kind": "operation", "label": "Whole"},
                {"id": "part", "kind": "state", "label": "Part"},
            ],
            "relations": [
                {"from": "whole", "to": "part", "kind": "containment"},
            ],
        },
    }
    assert blueprint_minimums(spec).flows == 0


def test_model_svg_skill_lists_canonical_values_and_storyboard_mapping() -> None:
    skill = (
        Path(__file__).parents[2] / "merak-skills" / "model-svg-figure" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for value in (*VISUAL_FORM_VALUES, *FLOW_KIND_VALUES):
        assert f"`{value}`" in skill
    for storyboard_kind, blueprint_kind in STORYBOARD_FLOW_KIND_DEFAULTS.items():
        assert f"`{storyboard_kind}` -> `{blueprint_kind}`" in skill


def test_method_blueprint_does_not_require_neural_network_topology() -> None:
    value = _blueprint()
    value["primitives"] = [
        {"id": "specimen", "visual_form": "cohort", "public_label": "Eligible specimen",
         "role": "source", "annotations": [], "scientific_meaning": "Biological source"},
        {"id": "intervention", "visual_form": "apparatus", "public_label": "Controlled exposure",
         "role": "control", "annotations": [], "scientific_meaning": "Controlled perturbation"},
        {"id": "transition", "visual_form": "state_trace", "public_label": "State transition",
         "role": "focal_process", "annotations": [], "scientific_meaning": "Biological process"},
        {"id": "interaction", "visual_form": "graph", "public_label": "Pathway interaction",
         "role": "interaction", "annotations": [], "scientific_meaning": "Coupled response"},
        {"id": "readout", "visual_form": "distribution", "public_label": "Assay readout",
         "role": "readout", "annotations": [], "scientific_meaning": "Measured consequence"},
    ]
    value["reading_order"] = [item["id"] for item in value["primitives"]]
    value["flows"] = [
        {"from": value["primitives"][index]["id"],
         "to": value["primitives"][index + 1]["id"], "kind": "causal"}
        for index in range(len(value["primitives"]) - 1)
    ]
    _normalized, issues = validate_visual_blueprint(value)
    assert issues == []


def test_blueprint_accepts_wrappable_publication_labels() -> None:
    value = _blueprint()
    value["primitives"][2]["public_label"] = (
        "Acquisition-heterogeneity interaction"
    )
    value["primitives"][3]["public_label"] = (
        "Leakage-safe cross-domain evaluation"
    )

    _normalized, issues = validate_visual_blueprint(value)

    assert not any("concise public_label" in issue for issue in issues)


def test_blueprint_rejects_text_card_wall() -> None:
    value = _blueprint()
    for primitive in value["primitives"]:
        primitive["visual_form"] = "card"
    _blueprint_value, issues = validate_visual_blueprint(value)
    assert any("unsupported visual forms" in issue for issue in issues)
    assert any(
        f"{MIN_BLUEPRINT_VISUAL_FORMS} distinct" in issue for issue in issues
    )


def test_blueprint_groups_must_exist_in_authored_svg() -> None:
    blueprint, _issues = validate_visual_blueprint(_blueprint())
    issues = blueprint_svg_issues(
        blueprint, ET.fromstring(
            '<svg><g id="input_signal"><path d="M0 0L1 1"/></g>'
            '<g id="encoded_state"><rect/></g>'
            '<g id="interaction"><rect/></g>'
            '<g id="secondary_branch"><circle/></g>'
            '<g id="operative_rule"><text>Rule</text><path d="M0 0L1 1"/></g></svg>'
        ),
    )
    assert issues == ["SVG is missing visual_blueprint groups: output_state"]


def test_blueprint_groups_are_semantic_anchors_not_geometry_templates() -> None:
    blueprint, _issues = validate_visual_blueprint(_blueprint())
    svg = ET.fromstring(
        '<svg>' + ''.join(
            f'<g id="{item["id"]}"><text>Named concept</text></g>'
            for item in blueprint["primitives"]
        ) + '</svg>'
    )
    assert blueprint_svg_issues(blueprint, svg) == []


def test_authored_svg_must_materialize_every_scientific_primitive() -> None:
    blueprint = _blueprint()
    root = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg">' + ''.join(
            f'<g id="{item["id"]}"><path d="M0 0L1 1"/></g>'
            for item in blueprint["primitives"]
        ) + '</svg>'
    )
    assert blueprint_svg_issues(blueprint, root) == []


def test_complex_method_gets_focused_detail_without_forcing_other_fields() -> None:
    from server.services.scientific_asset_portfolio import figure_portfolio

    context = {
        "claims": [{"id": "C1"}],
        "mechanisms": [{"name": "Selective interaction"}],
    }
    publication = {"language": "en"}
    story = {
        "contribution_type": "model_architecture", "preferred_backend": "rich_svg",
        "minimum_placed_font_pt": 8.0,
        "figure_portfolio": figure_portfolio({
            "contribution_type": "model_architecture",
            "required_figure_assets": ["core_mechanism"],
        }),
    }
    detail = _mechanism_detail_asset(
        context, {}, publication, story, {
            "schema": 1,
            "objects": [
                {"id": "input", "kind": "input", "label": "Input", "source_path": "a"},
                {"id": "mechanism", "kind": "operation", "label": "Mechanism", "source_path": "a"},
            ],
            "relations": [{"from": "input", "to": "mechanism", "kind": "data"}],
        }, ["experiments/METHOD_CONTRACT.json"], True,
    )
    assert detail is not None
    assert detail["id"] == "core_mechanism"
    assert detail["scene_contract"]["narrative_level"] == "mechanism_detail"
    assert detail["preferred_backend"] == "rich_svg"
    assert detail["layout_plan"]["split_required"] is False
    assert _mechanism_detail_asset(
        context, {}, publication,
        {
            **story,
            "contribution_type": "qualitative_framework",
            "figure_portfolio": figure_portfolio({
                "contribution_type": "qualitative_framework",
            }),
        }, {}, [], True,
    ) is None
