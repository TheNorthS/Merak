from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.agent.tools.figure_draft_review import require_current_composition_review
from server.agent.tools.figure_tool import FigureRequest, _apply_plan, _figure_code
from server.agent.tools.figure_draft_tools import (
    _blueprint_sha256,
    current_draft_matches_storyboard,
    draft_print_diagnostics,
    prepare_model_svg_draft,
    submit_model_svg_draft,
)
from server.services.figure_draft_best import preserve_best_draft
from server.services.figure_models import FigureType
from server.services.rich_svg_blueprint import (
    FLOW_KIND_VALUES,
    MIN_BLUEPRINT_PRIMITIVES,
    STORYBOARD_FLOW_KIND_DEFAULTS,
    VISUAL_FORM_VALUES,
)
from server.services.rich_svg_backend import _finish_rendered_candidate
from server.services.rich_svg_visual_review import REVIEW_POLICY_VERSION


def _blueprint() -> dict:
    primitives = [
        ("input", "signal", "source", "Input signal"),
        ("method", "algorithm", "focal_process", "Shared method"),
        ("control", "constraint", "control", "Matched control"),
        ("readout", "distribution", "readout", "Primary readout"),
        ("decision", "equation", "output", "Decision gate"),
    ]
    return {
        "schema": 1,
        "compiler": "model-authored-svg-v1",
        "narrative_level": "method_overview",
        "focal_message": "A matched comparison isolates the scientific mechanism.",
        "figure_label": "Matched mechanism overview",
        "primitives": [
            {
                "id": identity, "visual_form": form, "public_label": label,
                "role": role, "scientific_meaning": label,
                "annotations": [],
                **({"notation": "accept iff evidence passes"} if identity == "decision" else {}),
            }
            for identity, form, role, label in primitives
        ],
        "reading_order": [item[0] for item in primitives],
        "flows": [
            {"from": "input", "to": "method", "kind": "data"},
            {"from": "control", "to": "method", "kind": "control"},
            {"from": "method", "to": "readout", "kind": "causal"},
            {"from": "readout", "to": "decision", "kind": "logical"},
        ],
    }


def _svg(*, decision_x: int = 480) -> str:
    groups = [
        ("input", 20, "Input signal"),
        ("method", 140, "Shared method"),
        ("control", 260, "Matched control"),
        ("readout", 380, "Primary readout"),
        ("decision", decision_x, "Decision gate"),
    ]
    body = "".join(
        f'<g id="{identity}"><rect x="{x}" y="65" width="100" height="70" '
        f'fill="#e8f1f8" stroke="#334155"/><text x="{x + 50}" y="105" '
        f'font-size="18" text-anchor="middle">{label}</text></g>'
        for identity, x, label in groups
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 200">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" '
        'refY="4"><path d="M0 0L8 4L0 8Z" fill="#334155"/></marker></defs>'
        f'{body}<g id="relations"><path d="M120 100H140M240 100H260M360 100H380M480 100H{decision_x}" '
        'fill="none" stroke="#334155" marker-end="url(#arrow)"/></g></svg>'
    )


def _mappings(source_path: str = "ideas/SELECTED_IDEA.json") -> list[dict]:
    return [
        {
            "element_id": identity,
            "source_path": source_path,
            "semantic_role": identity,
        }
        for identity in ("input", "method", "control", "readout", "decision")
    ]


def _project(root: Path) -> None:
    (root / "figures").mkdir()
    (root / "ideas").mkdir()
    (root / "ideas" / "SELECTED_IDEA.json").write_text(
        '{"hypothesis":"matched comparison"}', encoding="utf-8",
    )
    (root / "figures" / "FIGURE_SPECS.json").write_text(json.dumps({
        "figures": [{
            "id": "method_architecture", "kind": "figure",
            "producer_kind": "model", "recommended_backend": "rich_svg",
            "recommended_skill": "model-svg-figure",
            "production_strategy": "model_composed_full_svg",
            "composition_owner": "model", "scientific_role": "method",
            "scientific_question": "How is the mechanism compared?",
            "reading_goal": "See the matched mechanism in five seconds.",
            "design_brief": {
                "schema": 1,
                "scientific_question": "How is the mechanism compared?",
                "reading_goal": "See the matched mechanism in five seconds.",
                "must_show": ["Input signal", "Shared method", "Decision gate"],
                "must_not_show": ["quantitative results"],
                "minimum_font_pt": 8.0,
                "maximum_primary_objects": 7,
            },
            "source_artifacts": ["ideas/SELECTED_IDEA.json"],
            "scientific_scene": {
                "schema": 1,
                "objects": [
                    {
                        "id": identity,
                        "kind": "operation",
                        "label": label,
                        "source_path": "ideas/SELECTED_IDEA.json",
                    }
                    for identity, label in (
                        ("input_source", "Input signal"),
                        ("shared_method", "Shared method"),
                        ("matched_control", "Matched control"),
                        ("primary_readout", "Primary readout"),
                        ("decision_gate", "Decision gate"),
                    )
                ],
                "relations": [],
            },
            "scene_contract": {
                "target_width_fraction": 1.0,
                "minimum_placed_font_pt": 8.0,
                "maximum_primary_nodes": 7,
            },
        }],
    }), encoding="utf-8")


