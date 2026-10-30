from __future__ import annotations

from server.tests._figure_workflow_support import (
    FigureType as FigureType,
    Image as Image,
    ImageDraw as ImageDraw,
    Path as Path,
    WorkflowEngine as WorkflowEngine,
    WorkflowRun as WorkflowRun,
    _author_excalidraw_asset as _author_excalidraw_asset,
    _disable_live_electron_renderer_discovery as _disable_live_electron_renderer_discovery,
    _seed_project as _seed_project,
    asyncio as asyncio,
    base64 as base64,
    csv as csv,
    figure_artifact_registry as figure_artifact_registry,
    figure_engine as figure_engine,
    figure_engine_module as figure_engine_module,
    json as json,
    os as os,
    pytest as pytest,
    run_process as run_process,
    scientific_asset_service as scientific_asset_service,
    sys as sys,
    time as time,
)


def test_svg_variant_conversion_preserves_drawio_text_fallback(
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    svg = tmp_path / "architecture.svg"
    pdf = tmp_path / "architecture.pdf"
    png = tmp_path / "architecture.png"
    svg.write_text(
        '''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xhtml="http://www.w3.org/1999/xhtml" width="600" height="220">
<rect x="20" y="40" width="560" height="130" fill="#edf2f7" stroke="#334155"/>
<switch><foreignObject x="40" y="75" width="520" height="60"><xhtml:div>Leakage Audit</xhtml:div></foreignObject>
<text x="300" y="115" text-anchor="middle" font-size="28">Leakage Audit</text></switch>
</svg>''',
        encoding="utf-8",
    )
    converted, error = figure_engine_module._convert_svg_variants(svg, pdf, png)
    assert converted is True, error
    document = fitz.open(pdf)
    assert "Leakage Audit" in " ".join(page.get_text() for page in document)
    document.close()
    assert png.is_file() and png.stat().st_size > 0


def test_drawio_render_text_gate_rejects_label_free_pdf(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    source = tmp_path / "method.drawio"
    source.write_text(
        '''<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="n1" value="Input Projection" vertex="1" parent="1"><mxGeometry x="10" y="10" width="180" height="70" as="geometry"/></mxCell>
<mxCell id="n2" value="Shared Encoder" vertex="1" parent="1"><mxGeometry x="230" y="10" width="180" height="70" as="geometry"/></mxCell>
</root></mxGraphModel>''',
        encoding="utf-8",
    )

    issues = figure_artifact_registry.mermaid_layout_issues(source)
    assert issues == []
    pdf = tmp_path / "method.pdf"
    document = fitz.open()
    document.new_page(width=600, height=220)
    document.save(pdf)
    document.close()
    issues = figure_artifact_registry.drawio_render_text_issues(source, pdf)
    assert issues == ["drawio paper PDF contains no extractable labels"]


def test_plan_curation_repairs_model_authored_role_drift(tmp_path: Path) -> None:
    figures = tmp_path / "figures"
    diagrams = figures / "diagrams"
    diagrams.mkdir(parents=True)
    source = diagrams / "evaluation_design.mmd"
    output = diagrams / "evaluation_design.pdf"
    source.write_text("flowchart LR\n  A[Train] --> B[Test]\n", encoding="utf-8")
    output.write_bytes(b"%PDF-1.4\n% deterministic fixture\n")
    figure_artifact_registry.record(
        output_dir=figures,
        figure_type="mermaid",
        description="Evaluation design separating training and held-out testing.",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "evaluation_design",
            "managed_by": "merak",
            "scientific_role": "protocol",
            "paper_selected": False,
            "manuscript_eligible": False,
            "submission_eligible": False,
            "evidence_status": "internal",
        },
    )
    payload = figure_artifact_registry.curate_to_plan(
        figures,
        {"evaluation_design"},
        evidence_mode="synthetic_preview",
        planned_assets={
            "evaluation_design": {
                "scientific_role": "evaluation_design",
                "manuscript_eligible": True,
                "submission_eligible": True,
                "evidence_status": "implemented_design",
                "generation_phase": "phase_2b",
                "generation_policy": "generate",
            }
        },
    )
    entry = next(item for item in payload["figures"] if item["id"] == "evaluation_design")
    assert entry["metadata"]["scientific_role"] == "evaluation_design"
    assert entry["metadata"]["paper_selected"] is True
    assert entry["paper_ready"] is True


def test_method_rich_svg_rejects_retired_raw_svg_submission(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    groups = []
    mappings = []
    for index in range(12):
        group_id = f"stage_{index}"
        groups.append(
            f'<g id="{group_id}"><rect x="{20 + index * 100}" y="150" '
            f'width="80" height="80" fill="#{index % 4 + 1}{index % 4 + 2}7788"/>'
            f'<text x="{25 + index * 100}" y="175">Scientific stage {index}</text>'
            f'<text x="{25 + index * 100}" y="195">Measured relation</text>'
            f'<circle cx="{55 + index * 100}" cy="215" r="8" fill="#52627A"/>'
            '</g>'
        )
        if index < 4:
            mappings.append({
                "element_id": group_id,
                "source_path": "experiments/METHOD_CONTRACT.json",
                "semantic_role": "scientific method stage",
            })
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 800">'
        '<title>Method</title><desc>Build Ledger Record and Canonical Sha256</desc>'
        + ''.join(groups)
        + '</svg>'
    )

    result = asyncio.run(figure_engine.generate(
        description="Method architecture",
        artifact_name="method_architecture",
        figure_type=FigureType.RICH_SVG,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code=svg,
        metadata={
            "scientific_role": "method",
            "element_mappings": mappings,
        },
    ))

    assert result.success is False
    assert "visual_blueprint.schema must equal 1" in (result.error or "")


def test_matplotlib_without_code_refuses_synthetic_metrics(tmp_path: Path) -> None:
    result = asyncio.run(
        figure_engine.generate(
            description="accuracy comparison",
            figure_type=FigureType.MATPLOTLIB,
            output_dir=str(tmp_path / "figures" / "plots"),
        )
    )

    assert result.success is False
    assert "will not fabricate sample metrics" in (result.error or "")
    assert result.output_path is None


def test_process_runner_executes_under_windows_compatible_event_loop() -> None:
    result = asyncio.run(run_process(
        [sys.executable, "-c", "print('merak-render-ok')"],
        timeout=10,
    ))

    assert result.returncode == 0
    assert b"merak-render-ok" in (result.stdout or b"")


def test_scientific_aggregate_write_preserves_identical_file_mtime(
    tmp_path: Path,
) -> None:
    path = tmp_path / "experiments" / "results" / "aggregates" / "main.csv"
    rows = [{"method": "proposed", "mean": "0.8"}]
    scientific_asset_service._write_csv(path, rows)
    old_time = time.time() - 60
    os.utime(path, (old_time, old_time))
    before = path.stat().st_mtime_ns

    scientific_asset_service._write_csv(path, rows)

    assert path.stat().st_mtime_ns == before


def test_matplotlib_persists_and_recovers_all_managed_variants(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "figures" / "plots"
    generated = asyncio.run(figure_engine.generate(
        description="Executed primary comparison",
        artifact_name="main_comparison",
        figure_type=FigureType.MATPLOTLIB,
        output_dir=str(output_dir),
        code=(
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots(figsize=(4, 3))\n"
            "ax.plot([0, 1], [0.2, 0.8])\n"
            "ax.set_xlabel('Condition')\n"
            "ax.set_ylabel('Score')\n"
        ),
        metadata={
            "semantic_key": "main_comparison",
            "scientific_role": "result",
        },
    ))

    assert generated.success is True, generated.error
    variants = dict((generated.metadata or {}).get("rendered_variants") or {})
    assert set(variants) == {"py", "pdf", "svg", "png"}
    source = Path(generated.source_path or "")
    for suffix in (".py", ".pdf", ".svg", ".png"):
        assert source.with_suffix(suffix).is_file()

    source.with_suffix(".pdf").unlink()
    source.with_suffix(".svg").unlink()
    source.with_suffix(".png").unlink()
    refreshed = asyncio.run(figure_engine.refresh_editable_source(source))

    assert refreshed["success"] is True, refreshed
    assert set(refreshed["entry"]["metadata"]["rendered_variants"]) == {
        "py", "pdf", "svg", "png",
    }


def test_matplotlib_export_helper_is_not_followed_by_blank_overwrite(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "figures" / "plots"
    generated = asyncio.run(figure_engine.generate(
        description="Helper-saved primary comparison",
        artifact_name="helper_saved_comparison",
        figure_type=FigureType.MATPLOTLIB,
        output_dir=str(output_dir),
        code=(
            "from pathlib import Path\n"
            "import matplotlib.pyplot as plt\n"
            "def save_all(fig, stem):\n"
            "    output = Path(__file__).with_name(stem)\n"
            "    fig.savefig(output.with_suffix('.pdf'))\n"
            "    fig.savefig(output.with_suffix('.svg'))\n"
            "    fig.savefig(output.with_suffix('.png'), dpi=180)\n"
            "    plt.close(fig)\n"
            "fig, ax = plt.subplots(figsize=(4, 3))\n"
            "ax.plot([0, 1, 2], [0.1, 0.8, 0.35], linewidth=3)\n"
            "ax.set_xlabel('Condition')\n"
            "ax.set_ylabel('Score')\n"
            "save_all(fig, 'helper_saved_comparison')\n"
        ),
        metadata={
            "semantic_key": "helper_saved_comparison",
            "scientific_role": "result",
        },
    ))

    assert generated.success is True, generated.error
    source = Path(generated.source_path or "")
    persisted_source = source.read_text(encoding="utf-8")
    assert "plt.tight_layout()\nplt.savefig" not in persisted_source
    with Image.open(source.with_suffix(".png")) as image:
        extrema = image.convert("L").getextrema()
    assert extrema[0] < 245


def test_generate_figure_surfaces_backend_failure_as_tool_failure(
    tmp_path: Path,
) -> None:
    from server.agent.tools import generate_figure

    with pytest.raises(RuntimeError, match="Figure generation failed"):
        asyncio.run(generate_figure(
            description="accuracy comparison",
            artifact_name="main_comparison",
            figure_type="matplotlib",
            output_dir=str(tmp_path / "figures" / "plots"),
        ))


def test_mermaid_without_faithful_renderer_keeps_editable_source_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ELECTRON_API_PORT", raising=False)
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    monkeypatch.setattr(figure_engine_module, "_candidate_electron_ports", lambda: [])
    async def unavailable_fallback(_code: str, _output: str | Path):
        return False, "bundled renderer unavailable"
    monkeypatch.setattr(
        figure_engine_module,
        "_render_mermaid_with_bundled_electron",
        unavailable_fallback,
    )

    result = asyncio.run(
        figure_engine.generate(
            description="flowchart LR\nA[Input] --> B[Output]",
            figure_type=FigureType.MERMAID,
            output_dir=str(tmp_path / "figures" / "diagrams"),
        )
    )

    assert result.success is True
    assert result.output_path is None
    assert result.source_path
    assert Path(result.source_path).is_file()
    assert not Path(result.source_path).with_suffix(".png").exists()
    assert "no degraded preview was created" in (result.install_hint or "")


def test_electron_renderer_port_discovery_prefers_explicit_port(monkeypatch) -> None:
    monkeypatch.setenv("MERAK_ELECTRON_API_PORT", "18772")
    monkeypatch.delenv("MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY", raising=False)

    ports = figure_engine_module._candidate_electron_ports()

    assert ports[0] == 18772
    assert ports.count(18772) == 1
    assert 18765 in ports
    assert 18784 in ports


def test_electron_renderer_port_discovery_can_be_disabled(monkeypatch) -> None:
    monkeypatch.delenv("MERAK_ELECTRON_API_PORT", raising=False)
    monkeypatch.setenv("MERAK_DISABLE_ELECTRON_RENDERER_DISCOVERY", "1")

    assert figure_engine_module._candidate_electron_ports() == []


@pytest.mark.parametrize(
    ("renderer_name", "source", "suffix", "endpoint"),
    [
        ("_render_mermaid_with_electron", "flowchart LR\nA-->B", ".svg", "mermaid-export"),
        ("_render_drawio_with_electron", "<mxfile/>", ".pdf", "drawio-export"),
    ],
)
def test_live_electron_renderers_decode_response_and_commit_locally(
    tmp_path: Path,
    monkeypatch,
    renderer_name: str,
    source: str,
    suffix: str,
    endpoint: str,
) -> None:
    import httpx

    rendered_bytes = b"renderer-owned-binary"
    requests: list[tuple[str, dict]] = []

    class Response:
        status_code = 200
        text = "ok"

        @staticmethod
        def json() -> dict:
            return {
                "success": True,
                "data": base64.b64encode(rendered_bytes).decode("ascii"),
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url: str, json: dict):
            requests.append((url, json))
            return Response()

    monkeypatch.setattr(figure_engine_module, "_candidate_electron_ports", lambda: [18765])
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    output = tmp_path / f"rendered{suffix}"

    success, error = asyncio.run(
        getattr(figure_engine_module, renderer_name)(source, output)
    )

    assert success is True, error
    assert output.read_bytes() == rendered_bytes
    assert requests[0][0].endswith(f"/{endpoint}")
    assert "output_path" not in requests[0][1]


def test_semantic_tokens_split_compound_domain_terms() -> None:
    from server.services.figure_artifacts import _semantic_tokens

    expected = _semantic_tokens("Reference-consistency objective")
    observed = _semantic_tokens("reference-consistency loss")

    assert {"reference", "consistency"} <= expected & observed


def test_mermaid_refresh_persists_svg_pdf_png_variants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "figures" / "diagrams" / "evaluation_design.mmd"
    source.parent.mkdir(parents=True)
    source.write_text(
        "flowchart LR\nA[Dataset split] --> B[Evaluation protocol]",
        encoding="utf-8",
    )
    old_svg = source.with_suffix(".svg")
    old_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>old</text></svg>',
        encoding="utf-8",
    )
    figure_artifact_registry.record(
        output_dir=source.parent,
        figure_type="mermaid",
        description="evaluation_design",
        output_path=str(old_svg),
        source_path=str(source),
        metadata={
            "semantic_key": "evaluation_design",
            "managed_by": "merak",
        },
    )

    async def render_variant(_code: str, output_path: str | Path):
        output = Path(output_path)
        if output.suffix == ".svg":
            output.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400">'
                '<rect width="800" height="400" fill="white"/>'
                '<text x="40" y="80">Evaluation protocol</text></svg>',
                encoding="utf-8",
            )
        elif output.suffix == ".pdf":
            output.write_bytes(b"%PDF-1.4\n% test\n")
        else:
            Image.new("RGB", (1600, 800), "white").save(output)
        return True, ""

    monkeypatch.setattr(
        figure_engine_module, "_render_mermaid_with_electron", render_variant
    )

    refreshed = asyncio.run(figure_engine.refresh_editable_source(
        source,
        metadata_override={
            "semantic_key": "evaluation_design",
            "scientific_role": "evaluation_design",
            "scientific_question": "How is the evaluation isolated?",
            "claim_ids": ["C1"],
            "source_data": ["ideas/SELECTED_IDEA.json"],
            "intended_comparison": "Held-out versus training data",
            "visual_encoding": "Directed evaluation flow",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "test-publication-style",
        },
    ))

    assert refreshed["success"] is True, refreshed
    assert Path(refreshed["output_path"]).suffix == ".pdf"
    for suffix in (".mmd", ".svg", ".pdf", ".png"):
        assert source.with_suffix(suffix).is_file()
    entry = refreshed["entry"]
    assert set(entry["metadata"]["rendered_variants"]) == {
        "mmd", "svg", "pdf", "png",
    }
    assert entry["metadata"]["preview_path"].endswith("evaluation_design.png")
    assert entry["metadata"]["paper_vector_path"].endswith("evaluation_design.pdf")


def test_mermaid_refresh_adopts_complete_current_variants_when_endpoint_is_offline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "figures" / "diagrams" / "evaluation_design.mmd"
    source.parent.mkdir(parents=True)
    source.write_text(
        "flowchart LR\nA[Dataset split] --> B[Held-out evaluation]",
        encoding="utf-8",
    )
    svg = source.with_suffix(".svg")
    pdf = source.with_suffix(".pdf")
    png = source.with_suffix(".png")
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>current</text></svg>',
        encoding="utf-8",
    )
    pdf.write_bytes(b"%PDF-1.4\n% current\n")
    Image.new("RGB", (800, 400), "white").save(png)
    current_time = source.stat().st_mtime + 2.0
    for candidate in (svg, pdf, png):
        os.utime(candidate, (current_time, current_time))

    async def renderer_unavailable(_code: str, _output: str | Path):
        return False, "renderer unavailable"

    monkeypatch.setattr(
        figure_engine_module,
        "_render_mermaid_with_electron",
        renderer_unavailable,
    )

    refreshed = asyncio.run(figure_engine.refresh_editable_source(source))

    assert refreshed["success"] is True
    assert refreshed["output_path"] == str(pdf.resolve())
    entry = refreshed["entry"]
    assert entry["paper_ready"] is True
    assert entry["metadata"]["reused_current_variants"] is True
    assert set(entry["metadata"]["rendered_variants"]) == {
        "mmd", "svg", "pdf", "png",
    }


