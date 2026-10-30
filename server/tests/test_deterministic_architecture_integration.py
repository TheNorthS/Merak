"""Pure/local regressions for source-grounded architecture production gates."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from server.services.deterministic_figure_builder import (
    DeterministicFigureProducerError,
    ensure_evaluation_design,
)
from server.services.figure_artifacts import figure_artifact_registry
from server.services.figure_engine import FigureType, figure_engine
from server.services.figure_models import FigureResult
from server.services.figure_scientific_alignment import (
    _projected_relation_issues,
    candidate_scientific_alignment_issues,
)
from server.services.figure_semantic_projection import project_figure_semantics
from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.services.svg_variant_conversion import convert_svg_variants


class _Registry:
    def __init__(self) -> None:
        self.figures: list[dict] = []

    def load(self, _figures_root: Path) -> dict:
        return {"figures": self.figures}


class _Host:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def _emit(self, _run: object, _event: str, payload: dict) -> None:
        self.events.append(payload)


def _asset() -> dict:
    source = "experiments/METHOD_CONTRACT.json"
    return {
        "id": "method_architecture", "scientific_role": "method",
        "narrative_level": "method_overview",
        "scientific_question": "How does the input become a representation?",
        "producer_kind": "deterministic",
        "production_strategy": "deterministic_architecture",
        "recommended_backend": "figurespec",
        "recommended_skill": "figure-spec",
        "publication_labels": [{
            "schema": 1, "id": "method.mechanism.1", "kind": "concept",
            "display_text": "Patch encoder",
        }],
        "scene_contract": {"contribution_type": "model_architecture"},
        "scientific_scene": {
            "schema": 1,
            "objects": [
                {"id": "input", "kind": "input", "label": "Input signal", "source_path": source},
                {"id": "patch", "kind": "operation", "label": "Patch encoder", "source_path": source},
                {"id": "latent", "kind": "state", "label": "Latent sequence", "source_path": source},
                {"id": "context", "kind": "operation", "label": "Context encoder", "source_path": source},
                {"id": "output", "kind": "output", "label": "Feature embedding", "source_path": source},
                {"id": "test", "kind": "measurement", "label": "Held-out accuracy", "source_path": source},
            ],
            "relations": [
                {"from": "input", "to": "patch", "kind": "data"},
                {"from": "patch", "to": "latent", "kind": "data"},
                {"from": "latent", "to": "context", "kind": "data"},
                {"from": "context", "to": "output", "kind": "data"},
                {"from": "output", "to": "test", "kind": "data"},
            ],
        },
    }


def test_mechanism_detail_keeps_only_authored_internal_story() -> None:
    overview = _asset()
    detail = {**overview, "id": "core_mechanism", "narrative_level": "mechanism_detail"}
    overview_spec = compile_scientific_scene_figure(overview).spec
    detail_spec = compile_scientific_scene_figure(detail).spec
    authored = {item["id"] for item in overview["scientific_scene"]["objects"]}

    assert {node["id"] for node in detail_spec["nodes"]} == {
        "patch", "latent", "context",
    }
    assert {node["id"] for node in overview_spec["nodes"]} != {
        node["id"] for node in detail_spec["nodes"]
    }
    assert {node["id"] for node in detail_spec["nodes"]} <= authored
    assert {(edge["from"], edge["to"]) for edge in detail_spec["edges"]} == {
        ("patch", "latent"), ("latent", "context"),
    }


def test_synthetic_eeg_scene_renders_readable_svg_pdf_png(tmp_path: Path) -> None:
    pytest.importorskip("fitz")
    from server.services.figure_engine import _load_figurespec_renderer
    from server.tests.test_scientific_scene_figure import _eeg_asset

    payload = compile_scientific_scene_figure(_eeg_asset()).spec
    renderer = _load_figurespec_renderer()
    assert renderer.validate_spec(payload) == []
    assert figurespec_layout_issues_payload(payload) == []
    svg, pdf, png = (tmp_path / f"synthetic_eeg_method.{suffix}"
                     for suffix in ("svg", "pdf", "png"))
    svg.write_text(renderer.render_svg(payload), encoding="utf-8")
    converted, error = convert_svg_variants(svg, pdf, png)

    assert converted, error
    assert all(path.is_file() and path.stat().st_size > 0 for path in (svg, pdf, png))
    assert figure_artifact_registry.raster_visual_quality_issues(png) == []


def test_packaged_desktop_includes_native_figurespec_renderer() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "electron-builder.yml").read_text(encoding="utf-8"))
    resources = config.get("extraResources") or []
    assert any(
        item.get("from") == "resources/server-bundle/runtime/win32-x64"
        and item.get("to") == "server-bundle/runtime/win32-x64"
        for item in resources if isinstance(item, dict)
    )
    assert (root / "merak-skills/figure-spec/scripts/figure_renderer.py").is_file()


@pytest.mark.asyncio
async def test_real_local_method_builder_satisfies_final_figure_quality(
    tmp_path: Path,
) -> None:
    pytest.importorskip("fitz")
    from server.services.scientific_assets import scientific_asset_service
    from server.services.figure_spec_repository import persist_figure_specs
    from server.tests._figure_workflow_support import _seed_project

    _seed_project(tmp_path)
    plan = scientific_asset_service.build_plan(
        tmp_path, experiment_requested=False,
    )
    specs = persist_figure_specs(tmp_path, plan)
    method = next(item for item in specs if item["id"] == "method_architecture")
    assert method["production_strategy"] == "deterministic_architecture"
    figures = tmp_path / "figures"
    await ensure_evaluation_design(
        _Host(), object(), figures, [method], plan, set(),
        figure_artifact_registry,
    )
    entry = next(item for item in figure_artifact_registry.load(figures)["figures"]
                 if item["id"] == "method_architecture")
    assert entry["paper_ready"] is True
    assert entry["metadata"]["model_authored"] is False
    assert entry["metadata"]["skill_invocation_verified_by"] == (
        "deterministic-runtime-figure-builder"
    )
    assert figure_artifact_registry.scientific_quality_issues(figures) == []
    assert figure_artifact_registry.scientific_alignment_issues(figures) == []


@pytest.mark.asyncio
async def test_builder_emits_source_bound_provenance_and_reuses_unchanged_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    registry, host = _Registry(), _Host()
    calls: list[dict] = []

    async def generate(**kwargs: object) -> FigureResult:
        calls.append(dict(kwargs))
        metadata = dict(kwargs["metadata"])
        source = figures / "diagrams/method_architecture.json"
        output = figures / "diagrams/method_architecture.pdf"
        source.parent.mkdir(exist_ok=True)
        source.write_text(str(kwargs["code"]), encoding="utf-8")
        output.write_bytes(b"%PDF-1.4\nsource-bound-figure")
        svg = source.with_suffix(".svg")
        png = source.with_suffix(".png")
        svg.write_text("<svg/>", encoding="utf-8")
        png.write_bytes(b"reviewed-pixels")
        metadata["rendered_variants"] = {
            suffix: f"figures/diagrams/method_architecture.{suffix}"
            for suffix in ("json", "svg", "pdf", "png")
        }
        metadata["rendered_variant_sha256"] = {
            suffix: sha256((source.parent / f"method_architecture.{suffix}").read_bytes()).hexdigest()
            for suffix in ("json", "svg", "pdf", "png")
        }
        metadata["visual_review_rounds"] = [{
            "status": "passed",
            "content_sha256": metadata["rendered_variant_sha256"]["json"],
            "render_sha256": metadata["rendered_variant_sha256"]["png"],
        }]
        registry.figures = [{
            "source_path": "figures/diagrams/method_architecture.json",
            "output_path": "figures/diagrams/method_architecture.pdf",
            "source_sha256": sha256(source.read_bytes()).hexdigest(),
            "output_sha256": sha256(output.read_bytes()).hexdigest(),
            "metadata": metadata,
        }]
        return FigureResult(
            True, FigureType.FIGURESPEC,
            source_path=registry.figures[0]["source_path"],
            output_path=registry.figures[0]["output_path"],
        )

    monkeypatch.setattr(figure_engine, "generate", generate)
    spec = _asset()
    entries = await ensure_evaluation_design(
        host, object(), figures, [spec], {}, set(), registry,
    )
    assert len(calls) == 1, [
        call["metadata"]["producer_input_sha256"] for call in calls
    ]
    assert calls[0]["figure_type"] is FigureType.FIGURESPEC
    source = json.loads(str(calls[0]["code"]))
    projected = project_figure_semantics(spec)
    assert {node["id"] for node in source["nodes"]} == {
        item["id"] for item in projected["entities_states_transformations"]
    }
    assert {(edge["from"], edge["to"]) for edge in source["edges"]} == {
        (item["from"], item["to"]) for item in projected["relations"]
    }
    metadata = dict(calls[0]["metadata"])
    assert metadata["producer_kind"] == "deterministic"
    assert metadata["generator_skill"] == "figure-spec"
    assert metadata["skill_invocation_verified_by"] == "deterministic-runtime-figure-builder"
    assert metadata["architecture_source"] == "deterministic-source-grounded-scene"
    assert len(metadata["producer_input_sha256"]) == 64
    assert all(
        entries["method_architecture"]["metadata"].get(key) == value
        for key, value in metadata.items()
    )
    assert host.events[-1]["success"] is True

    await ensure_evaluation_design(host, object(), figures, [spec], {}, set(), registry)
    assert len(calls) == 1, [
        call["metadata"]["producer_input_sha256"] for call in calls
    ]
    (figures / "diagrams/method_architecture.png").write_bytes(b"tampered-pixels")
    await ensure_evaluation_design(host, object(), figures, [spec], {}, set(), registry)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_invalid_scene_fails_before_any_render_or_manifest_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    registry = _Registry()
    calls = 0

    async def generate(**_kwargs: object) -> FigureResult:
        nonlocal calls
        calls += 1
        return FigureResult(True, FigureType.FIGURESPEC)

    monkeypatch.setattr(figure_engine, "generate", generate)
    spec = _asset()
    spec["scientific_scene"]["relations"][0]["to"] = "missing_object"
    with pytest.raises(DeterministicFigureProducerError, match="source-grounded architecture compilation failed"):
        await ensure_evaluation_design(
            _Host(), object(), figures, [spec], {}, set(), registry,
        )
    assert calls == 0
    assert registry.figures == []


@pytest.mark.asyncio
async def test_one_bad_architecture_does_not_skip_a_sibling_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    registry, host = _Registry(), _Host()
    bad, good = _asset(), deepcopy(_asset())
    bad["id"] = "bad_architecture"
    bad["scientific_scene"]["relations"][0]["to"] = "absent"
    good["id"] = "good_architecture"
    generated: list[str] = []

    async def generate(**kwargs: object) -> FigureResult:
        generated.append(str(kwargs["artifact_name"]))
        return FigureResult(True, FigureType.FIGURESPEC)

    monkeypatch.setattr(figure_engine, "generate", generate)
    with pytest.raises(DeterministicFigureProducerError, match="bad_architecture"):
        await ensure_evaluation_design(
            host, object(), figures, [bad, good], {}, set(), registry,
        )
    assert generated == ["good_architecture"]


def test_scoped_relation_and_publication_label_gates_remain_blocking(tmp_path: Path) -> None:
    spec = _asset()
    source = tmp_path / "figures" / "diagrams" / "method_architecture.json"
    source.parent.mkdir(parents=True)
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text("{}", encoding="utf-8")
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [spec]}), encoding="utf-8",
    )
    payload = compile_scientific_scene_figure(spec).spec
    source.write_text(json.dumps(payload), encoding="utf-8")
    metadata = {**spec, "semantic_key": spec["id"]}

    assert _projected_relation_issues(spec["id"], spec, source) == []
    assert candidate_scientific_alignment_issues(
        figure_artifact_registry, tmp_path, metadata, source,
    ) == []

    payload["edges"].pop()
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert any("relations differ" in issue for issue in _projected_relation_issues(
        spec["id"], spec, source,
    ))
    assert any("relations differ" in issue for issue in candidate_scientific_alignment_issues(
        figure_artifact_registry, tmp_path, metadata, source,
    ))

    payload = compile_scientific_scene_figure(spec).spec
    next(node for node in payload["nodes"] if node["id"] == "patch")["label"] = "Generic transformation"
    source.write_text(json.dumps(payload), encoding="utf-8")
    issues = candidate_scientific_alignment_issues(
        figure_artifact_registry, tmp_path, metadata, source,
    )
    assert any("omits required domain-facing terms" in issue for issue in issues)
