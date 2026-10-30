from __future__ import annotations

from server.tests._figure_workflow_support import (
    AgentEngine as AgentEngine,
    ET as ET,
    FigureResult as FigureResult,
    FigureType as FigureType,
    Image as Image,
    Path as Path,
    ToolCall as ToolCall,
    WorkflowEngine as WorkflowEngine,
    WorkflowRun as WorkflowRun,
    _author_plan_figures as _author_plan_figures,
    _author_rich_svg_asset as _author_rich_svg_asset,
    _build_figures as _build_figures,
    _disable_live_electron_renderer_discovery as _disable_live_electron_renderer_discovery,
    _seed_project as _seed_project,
    asyncio as asyncio,
    csv as csv,
    figure_artifact_registry as figure_artifact_registry,
    figure_engine as figure_engine,
    hashlib as hashlib,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    pytest as pytest,
    re as re,
    scientific_asset_service as scientific_asset_service,
)
from server.services.api_visual_review_invocation import ApiVisualReview
from server.services.api_visual_review_schemas import RICH_SVG_CHECKS


async def _semantic_name_renderer_transport(code: str, output_path: str | Path) -> tuple[bool, str]:
    """A finite unit-transport scene; conversion, registration and gates remain real."""
    from server.services.svg_variant_conversion import convert_svg_variants

    assert "A[EEG channels] --> B[Montage adapter] --> C[Encoder]" in code
    output = Path(output_path)
    svg = output.with_suffix(".svg")
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="480" viewBox="0 0 1200 480">'
        '<rect width="1200" height="480" fill="white"/>'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
        '<path d="M 0 0 L 10 5 L 0 10 Z" fill="#33556A"/></marker></defs>'
        '<g fill="#E8F1F7" stroke="#33556A" stroke-width="3">'
        '<rect id="A" x="50" y="170" width="300" height="140" rx="12"/>'
        '<rect id="B" x="450" y="170" width="300" height="140" rx="12"/>'
        '<rect id="C" x="850" y="170" width="300" height="140" rx="12"/></g>'
        '<g stroke="#33556A" stroke-width="4" marker-end="url(#arrow)">'
        '<path id="A-B" d="M 350 240 L 450 240"/><path id="B-C" d="M 750 240 L 850 240"/></g>'
        '<g font-family="Arial" font-size="30" text-anchor="middle" fill="#182535">'
        '<text x="200" y="250">EEG channels</text><text x="600" y="250">Montage adapter</text>'
        '<text x="1000" y="250">Encoder</text></g></svg>', encoding="utf-8")
    if output.suffix == ".svg":
        return True, ""
    return convert_svg_variants(svg, output.with_suffix(".pdf"), output.with_suffix(".png"))