def test_model_composed_svg_is_source_bound_and_print_checked(tmp_path: Path) -> None:
    _project(tmp_path)
    prepared = json.loads(prepare_model_svg_draft(
        "method_architecture", str(tmp_path),
    ))
    assert prepared["production_strategy"] == "model_composed_full_svg"
    assert prepared["design_brief"]["must_show"][-1] == "Decision gate"
    assert prepared["source_bindings"][0]["status"] == "file"
    blueprint_contract = prepared["visual_blueprint_contract"]
    assert blueprint_contract["visual_forms"] == list(VISUAL_FORM_VALUES)
    assert blueprint_contract["flow_kinds"] == list(FLOW_KIND_VALUES)
    assert blueprint_contract["minimum_primitives"] == MIN_BLUEPRINT_PRIMITIVES
    assert blueprint_contract["maximum_primitives"] == 7
    assert blueprint_contract["storyboard_flow_kind_defaults"] == (
        STORYBOARD_FLOW_KIND_DEFAULTS
    )
    mapping_contract = prepared["element_mapping_contract"]
    assert mapping_contract["minimum_mapped_groups"] == 4
    assert mapping_contract["candidate_exhaustion_required"] is False
    assert mapping_contract["mapping_candidates"][0]["origin"] == (
        "scientific_scene"
    )
    assert "storyboard-only relation kinds" in prepared["instruction"]

    staged = json.loads(submit_model_svg_draft(
        "method_architecture", _svg(), _blueprint(), str(tmp_path),
        element_mappings=_mappings(),
    ))
    assert staged["status"] == "finalized"
    assert staged["authoring_mode"] == "model_composed"
    assert staged["semantic_group_ids"] == [
        "control", "decision", "input", "method", "readout",
    ]
    assert staged["element_mappings"] == _mappings()
    manifest = json.loads((
        tmp_path / ".merak" / "figure-drafts" / "method_architecture"
        / "manifest.json"
    ).read_text(encoding="utf-8"))
    assert manifest["element_mappings"] == _mappings()
    assert manifest["element_mappings_sha256"] == staged[
        "element_mappings_sha256"
    ]
    source = (
        tmp_path / ".merak" / "figure-drafts" / "method_architecture"
        / "method_architecture.svg"
    )
    assert source.read_text(encoding="utf-8") == _svg().strip() + "\n"
    assert current_draft_matches_storyboard(tmp_path, "method_architecture")
    diagnostics = json.loads(draft_print_diagnostics(
        "method_architecture", str(tmp_path),
    ))
    assert diagnostics["status"] == "print_ready"

    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        '{"hypothesis":"changed after SVG review"}', encoding="utf-8",
    )
    assert not current_draft_matches_storyboard(tmp_path, "method_architecture")


def test_prepare_and_review_share_only_compact_probe_states(tmp_path: Path) -> None:
    from server.agent.tools.figure_draft_review import _composition_metadata
    from server.services.rich_svg_visual_review import _brief_sha256, _prompt

    _project(tmp_path)
    specs_path = tmp_path / "figures" / "FIGURE_SPECS.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    status = {
        "name": "subject_session_probe", "mechanism_id": "M2",
        "source_path": "experiments/configs/main.yaml",
        "training_mode": "frozen_downstream", "head_status": "not_required",
        "joint_objective_status": "inactive", "missing_heads": [],
    }
    specs["figures"][0]["method_brief"] = {
        "probe_configuration": [{**status, "unrelated_yaml": "do not reveal"}],
    }
    specs_path.write_text(json.dumps(specs), encoding="utf-8")

    prepared = json.loads(prepare_model_svg_draft("method_architecture", str(tmp_path)))
    metadata = _composition_metadata(tmp_path, "method_architecture", _blueprint())
    assert prepared["probe_configuration"] == [status]
    assert metadata["probe_configuration"] == [status]
    prompt = _prompt("method_architecture", metadata)
    assert '"training_mode": "frozen_downstream"' in prompt
    assert "do not reveal" not in prompt
    original_brief = _brief_sha256(metadata)
    metadata["probe_configuration"][0]["training_mode"] = "joint_objective"
    assert _brief_sha256(metadata) != original_brief


