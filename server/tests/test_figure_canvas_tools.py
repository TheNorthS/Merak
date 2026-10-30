"""Hybrid canvas owns global geometry while local scientific glyphs stay editable."""

import json
from pathlib import Path

import pytest

from server.agent.tools.figure_draft_tools import current_draft_matches_storyboard
from server.agent.tools.figure_canvas_tools import (
    append_figure_canvas_primitive,
    finalize_figure_svg_canvas,
    prepare_figure_svg_canvas,
    refresh_figure_canvas_runtime,
    replace_figure_canvas_primitive,
)
from server.agent.tools.figure_storyboard_tools import submit_figure_storyboard
from server.services.figure_mechanism_ir import validate_mechanism_ir
from server.services.figure_mechanism_ir import canonicalize_mechanism_blueprint


def _candidate(
    identity: str, topology: str, regions: list[dict] | None = None,
) -> dict:
    candidate_regions = regions or [
        {"id": "source", "purpose": "Show the scientific source",
         "visual_grammar": "domain source glyph", "relative_weight": 1},
        {"id": "process", "purpose": "Show the focal transformation",
         "visual_grammar": "custom operation glyph", "relative_weight": 4},
        {"id": "synthesis", "purpose": "Show the scientific synthesis",
         "visual_grammar": "formal readout glyph", "relative_weight": 2},
    ]
    reading_order = [str(item["id"]) for item in candidate_regions]
    return {
        "id": identity, "topology": topology,
        "focal_message": "One source enters a focal process and produces one synthesis",
        "regions": candidate_regions,
        "reading_order": reading_order,
        "connections": [
            {
                "id": f"{source}_to_{target}", "from": source, "to": target,
                "kind": "main",
                "scientific_meaning": "Scientific evidence advances to the next region",
            }
            for source, target in zip(reading_order, reading_order[1:])
        ],
        "strengths": [], "risks": [],
    }


def _storyboard(
    root: Path, publication_labels: list[dict] | None = None,
    regions: list[dict] | None = None, selected_id: str = "linear_flow",
) -> None:
    figures = root / "figures"
    figures.mkdir(exist_ok=True)
    (figures / "FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "figures": [{
            "id": "method_architecture", "scientific_role": "method",
            "scientific_question": "How does the focal process transform its source?",
            "publication_labels": publication_labels or [],
            "scientific_scene": {"objects": [], "relations": []},
        }],
    }), encoding="utf-8")
    candidates = [
        _candidate("linear_flow", "linear", regions),
        _candidate("causal_flow", "causal", regions),
        _candidate("hierarchy_flow", "hierarchical", regions),
    ]
    submit_figure_storyboard(
        "method_architecture", candidates, selected_id, "clearest", str(root),
    )


def _mechanism_ir() -> dict:
    primitives = [
        {"id": "observed_source", "region_id": "source", "public_label": "Observed source",
         "role": "source", "visual_form": "signal", "semantic_cues": ["observed evidence"]},
        {"id": "focal_process", "region_id": "process", "public_label": "Focal process",
         "role": "focal_process", "visual_form": "algorithm", "semantic_cues": ["shared transformation"]},
        {"id": "interaction_a", "region_id": "process", "public_label": "Interaction A",
         "role": "interaction", "visual_form": "graph", "notation": "L_A",
         "semantic_cues": ["paired local relation"]},
        {"id": "interaction_b", "region_id": "process", "public_label": "Interaction B",
         "role": "interaction", "visual_form": "matrix", "notation": "L_B",
         "semantic_cues": ["aligned matrix views"]},
        {"id": "final_synthesis", "region_id": "synthesis", "public_label": "Final synthesis",
         "role": "synthesis", "visual_form": "equation", "notation": "y=L_A+L_B",
         "semantic_cues": ["combined objective"]},
    ]
    return {
        "schema": 2, "primitives": primitives,
        "reading_order": [item["id"] for item in primitives],
        "flows": [
            {"id": "source_to_process", "from": "observed_source", "to": "focal_process", "kind": "data", "label": "observed evidence"},
            {"id": "process_to_a", "from": "focal_process", "to": "interaction_a", "kind": "data", "label": "shared state"},
            {"id": "process_to_b", "from": "focal_process", "to": "interaction_b", "kind": "data", "label": "shared state"},
            {"id": "a_to_sum", "from": "interaction_a", "to": "final_synthesis", "kind": "causal", "label": "L_A"},
            {"id": "b_to_sum", "from": "interaction_b", "to": "final_synthesis", "kind": "causal", "label": "L_B"},
        ],
    }


