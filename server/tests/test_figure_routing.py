import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from server.agent import ToolCall
from server.agent.engine import AgentEngine
from server.agent.tools import generate_figure
from server.services.figure_artifacts import figure_artifact_registry
from server.services.api_visual_review_invocation import ApiVisualReview
from server.services.api_visual_review_schemas import RICH_SVG_CHECKS
from server.services.figure_engine import (
    FigureResult,
    FigureType,
    _inline_svg_vector_class_styles,
    _raise_svg_connectors,
    _normalize_svg_marker_viewports,
    figure_engine,
)
from server.services.figure_routing import (
    expected_source_extensions,
    manifest_backend_matches,
    normalize_illustration_mode,
    recommend_figure_route,
)
from server.services.figure_producer_policy import figure_production_issues
from server.workflows.engine import WorkflowEngine, WorkflowRun


@pytest.fixture
def accepted_rich_svg_review(monkeypatch):
    async def fake_review(**kwargs):
        root = Path(kwargs["project_path"])
        image = Path(kwargs["image_path"])
        trace = root / ".merak" / "model-api-reviewer" / "fixture-rich-svg"
        trace.mkdir(parents=True, exist_ok=True)
        (trace / "meta.json").write_text(json.dumps({
            "success": True, "invocation_id": "model-api:fixture",
            "model_identity": "fixture-reviewer", "image_attachment_mode": "api-native-image-content",
            "image_sha256": {image.relative_to(root).as_posix(): hashlib.sha256(image.read_bytes()).hexdigest()},
        }), encoding="utf-8")
        response = {
            "score": 8.5, "verdict": "accept", "issues": [], "strengths": ["Readable"],
            "improvement_prompt": "", "checklist": {key: True for key in RICH_SVG_CHECKS},
        }
        return ApiVisualReview(
            json.dumps(response), "model-api:fixture", "fixture-reviewer", "fixture", str(trace),
        )

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg", fake_review,
    )


def _method_visual_blueprint() -> dict:
    roles = ("source", "focal_process", "interaction", "interaction", "synthesis")
    primitives = [
        {"id": f"method_stage_{index}", "visual_form": form,
         "public_label": f"Stage {index}",
         "role": roles[index - 1], "annotations": [],
         "scientific_meaning": f"Scientific transformation {index}",
         **({"notation": "z = f(x)"} if form == "equation" else {})}
        for index, form in enumerate(
            ("signal", "tensor", "matrix", "equation", "graph"), start=1,
        )
    ]
    return {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_level": "method_overview", "figure_label": "Method overview",
        "focal_message": "Source-grounded transformations produce the registered representation",
        "primitives": primitives,
        "reading_order": [item["id"] for item in primitives],
        "flows": [
            {"from": primitives[index]["id"], "to": primitives[index + 1]["id"], "kind": "data"}
            for index in range(4)
        ],
    }


def test_rich_svg_marker_viewport_is_normalized_for_faithful_rendering() -> None:
    unsafe = (
        '<svg viewBox="0 0 1800 1000"><defs>'
        '<marker id="arrow" markerWidth="10" markerHeight="8" '
        'refX="9" refY="4" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L10,4 L0,8 Z"/></marker></defs></svg>'
    )

    normalized = _normalize_svg_marker_viewports(unsafe)

    assert 'markerUnits="userSpaceOnUse"' in normalized
    assert 'viewBox="0 0 10 8"' in normalized


def test_rich_svg_css_no_fill_is_inlined_for_headless_renderers() -> None:
    unsafe = (
        '<svg viewBox="0 0 1800 1000"><style>'
        '.audit{fill:none;stroke:#8B72B6}</style>'
        '<path d="M100 700 C400 900 700 300 900 700" class="audit"/>'
        '</svg>'
    )

    normalized = _inline_svg_vector_class_styles(unsafe)

    assert 'class="audit" fill="none"' in normalized


def test_rich_svg_rect_fill_class_is_inlined_for_pdf_renderer() -> None:
    authored = (
        '<svg><style>.panel{fill:#F8FAFC;stroke:#B7C3D3;stroke-width:3}</style>'
        '<rect class="panel" x="10" y="10" width="200" height="100"/></svg>'
    )
    normalized = _inline_svg_vector_class_styles(authored)
    assert 'fill="#F8FAFC"' in normalized
    assert 'stroke="#B7C3D3"' in normalized