def test_formal_submission_preserves_preflight_brief_with_probe_states(
    tmp_path: Path,
) -> None:
    from server.agent.tools.figure_draft_review import (
        _composition_metadata, _persist_composition_review,
    )
    from server.agent.tools.figure_tool import _metadata
    from server.services.api_visual_review_schemas import RICH_SVG_CHECKS
    from server.services.rich_svg_visual_review import _brief_sha256, native_review_issues

    _project(tmp_path)
    specs_path = tmp_path / "figures" / "FIGURE_SPECS.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    specs["figures"][0]["method_brief"] = {"probe_configuration": [{
        "name": "subject_probe", "mechanism_id": "M2",
        "training_mode": "frozen_downstream", "head_status": "not_required",
        "joint_objective_status": "inactive",
    }]}
    specs_path.write_text(json.dumps(specs), encoding="utf-8")
    blueprint = _blueprint()
    staged = json.loads(submit_model_svg_draft(
        "method_architecture", _svg(), blueprint, str(tmp_path),
        element_mappings=_mappings(),
    ))
    source = tmp_path / staged["source_path"]
    directory = source.parent
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    preflight = _composition_metadata(tmp_path, "method_architecture", blueprint, manifest)
    preview = directory / "preview.png"
    preview.write_bytes(b"local test pixels")
    image_sha = hashlib.sha256(preview.read_bytes()).hexdigest()
    trace = tmp_path / ".merak" / "model-api-reviewer" / "parity-test"
    trace.mkdir(parents=True)
    (trace / "meta.json").write_text(json.dumps({
        "success": True, "invocation_id": "test-invocation", "model_identity": "test-model",
        "image_sha256": {"preview": image_sha},
        "image_attachment_mode": "api-native-image-content",
    }), encoding="utf-8")
    review = {
        "protocol": "native-image-v1", "score": 8.8, "verdict": "accept",
        "review_policy_version": REVIEW_POLICY_VERSION, "findings": [],
        "checklist": {key: True for key in RICH_SVG_CHECKS}, "issues": [],
        "brief_sha256": _brief_sha256(preflight), "source_sha256": staged["source_sha256"],
        "image_sha256": image_sha, "review_trace_path": str(trace),
        "review_invocation_id": "test-invocation", "review_model_identity": "test-model",
        "blind_readback": {"mechanism_recoverable": True, "directed_relations": ["a", "b", "c"]},
        "blind_readback_issues": [], "blind_readback_trace_path": str(trace),
    }
    _persist_composition_review(directory, source.read_text(encoding="utf-8"), blueprint, review, [], preview)

    class Registry:
        @staticmethod
        def project_root(_figures_root: Path) -> Path:
            return tmp_path

    request = FigureRequest(
        description="model-owned concept diagram", artifact_name="method_architecture",
        figure_type="rich_svg", source_path=staged["source_path"],
        visual_blueprint=blueprint, generator_skill="model-svg-figure",
        planned_spec=specs["figures"][0],
    )
    formal = _metadata(request)
    assert _figure_code(request, Registry(), tmp_path / "figures", formal) == _svg().strip() + "\n"
    assert formal["probe_configuration"] == preflight["probe_configuration"]
    assert _brief_sha256(formal) == review["brief_sha256"]
    assert native_review_issues(formal, tmp_path, source, preview) == []