def _dense_mechanism_ir() -> dict:
    primitives = [
        {"id": "eeg_lineage", "region_id": "source_lineage",
         "public_label": "EEG lineage", "role": "source", "visual_form": "signal",
         "notation": "X", "semantic_cues": ["stacked EEG traces", "participant/session split"]},
        {"id": "leakage_safe_cross_domain_evaluation", "region_id": "source_lineage",
         "public_label": "Leakage-safe cross-domain evaluation", "role": "constraint",
         "visual_form": "constraint", "notation": "S",
         "semantic_cues": ["participant/session isolation", "preprocessing boundary"]},
        {"id": "shared_encoder", "region_id": "matched_objective_process",
         "public_label": "Shared encoder", "role": "focal_process", "visual_form": "tensor",
         "notation": "z", "semantic_cues": ["common representation stream", "acquisition-conditioned tokens"]},
        {"id": "contrastive_loss", "region_id": "matched_objective_process",
         "public_label": "Contrastive route", "role": "interaction", "visual_form": "graph",
         "notation": "Lctr", "semantic_cues": ["paired embedding alignment", "contrastive objective"]},
        {"id": "waveform_loss", "region_id": "matched_objective_process",
         "public_label": "Waveform-mask route", "role": "interaction", "visual_form": "signal",
         "notation": "Lwav", "semantic_cues": ["masked waveform reconstruction", "visible mask blocks"]},
        {"id": "latent_loss", "region_id": "matched_objective_process",
         "public_label": "Latent-mask route", "role": "interaction", "visual_form": "matrix",
         "notation": "Llat", "semantic_cues": ["masked latent prediction", "token matrix"]},
        {"id": "structure_loss", "region_id": "matched_objective_process",
         "public_label": "Structure-joint route", "role": "interaction", "visual_form": "graph",
         "notation": "Lstr", "semantic_cues": ["channel topology edges", "joint structural objective"]},
        {"id": "matched_objective_comparison", "region_id": "matched_objective_process",
         "public_label": "Matched objective comparison", "role": "synthesis",
         "visual_form": "equation", "notation": "E=Lctr+Lwav+Llat+Lstr",
         "semantic_cues": ["four-term objective collection", "matched-opportunity brace"]},
        {"id": "acquisition_heterogeneity_interaction", "region_id": "interaction_audit",
         "public_label": "Acquisition-heterogeneity interaction", "role": "interaction",
         "visual_form": "state_trace", "notation": "Δrank(h)",
         "semantic_cues": ["heterogeneity rank trajectories", "metadata-defined strata"]},
        {"id": "channel_source_reliance_audit", "region_id": "interaction_audit",
         "public_label": "Channel/source reliance audit", "role": "readout",
         "visual_form": "graph", "notation": "A",
         "semantic_cues": ["three intervention probes", "channel and source sensitivity"]},
        {"id": "registered_endpoints", "region_id": "registered_synthesis",
         "public_label": "Registered endpoints", "role": "output",
         "visual_form": "distribution", "notation": "R",
         "semantic_cues": ["equal-dataset mean", "worst-domain floor and paired interval"]},
    ]
    return {
        "schema": 2, "primitives": primitives,
        "reading_order": [item["id"] for item in primitives],
        "flows": [
            {"id": "lineage_to_split", "from": "eeg_lineage",
             "to": "leakage_safe_cross_domain_evaluation", "kind": "constraint",
             "label": "participant boundary"},
            {"id": "lineage_to_encoder", "from": "eeg_lineage", "to": "shared_encoder",
             "kind": "data", "label": "split-safe X"},
            *[
                {"id": f"encoder_to_{target}", "from": "shared_encoder", "to": target,
                 "kind": "data", "label": "z"}
                for target in ("contrastive_loss", "waveform_loss", "latent_loss", "structure_loss")
            ],
            *[
                {"id": f"{source}_to_comparison", "from": source,
                 "to": "matched_objective_comparison", "kind": "comparison", "label": notation}
                for source, notation in (
                    ("contrastive_loss", "Lctr"), ("waveform_loss", "Lwav"),
                    ("latent_loss", "Llat"), ("structure_loss", "Lstr"),
                )
            ],
            {"id": "comparison_to_interaction", "from": "matched_objective_comparison",
             "to": "acquisition_heterogeneity_interaction", "kind": "comparison",
             "label": "E across h"},
            {"id": "interaction_to_audit", "from": "acquisition_heterogeneity_interaction",
             "to": "channel_source_reliance_audit", "kind": "data", "label": "Δrank(h)"},
            {"id": "audit_to_endpoints", "from": "channel_source_reliance_audit",
             "to": "registered_endpoints", "kind": "data", "label": "audited A"},
        ],
    }