@pytest.fixture(autouse=True)
def _accept_local_figure_pixels_without_external_reviewer(monkeypatch) -> None:
    async def fake_review(**kwargs):
        root = Path(kwargs["project_path"])
        preview = Path(kwargs["image_path"])
        trace = root / ".merak" / "model-api-reviewer" / "fixture-rich-svg"
        trace.mkdir(parents=True, exist_ok=True)
        (trace / "meta.json").write_text(json.dumps({
            "success": True, "invocation_id": "model-api:fixture",
            "model_identity": "fixture-reviewer",
            "image_attachment_mode": "api-native-image-content",
            "image_sha256": {
                preview.relative_to(root).as_posix(): hashlib.sha256(preview.read_bytes()).hexdigest(),
            },
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


def test_figure_alignment_accepts_agent_svg_public_semantic_aggregation(
    tmp_path: Path,
) -> None:
    """A rich SVG must not be forced to expose low-level code symbols.

    Agent-authored SVGs do not carry the deterministic compiler profile.  Their
    visible mechanism blocks plus hash-bound element mappings provide the same
    proof that implementation components were aggregated into paper language.
    """
    (tmp_path / "ideas").mkdir(parents=True)
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    mechanism_names = (
        "Registered multi-axis estimation", "Traceable comparison evidence",
        "Matched protocol ablation", "Protected evaluation isolation",
        "Controlled device measurement",
    )
    mechanisms = [
        {
            "id": f"M{index}", "name": name,
            "publication_name": name,
            "publication_description": f"Defines the {name.casefold()} operation.",
            "publication_evaluation": "Matched comparison against the control.",
        }
        for index, name in enumerate(mechanism_names, start=1)
    ]
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Multi-axis comparison study",
            "claims": [{"id": "C1", "statement": "Rankings vary by axis."}],
            "mechanisms": mechanisms,
        }),
        encoding="utf-8",
    )
    components = [
        {
            "id": f"component_{index}",
            "display_name": f"Internal Function {index}",
            "source_path": f"experiments/src/module_{index}.py",
            "source_symbol": f"internal_function_{index}",
            "required_visual": True,
        }
        for index in range(12)
    ]
    asset = {
        "id": "method_architecture",
        "scientific_role": "method",
        "claim_ids": ["C1"],
        "publication_labels": [
            {"schema": 1, "id": f"method.component.{index}", "kind": "concept", "display_text": item["display_name"]}
            for index, item in enumerate(components, start=1)
        ],
        "architecture_blueprint": {"components": components},
    }
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [asset]}),
        encoding="utf-8",
    )
    mapped_indexes = [0, 3, 6, 9, 11]
    mappings = [
        {
            "element_id": f"public_block_{offset}",
            "semantic_role": mechanisms[offset]["name"],
            "source_path": components[index]["source_path"],
            "source_symbol": components[index]["source_symbol"],
        }
        for offset, index in enumerate(mapped_indexes)
    ]
    source = diagrams / "method_architecture.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        + "".join(
            f'<g id="public_block_{index}"><text>{item["publication_name"]}</text></g>'
            for index, item in enumerate(mechanisms)
        )
        + "</svg>",
        encoding="utf-8",
    )
    output = diagrams / "method_architecture.png"
    Image.new("RGB", (1600, 900), "white").save(output)
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="rich_svg",
        description="method_architecture",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "method_architecture",
            "managed_by": "merak",
            "scientific_role": "method",
            "paper_selected": True,
            "claim_ids": ["C1"],
            "source_data": ["ideas/SELECTED_IDEA.json"],
            "scientific_question": "How is the comparison operationalized?",
            "intended_comparison": "Registered model rankings",
            "visual_encoding": "Publication-facing mechanism blocks",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
            "element_mappings": mappings,
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(
        tmp_path / "figures"
    )

    assert not any("architecture renders only" in issue for issue in issues)
    assert not any("source omits required domain-facing terms" in issue for issue in issues)


def test_figure_gate_rejects_hash_valid_generic_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    manifest_path = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    method = next(
        item for item in manifest["figures"]
        if (item.get("metadata") or {}).get("semantic_key") == "method_architecture"
    )
    source = tmp_path / method["source_path"]
    output = tmp_path / method["output_path"]
    source.write_text(
        "stateDiagram-v2\n"
        "[*] --> Idle\n"
        "Idle --> Running: start\n"
        "Running --> Completed: success\n"
        "Running --> Failed: error\n",
        encoding="utf-8",
    )
    figure_artifact_registry.record(
        output_dir=source.parent,
        figure_type="mermaid",
        description=method["description"],
        output_path=str(output),
        source_path=str(source),
        metadata=dict(method["metadata"]),
    )

    gate = engine._figure_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert any(
        "generic template" in issue
        or "omits frozen claim IDs" in issue
        or "required mechanism IDs" in issue
        for issue in gate["details"]["issues"]
    )