def test_design_assets_scene_sources_feed_model_mapping_contract(
    tmp_path: Path,
) -> None:
    from server.services.figure_spec_repository import persist_figure_specs
    from server.services.scientific_asset_builders import design_assets
    from server.services.scientific_asset_routing import route_scientific_assets

    (tmp_path / "ideas").mkdir()
    (tmp_path / "figures").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        '{"hypothesis":"matched comparison"}', encoding="utf-8",
    )
    labels = [
        "Input signal", "Shared method", "Matched control",
        "Primary readout", "Decision gate",
    ]
    scene_objects = [
        {
            "id": f"scene_{index}",
            "kind": "operation",
            "label": label,
            "source_path": "ideas/SELECTED_IDEA.json",
        }
        for index, label in enumerate(labels, 1)
    ]
    context = {
        "title": "Matched mechanism study",
        "hypothesis": "A matched comparison isolates the mechanism.",
        "claims": [{"id": "C1"}],
        "mechanisms": [
            {"name": label, "publication_name": label} for label in labels
        ],
        "source_artifacts": ["ideas/SELECTED_IDEA.json"],
        "publication": {
            "language": "en",
            "method_name": "Shared method",
            "contribution_type": "model_architecture",
        },
        "method_contract": {
            "scientific_scene": {
                "schema": 1,
                "objects": scene_objects,
                "relations": [
                    {"from": "scene_1", "to": "scene_2", "kind": "data"},
                    {"from": "scene_3", "to": "scene_2", "kind": "constraint"},
                    {"from": "scene_2", "to": "scene_4", "kind": "causal"},
                    {"from": "scene_4", "to": "scene_5", "kind": "logical"},
                ],
            },
        },
    }
    style = {
        "family": "machine_learning",
        "study_archetype": "algorithm_benchmark",
        "figure_roles": [],
    }
    assets = design_assets(context, {}, True, publication_style=style)
    method_asset = next(item for item in assets if item["id"] == "method_architecture")
    method_asset["production_strategy"] = "model_composed_full_svg"
    plot_roles = {
        "result": "interval_comparison",
        "ablation": "interval_comparison",
        "robustness": "stress_curve",
        "calibration": "calibration",
    }
    route_scientific_assets(
        assets, style, "", {
            "generic_empirical": plot_roles,
            "algorithm_benchmark": plot_roles,
        },
    )
    persist_figure_specs(tmp_path, {
        "assets": assets,
        "publication_style": style,
        "evidence_mode": "design_only",
    })
    spec = next(item for item in assets if item["id"] == "method_architecture")
    assert "element_mappings" not in spec
    assert spec["scientific_scene"]["objects"] == scene_objects

    prepared = json.loads(prepare_model_svg_draft(
        "method_architecture", str(tmp_path),
    ))
    candidates = prepared["element_mapping_contract"]["mapping_candidates"]
    assert {
        item["scientific_object_id"] for item in candidates
        if item.get("scientific_object_id")
    } == {
        f"scene_{index}" for index in range(1, 6)
    }
    blueprint = _blueprint()
    for index, primitive in enumerate(blueprint["primitives"][:4], 1):
        primitive["scientific_object_id"] = f"scene_{index}"
    staged = json.loads(submit_model_svg_draft(
        "method_architecture", _svg(), blueprint, str(tmp_path),
        element_mappings=_mappings()[:4],
    ))
    assert len(staged["element_mappings"]) == 4


def test_generate_route_accepts_model_svg_skill_for_full_composition(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    spec = json.loads(
        (tmp_path / "figures" / "FIGURE_SPECS.json").read_text(encoding="utf-8")
    )["figures"][0]
    request = FigureRequest(
        description="model-owned concept diagram",
        artifact_name="method_architecture",
        figure_type="rich_svg",
        recommended_backend="rich_svg",
        recommended_skill="model-svg-figure",
        planned_spec=spec,
    )
    assert _apply_plan(request, object(), tmp_path / "figures") == ""
    assert request.recommended_skill == "model-svg-figure"


@pytest.mark.parametrize(
    ("mappings", "message"),
    [
        (
            [
                {**item, "element_id": "unknown_group"}
                if index == 0 else item
                for index, item in enumerate(_mappings())
            ],
            "unknown semantic group 'unknown_group'",
        ),
        (
            [
                {**item, "source_path": "secrets/undeclared.json"}
                if index == 0 else item
                for index, item in enumerate(_mappings())
            ],
            "is not declared by FIGURE_SPECS",
        ),
    ],
)
def test_model_composed_submission_rejects_unknown_mapping_contract_values(
    tmp_path: Path, mappings: list[dict], message: str,
) -> None:
    _project(tmp_path)

    with pytest.raises(ValueError, match=message):
        submit_model_svg_draft(
            "method_architecture", _svg(), _blueprint(), str(tmp_path),
            element_mappings=mappings,
        )


def test_model_composed_submission_requires_explicit_mappings(tmp_path: Path) -> None:
    from server.agent.tools.tool_registration import TOOL_SPECS

    _project(tmp_path)
    schema = next(
        item[2] for item in TOOL_SPECS if item[0] == "submit_model_svg_draft"
    )
    assert "element_mappings" in schema["required"]
    assert schema["properties"]["element_mappings"]["items"][
        "additionalProperties"
    ] is False

    with pytest.raises(ValueError, match="element_mappings must be an array"):
        submit_model_svg_draft(
            "method_architecture", _svg(), _blueprint(), str(tmp_path),
        )


def _source_bound_pair(root: Path) -> dict:
    _project(root)
    path = root / "figures" / "FIGURE_SPECS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["figures"][0]["scientific_scene"]["relations"] = [{
        "from": "input_source", "to": "shared_method", "kind": "data",
    }]
    path.write_text(json.dumps(payload), encoding="utf-8")
    blueprint = _blueprint()
    blueprint["primitives"][0]["scientific_object_id"] = "input_source"
    blueprint["primitives"][1]["scientific_object_id"] = "shared_method"
    return blueprint