def _glyph() -> str:
    return '<path d="M8 40C24 8 42 72 60 40S96 8 112 40" fill="none" stroke="#4E82C3" stroke-width="4"/>'


def test_canvas_places_primitives_and_owns_all_labels_and_routes(tmp_path: Path) -> None:
    _storyboard(tmp_path)
    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", _mechanism_ir(), str(tmp_path),
    ))
    assert len(prepared["primitives"]) == 4
    assert prepared["runtime_primitives"] == ["final_synthesis"]
    for primitive in prepared["primitives"]:
        append_figure_canvas_primitive(
            "method_architecture", primitive["id"], _glyph(), str(tmp_path),
        )
    result = json.loads(finalize_figure_svg_canvas("method_architecture", str(tmp_path)))
    content = (tmp_path / result["source_path"]).read_text(encoding="utf-8")
    assert 'id="mechanism_connections"' in content
    assert 'id="mechanism_frames"' in content
    assert 'id="mechanism_connection_labels"' in content
    assert '>Interaction A</text>' in content
    assert "Lₐ" in content
    assert 'id="interaction_a"' in content


def test_canvas_accepts_exact_required_labels_that_wrap(tmp_path: Path) -> None:
    required_labels = [
        "Acquisition-heterogeneity interaction",
        "Matched objective comparison",
        "Channel/source reliance audit",
        "Leakage-safe cross-domain evaluation",
    ]
    _storyboard(tmp_path, [
        {
            "schema": 1,
            "id": f"method.mechanism.{index}",
            "kind": "concept",
            "display_text": label,
        }
        for index, label in enumerate(required_labels, start=1)
    ])
    mechanism = _mechanism_ir()
    labels_by_primitive = {
        "observed_source": "Leakage-safe cross-domain evaluation",
        "focal_process": "Matched objective comparison",
        "interaction_a": "Acquisition-heterogeneity interaction",
        "interaction_b": "Channel/source reliance audit",
    }
    for primitive in mechanism["primitives"]:
        if primitive["id"] in labels_by_primitive:
            primitive["public_label"] = labels_by_primitive[primitive["id"]]

    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", mechanism, str(tmp_path),
    ))

    assert prepared["required_mechanism_labels"] == required_labels
    assert {
        item["public_label"] for item in prepared["primitives"]
    }.issuperset(required_labels)
    layout = json.loads((
        tmp_path / ".merak" / "figure-drafts" / "method_architecture"
        / "canvas-layout.json"
    ).read_text(encoding="utf-8"))
    labels = {
        item["public_label"]: item["label_lines"]
        for item in layout["primitive_boxes"]
    }
    assert labels["Leakage-safe cross-domain evaluation"] == [
        "Leakage-safe", "cross-domain", "evaluation",
    ]