def test_rich_svg_later_class_rule_merges_instead_of_dropping_fill_none() -> None:
    authored = (
        '<svg><style>.arrow{fill:none;stroke:#52627A;marker-end:url(#a)}</style>'
        '<style>.arrow{stroke:#4E82C3}</style>'
        '<path class="arrow" d="M0 0H100"/></svg>'
    )
    normalized = _inline_svg_vector_class_styles(authored)
    assert 'fill="none"' in normalized
    assert 'stroke="#4E82C3"' in normalized
    assert 'marker-end="url(#a)"' in normalized


def test_rich_svg_connector_css_is_inlined_without_replacing_model_geometry() -> None:
    authored = (
        '<svg viewBox="0 0 1800 1000"><defs><style>'
        '.flow{fill:none;stroke:#52627A;stroke-width:3;'
        'stroke-dasharray:10 7;marker-end:url(#arrow)}</style></defs>'
        '<path class="flow" d="M292 305H350"/></svg>'
    )

    normalized = _inline_svg_vector_class_styles(authored)

    assert 'd="M292 305H350"' in normalized
    assert 'stroke="#52627A"' in normalized
    assert 'stroke-width="3"' in normalized
    assert 'stroke-dasharray="10 7"' in normalized
    assert 'marker-end="url(#arrow)"' in normalized


def test_rich_svg_connectors_are_painted_above_nodes_without_geometry_changes() -> None:
    authored = (
        '<svg viewBox="0 0 400 200">'
        '<path class="flow" d="M20 100H380" marker-end="url(#arrow)"/>'
        '<g id="node"><rect x="300" y="60" width="80" height="80"/></g>'
        '</svg>'
    )

    normalized = _raise_svg_connectors(authored)

    assert normalized.count('d="M20 100H380"') == 1
    assert normalized.index('id="node"') < normalized.index('data-runtime-layer="connectors"')
    assert normalized.index('data-runtime-layer="connectors"') < normalized.index('</svg>')