def test_semantic_figure_name_is_stable_and_reused(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ELECTRON_API_PORT", raising=False)
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    calls = []
    async def transport(code, output):
        calls.append(Path(output).suffix)
        return await _semantic_name_renderer_transport(code, output)
    monkeypatch.setattr("server.services.figure_engine._render_mermaid_with_electron", transport)
    output_dir = tmp_path / "figures" / "diagrams"
    kwargs = {
        "description": "EEG montage-aware method architecture",
        "artifact_name": "eeg_montage_method_architecture",
        "figure_type": FigureType.MERMAID,
        "output_dir": str(output_dir),
        "code": "flowchart LR\nA[EEG channels] --> B[Montage adapter] --> C[Encoder]",
        "metadata": {"scientific_role": "method", "claim_ids": ["C1"]},
    }

    first = asyncio.run(figure_engine.generate(**kwargs))
    second = asyncio.run(figure_engine.generate(**kwargs))
    refreshed = asyncio.run(figure_engine.generate(
        **{
            **kwargs,
            "metadata": {
                **kwargs["metadata"],
                "scientific_question": "Does the adapter preserve the declared mechanism?",
                "intended_comparison": "Adapter path versus fixed-channel path",
                "visual_encoding": "Mechanism graph",
                "uncertainty_encoding": "not_applicable",
                "evidence_status": "implemented_design",
                "label": "fig:method-architecture",
            },
        }
    ))

    assert first.success, (first.error, first.install_hint)
    assert second.success, (second.error, second.install_hint)
    assert refreshed.success, (refreshed.error, refreshed.install_hint)
    assert calls == [".svg", ".pdf", ".png"]
    assert first.source_path == second.source_path
    assert Path(first.source_path).name == "eeg_montage_method_architecture.mmd"
    assert second.metadata["reused"] is True
    payload = json.loads((tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(encoding="utf-8"))
    assert len(payload["figures"]) == 1
    assert payload["figures"][0]["id"] == "eeg_montage_method_architecture"
    assert payload["figures"][0]["metadata"]["semantic_key"] == "eeg_montage_method_architecture"
    assert payload["figures"][0]["metadata"]["scientific_question"].startswith("Does the adapter")
    entry = payload["figures"][0]
    assert entry["paper_ready"] is True and refreshed.metadata["reused"] is True
    assert entry["source_sha256"] == hashlib.sha256(Path(first.source_path).read_bytes()).hexdigest()
    assert entry["output_sha256"] == hashlib.sha256(Path(first.output_path).read_bytes()).hexdigest()
    variants, hashes = entry["metadata"]["rendered_variants"], entry["metadata"]["rendered_variant_sha256"]
    assert set(variants) == set(hashes) == {"mmd", "svg", "pdf", "png"}
    assert all(hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest() == hashes[kind]
               for kind, relative in variants.items())
    import fitz
    with fitz.open(first.output_path) as document:
        assert all(label in document[0].get_text() for label in ("EEG channels", "Montage adapter", "Encoder"))


@pytest.mark.asyncio
async def test_concurrent_same_semantic_figure_serializes_generation_and_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sessions must not interleave writes to one stable artifact stem."""

    output_dir = tmp_path / "figures" / "diagrams"
    calls = 0

    async def fake_mermaid(
        _self,
        _description: str,
        output_dir: str,
        *,
        artifact_stem: str,
    ) -> FigureResult:
        nonlocal calls
        calls += 1
        # Yield so the second request reaches generate while the first is in
        # flight.  The per-artifact lock must keep it out of the write phase.
        await asyncio.sleep(0.02)
        source = Path(output_dir) / f"{artifact_stem}.mmd"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "flowchart LR\nA[Claim] --> B[Test]\n",
            encoding="utf-8",
        )
        return FigureResult(
            success=True,
            figure_type=FigureType.MERMAID,
            source_path=str(source),
            metadata={"renderer": "test"},
        )

    monkeypatch.setattr(type(figure_engine), "_generate_mermaid", fake_mermaid)
    kwargs = {
        "description": "Concurrent claim test flow",
        "figure_type": FigureType.MERMAID,
        "output_dir": str(output_dir),
        "code": "flowchart LR\nA[Claim] --> B[Test]",
        "artifact_name": "concurrent_claim_test",
        "metadata": {"scientific_role": "protocol"},
    }

    first, second = await asyncio.gather(
        figure_engine.generate(**kwargs),
        figure_engine.generate(**kwargs),
    )

    assert first.success and second.success
    assert calls == 1
    assert first.source_path == second.source_path
    manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(manifest["figures"]) == 1
    entry = manifest["figures"][0]
    source = tmp_path / entry["source_path"]
    assert source.is_file() and source.stat().st_size > 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["source_sha256"]


def test_stale_manifest_entry_is_not_reused(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "figures" / "diagrams"
    source = output_dir / "stale_claim.mmd"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("flowchart LR\nA[old] --> B[test]\n", encoding="utf-8")
    figure_artifact_registry.record(
        output_dir=output_dir,
        figure_type="mermaid",
        description="Stale claim test",
        source_path=str(source),
        metadata={
            "semantic_key": "stale_claim",
            "content_sha256": "content-v1",
        },
    )
    source.write_text("flowchart LR\nA[changed] --> B[test]\n", encoding="utf-8")

    assert (
        figure_artifact_registry.find_reusable(
            output_dir,
            "stale_claim",
            "content-v1",
        )
        is None
    )


def test_source_only_and_small_previews_are_repaired_without_model_calls(
    tmp_path: Path,
) -> None:
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    source = diagrams / "falsification_design.mmd"
    source.write_text(
        "flowchart LR\nC1[Claim C1] --> T1[Matched test] --> D1{Pass criterion?}",
        encoding="utf-8",
    )
    preview = diagrams / "falsification_design.png"
    Image.new("RGB", (541, 161), "white").save(preview)
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="mermaid",
        description="Falsification design for C1",
        output_path=str(preview),
        source_path=str(source),
        metadata={
            "semantic_key": "falsification_design",
            "managed_by": "merak",
            "scientific_role": "protocol",
            "scientific_question": "Can the matched test falsify C1?",
            "claim_ids": ["C1"],
            "source_data": ["figures/diagrams/falsification_design.mmd"],
            "intended_comparison": "Proposed method versus matched control",
            "visual_encoding": "Claim-to-test graph",
            "uncertainty_encoding": "Prespecified criterion",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
        },
    )

    repaired = figure_artifact_registry.repair_previews(tmp_path / "figures")

    assert str(preview) in repaired
    with Image.open(preview) as image:
        assert image.width >= 1000
        assert image.height >= 450
    assert figure_artifact_registry.scientific_quality_issues(tmp_path / "figures") == []


def test_unplanned_managed_figures_remain_in_ide_but_leave_paper_manifest(
    tmp_path: Path,
) -> None:
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    for semantic_key in ("method_architecture", "experimental_design_matrix"):
        output = diagrams / f"{semantic_key}.png"
        source = diagrams / f"{semantic_key}.mmd"
        Image.new("RGB", (1600, 700), "white").save(output)
        source.write_text("flowchart LR\nA[Claim] --> B[Test]", encoding="utf-8")
        figure_artifact_registry.record(
            output_dir=diagrams,
            figure_type="mermaid",
            description=semantic_key,
            output_path=str(output),
            source_path=str(source),
            metadata={
                "semantic_key": semantic_key,
                "managed_by": "merak",
                "scientific_role": "method" if semantic_key == "method_architecture" else "experimental_design",
                "scientific_question": "What scientific question is tested?",
                "claim_ids": ["C1"],
                "source_data": ["ideas/SELECTED_IDEA.json"],
                "intended_comparison": "Declared contrast",
                "visual_encoding": "Contract graph",
                "uncertainty_encoding": "not_applicable",
                "evidence_status": "planned_design",
                "style_profile": "merak-publication-v1",
            },
        )

    payload = figure_artifact_registry.curate_to_plan(
        tmp_path / "figures",
        {"method_architecture"},
        evidence_mode="planned",
    )
    by_key = {
        item["metadata"]["semantic_key"]: item
        for item in payload["figures"]
    }

    assert by_key["method_architecture"]["paper_ready"] is True
    assert by_key["experimental_design_matrix"]["paper_ready"] is False
    assert by_key["experimental_design_matrix"]["metadata"]["paper_selected"] is False
    assert (diagrams / "experimental_design_matrix.png").is_file()


def test_figure_reconcile_is_idempotent_and_does_not_rotate_provenance(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures" / "diagrams"
    figures.mkdir(parents=True)
    output = figures / "method_architecture.png"
    source = figures / "method_architecture.mmd"
    Image.new("RGB", (1200, 600), "white").save(output)
    source.write_text("flowchart LR\nA[Input] --> B[Method]", encoding="utf-8")
    figure_artifact_registry.record(
        output_dir=figures,
        figure_type="mermaid",
        description="method_architecture",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "managed_by": "merak",
            "scientific_role": "method",
            "scientific_question": "Which mechanism is tested?",
            "evidence_status": "planned_design",
            "paper_selected": True,
        },
    )

    first = figure_artifact_registry.reconcile(tmp_path / "figures")
    second = figure_artifact_registry.reconcile(tmp_path / "figures")

    assert first["updated_at"] == second["updated_at"]
    assert first["figures"] == second["figures"]


def test_figure_workflow_events_never_auto_open_editor_tabs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = WorkflowEngine()
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={"run_experiment": False},
    )
    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="design_only",
    )
    _author_plan_figures(tmp_path, plan)
    events: list[tuple[str, dict]] = []

    async def capture(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_emit", capture)
    asyncio.run(
        engine._ensure_figure_artifacts(
            run,
            "Artifact-grounded research agent",
            "Artifact-grounded research agent",
        )
    )

    generated = [payload for event, payload in events if event == "figure_artifact_generated"]
    assert generated
    assert all(payload["auto_open"] is False for payload in generated)
    assert {Path(payload["source_path"]).stem for payload in generated} == {
        "method_architecture",
        "evaluation_design",
    }


def test_retired_drawio_artifact_is_replaced_by_default_figurespec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ELECTRON_API_PORT", raising=False)
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    source = diagrams / "method_architecture.drawio"
    output = diagrams / "method_architecture.png"
    source.write_text(
        "<mxfile><diagram>Comparison models: Baseline; Cohorts and tasks: Data; "
        "Method and analysis: Generic method</diagram></mxfile>",
        encoding="utf-8",
    )
    Image.new("RGB", (1600, 700), "white").save(output)
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="drawio",
        description="Research method architecture (Draw.io): unsupported route",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "method_architecture",
            "managed_by": "merak",
            "scientific_role": "method",
            "scientific_question": "How does the method operate?",
            "claim_ids": ["C1"],
            "source_data": ["ideas/SELECTED_IDEA.json"],
            "intended_comparison": "Declared contrast",
            "visual_encoding": "Mechanism graph",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
        },
    )

    engine = WorkflowEngine()
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": False})
    asyncio.run(
        engine._ensure_figure_artifacts(
            run,
            "Artifact-grounded research agent",
            "Artifact-grounded research agent",
        )
    )

    manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(encoding="utf-8")
    )
    method = next(
        item for item in manifest["figures"]
        if (item.get("metadata") or {}).get("semantic_key") == "method_architecture"
    )
    assert method["type"] == "figurespec"
    assert method["source_path"].endswith("method_architecture.json")
    assert (tmp_path / method["source_path"]).is_file()
    gate = engine._figure_acceptance_gate(str(tmp_path))
    assert gate["accepted"] is True, gate


def test_method_asset_roles_use_mechanism_names_before_cross_references(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    selected_path = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    selected["mechanisms"] = [
        {
            "id": "M1",
            "name": "Metadata-aware token encoder",
            "description": "Encodes inputs and passes metadata to a calibration module.",
            "publication_name": "Metadata-aware token encoder",
            "publication_description": "Encodes inputs for calibrated prediction.",
            "publication_evaluation": "Encoder removal comparison.",
        },
        {
            "id": "M2",
            "name": "Observation mask",
            "description": "Defines availability for downstream prediction.",
            "publication_name": "Observation mask",
            "publication_description": "Defines observed inputs for prediction.",
            "publication_evaluation": "Mask removal comparison.",
        },
        {
            "id": "M3",
            "name": "Structured dropout",
            "description": "Applied during training.",
            "publication_name": "Structured dropout",
            "publication_description": "Regularizes the training representation.",
            "publication_evaluation": "Dropout removal comparison.",
        },
        {
            "id": "M4",
            "name": "Risk prediction head",
            "description": "Consumes the representation and observation state.",
            "publication_name": "Risk prediction head",
            "publication_description": "Predicts risk from the representation.",
            "publication_evaluation": "Held-out risk prediction.",
        },
    ]
    selected_path.write_text(json.dumps(selected), encoding="utf-8")

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="design_only",
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    roles = {
        item["id"]: item["role"]
        for item in method["method_brief"]["mechanism_nodes"]
    }

    assert roles == {
        "M1": "core",
        "M2": "conditioning",
        "M3": "training",
        "M4": "output",
    }


def test_explicit_model_svg_is_not_overwritten_by_deterministic_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ELECTRON_API_PORT", raising=False)
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    plan = scientific_asset_service.build_plan(
        tmp_path, experiment_requested=False, requested_evidence_mode="design_only",
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    method.update({
        "production_strategy": "model_composed_full_svg",
        "producer_kind": "model",
        "composition_owner": "model",
        "full_svg_authority": True,
        "recommended_backend": "rich_svg",
        "recommended_skill": "model-svg-figure",
    })
    _author_rich_svg_asset(tmp_path, method)
    source_path = tmp_path / "figures/diagrams/method_architecture.svg"
    persisted_source = source_path.read_text(encoding="utf-8")

    engine = WorkflowEngine()
    run = WorkflowRun(project_path=str(tmp_path))
    monkeypatch.setattr(scientific_asset_service, "build_plan", lambda *_args, **_kwargs: plan)
    asyncio.run(engine._ensure_figure_artifacts(run, "agent completed", "EEG foundation model"))

    assert source_path.read_text(encoding="utf-8") == persisted_source
    manifest = json.loads((tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(encoding="utf-8"))
    methods = [
        item for item in manifest["figures"]
        if item["metadata"]["semantic_key"] == "method_architecture"
    ]
    assert len(methods) == 1
    assert methods[0]["source_path"].endswith("method_architecture.svg")


def test_figure_agent_session_has_hard_iteration_and_generation_limits(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    session = type("Session", (), {
        "max_iterations": 100,
        "tool_call_limits": {},
    })()

    engine._configure_agent_limits(session, "figure", "beast", str(tmp_path))

    assert session.max_iterations == 16
    assert session.tool_call_limits["generate_figure"] == 6
    assert session.tool_call_limits["Skill"] == 5


def test_generate_figure_tool_budget_blocks_extra_calls() -> None:
    calls: list[str] = []

    async def fake_generate(description: str) -> str:
        calls.append(description)
        return "generated"

    engine = AgentEngine(type("Router", (), {})())
    engine.register_tool(
        "generate_figure",
        "Generate a figure",
        {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
        fake_generate,
    )
    session = engine.create_session()
    session.tool_call_limits["generate_figure"] = 1

    first = asyncio.run(engine._execute_tool(
        session,
        ToolCall(id="first", name="generate_figure", arguments={"description": "method"}),
    ))
    second = asyncio.run(engine._execute_tool(
        session,
        ToolCall(id="second", name="generate_figure", arguments={"description": "duplicate"}),
    ))

    assert first.success is True
    assert second.success is False
    assert "TOOL_CALL_LIMIT_REACHED" in second.output
    assert calls == ["method"]


def test_figure_workflow_persists_real_outputs_sources_and_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)

    gate = engine._figure_acceptance_gate(str(tmp_path))
    assert gate["accepted"] is True, gate

    manifest_path = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(payload["figures"]) >= 1
    assert all(not item["description"].lower().startswith("project artifact") for item in payload["figures"])
    specs = json.loads((tmp_path / "figures" / "FIGURE_SPECS.json").read_text(encoding="utf-8"))
    assert len(specs["figures"]) >= 1
    assert all(item["claim_ids"] for item in specs["figures"])

    paper_ready = [item for item in payload["figures"] if item["paper_ready"]]
    editable = [item for item in payload["figures"] if item["editable"]]
    assert len(paper_ready) >= 1
    assert editable
    roles = {(item.get("metadata") or {}).get("scientific_role") for item in paper_ready}
    assert "method" in roles
    assert "protocol" not in roles
    assert all(str((item.get("metadata") or {}).get("style_profile") or "") for item in paper_ready)
    method = next(
        item for item in paper_ready
        if (item.get("metadata") or {}).get("semantic_key") == "method_architecture"
    )
    assert method["type"] == "figurespec"
    assert method["metadata"]["source_faithful"] == "deterministic-json-to-svg-same-source"
    assert method["metadata"]["generator"] == "deterministic-figurespec"
    assert method["metadata"]["skill"] == "figure-spec"
    assert method["metadata"]["model_authored"] is False
    assert set(method["metadata"]["rendered_variants"]) == {"json", "svg", "pdf", "png"}
    method_source = json.loads((tmp_path / method["source_path"]).read_text(encoding="utf-8"))
    assert {node["id"] for node in method_source["nodes"]} == {
        "research_inputs", "claim_binding", "matched_control",
        "bounded_conclusion",
    }
    assert {(edge["from"], edge["to"]) for edge in method_source["edges"]} == {
        ("research_inputs", "claim_binding"),
        ("claim_binding", "bounded_conclusion"),
        ("matched_control", "claim_binding"),
        ("matched_control", "bounded_conclusion"),
    }
    last_review = method["metadata"]["visual_review_rounds"][-1]
    assert last_review["status"] == "passed"
    assert last_review["content_sha256"] == method["source_sha256"]
    assert last_review["render_sha256"] == method["metadata"]["rendered_variant_sha256"]["png"]
    visible_text = figure_artifact_registry._source_semantic_text(
        tmp_path / method["source_path"]
    )
    assert not re.search(
        r"(?<![A-Za-z0-9])(?:C|M|F|I)\d+(?![A-Za-z0-9])",
        visible_text,
    )
    preview_path = method["metadata"]["rendered_variants"]["png"]
    with Image.open(tmp_path / preview_path) as preview:
        assert preview.width >= 1600
        assert len(preview.convert("RGB").getcolors(maxcolors=1_000_000) or []) >= 5
    assert figure_artifact_registry.scientific_quality_issues(tmp_path / "figures") == []
    for item in payload["figures"]:
        for key in ("output_path", "source_path"):
            if item.get(key):
                asset = tmp_path / item[key]
                assert asset.is_file()
                assert asset.stat().st_size > 0


def test_figure_gate_rejects_removed_specs_key_without_rewriting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    specs_path = tmp_path / "figures" / "FIGURE_SPECS.json"
    payload = json.loads(specs_path.read_text(encoding="utf-8"))
    figures = payload.pop("figures")
    payload["specs"] = figures
    specs_path.write_text(json.dumps(payload), encoding="utf-8")

    gate = engine._figure_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert "must define at least 1 manuscript figure" in gate["summary"]
    unchanged = json.loads(specs_path.read_text(encoding="utf-8"))
    assert unchanged["specs"] == figures
    assert "figures" not in unchanged


def test_paper_gate_rejects_thin_paper_and_accepts_manifest_backed_paper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(exist_ok=True)

    thin = "\\documentclass{article}\\begin{document}Thin draft\\end{document}"
    (paper_dir / "main.tex").write_text(thin, encoding="utf-8")
    rejected = engine._paper_acceptance_gate(str(tmp_path))
    assert rejected["accepted"] is False
    assert rejected["reason"] == "paper quality contract failed"

    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    generated = main_path.read_text(encoding="utf-8")
    assert "\\input{generated_method_figures}" in generated
    assert "\\input{tables/study_design}" in generated
    assert "\\input{tables/method_components}" in generated
    assert "claim_evidence" not in generated
    assert (paper_dir / "tables" / "TABLE_MANIFEST.json").is_file()
    accepted = engine._paper_acceptance_gate(str(tmp_path))
    assert accepted["accepted"] is True, accepted
    assert accepted["details"]["figures"] >= 1
    assert accepted["details"]["tables"] >= 2


def test_paper_artifacts_use_publication_fields_for_cjk_contract_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """English pdfLaTeX output must not inherit CJK-only planning prose."""
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    _build_figures(tmp_path)

    selected_path = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    selected["mechanisms"][0].update({
        "name": "运行级证据账本",
        "description": "为每次运行保存可追溯配置和测量证据。",
        "supports_claims": ["C1"],
        "publication_name": "Run-level evidence ledger",
        "publication_description": "Preserves traceable configuration and measured evidence for each run.",
        "publication_evaluation": "Matched provenance and evidence coverage comparison.",
    })
    selected_path.write_text(
        json.dumps(selected, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    method = next(
        item
        for item in manifest["figures"]
        if (item.get("metadata") or {}).get("scientific_role") == "method"
    )
    method["caption"] = "中文方法架构图注。"
    method["description"] = (
        "Publication-facing method overview with controlled comparisons "
        "and traceable evidence."
    )
    method.setdefault("metadata", {})["caption"] = "中文方法架构图注。"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    paper_artifact_builder.prepare(tmp_path, "Artifact-grounded research agent")

    method_figures = (
        tmp_path / "paper" / "generated_method_figures.tex"
    ).read_text(encoding="utf-8")
    method_table = (
        tmp_path / "paper" / "tables" / "method_components.tex"
    ).read_text(encoding="utf-8")
    evidence_csv = (
        tmp_path / "paper" / "tables" / "method_components.csv"
    ).read_text(encoding="utf-8-sig")

    assert "Method overview showing the scientific mechanism" in method_figures
    assert "Publication-facing" not in method_figures
    assert "Run-level evidence ledger" in method_table
    assert not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", method_figures)
    assert not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", method_table)
    assert list(csv.DictReader(evidence_csv.splitlines())) == [
        {"component": mechanism["publication_name"], "function": mechanism["publication_description"],
         "evaluation": mechanism["publication_evaluation"]}
        for mechanism in selected["mechanisms"]
    ]
    raw_records = json.loads((tmp_path / ".merak/paper-table-records/method_components.json").read_text(encoding="utf-8"))
    assert raw_records["schema"] == 1
    assert raw_records["records"][0]["component"] == "运行级证据账本"
    assert raw_records["records"][0]["function"] == "为每次运行保存可追溯配置和测量证据。"


def test_paper_gate_accepts_grouped_refs_ranges_and_optional_short_captions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    content = main_path.read_text(encoding="utf-8")
    directly_referenced = list(dict.fromkeys(
        re.findall(r"\\ref\{((?:fig|tab):[^}]+)\}", content)
    ))
    assert len(directly_referenced) >= 2
    first, second = directly_referenced[:2]
    content = content.replace(f"\\ref{{{first}}}", "the first asset")
    content = content.replace(f"\\ref{{{second}}}", "the second asset")
    content = content.replace(
        "\\begin{document}",
        (
            "\\begin{document}\n"
            f"The registered assets \\cref{{{first},{second}}} show and compare "
            "the mechanism with its evaluation protocol.\n"
            f"The span \\crefrange{{{first}}}{{{second}}} records the same "
            "scientific comparison.\n"
        ),
        1,
    )
    content = content.replace("\\caption{", "\\caption[Short]{")
    main_path.write_text(content, encoding="utf-8")

    gate = engine._paper_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is True, gate
    assert not any(
        "never referenced in prose" in issue
        for issue in gate["details"]["issues"]
    )
    assert not any(
        "has no caption" in issue
        for issue in gate["details"]["issues"]
    )
