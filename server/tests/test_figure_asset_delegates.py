from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent.tools.figure_storyboard_tools import submit_figure_storyboard
from server.agent.tools.figure_draft_tools import (
    append_figure_svg_fragment,
    begin_figure_svg_draft,
    finalize_figure_svg_draft,
)
from server.workflows.figure_asset_delegates import (
    _accepted_entry,
    _active_mechanism_guidance,
    _layout_scope,
    run_figure_asset_delegates,
)
from server.services.figure_semantic_projection import semantic_projection_sha256
from server.services.rich_svg_visual_review import REVIEW_POLICY_VERSION


def test_method_overview_scope_excludes_evaluation_dashboard() -> None:
    scope = _layout_scope({
        "scientific_role": "method",
        "scene_contract": {"contribution_type": "system_architecture"},
    })
    assert "3–4 connected regions" in scope
    assert "Exclude downstream evaluation" in scope
    assert "storyboard.connections" in scope
    assert "Omit annotation_only controls" in scope


def test_unconfigured_probe_is_not_presented_as_active_grl() -> None:
    guidance = _active_mechanism_guidance({
        "method_brief": {
            "probe_configuration": [{
                "name": "subject_session_probe", "mechanism_id": "M2",
                "training_mode": "unspecified", "head_status": "unverified_mode",
                "joint_objective_status": "inactive",
                "missing_heads": ["model.subject_classes=None"],
            }],
        },
    })
    assert "subject_session_probe (M2)" in guidance
    assert "joint training not established" in guidance
    assert "Do not draw an unverified probe as an always-active GRL" in guidance


@pytest.mark.asyncio
async def test_model_composed_asset_uses_full_svg_skill_and_authority_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = {
        "id": "method_architecture", "kind": "figure", "required": True,
        "producer_kind": "model", "generation_policy": "generate",
        "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure",
        "production_strategy": "model_composed_full_svg",
        "composition_owner": "model", "full_svg_authority": True,
        "scientific_question": "How does the method transform the input?",
        "content_boundary": "Exclude evaluation and numerical results.",
    }
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.scientific_asset_service.build_plan",
        lambda *args, **kwargs: {"assets": [asset]},
    )
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.persist_figure_specs",
        lambda *args, **kwargs: [asset],
    )
    accepted = False
    prompts: list[tuple[str, str]] = []
    limits: list[dict] = []
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda *_args: {"id": "method_architecture"} if accepted else None,
    )

    async def fake_invoke(skill_name: str, arguments: str, **_kwargs):
        nonlocal accepted
        prompts.append((skill_name, arguments))
        limits.append(_kwargs)
        if skill_name == "figure-layout-director":
            candidates = [{
                "id": f"layout_{index}", "topology": topology,
                "focal_message": "One clear scientific transformation",
                "regions": [
                    {"id": "source", "purpose": "Show source", "visual_grammar": "signal", "relative_weight": 2},
                    {"id": "method", "purpose": "Show method", "visual_grammar": "operation", "relative_weight": 5},
                ],
                "reading_order": ["source", "method"],
                "connections": [{"id": "source_to_method", "from": "source",
                                 "to": "method", "kind": "main",
                                 "scientific_meaning": "Source enters method"}],
                "strengths": [], "risks": [],
            } for index, topology in enumerate(("linear", "parallel", "causal"), 1)]
            submit_figure_storyboard(
                "method_architecture", candidates, "layout_1", "clear", str(tmp_path),
            )
        else:
            accepted = True
        return "done"

    monkeypatch.setattr("server.agent.tools.skill_tool.invoke_skill", fake_invoke)

    class Host:
        async def _emit(self, *_args, **_kwargs):
            return None

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"),
        opts={"visual_storyboard_review": False}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run"),
    )

    await run_figure_asset_delegates(context)

    assert [item[0] for item in prompts] == ["model-svg-figure"]
    assert limits[0]["max_iterations"] == 24
    assert limits[0]["tool_call_limits"] == {
        "submit_model_svg_draft": 3, "review_figure_svg_composition": 2,
    }
    illustration = prompts[0][1]
    assert "Call prepare_model_svg_draft first" in illustration
    assert "You own all visible text, arrows, equations, spacing, and layout" in illustration
    assert "Do not call prepare_figure_svg_canvas" in illustration
    assert "signal, tensor, matrix, equation, graph" in illustration
    assert "do not spend a separate model session generating layout alternatives" in illustration
    assert "Arrows/connectors are flows, never primitives" in illustration