def test_rich_svg_source_gate_rejects_css_only_no_fill_paths(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.svg"
    unsafe = (
        '<svg viewBox="0 0 1800 1000"><style>'
        '.wire{fill:none;stroke:#52627A}</style>'
        '<path d="M100 700 C400 900 700 300 900 700" class="wire"/>'
        '</svg>'
    )
    source.write_text(unsafe, encoding="utf-8")

    issues = figure_artifact_registry.rich_svg_source_issues(source)
    assert any("inline fill=none" in issue for issue in issues)

    source.write_text(
        _inline_svg_vector_class_styles(unsafe),
        encoding="utf-8",
    )
    assert figure_artifact_registry.rich_svg_source_issues(source) == []


def test_rich_svg_render_gate_rejects_giant_solid_arrow_blob(tmp_path: Path) -> None:
    preview = tmp_path / "giant-arrow.png"
    image = Image.new("RGB", (1800, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon([(650, 450), (1180, 300), (1180, 620)], fill="black")
    image.save(preview)

    issues = figure_artifact_registry.rich_svg_render_issues(preview)

    assert any("implausibly large near-black solid component" in issue for issue in issues)


def test_rich_svg_render_gate_allows_small_ink_glyphs(tmp_path: Path) -> None:
    preview = tmp_path / "small-glyphs.png"
    image = Image.new("RGB", (1800, 1000), "white")
    draw = ImageDraw.Draw(image)
    for x in range(100, 1700, 180):
        draw.ellipse((x, 480, x + 18, 498), fill="black")
    image.save(preview)

    assert figure_artifact_registry.rich_svg_render_issues(preview) == []


def test_quantitative_assets_use_reproducible_python() -> None:
    route = recommend_figure_route({
        "kind": "figure",
        "scientific_role": "ablation",
        "data_path": "experiments/results/aggregates/ablation.csv",
    })

    assert route["recommended_backend"] == "matplotlib"
    assert route["recommended_skill"] == "paper-figure"
    assert route["editable_source_extensions"] == [".py"]
    assert route["figure_nature"] == "quantitative"
    assert route["production_strategy"] == "deterministic_plot"
    assert route["producer_kind"] == "deterministic"


@pytest.mark.parametrize(
    ("family", "archetype", "visual"),
    (
        ("machine_learning", "algorithm_benchmark", "Model computation"),
        ("computer_systems", "systems_testbed", "Service topology"),
        ("theoretical_formal", "formal_theory", "Theorem dependency"),
        ("clinical_biomedical", "intervention_trial", "Biological mechanism"),
        ("experimental_natural_science", "controlled_experiment", "Specimen mechanism"),
        ("qualitative_humanities", "qualitative_mixed", "Coding framework"),
    ),
)
def test_conceptual_route_is_domain_independent_figurespec(
    family: str, archetype: str, visual: str,
) -> None:
    route = recommend_figure_route(
        {
            "kind": "figure", "scientific_role": "method",
            "figure_nature": "conceptual", "visual_encoding": visual,
        },
        {"family": family, "study_archetype": archetype},
    )

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"
    assert route["production_strategy"] == "deterministic_architecture"
    assert route["producer_kind"] == "deterministic"
    assert route["composition_owner"] == "runtime"
    assert route["full_svg_authority"] is False


def test_declared_production_contract_rejects_split_ownership() -> None:
    issues = figure_production_issues({
        "figure_nature": "conceptual",
        "production_strategy": "model_composed_full_svg",
        "producer_kind": "model",
        "recommended_backend": "rich_svg",
        "recommended_skill": "model-svg-figure",
        "composition_owner": "runtime",
        "full_svg_authority": False,
    })

    assert "model_composed_full_svg requires composition_owner=model" in issues
    assert "model_composed_full_svg requires full_svg_authority=true" in issues


def test_quantitative_reuse_is_not_overridden_by_phase_2b_selector() -> None:
    route = recommend_figure_route({
        "kind": "figure",
        "generation_phase": "phase_2b",
        "generation_policy": "reuse",
        "illustration_mode": "auto",
        "scientific_role": "ablation",
        "recommended_backend": "matplotlib",
        "data_path": "experiments/results/simulated/ablation.csv",
    })

    assert route["recommended_backend"] == "matplotlib"
    assert route["recommended_skill"] == "paper-figure"
    assert route["generation_policy"] == "reuse"


def test_conceptual_method_overview_uses_figurespec_by_default() -> None:
    route = recommend_figure_route(
        {
            "kind": "figure",
            "scientific_role": "method",
            "recommended_plot_type": "editable_vector_diagram",
        },
        {"family": "machine_learning", "study_archetype": "algorithm_benchmark"},
    )

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"
    assert route["figure_nature"] == "conceptual"
    assert route["production_strategy"] == "deterministic_architecture"
    assert route["composition_owner"] == "runtime"
    assert route["full_svg_authority"] is False


def test_conceptual_route_preserves_figurespec_recommendation() -> None:
    route = recommend_figure_route({
        "id": "method_architecture",
        "kind": "figure",
        "scientific_role": "method",
        "recommended_backend": "figurespec",
        "recommended_skill": "figure-spec",
    })

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"


def test_explicit_conceptual_full_svg_retains_model_ownership() -> None:
    route = recommend_figure_route({
        "id": "method_architecture", "kind": "figure",
        "scientific_role": "method", "production_strategy": "model_composed_full_svg",
    })

    assert route["recommended_backend"] == "rich_svg"
    assert route["recommended_skill"] == "model-svg-figure"
    assert route["producer_kind"] == "model"
    assert route["composition_owner"] == "model"
    assert route["full_svg_authority"] is True


def test_declared_producer_strategy_cannot_silently_change_figure_nature() -> None:
    with pytest.raises(ValueError, match="conflicts with figure_nature=conceptual"):
        recommend_figure_route({
            "id": "method_architecture", "kind": "figure",
            "figure_nature": "conceptual", "production_strategy": "deterministic_plot",
        })


@pytest.mark.parametrize("mode", ["figurespec", "gemini", "mermaid", "false"])
def test_removed_phase_2b_selectors_are_rejected(mode: str) -> None:
    with pytest.raises(ValueError, match="unsupported illustration mode"):
        recommend_figure_route({
            "kind": "figure", "generation_phase": "phase_2b",
            "illustration_mode": mode, "scientific_role": "method",
        })


def test_figure_prompt_blocks_missing_publication_contract_before_renderer_selection(
    tmp_path: Path,
) -> None:
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "illustration_mode": "auto",
        },
    )

    prompt = WorkflowEngine()._input_figure(
        "A project-grounded method architecture",
        {},
        run,
    )

    assert "Figure stage blocked by upstream scientific asset contract" in prompt
    assert "contribution_type is required" in prompt
    assert "generate_figure" not in prompt


def test_synthetic_mode_does_not_bypass_missing_publication_contract(
    tmp_path: Path,
) -> None:
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    prompt = WorkflowEngine()._input_figure(
        "A deterministic benchmark figure set",
        {},
        run,
    )

    assert "Figure stage blocked by upstream scientific asset contract" in prompt
    assert "contribution_type is required" in prompt
    assert "generate_figure" not in prompt


def test_removed_illustration_selector_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported illustration mode"):
        normalize_illustration_mode("codex-image2")


def test_manifest_backend_mapping_is_exact_and_prompt_source_is_allowed() -> None:
    assert manifest_backend_matches(
        "gpt_image",
        "paper-illustration",
        "nano_banana",
    ) is False
    assert manifest_backend_matches(
        "gpt_image",
        "paper-illustration",
        "rich_svg",
    ) is False
    assert manifest_backend_matches(
        "nano_banana",
        "paper-illustration",
        "rich_svg",
    ) is False
    assert ".json" in expected_source_extensions("gpt_image")
    assert ".prompt.json" in expected_source_extensions("gpt_image")


def test_auto_mode_keeps_per_asset_semantic_routing() -> None:
    method = recommend_figure_route({
        "kind": "figure",
        "generation_phase": "phase_2b",
        "illustration_mode": "auto",
        "scientific_role": "method",
    })
    evaluation = recommend_figure_route({
        "kind": "figure",
        "generation_phase": "phase_2b",
        "illustration_mode": "auto",
        "scientific_role": "evaluation_design",
    })

    assert method["recommended_backend"] == "figurespec"
    assert method["recommended_skill"] == "figure-spec"
    assert method["producer_kind"] == "deterministic"
    assert evaluation["recommended_backend"] == "rich_svg"
    assert evaluation["recommended_skill"] == "deterministic-figure-template"
    assert evaluation["production_strategy"] == "deterministic_template"
    assert evaluation["producer_kind"] == "deterministic"


def test_false_mode_cannot_disable_system_planned_phase_2b() -> None:
    with pytest.raises(ValueError, match="unsupported illustration mode"):
        recommend_figure_route({
            "kind": "figure", "generation_phase": "phase_2b",
            "illustration_mode": "false", "scientific_role": "method",
        })


def test_complex_implementation_blueprint_uses_source_grounded_figurespec() -> None:
    route = recommend_figure_route({
        "kind": "figure",
        "generation_phase": "phase_2b",
        "scientific_role": "method",
        "architecture_blueprint": {
            "components": [{"id": f"component_{index}"} for index in range(8)],
            "training_paths": [["component_1", "component_2"]],
            "auxiliary_paths": [["component_7", "component_8"]],
            "requires_multi_lane_layout": True,
        },
    })

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"


def test_rich_svg_backend_persists_editable_same_source_variants(
    tmp_path: Path, accepted_rich_svg_review,
) -> None:
    source = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"method": "source grounded"}', encoding="utf-8")
    colors = ["#E8F1FB", "#E4F5F1", "#FFF0DF", "#F1ECF8"]
    panels = "".join(
        f'<g id="method_stage_{index + 1}"><rect x="{55 + (index % 4) * 425}" y="{150 + (index // 4) * 220}" '
        f'width="385" height="185" rx="12" fill="{colors[index % 4]}" '
        'stroke="#52627A" stroke-width="2"/></g>'
        for index in range(12)
    )
    labels = "".join(
        f'<text x="{80 + (index % 4) * 425}" y="{180 + (index // 4) * 220 + (index % 3) * 28}" '
        'font-family="Arial" font-size="34" fill="#17233C">'
        f'Operation {index + 1}</text>'
        for index in range(30)
    )
    glyphs = "".join(
        f'<circle cx="{100 + index * 125}" cy="850" r="18" '
        f'fill="{colors[index % 4]}" stroke="#17233C"/>'
        for index in range(13)
    )
    rich_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1000" '
        'viewBox="0 0 1800 1000">'
        '<rect x="0" y="0" width="1800" height="1000" fill="#FFFFFF"/>'
        '<g id="method_contract">'
        '<text x="55" y="70" font-family="Arial" font-size="42" '
        'font-weight="700" fill="#17233C">Rich scientific architecture</text>'
        f'{panels}{labels}{glyphs}</g></svg>'
    )
    result = asyncio.run(figure_engine.generate(
        "Source-grounded method architecture",
        FigureType.RICH_SVG,
        str(tmp_path / "figures" / "diagrams"),
        code=rich_svg,
        artifact_name="method_architecture",
        metadata={
            "scientific_role": "method",
            "scientific_question": "How does the method operate?",
            "intended_comparison": "Internal mechanism and controls",
            "visual_encoding": "Domain-specific vector internals",
            "source_data": ["experiments/METHOD_CONTRACT.json"],
            "element_mappings": [
                {
                    "element_id": f"method_stage_{index}",
                    "source_path": "experiments/METHOD_CONTRACT.json",
                    "semantic_role": "method contract stage",
                }
                for index in range(1, 5)
            ],
            "generator_skill": "rich-svg-figure",
            "skill": "rich-svg-figure",
            "skill_invocation_verified": True,
            "visual_review_policy": "enhanced_local_pixels_required",
            "visual_blueprint": _method_visual_blueprint(),
        },
    ))

    assert result.success, result.error
    assert result.figure_type == FigureType.RICH_SVG
    assert Path(result.source_path or "").suffix == ".svg"
    variants = dict((result.metadata or {}).get("rendered_variants") or {})
    assert set(variants) == {"svg", "pdf", "png"}
    assert all((tmp_path / value).is_file() for value in variants.values())
    assert (result.metadata or {}).get("renderer") == "rich-svg-vector-v1"