def test_figure_postprocessor_does_not_recover_unregistered_legacy_source(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    source = tmp_path / "figures" / "diagrams" / "evaluation_design.mmd"
    source.parent.mkdir(parents=True)
    source.write_text(
        "flowchart LR\n"
        "    data[Study data] --> split[Leakage-safe split]\n"
        "    split --> heldout[Held-out evaluation]\n",
        encoding="utf-8",
    )
    run = WorkflowRun(
        id="recover-source",
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "design_only",
        },
    )

    asyncio.run(WorkflowEngine()._ensure_figure_artifacts(
        run,
        "source persisted before tool completion",
        "Artifact-grounded research agent",
    ))

    manifest = figure_artifact_registry.load(tmp_path / "figures")
    evaluation = next(
        item for item in manifest["figures"] if item["id"] == "evaluation_design"
    )
    assert evaluation["type"] == "rich_svg"
    assert evaluation["metadata"]["producer_kind"] == "deterministic"
    assert evaluation["source_path"] != "figures/diagrams/evaluation_design.mmd"
    assert source.read_text(encoding="utf-8").startswith("flowchart LR")


def test_diagram_generation_rejects_prose_template_fallbacks(tmp_path: Path) -> None:
    mermaid = asyncio.run(
        figure_engine.generate(
            description="A research method architecture for the selected idea",
            figure_type=FigureType.MERMAID,
            output_dir=str(tmp_path / "figures" / "diagrams"),
        )
    )
    drawio = asyncio.run(
        figure_engine.generate(
            description="A research method architecture for the selected idea",
            figure_type=FigureType.DRAWIO,
            output_dir=str(tmp_path / "figures" / "diagrams"),
        )
    )

    assert mermaid.success is False
    assert "complete Mermaid source" in (mermaid.error or "")
    assert drawio.success is False
    assert "complete mxfile XML" in (drawio.error or "")