def test_dense_hierarchy_uses_capacity_safe_storyboard_fallback(tmp_path: Path) -> None:
    required_labels = [
        "Acquisition-heterogeneity interaction",
        "Matched objective comparison",
        "Channel/source reliance audit",
        "Leakage-safe cross-domain evaluation",
    ]
    regions = [
        {"id": "source_lineage", "purpose": "Show isolated EEG inputs",
         "visual_grammar": "waveform lineage", "relative_weight": 1},
        {"id": "matched_objective_process", "purpose": "Show matched objectives",
         "visual_grammar": "shared comparison engine", "relative_weight": 5},
        {"id": "interaction_audit", "purpose": "Show interaction audits",
         "visual_grammar": "rank and intervention traces", "relative_weight": 3},
        {"id": "registered_synthesis", "purpose": "Show registered endpoints",
         "visual_grammar": "endpoint synthesis", "relative_weight": 2},
    ]
    _storyboard(
        tmp_path,
        [{"schema": 1, "id": f"method.mechanism.{index}", "kind": "concept",
          "display_text": label}
         for index, label in enumerate(required_labels, start=1)],
        regions=regions, selected_id="hierarchy_flow",
    )

    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", _dense_mechanism_ir(), str(tmp_path),
    ))

    assert prepared["storyboard_selected_id"] == "hierarchy_flow"
    assert prepared["storyboard_candidate_id"] == "linear_flow"
    assert prepared["layout_fallback"]["from"] == "hierarchy_flow"
    manifest = json.loads((
        tmp_path / ".merak" / "figure-drafts" / "method_architecture"
        / "manifest.json"
    ).read_text(encoding="utf-8"))
    assert manifest["storyboard_selected_id"] == "hierarchy_flow"
    assert manifest["storyboard_candidate_id"] == "linear_flow"
    assert len(manifest["storyboard_candidate_sha256"]) == 64
    layout = json.loads((
        tmp_path / ".merak" / "figure-drafts" / "method_architecture"
        / "canvas-layout.json"
    ).read_text(encoding="utf-8"))
    assert len(layout["primitive_boxes"]) == 11
    assert min(item["glyph_height"] for item in layout["primitive_boxes"]) >= 40
    assert any(item["hidden_semantic_cues"] for item in layout["primitive_boxes"])
    assert sum(
        len(item["semantic_cues"])
        for item in layout["mechanism_ir"]["primitives"]
    ) == 22
    for primitive in prepared["primitives"]:
        append_figure_canvas_primitive(
            "method_architecture", primitive["id"], _glyph(), str(tmp_path),
        )
    finalize_figure_svg_canvas("method_architecture", str(tmp_path))
    assert current_draft_matches_storyboard(tmp_path, "method_architecture")

    storyboard_path = (
        tmp_path / ".merak" / "figure-storyboards" / "method_architecture.json"
    )
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    fallback = next(
        item for item in storyboard["candidates"] if item["id"] == "linear_flow"
    )
    fallback["focal_message"] = "A changed fallback composition"
    storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
    assert not current_draft_matches_storyboard(tmp_path, "method_architecture")


def test_primitive_glyph_rejects_model_text(tmp_path: Path) -> None:
    _storyboard(tmp_path)
    prepare_figure_svg_canvas("method_architecture", _mechanism_ir(), str(tmp_path))
    with pytest.raises(ValueError, match="cannot contain text"):
        append_figure_canvas_primitive(
            "method_architecture", "observed_source",
            '<text x="10" y="30">Model label</text><circle cx="20" cy="50" r="10"/>',
            str(tmp_path),
        )