def test_evaluation_design_rich_svg_does_not_replace_model_source(
    tmp_path: Path,
) -> None:
    result = asyncio.run(figure_engine.generate(
        "Leakage-safe held-out evaluation protocol",
        FigureType.RICH_SVG,
        str(tmp_path / "figures" / "diagrams"),
        code="<svg/>",
        artifact_name="evaluation_design",
        metadata={
            "scientific_role": "evaluation_design",
            "method_brief": {
                "problem": "Generalization under unseen acquisition stress",
            },
            "generator_skill": "rich-svg-figure",
            "skill": "rich-svg-figure",
            "skill_invocation_verified": True,
        },
    ))

    assert not result.success
    assert "visual_blueprint" in (result.error or "")
    assert "Leakage-safe split" not in (result.code or "")


def test_system_method_architecture_uses_figurespec() -> None:
    route = recommend_figure_route(
        {
            "kind": "figure",
            "scientific_role": "method",
            "visual_encoding": "Service and deployment topology",
        },
        {"family": "computer_systems", "study_archetype": "systems_testbed"},
    )

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"


def test_comparative_model_suite_uses_source_grounded_figurespec() -> None:
    route = recommend_figure_route({
        "id": "method_architecture",
        "kind": "figure",
        "scientific_role": "method",
        "recommended_backend": "rich_svg",
        "architecture_blueprint": {
            "model_configuration": {
                "model_suite": ["linear_reference", "mlp_reference", "residual_mlp"],
            },
        },
    })

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"