@pytest.mark.asyncio
async def test_model_composed_asset_uses_one_bounded_session_then_defers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = {
        "id": "method_architecture", "kind": "figure", "required": True,
        "producer_kind": "model", "generation_policy": "generate",
        "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure",
        "production_strategy": "model_composed_full_svg",
        "composition_owner": "model", "full_svg_authority": True,
        "scientific_question": "How does the method transform the input?",
    }
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.scientific_asset_service.build_plan",
        lambda *args, **kwargs: {"assets": [asset]},
    )
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.persist_figure_specs",
        lambda *args, **kwargs: [asset],
    )
    accepted = False
    illustration_calls = 0
    prompts: list[str] = []
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda *_args: {"id": "method_architecture"} if accepted else None,
    )

    async def fake_invoke(skill_name: str, arguments: str, **_kwargs):
        nonlocal accepted, illustration_calls
        if skill_name == "figure-layout-director":
            candidates = [{
                "id": f"layout_{index}", "topology": topology,
                "focal_message": "One clear scientific transformation",
                "regions": [
                    {"id": "source", "purpose": "Show source", "visual_grammar": "signal", "relative_weight": 2},
                    {"id": "method", "purpose": "Show method", "visual_grammar": "operation", "relative_weight": 5},
                ],
                "reading_order": ["source", "method"],
                "connections": [{"id": "source_to_method", "from": "source",
                                 "to": "method", "kind": "main",
                                 "scientific_meaning": "Source enters method"}],
                "strengths": [], "risks": [],
            } for index, topology in enumerate(("linear", "parallel", "causal"), 1)]
            submit_figure_storyboard(
                "method_architecture", candidates, "layout_1", "clear", str(tmp_path),
            )
        else:
            illustration_calls += 1
            prompts.append(arguments)
            if illustration_calls == 1:
                directory = (
                    tmp_path / ".merak" / "figure-drafts" / "method_architecture"
                )
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "manifest.json").write_text(json.dumps({
                    "composition_review": {
                        "verdict": "refine", "score": 7.2,
                        "checklist": {"causal_flow": False, "label_economy": True},
                        "issues": ["Mask target and context arrows are ambiguous"],
                        "improvement_prompt": "Connect both branches to the shared loss",
                    },
                }), encoding="utf-8")
        return "done"

    monkeypatch.setattr("server.agent.tools.skill_tool.invoke_skill", fake_invoke)
    events: list[tuple[str, dict]] = []

    class Host:
        async def _emit(self, _run, event: str, payload: dict):
            events.append((event, payload))

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"),
        opts={"visual_storyboard_review": False}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run"),
    )

    with pytest.raises(RuntimeError, match="single bounded session"):
        await run_figure_asset_delegates(context)

    assert illustration_calls == 1
    assert "at most three complete submissions" in prompts[0]
    with pytest.raises(RuntimeError, match="automatic model redraw deferred"):
        await run_figure_asset_delegates(context)
    assert illustration_calls == 1
    repair_events = [payload for event, payload in events if event == "figure_asset_delegate_repair"]
    assert repair_events == []


@pytest.mark.asyncio
async def test_each_model_figure_gets_layout_then_illustration_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = [{
        "id": identity, "kind": "figure", "required": True,
        "producer_kind": "model", "generation_policy": "generate",
        "recommended_backend": "rich_svg", "recommended_skill": "rich-svg-figure",
        "scientific_question": f"How does {identity} communicate its mechanism?",
    } for identity in ("method_architecture", "core_mechanism")]
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.scientific_asset_service.build_plan",
        lambda *args, **kwargs: {"assets": assets},
    )
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.persist_figure_specs",
        lambda *args, **kwargs: assets,
    )
    calls: list[tuple[str, str]] = []
    accepted: set[str] = set()
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda _root, asset: {"id": asset["id"]} if asset["id"] in accepted else None,
    )

    async def fake_invoke(skill_name: str, arguments: str, **kwargs):
        identity = next(item for item in ("method_architecture", "core_mechanism") if f"`{item}`" in arguments)
        calls.append((skill_name, identity))
        if skill_name == "figure-layout-director":
            candidates = [{
                "id": f"layout_{index}", "topology": topology,
                "focal_message": "A concrete scientific mechanism follows one readable path",
                "regions": [
                    {"id": "input_region", "purpose": "Show scientific inputs", "visual_grammar": "signal glyph", "relative_weight": 2},
                    {"id": "mechanism_region", "purpose": "Show operative mechanism", "visual_grammar": "tensor equation", "relative_weight": 5},
                ],
                "reading_order": ["input_region", "mechanism_region"],
                "connections": [{"id": "input_to_method", "from": "input_region",
                                 "to": "mechanism_region", "kind": "main",
                                 "scientific_meaning": "Observed input enters the mechanism"}],
                "strengths": [], "risks": [],
            } for index, topology in enumerate(("linear", "parallel", "hierarchical"), start=1)]
            submit_figure_storyboard(
                identity, candidates, "layout_1",
                "The selected layout provides the clearest scientific reading path.", str(tmp_path),
            )
        else:
            accepted.add(identity)
        return "done"

    monkeypatch.setattr("server.agent.tools.skill_tool.invoke_skill", fake_invoke)

    events: list[tuple[str, dict]] = []

    class Host:
        async def _emit(self, _run, event: str, payload: dict):
            events.append((event, payload))

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"), opts={"visual_storyboard_review": False}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run-1"),
    )
    result = await run_figure_asset_delegates(context)
    assert calls == [
        ("figure-layout-director", "method_architecture"),
        ("rich-svg-figure", "method_architecture"),
        ("figure-layout-director", "core_mechanism"),
        ("rich-svg-figure", "core_mechanism"),
    ]
    assert "method_architecture, core_mechanism" in str(result)
    assert len([event for event, _payload in events if event == "figure_asset_delegate_completed"]) == 2