@pytest.mark.parametrize("fragment, message", [
    (
        '<defs><marker id="arrow"><path d="M0 0L5 2L0 4Z"/></marker></defs>'
        '<path d="M0 0H80" marker-end="url(#arrow)"/>',
        "cannot contain markers",
    ),
    ('<path d="M0 0H80" style="marker-end:url(#arrow)"/>', "cannot contain markers"),
    ('<path id="local_connector" d="M0 0H80"/>', "cannot contain connectors"),
    ('<circle data-port="output" cx="20" cy="20" r="8"/>', "cannot contain connectors"),
])
def test_primitive_glyph_rejects_model_owned_relations(
    tmp_path: Path, fragment: str, message: str,
) -> None:
    _storyboard(tmp_path)
    prepare_figure_svg_canvas("method_architecture", _mechanism_ir(), str(tmp_path))
    with pytest.raises(ValueError, match=message):
        append_figure_canvas_primitive(
            "method_architecture", "observed_source", fragment, str(tmp_path),
        )


def _typed_terminal_ir(runtime_type: str, role: str = "synthesis") -> dict:
    mechanism = _mechanism_ir()
    terminal = mechanism["primitives"][-1]
    terminal["role"] = role
    terminal["notation"] = ""
    terminal["subitems"] = [
        {"id": "primary_condition", "label": "Primary condition"},
        {"id": "robustness_condition", "label": "Robustness condition"},
    ]
    terminal["output_label"] = "Registered conclusion"
    if role == "synthesis":
        terminal["synthesis_type"] = runtime_type
    else:
        terminal["readout_type"] = runtime_type
    return mechanism


@pytest.mark.parametrize(("runtime_type", "role", "operator"), [
    ("decision_gate", "synthesis", "gate"),
    ("reported_endpoint", "output", "endpoint"),
    ("proof_implication", "synthesis", "⇒"),
])
def test_typed_runtime_terminal_renders_without_additive_notation(
    tmp_path: Path, runtime_type: str, role: str, operator: str,
) -> None:
    _storyboard(tmp_path)
    mechanism = _typed_terminal_ir(runtime_type, role)

    normalized = validate_mechanism_ir(
        mechanism, {"source", "process", "synthesis"},
    )
    terminal = normalized["primitives"][-1]
    assert terminal["runtime_type"] == runtime_type
    assert terminal["subitems"][0]["label"] == "Primary condition"

    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", mechanism, str(tmp_path),
    ))
    assert prepared["runtime_primitives"] == ["final_synthesis"]
    for primitive in prepared["primitives"]:
        append_figure_canvas_primitive(
            "method_architecture", primitive["id"], _glyph(), str(tmp_path),
        )
    result = json.loads(finalize_figure_svg_canvas(
        "method_architecture", str(tmp_path),
    ))
    content = (tmp_path / result["source_path"]).read_text(encoding="utf-8")
    assert f">{operator}</text>" in content
    assert ">Primary condition</text>" in content
    assert ">Registered conclusion</text>" in content
    assert ">min L</text>" not in content
    assert ">Σ</text>" not in content


def test_legacy_additive_synthesis_infers_type_without_minimum_claim(tmp_path: Path) -> None:
    _storyboard(tmp_path)
    mechanism = _mechanism_ir()
    normalized = validate_mechanism_ir(
        mechanism, {"source", "process", "synthesis"},
    )
    assert normalized["primitives"][-1]["synthesis_type"] == "additive_objective"

    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", mechanism, str(tmp_path),
    ))
    for primitive in prepared["primitives"]:
        append_figure_canvas_primitive(
            "method_architecture", primitive["id"], _glyph(), str(tmp_path),
        )
    result = json.loads(finalize_figure_svg_canvas(
        "method_architecture", str(tmp_path),
    ))
    content = (tmp_path / result["source_path"]).read_text(encoding="utf-8")
    assert ">Σ</text>" in content
    assert ">y</text>" in content
    assert ">min L</text>" not in content