def test_evaluation_flow_uses_deterministic_protocol_template() -> None:
    route = recommend_figure_route({
        "kind": "figure",
        "scientific_role": "evaluation_design",
        "recommended_plot_type": "participant_or_sample_flow",
    })

    assert route["recommended_backend"] == "rich_svg"
    assert route["recommended_skill"] == "deterministic-figure-template"
    assert route["producer_kind"] == "deterministic"


def test_formal_structure_uses_deterministic_architecture() -> None:
    route = recommend_figure_route(
        {
            "kind": "figure",
            "scientific_role": "method",
            "visual_encoding": "Proof dependency and theorem structure",
        },
        {"family": "theoretical_formal", "study_archetype": "formal_theory"},
    )

    assert route["recommended_backend"] == "figurespec"
    assert route["recommended_skill"] == "figure-spec"
    assert route["production_strategy"] == "deterministic_architecture"


def test_image_backend_requires_an_explicit_naturalistic_need() -> None:
    route = recommend_figure_route({
        "kind": "figure",
        "scientific_role": "qualitative",
        "requires_naturalistic_imagery": True,
    })

    assert route["recommended_backend"] == "nano_banana"
    assert route["recommended_skill"] == "paper-illustration"


def test_runtime_injects_the_actual_figure_skill() -> None:
    observed: list[str] = []

    async def generated(description: str, generator_skill: str = "") -> str:
        observed.append(generator_skill)
        return description

    engine = AgentEngine(type("Router", (), {})())
    engine.register_tool(
        "generate_figure",
        "Generate",
        {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
        generated,
    )
    session = engine.create_session()
    session.context_key = "skill-chain:paper-figure>mermaid-diagram"

    result = asyncio.run(engine._execute_tool(
        session,
        ToolCall(
            id="figure",
            name="generate_figure",
            arguments={"description": "evaluation flow"},
        ),
    ))

    assert result.success is True
    assert observed == ["mermaid-diagram"]


def _write_specs(figures: Path, *, backend: str, skill: str) -> None:
    figures.mkdir(parents=True)
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({
            "schema": 3,
            "figures": [{
                "id": "method_architecture",
                "recommended_backend": backend,
                "recommended_skill": skill,
                "generation_policy": "generate",
            }],
        }),
        encoding="utf-8",
    )