def test_accepted_entry_rejects_unattested_rich_svg_even_with_matching_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures" / "diagrams"
    figures.mkdir(parents=True)
    source = figures / "evaluation_design.svg"
    output = figures / "evaluation_design.pdf"
    source.write_text("<svg/>", encoding="utf-8")
    output.write_bytes(b"pdf")
    entry = {
        "id": "evaluation_design",
        "paper_ready": True,
        "source_path": str(source),
        "output_path": str(output),
        "metadata": {
            "semantic_key": "evaluation_design",
            "generator": "deterministic-runtime-rich-svg",
            "independent_visual_review": {
                "verdict": "accept", "score": 8.0, "findings": [],
                "review_policy_version": REVIEW_POLICY_VERSION,
                "checklist": {
                    "five_second_comprehension": True,
                    "scientific_mechanism_clarity": True,
                    "causal_flow": True,
                    "paper_scale_readability": True,
                    "no_visual_artifacts": True,
                },
            },
        },
    }
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.figure_artifact_registry.load",
        lambda _figures_root: {"figures": [entry]},
    )

    deterministic = {
        "id": "evaluation_design",
        "recommended_backend": "rich_svg",
        "production_strategy": "deterministic_template",
        "producer_kind": "deterministic",
    }
    assert _accepted_entry(tmp_path, deterministic) is None
    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.native_review_issues", lambda *_args: [],
    )
    entry["metadata"]["independent_visual_review"]["review_policy_version"] = REVIEW_POLICY_VERSION
    assert _accepted_entry(tmp_path, deterministic) == entry

    model = {
        "id": "evaluation_design",
        "recommended_backend": "rich_svg",
        "production_strategy": "model_composed_full_svg",
        "producer_kind": "model",
    }
    assert _accepted_entry(tmp_path, model) is None

    entry["metadata"]["generator"] = "model-authored-rich-svg"
    assert _accepted_entry(tmp_path, model) == entry


@pytest.mark.asyncio
async def test_failed_model_asset_does_not_block_later_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = [
        {"id": "method_architecture", "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure"},
        {"id": "core_mechanism", "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure"},
    ]
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._model_assets",
        lambda _context: assets,
    )
    accepted: set[str] = set()
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda _root, asset: {"id": asset["id"]} if asset["id"] in accepted else None,
    )

    async def fake_plan(*_args, **_kwargs):
        return {
            "id": "layout_1",
            "selected_id": "layout_1",
            "candidates": [{"id": "layout_1"}],
        }

    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._plan_storyboard",
        fake_plan,
    )
    attempts: list[str] = []

    async def fake_illustrate(_context, asset, identity, *_args, **_kwargs):
        attempts.append(identity)
        if identity == "method_architecture":
            raise RuntimeError("visual review rejected")
        accepted.add(str(asset["id"]))

    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._illustrate_asset",
        fake_illustrate,
    )
    events: list[tuple[str, dict]] = []

    class Host:
        async def _emit(self, _run, event: str, payload: dict):
            events.append((event, payload))

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"), opts={}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run"),
    )

    with pytest.raises(RuntimeError, match="method_architecture: RuntimeError: visual review rejected"):
        await run_figure_asset_delegates(context)

    assert attempts == ["method_architecture", "core_mechanism"]
    failed = [payload for event, payload in events if event == "figure_asset_delegate_failed"]
    assert failed == [{
        "node_id": "figure", "asset_id": "method_architecture",
        "error": "RuntimeError: visual review rejected",
        "completed_assets": [],
    }]
    assert any(
        event == "figure_asset_delegate_completed"
        and payload["asset_id"] == "core_mechanism"
        for event, payload in events
    )