def test_missing_source_relation_is_rejected_before_draft_write(tmp_path: Path) -> None:
    blueprint = _source_bound_pair(tmp_path)
    blueprint["flows"] = blueprint["flows"][1:]

    with pytest.raises(ValueError, match="input_source->shared_method \\(data\\)"):
        submit_model_svg_draft(
            "method_architecture", _svg(), blueprint, str(tmp_path),
            element_mappings=_mappings(),
        )

    assert not (tmp_path / ".merak" / "figure-drafts" / "method_architecture" / "manifest.json").exists()
    assert not (tmp_path / ".merak" / "figure-drafts" / "method_architecture" / "method_architecture.svg").exists()


def test_formal_submission_rechecks_source_relation_contract(tmp_path: Path) -> None:
    from server.agent.tools.figure_draft_review import _model_composed_blueprint_issues

    blueprint = _source_bound_pair(tmp_path)
    submit_model_svg_draft(
        "method_architecture", _svg(), blueprint, str(tmp_path),
        element_mappings=_mappings(),
    )
    path = tmp_path / "figures" / "FIGURE_SPECS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["figures"][0]["scientific_scene"]["relations"][0]["kind"] = "control"
    path.write_text(json.dumps(payload), encoding="utf-8")
    directory = tmp_path / ".merak" / "figure-drafts" / "method_architecture"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))

    issues = _model_composed_blueprint_issues(directory, manifest, blueprint)

    assert any("cannot be drawn as active data/causal" in item for item in issues)


@pytest.mark.parametrize("bad_source", [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><script/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><g id="input"/><g id="input"/></svg>',
])
def test_model_composed_svg_rejects_unsafe_or_ambiguous_source(
    tmp_path: Path, bad_source: str,
) -> None:
    _project(tmp_path)
    with pytest.raises(ValueError, match="model-composed SVG contract failed"):
        submit_model_svg_draft(
            "method_architecture", bad_source, _blueprint(), str(tmp_path),
            element_mappings=_mappings(),
        )