def test_generate_figure_rejects_backend_that_conflicts_with_plan(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    _write_specs(figures, backend="figurespec", skill="figure-spec")

    with pytest.raises(ValueError, match="expected rich_svg, got excalidraw"):
        asyncio.run(generate_figure(
            "Method architecture",
            artifact_name="method_architecture",
            figure_type="excalidraw",
            output_dir=str(figures / "diagrams"),
        ))


def test_generate_figure_uses_planned_backend_when_model_omits_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    _write_specs(figures, backend="mermaid", skill="mermaid-diagram")
    captured: dict = {}
    output = figures / "diagrams" / "method_architecture.svg"
    output.parent.mkdir(parents=True)
    output.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    async def fake_generate(_description, selected_type, _output_dir, **kwargs):
        captured["type"] = selected_type
        captured["metadata"] = dict(kwargs.get("metadata") or {})
        return FigureResult(
            success=True,
            figure_type=selected_type,
            output_path=str(output),
            metadata={},
        )

    monkeypatch.setattr(figure_engine, "generate", fake_generate)
    result = asyncio.run(generate_figure(
        "Method architecture",
        artifact_name="method_architecture",
        output_dir=str(figures / "diagrams"),
    ))

    assert "Figure generated (mermaid)" in result
    assert captured["type"] == FigureType.MERMAID
    assert captured["metadata"]["recommended_backend"] == "mermaid"
    assert captured["metadata"]["recommended_skill"] == "mermaid-diagram"


def test_generate_figure_reuses_canonical_plan_asset_without_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    diagrams = figures / "simulated"
    diagrams.mkdir(parents=True)
    source = diagrams / "simulated_main.py"
    output = diagrams / "simulated_main.pdf"
    source.write_text("print('canonical')\n", encoding="utf-8")
    output.write_bytes(b"%PDF-1.4\ncanonical\n")
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({
            "schema": 3,
            "figures": [{
                "id": "synthetic_preview_main",
                "recommended_backend": "matplotlib",
                "recommended_skill": "paper-figure",
                "generation_policy": "reuse",
            }],
        }),
        encoding="utf-8",
    )
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="matplotlib",
        description="Primary comparison",
        output_path=output,
        source_path=source,
        metadata={
            "semantic_key": "synthetic_preview_main",
            "managed_by": "merak",
            "paper_selected": True,
        },
    )

    async def forbidden_generate(*_args, **_kwargs):
        raise AssertionError("canonical reuse asset must not be rendered again")

    monkeypatch.setattr(figure_engine, "generate", forbidden_generate)
    result = asyncio.run(generate_figure(
        "Primary comparison",
        artifact_name="synthetic_preview_main",
        output_dir=str(figures / "plots"),
    ))

    assert "Figure reused (matplotlib)" in result
    assert "No new artifact was generated" in result