def test_primitive_repair_preserves_runtime_box(tmp_path: Path) -> None:
    _storyboard(tmp_path)
    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", _mechanism_ir(), str(tmp_path),
    ))
    for primitive in prepared["primitives"]:
        append_figure_canvas_primitive(
            "method_architecture", primitive["id"], _glyph(), str(tmp_path),
        )
    replace_figure_canvas_primitive(
        "method_architecture", "interaction_a", '<circle cx="45" cy="45" r="30"/>',
        str(tmp_path),
    )
    result = json.loads(finalize_figure_svg_canvas("method_architecture", str(tmp_path)))
    content = (tmp_path / result["source_path"]).read_text(encoding="utf-8")
    assert 'id="frame-interaction_a"' in content
    assert 'cx="45" cy="45" r="30"' in content


def test_runtime_refresh_preserves_model_glyphs(tmp_path: Path) -> None:
    _storyboard(tmp_path)
    prepared = json.loads(prepare_figure_svg_canvas(
        "method_architecture", _mechanism_ir(), str(tmp_path),
    ))
    for primitive in prepared["primitives"]:
        append_figure_canvas_primitive(
            "method_architecture", primitive["id"], _glyph(), str(tmp_path),
        )
    finalize_figure_svg_canvas("method_architecture", str(tmp_path))
    result = json.loads(refresh_figure_canvas_runtime(
        "method_architecture", str(tmp_path),
    ))
    content = (tmp_path / result["source_path"]).read_text(encoding="utf-8")
    assert result["status"] == "runtime_layers_refreshed"
    assert 'id="interaction_a"' in content
    assert "Lₐ" in content


def test_canvas_requires_every_mechanism_primitive(tmp_path: Path) -> None:
    _storyboard(tmp_path)
    prepare_figure_svg_canvas("method_architecture", _mechanism_ir(), str(tmp_path))
    append_figure_canvas_primitive(
        "method_architecture", "observed_source", _glyph(), str(tmp_path),
    )
    with pytest.raises(ValueError, match="canvas primitives are missing"):
        finalize_figure_svg_canvas("method_architecture", str(tmp_path))


def test_mechanism_ir_rejects_floating_readout() -> None:
    value = _mechanism_ir()
    value["primitives"].insert(4, {
        "id": "floating_readout", "region_id": "process",
        "public_label": "Floating readout", "role": "readout",
        "visual_form": "state_trace", "notation": "L_R",
        "semantic_cues": ["derived readout"],
    })
    value["reading_order"].insert(4, "floating_readout")
    value["flows"].append({
        "id": "readout_to_sum", "from": "floating_readout",
        "to": "final_synthesis", "kind": "data", "label": "L_R",
    })
    with pytest.raises(ValueError, match="requires an upstream input"):
        validate_mechanism_ir(value, {"source", "process", "synthesis"})


def test_blueprint_wording_cannot_fork_the_mechanism_identity() -> None:
    mechanism = _mechanism_ir()
    first = canonicalize_mechanism_blueprint(mechanism, {
        "figure_label": "First wording", "focal_message": "First prose",
        "narrative_level": "method_overview", "formal_relation": "wrong",
        "primitives": [{"id": item["id"]} for item in mechanism["primitives"]],
    })
    second = canonicalize_mechanism_blueprint(mechanism, {
        "figure_label": "Second wording", "focal_message": "Second prose",
        "narrative_level": "mechanism_detail", "formal_relation": "also wrong",
        "primitives": [{"id": item["id"]} for item in mechanism["primitives"]],
    })
    assert first == second
    assert first["formal_relation"] == "y=L_A+L_B"