def test_model_composed_submission_reports_canonical_values_for_aliases(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    blueprint = _blueprint()
    blueprint["primitives"][0]["visual_form"] = "waveform"
    blueprint["flows"][0]["kind"] = "main"

    with pytest.raises(ValueError) as captured:
        submit_model_svg_draft(
            "method_architecture", _svg(), blueprint, str(tmp_path),
            element_mappings=_mappings(),
        )

    message = str(captured.value)
    assert "unsupported visual forms: waveform" in message
    assert "accepted visual_form values: " + ", ".join(VISUAL_FORM_VALUES) in message
    assert "unsupported kind 'main'" in message
    assert "accepted flow kind values: " + ", ".join(FLOW_KIND_VALUES) in message


def test_model_composed_submission_is_hash_bound_to_accepted_review(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    blueprint = _blueprint()
    staged = json.loads(submit_model_svg_draft(
        "method_architecture", _svg(), blueprint, str(tmp_path),
        element_mappings=_mappings(),
    ))
    directory = tmp_path / ".merak" / "figure-drafts" / "method_architecture"
    source = directory / "method_architecture.svg"
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["composition_review"] = {
        "source_sha256": staged["source_sha256"],
        "source_bundle_sha256": staged["source_bundle_sha256"],
        "figure_spec_sha256": staged["figure_spec_sha256"],
        "element_mappings_sha256": staged["element_mappings_sha256"],
        "visual_blueprint_sha256": _blueprint_sha256(blueprint),
        "score": 8.8, "verdict": "accept", "issues": [], "findings": [],
        "checklist": {
            "five_second_comprehension": True,
            "scientific_mechanism_clarity": True,
            "causal_flow": True,
            "paper_scale_readability": True,
            "no_visual_artifacts": True,
        },
        "independent_visual_review": {"review_policy_version": REVIEW_POLICY_VERSION},
        "blind_readback_issues": [],
        "blind_readback": {
            "mechanism_recoverable": True,
            "directed_relations": ["a", "b", "c"],
        },
        "blind_readback_trace_path": ".merak/model-api-reviewer/readback",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    require_current_composition_review(
        tmp_path, "method_architecture", source, blueprint,
    )

    class Registry:
        @staticmethod
        def project_root(_figures_root: Path) -> Path:
            return tmp_path

    request = FigureRequest(
        description="model-owned concept diagram",
        artifact_name="method_architecture", figure_type="rich_svg",
        source_path=source.relative_to(tmp_path).as_posix(),
        visual_blueprint=blueprint, generator_skill="model-svg-figure",
    )
    metadata: dict = {}
    assert _figure_code(request, Registry(), tmp_path / "figures", metadata) == (
        _svg().strip() + "\n"
    )
    assert metadata["element_mappings"] == _mappings()
    assert metadata["element_mappings_sha256"] == staged[
        "element_mappings_sha256"
    ]

    source.write_text(_svg(decision_x=500), encoding="utf-8")
    with pytest.raises(ValueError, match="changed after semantic validation"):
        require_current_composition_review(
            tmp_path, "method_architecture", source, blueprint,
        )


def test_model_composed_best_draft_restores_lower_scoring_revision(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    blueprint = _blueprint()
    first = json.loads(submit_model_svg_draft(
        "method_architecture", _svg(), blueprint, str(tmp_path),
        element_mappings=_mappings(),
    ))
    directory = tmp_path / ".merak" / "figure-drafts" / "method_architecture"
    source = directory / "method_architecture.svg"
    regressed, score = preserve_best_draft(
        directory, source,
        {"score": 8.2, "verdict": "refine", "findings": []},
        ["minor spacing"], _blueprint_sha256(blueprint),
    )
    assert not regressed and score == 8.2

    submit_model_svg_draft(
        "method_architecture", _svg(decision_x=500), blueprint, str(tmp_path),
        element_mappings=_mappings(),
    )
    regressed, score = preserve_best_draft(
        directory, source,
        {"score": 7.5, "verdict": "refine", "findings": []},
        ["worse spacing"], _blueprint_sha256(blueprint),
    )
    assert regressed and score == 8.2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == first["source_sha256"]


@pytest.mark.asyncio
async def test_formal_render_reuses_hash_bound_preflight_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "concept.svg"
    pdf = tmp_path / "concept.pdf"
    png = tmp_path / "concept.png"
    for path, payload in ((source, b"<svg/>"), (pdf, b"pdf"), (png, b"png")):
        path.write_bytes(payload)
    accepted = {
        "protocol": "native-image-v1", "verdict": "accept", "score": 9.0,
        "checklist": {},
    }

    class Registry:
        @staticmethod
        def raster_visual_quality_issues(_path: Path) -> list[str]:
            return []

        @staticmethod
        def rich_svg_render_issues(_path: Path) -> list[str]:
            return []

    import server.services.rich_svg_visual_review as review_module

    monkeypatch.setattr(review_module, "native_review_issues", lambda *args: [])

    async def duplicate_review(**_kwargs: object) -> tuple[dict, list[str]]:
        raise AssertionError("formal render must not repeat an identical model review")

    monkeypatch.setattr(review_module, "review_candidate", duplicate_review)
    result = await _finish_rendered_candidate(
        registry=Registry(), root_path=tmp_path, artifact_stem="concept",
        source=source, pdf=pdf, png=png, svg="<svg/>\n",
        value={
            "production_strategy": "model_composed_full_svg",
            "independent_visual_review": accepted,
        },
        mappings=[], ids=set(), review=tmp_path / "review.json",
        append_review=lambda _path, record: [record],
        sha256_path=lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert result.success
    assert result.figure_type == FigureType.RICH_SVG
    assert result.metadata["independent_visual_review"] == accepted