def test_drawio_generation_requires_all_paper_variants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _render_source_only(_xml: str, svg_path: Path):
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60">'
            '<text x="10" y="30">Encoder</text></svg>',
            encoding="utf-8",
        )
        return True, None

    monkeypatch.setattr(
        figure_engine_module,
        "_render_drawio_with_electron",
        _render_source_only,
    )
    monkeypatch.setattr(
        figure_engine_module,
        "_convert_svg_variants",
        lambda *_args: (False, "PDF/PNG conversion failed"),
    )
    xml = (
        '<mxfile><diagram><mxGraphModel><root><mxCell id="0"/>'
        '<mxCell id="1" parent="0"/><mxCell id="encoder" value="Encoder" '
        'vertex="1" parent="1"><mxGeometry x="10" y="10" width="120" '
        'height="60" as="geometry"/></mxCell></root></mxGraphModel>'
        '</diagram></mxfile>'
    )

    result = asyncio.run(
        figure_engine._generate_drawio(
            xml,
            output_dir=str(tmp_path),
            artifact_stem="method_architecture",
        )
    )

    assert result.success is False
    assert result.source_path and Path(result.source_path).is_file()
    assert (tmp_path / "method_architecture.svg").is_file()
    assert not (tmp_path / "method_architecture.pdf").exists()
    assert not (tmp_path / "method_architecture.png").exists()
    assert "PDF/PNG conversion failed" in (result.error or "")