@pytest.mark.asyncio
async def test_missing_storyboard_gets_one_artifact_repair_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = {
        "id": "method_architecture", "kind": "figure", "required": True,
        "producer_kind": "model", "generation_policy": "generate",
        "recommended_backend": "rich_svg", "recommended_skill": "rich-svg-figure",
    }
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.scientific_asset_service.build_plan",
        lambda *args, **kwargs: {"assets": [asset]},
    )
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.persist_figure_specs",
        lambda *args, **kwargs: [asset],
    )
    accepted = False
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda *_args: {"id": "method_architecture"} if accepted else None,
    )
    layout_calls = 0

    async def fake_invoke(skill_name: str, arguments: str, **kwargs):
        nonlocal layout_calls, accepted
        if skill_name == "figure-layout-director":
            layout_calls += 1
            if layout_calls == 2:
                candidates = [{
                    "id": f"layout_{index}", "topology": topology,
                    "focal_message": "One scientific mechanism follows one readable path",
                    "regions": [
                        {"id": "input_region", "purpose": "Show inputs", "visual_grammar": "signal", "relative_weight": 2},
                        {"id": "mechanism_region", "purpose": "Show mechanism", "visual_grammar": "equation", "relative_weight": 5},
                    ],
                    "reading_order": ["input_region", "mechanism_region"],
                    "connections": [{"id": "input_to_method", "from": "input_region",
                                     "to": "mechanism_region", "kind": "main",
                                     "scientific_meaning": "Observed input enters the mechanism"}],
                    "strengths": [], "risks": [],
                } for index, topology in enumerate(("linear", "parallel", "hierarchical"), 1)]
                submit_figure_storyboard(
                    "method_architecture", candidates, "layout_1", "最清晰", str(tmp_path),
                )
        else:
            accepted = True
        return "done"

    monkeypatch.setattr("server.agent.tools.skill_tool.invoke_skill", fake_invoke)
    events: list[str] = []

    class Host:
        async def _emit(self, _run, event: str, _payload: dict):
            events.append(event)

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"), opts={"visual_storyboard_review": False}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run"),
    )
    result = await run_figure_asset_delegates(context)
    assert layout_calls == 2
    assert "figure_asset_delegate_repair" in events
    assert "method_architecture" in str(result)


@pytest.mark.asyncio
async def test_current_storyboard_is_reused_without_layout_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = {
        "id": "method_architecture", "kind": "figure", "required": True,
        "producer_kind": "model", "generation_policy": "generate",
        "recommended_backend": "rich_svg", "recommended_skill": "rich-svg-figure",
    }
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.scientific_asset_service.build_plan",
        lambda *args, **kwargs: {"assets": [asset]},
    )
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates.persist_figure_specs",
        lambda *args, **kwargs: [asset],
    )
    candidates = [{
        "id": f"layout_{index}", "topology": topology,
        "focal_message": "One scientific mechanism follows one readable path",
        "regions": [
            {"id": "input_region", "purpose": "Show inputs", "visual_grammar": "signal", "relative_weight": 2},
            {"id": "mechanism_region", "purpose": "Show mechanism", "visual_grammar": "equation", "relative_weight": 5},
        ],
        "reading_order": ["input_region", "mechanism_region"],
        "connections": [{"id": "input_to_method", "from": "input_region",
                         "to": "mechanism_region", "kind": "main",
                         "scientific_meaning": "Observed input enters the mechanism"}],
        "strengths": [], "risks": [],
    } for index, topology in enumerate(("linear", "parallel", "hierarchical"), 1)]
    submit_figure_storyboard(
        "method_architecture", candidates, "layout_1", "最清晰", str(tmp_path),
        semantic_projection_sha256=semantic_projection_sha256(asset),
    )
    accepted = False
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda *_args: {"id": "method_architecture"} if accepted else None,
    )
    calls: list[str] = []
    prompts: list[str] = []
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    for identity in ("input_layer", "mechanism_layer", "output_layer"):
        append_figure_svg_fragment(
            "method_architecture", identity,
            f'<g id="{identity}"><path d="M0 0L1 1"/></g>', str(tmp_path),
        )
    finalize_figure_svg_draft("method_architecture", str(tmp_path))

    async def fake_invoke(skill_name: str, arguments: str, **_kwargs):
        nonlocal accepted
        calls.append(skill_name)
        prompts.append(arguments)
        accepted = True
        return "done"

    monkeypatch.setattr("server.agent.tools.skill_tool.invoke_skill", fake_invoke)

    class Host:
        async def _emit(self, *_args, **_kwargs):
            return None

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"), opts={"visual_storyboard_review": False}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run"),
    )
    await run_figure_asset_delegates(context)
    assert calls == ["rich-svg-figure"]
    assert ".merak/figure-drafts/method_architecture/method_architecture.svg" in prompts[0]
    assert "Do not read or submit `figures/method_architecture.svg`" in prompts[0]