def test_reused_phase2a_assets_do_not_consume_phase2b_generation_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    diagrams = figures / "diagrams"
    diagrams.mkdir(parents=True)
    specs = [
        {
            "id": f"synthetic_preview_{index}",
            "recommended_backend": "matplotlib",
            "recommended_skill": "paper-figure",
            "generation_phase": "phase_2a",
            "generation_policy": "reuse",
        }
        for index in range(6)
    ]
    specs.append({
        "id": "method_architecture",
        "recommended_backend": "figurespec",
        "recommended_skill": "figure-spec",
        "generation_phase": "phase_2b",
        "generation_policy": "generate",
    })
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({"schema": 3, "figures": specs}),
        encoding="utf-8",
    )
    for index in range(6):
        source = diagrams / f"synthetic_preview_{index}.py"
        output = diagrams / f"synthetic_preview_{index}.pdf"
        source.write_text("print('reuse')\n", encoding="utf-8")
        output.write_bytes(b"%PDF-1.4\n")
        figure_artifact_registry.record(
            output_dir=diagrams,
            figure_type="matplotlib",
            description=f"Synthetic preview {index}",
            output_path=output,
            source_path=source,
            metadata={
                "semantic_key": f"synthetic_preview_{index}",
                "generation_policy": "reuse",
            },
        )

    output = diagrams / "method_architecture.pdf"
    output.write_bytes(b"%PDF-1.4\nmethod\n")

    async def fake_generate(_description, selected_type, _output_dir, **_kwargs):
        return FigureResult(
            success=True,
            figure_type=selected_type,
            output_path=str(output),
            metadata={},
        )

    monkeypatch.setattr(figure_engine, "generate", fake_generate)
    result = asyncio.run(generate_figure(
        "Method architecture",
        artifact_name="method_architecture",
        output_dir=str(diagrams),
        code='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0L100 100"/></svg>',
        figure_budget=2,
    ))

    assert "Figure generated (rich_svg)" in result


def test_generate_figure_rejects_removed_method_route_without_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    _write_specs(
        figures,
        backend="gpt_image",
        skill="paper-illustration-image2",
    )
    captured: dict = {}
    output = figures / "diagrams" / "method_architecture.svg"
    output.parent.mkdir(parents=True)
    output.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    async def fake_generate(_description, selected_type, _output_dir, **kwargs):
        captured["type"] = selected_type
        captured["metadata"] = dict(kwargs.get("metadata") or {})
        return FigureResult(
            success=True,
            figure_type=selected_type,
            output_path=str(output),
            metadata={},
        )

    monkeypatch.setattr(figure_engine, "generate", fake_generate)
    with pytest.raises(ValueError, match="unsupported current figure route"):
        asyncio.run(generate_figure(
            "Method architecture", artifact_name="method_architecture",
            output_dir=str(figures / "diagrams"),
        ))
    assert captured == {}


def test_backend_cannot_spoof_the_runtime_figure_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "figures" / "ai_generated" / "method.png"
    source = output.with_suffix(".prompt.json")
    output.parent.mkdir(parents=True)
    output.write_bytes(b"png")
    source.write_text("{}", encoding="utf-8")
    engine = type(figure_engine)()

    async def fake_nano_banana(*_args, **_kwargs):
        return FigureResult(
            success=True,
            figure_type=FigureType.NANO_BANANA,
            output_path=str(output),
            source_path=str(source),
            metadata={
                "generator_skill": "paper-illustration",
                "skill": "paper-illustration",
            },
        )

    monkeypatch.setattr(engine, "_generate_nano_banana", fake_nano_banana)
    result = asyncio.run(engine.generate(
        "Method architecture",
        figure_type=FigureType.NANO_BANANA,
        output_dir=str(tmp_path / "figures"),
        artifact_name="method_architecture",
        metadata={
            "generator_skill": "paper-figure",
            "skill": "paper-figure",
            "skill_invocation_verified": True,
            "skill_invocation_verified_by": "agent-runtime",
        },
    ))

    assert result.success is True
    assert result.metadata["generator_skill"] == "paper-figure"
    assert result.metadata["skill"] == "paper-figure"
    assert result.metadata["skill_invocation_verified"] is True
    assert result.metadata["skill_invocation_verified_by"] == "agent-runtime"


def test_gemini_skill_proof_requires_a_durable_specialist_session(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / ".merak" / "agent-sessions"
    sessions.mkdir(parents=True)
    transcript = sessions / "session.json"
    transcript.write_text(
        json.dumps({
            "context_key": "skill-chain:paper-figure>paper-illustration",
            "tool_call_counts": {"generate_figure": 1},
            "messages": [{
                "role": "assistant",
                "content": "generated method_architecture",
            }],
        }),
        encoding="utf-8",
    )

    assert WorkflowEngine._verified_figure_skill_invocation(
        tmp_path,
        "method_architecture",
        "paper-illustration",
    ) is True
    assert WorkflowEngine._verified_figure_skill_invocation(
        tmp_path,
        "method_architecture",
        "paper-figure",
    ) is False