def test_excalidraw_method_scene_requires_project_source_mappings(
    tmp_path: Path,
) -> None:
    scene = {
        "elements": [
            {
                "id": "title",
                "type": "text",
                "x": 100,
                "y": 0,
                "width": 950,
                "height": 60,
                "fontSize": 26,
                "text": "Source-grounded scientific architecture",
            },
            {
                "id": "observations",
                "type": "rectangle",
                "x": 0,
                "y": 140,
                "width": 280,
                "height": 130,
                "text": "Observed research signals",
            },
            {
                "id": "mechanism",
                "type": "rectangle",
                "x": 420,
                "y": 120,
                "width": 320,
                "height": 170,
                "text": "Implemented representation mechanism",
            },
            {
                "id": "endpoint",
                "type": "rectangle",
                "x": 880,
                "y": 140,
                "width": 280,
                "height": 130,
                "text": "Prespecified scientific endpoint",
            },
            {
                "id": "control",
                "type": "rectangle",
                "x": 420,
                "y": 440,
                "width": 320,
                "height": 120,
                "text": "Matched control condition",
            },
            {
                "id": "flow-1",
                "type": "arrow",
                "startElementId": "observations",
                "endElementId": "mechanism",
            },
            {
                "id": "flow-2",
                "type": "arrow",
                "startElementId": "mechanism",
                "endElementId": "endpoint",
            },
            {
                "id": "flow-3",
                "type": "arrow",
                "startElementId": "control",
                "endElementId": "mechanism",
            },
        ],
    }

    result = asyncio.run(figure_engine.generate(
        description="A source-grounded method architecture",
        artifact_name="method_architecture",
        figure_type=FigureType.EXCALIDRAW,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code=json.dumps(scene),
        metadata={"scientific_role": "method"},
    ))

    assert result.success is False
    assert "requires element_mappings" in (result.error or "")
    assert result.output_path is None


def test_saving_excalidraw_refreshes_all_same_scene_variants(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    asset = {
        "id": "method_architecture",
        "scientific_role": "method",
        "scientific_question": "How does claim-linked planning bind evidence?",
        "claim_ids": ["C1"],
        "source_data": ["ideas/SELECTED_IDEA.json"],
        "intended_comparison": "Linked and unlinked research planning",
        "visual_encoding": "Directed mechanism architecture",
        "uncertainty_encoding": "not_applicable",
        "evidence_status": "planned_design",
        "caption": "Claim-linked planning architecture.",
        "publication_labels": [{"schema": 1, "id": "method.binding", "kind": "concept", "display_text": "Claim-to-evidence binding"}],
    }
    _author_excalidraw_asset(tmp_path, asset)
    source = tmp_path / "figures" / "diagrams" / "method_architecture.excalidraw"
    scene = json.loads(source.read_text(encoding="utf-8"))
    label = next(
        item
        for item in scene["elements"]
        if item.get("type") == "text"
        and "Claim-to-evidence" in str(item.get("text") or "")
    )
    label["text"] = "Evidence-linked planning"
    label["originalText"] = "Evidence-linked planning"
    source.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")

    for suffix in (".svg", ".pdf", ".png"):
        source.with_suffix(suffix).unlink()

    refreshed = asyncio.run(figure_engine.refresh_editable_source(source))

    assert refreshed["success"] is True, refreshed
    for suffix in (".excalidraw", ".svg", ".pdf", ".png"):
        variant = source.with_suffix(suffix)
        assert variant.is_file()
        assert variant.stat().st_size > 0
    manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(encoding="utf-8")
    )
    entry = next(
        item
        for item in manifest["figures"]
        if (item.get("metadata") or {}).get("semantic_key") == "method_architecture"
    )
    assert set(entry["metadata"]["rendered_variants"]) == {
        "excalidraw", "svg", "pdf", "png",
    }


def test_element_mapping_accepts_qualified_class_member_symbols(
    tmp_path: Path,
) -> None:
    from server.services.excalidraw_renderer import verify_element_mappings

    source = tmp_path / "experiments" / "src" / "calibration.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class ConformalCalibrator:\n"
        "    def _fit_thresholds(self):\n"
        "        self.threshold_records = []\n",
        encoding="utf-8",
    )
    scene = {"elements": [{"id": "calibrator", "type": "rectangle"}]}

    issues = verify_element_mappings(
        scene,
        [
            {
                "element_id": "calibrator",
                "source_path": "experiments/src/calibration.py",
                "source_symbol": "ConformalCalibrator._fit_thresholds",
            },
            {
                "element_id": "calibrator",
                "source_path": "experiments/src/calibration.py",
                "source_symbol": "ConformalCalibrator.threshold_records",
            },
        ],
        tmp_path,
    )

    assert issues == []


def test_raster_quality_detects_a_transparent_or_empty_canvas(tmp_path: Path) -> None:
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    output = diagrams / "method_architecture.png"
    source = diagrams / "method_architecture.mmd"
    image = Image.new("RGBA", (1600, 900), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 40, 1550, 180), fill=(230, 244, 241, 255))
    image.save(output)
    source.write_text(
        "flowchart LR\nA[Method C1 M1] --> B[Evidence]",
        encoding="utf-8",
    )
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="mermaid",
        description="method_architecture",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "method_architecture",
            "managed_by": "merak",
            "scientific_role": "method",
            "scientific_question": "Which mechanism is tested?",
            "claim_ids": ["C1"],
            "source_data": ["ideas/SELECTED_IDEA.json"],
            "intended_comparison": "Declared contrast",
            "visual_encoding": "Mechanism graph",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
        },
    )

    issues = figure_artifact_registry.scientific_quality_issues(tmp_path / "figures")

    assert any("transparent" in issue or "height" in issue for issue in issues)


def test_synthetic_preview_runs_the_same_scientific_quality_checks(
    tmp_path: Path,
) -> None:
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    output = diagrams / "preview.png"
    source = diagrams / "preview.py"
    Image.new("RGB", (1600, 900), "white").save(output)
    source.write_text("print('registered preview')\n", encoding="utf-8")
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="matplotlib",
        description="synthetic_preview_main_comparison",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "synthetic_preview_main_comparison",
            "caption": "ROC",
            "managed_by": "merak",
            "scientific_role": "result",
            "evidence_status": "synthetic_preview",
            "paper_selected": False,
            "manuscript_eligible": False,
        },
    )

    issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )

    assert any("caption is too generic" in issue for issue in issues)
    assert any("missing publication style profile" in issue for issue in issues)
    assert all("watermark" not in issue.casefold() for issue in issues)
