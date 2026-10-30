from __future__ import annotations

from server.tests._figure_workflow_support import (
    FigureType as FigureType,
    Image as Image,
    Path as Path,
    _disable_live_electron_renderer_discovery as _disable_live_electron_renderer_discovery,
    _seed_project as _seed_project,
    asyncio as asyncio,
    csv as csv,
    figure_artifact_registry as figure_artifact_registry,
    figure_engine as figure_engine,
    hashlib as hashlib,
    json as json,
    pytest as pytest,
    scientific_architecture_compiler as scientific_architecture_compiler,
    scientific_asset_service as scientific_asset_service,
)
from server.services.scientific_scene_figure import compile_scientific_scene_figure


def test_vector_figure_quality_checks_its_derived_raster_preview(
    tmp_path: Path,
) -> None:
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    output = diagrams / "evaluation_design.pdf"
    source = diagrams / "evaluation_design.mmd"
    preview = diagrams / "evaluation_design.png"
    output.write_bytes(b"%PDF-1.4\n%%EOF")
    source.write_text("flowchart LR\nA[Input] --> B[Output]", encoding="utf-8")
    Image.new("RGB", (4200, 500), "white").save(preview)
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="mermaid",
        description="evaluation_design",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "evaluation_design",
            "managed_by": "merak",
            "scientific_role": "evaluation_design",
            "scientific_question": "How is the evaluation executed?",
            "claim_ids": ["C1"],
            "source_data": ["ideas/SELECTED_IDEA.json"],
            "intended_comparison": "Method versus matched control",
            "visual_encoding": "Evaluation flow",
            "uncertainty_encoding": "Paired confidence interval",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
        },
    )

    issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )

    assert any("extreme aspect ratio" in issue for issue in issues)


def test_quarantined_synthetic_preview_does_not_block_on_canvas_crop(
    tmp_path: Path,
) -> None:
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    output = diagrams / "preview.pdf"
    source = diagrams / "preview.py"
    preview = diagrams / "preview.png"
    output.write_bytes(b"%PDF-1.4\n%%EOF")
    source.write_text("print('registered preview')", encoding="utf-8")
    Image.new("RGB", (2000, 420), "white").save(preview)
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="matplotlib",
        description="synthetic_preview_main_comparison",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "synthetic_preview_main_comparison",
            "scientific_role": "result",
            "evidence_status": "synthetic_preview",
            "paper_selected": False,
            "manuscript_eligible": False,
            "style_profile": "merak-publication-v1",
        },
    )

    issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )

    assert not any("canvas edge" in issue for issue in issues)


def test_figurespec_layout_rejects_overlap_broken_and_duplicate_edges() -> None:
    issues = figure_artifact_registry.figurespec_layout_issues_payload({
        "canvas": {"width": 900, "height": 500},
        "style": {"font_size": 16},
        "nodes": [
            {"id": "source", "label": "Verified source cohort", "x": 250, "y": 240, "width": 280, "height": 120},
            {"id": "method", "label": "Domain-specific mechanism", "x": 360, "y": 240, "width": 280, "height": 120},
        ],
        "edges": [
            {"from": "source", "to": "missing", "label": "feeds"},
            {"from": "source", "to": "method", "label": "conditions"},
            {"from": "source", "to": "method", "label": "conditions"},
        ],
    })

    assert any("nodes source and method overlap" in issue for issue in issues)
    assert any("unknown to endpoint missing" in issue for issue in issues)
    assert any("duplicates source->method" in issue for issue in issues)


def test_figurespec_layout_rejects_crossing_and_node_occluding_edges() -> None:
    issues = figure_artifact_registry.figurespec_layout_issues_payload({
        "canvas": {"width": 900, "height": 520},
        "nodes": [
            {"id": "left_top", "label": "Source A", "x": 120, "y": 100, "width": 140, "height": 70},
            {"id": "right_bottom", "label": "Target A", "x": 780, "y": 420, "width": 140, "height": 70},
            {"id": "left_bottom", "label": "Source B", "x": 120, "y": 420, "width": 140, "height": 70},
            {"id": "right_top", "label": "Target B", "x": 780, "y": 100, "width": 140, "height": 70},
            {"id": "middle", "label": "Unrelated mechanism", "x": 450, "y": 260, "width": 170, "height": 90},
        ],
        "edges": [
            {"from": "left_top", "to": "right_bottom"},
            {"from": "left_bottom", "to": "right_top"},
        ],
    })

    assert any("passes through unrelated node middle" in issue for issue in issues)
    assert any("edges left_top->right_bottom and left_bottom->right_top cross" in issue for issue in issues)


def test_figurespec_layout_rejects_overlapping_groups_and_dense_labels() -> None:
    issues = figure_artifact_registry.figurespec_layout_issues_payload({
        "canvas": {"width": 900, "height": 500},
        "style": {"font_size": 14},
        "nodes": [
            {
                "id": "encoder",
                "label": "A deliberately overlong mechanism label that cannot be scanned quickly in a paper figure",
                "x": 330,
                "y": 240,
                "width": 300,
                "height": 100,
            },
            {
                "id": "objective",
                "label": "Matched objective",
                "x": 570,
                "y": 240,
                "width": 150,
                "height": 80,
            },
        ],
        "groups": [
            {"id": "representation", "node_ids": ["encoder"], "padding": 35},
            {"id": "training", "node_ids": ["objective"], "padding": 35},
        ],
        "edges": [{"from": "encoder", "to": "objective"}],
    })

    assert any("label is too long" in issue for issue in issues)
    assert any("groups representation and training overlap" in issue for issue in issues)


def test_figurespec_generation_fails_before_persisting_invalid_geometry(
    tmp_path: Path,
) -> None:
    result = asyncio.run(figure_engine.generate(
        description="Invalid overlapping evaluation design",
        artifact_name="evaluation_design",
        figure_type=FigureType.FIGURESPEC,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code=json.dumps({
            "canvas": {"width": 900, "height": 500},
            "nodes": [
                {"id": "source", "label": "Verified source", "x": 300, "y": 240, "width": 300, "height": 130},
                {"id": "method", "label": "Declared mechanism", "x": 380, "y": 240, "width": 300, "height": 130},
            ],
            "edges": [{"from": "source", "to": "missing"}],
        }),
        metadata={
            "scientific_role": "evaluation_design",
            "generator_skill": "figure-spec",
            "skill": "figure-spec",
            "skill_invocation_verified": True,
        },
    ))

    assert result.success is False
    assert "overlap" in str(result.error)
    assert "unknown to endpoint missing" in str(result.error)
    assert not (tmp_path / "figures" / "FIGURE_MANIFEST.json").exists()
    review = json.loads(
        (tmp_path / ".merak" / "figure-reviews" / "evaluation_design.json").read_text(
            encoding="utf-8"
        )
    )
    assert review[-1]["status"] == "failed"


def test_figurespec_visual_review_is_bound_to_source_hash(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    compilation = compile_scientific_scene_figure(method)
    result = asyncio.run(figure_engine.generate(
        description=str(method["caption"]),
        artifact_name="method_architecture",
        figure_type=FigureType.FIGURESPEC,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code=json.dumps(compilation.spec),
        metadata={
            **method,
            "element_mappings": compilation.element_mappings,
            "architecture_compiler": compilation.profile,
            "generator_skill": "figure-spec",
            "skill": "figure-spec",
            "skill_invocation_verified": True,
        },
    ))
    assert result.success is True, result.error
    source = tmp_path / "figures" / "diagrams" / "method_architecture.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["nodes"][0]["label"] = "Unreviewed source mutation"
    source.write_text(json.dumps(payload), encoding="utf-8")
    figure_artifact_registry.reconcile(tmp_path / "figures")

    issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )

    assert any("visual review is stale for editable source" in issue for issue in issues)


def test_drawio_layout_detects_hidden_text_overflow(tmp_path: Path) -> None:
    source = tmp_path / "overflow.drawio"
    source.write_text(
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="crowded" vertex="1" parent="1" '
        'value="A very long scientific claim that cannot fit inside this tiny box '
        'without silently dropping several important lines" '
        'style="whiteSpace=wrap;fontSize=18;">'
        '<mxGeometry x="0" y="0" width="120" height="45" as="geometry"/>'
        '</mxCell></root></mxGraphModel></diagram></mxfile>',
        encoding="utf-8",
    )

    issues = figure_artifact_registry.drawio_text_layout_issues(source)

    assert any("crowded" in issue and "allows" in issue for issue in issues)


def test_drawio_layout_preserves_authored_xml_line_breaks(tmp_path: Path) -> None:
    source = tmp_path / "authored-lines.drawio"
    source.write_text(
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="manifest" vertex="1" parent="1" '
        'value="EEG manifest&#xa;signal · label · metadata&#xa;required fields checked" '
        'style="whiteSpace=wrap;fontSize=11;spacingTop=5;spacingBottom=5;">'
        '<mxGeometry x="0" y="0" width="170" height="68" as="geometry"/>'
        '</mxCell></root></mxGraphModel></diagram></mxfile>',
        encoding="utf-8",
    )

    issues = figure_artifact_registry.drawio_text_layout_issues(source)

    assert issues == []


def test_drawio_autofit_repairs_all_text_cells_before_render(tmp_path: Path) -> None:
    xml = (
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="crowded" vertex="1" parent="1" '
        'value="line one&#xa;line two&#xa;line three&#xa;line four" '
        'style="whiteSpace=wrap;fontSize=14;spacingTop=4;spacingBottom=4;">'
        '<mxGeometry x="0" y="0" width="150" height="42" as="geometry"/>'
        '</mxCell></root></mxGraphModel></diagram></mxfile>'
    )

    fitted, adjustments = figure_artifact_registry.autofit_drawio_text(xml)
    source = tmp_path / "fitted.drawio"
    source.write_text(fitted, encoding="utf-8")

    assert adjustments and adjustments[0].startswith("crowded:")
    assert figure_artifact_registry.drawio_text_layout_issues(source) == []


def test_mermaid_layout_rejects_dense_paper_diagram(tmp_path: Path) -> None:
    source = tmp_path / "dense.mmd"
    lines = ["flowchart LR"]
    for index in range(26):
        lines.append(f'N{index}["Scientific node {index}"]')
        if index:
            lines.append(f"N{index - 1} --> N{index}")
    source.write_text("\n".join(lines), encoding="utf-8")

    issues = figure_artifact_registry.mermaid_layout_issues(source)

    assert any("26 nodes" in issue for issue in issues)


def test_mermaid_layout_honors_explicit_breaks_and_reports_long_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "explicit-lines.mmd"
    source.write_text(
        'flowchart LR\n'
        'ok["evidence ledger<br/>run and data identity<br/>device contract<br/>failures"]\n'
        'bad["evidence ledger<br/>run and data identity<br/>'
        'calibration and fixed-device contract plus raw predictions<br/>failures"]',
        encoding="utf-8",
    )


def test_mermaid_render_text_rejects_labels_tiny_at_paper_width(
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "panoramic.pdf"
    document = fitz.open()
    page = document.new_page(width=2400, height=1200)
    page.insert_text((100, 100), "Protocol node", fontsize=10)
    document.save(pdf)
    document.close()

    issues = figure_artifact_registry.mermaid_render_text_issues(pdf)

    assert any("unreadable median size" in issue for issue in issues)


def test_mermaid_concept_matching_accepts_scientific_synonyms() -> None:
    source = (
        "Group-disjoint allocation with subject and record isolation. "
        "A locked test is used with no further selection."
    )

    assert figure_artifact_registry.mermaid_concept_present(
        "Leakage-safe split", source
    )
    assert figure_artifact_registry.mermaid_concept_present(
        "Held-out evaluation", source
    )


def test_evaluation_mermaid_repair_compacts_labels_and_removes_code_ids(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    diagrams = figures / "diagrams"
    diagrams.mkdir(parents=True)
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({
            "figures": [{
                "id": "evaluation_design",
                "source_path": "figures/diagrams/evaluation_design.mmd",
                "publication_labels": [
                    {"schema": 1, "id": "evaluation.data", "kind": "concept", "display_text": "Study data"},
                    {"schema": 1, "id": "evaluation.split", "kind": "concept", "display_text": "Leakage-safe split"},
                    {"schema": 1, "id": "evaluation.heldout", "kind": "concept", "display_text": "Held-out evaluation"},
                ],
            }],
        }),
        encoding="utf-8",
    )
    source = diagrams / "evaluation_design.mmd"
    source.write_text(
        'flowchart TB\n'
        'data["Study data<br/>records, labels, metadata"]\n'
        'safe["Group-disjoint allocation<br/>subject / record isolated"]\n'
        'endpoint["Very long endpoint summary with spectral and topology fidelity"]\n'
        'unit["Analysis-unit aggregation<br/>subject_id"]\n'
        'data --> safe --> endpoint --> unit\n',
        encoding="utf-8",
    )

    repaired = figure_artifact_registry.repair_evaluation_mermaid(
        tmp_path, "evaluation_design"
    )
    text = source.read_text(encoding="utf-8")

    assert repaired["changed"] is True
    assert "flowchart LR" in text
    assert "Leakage-safe split" in text
    assert "Held-out evaluation" in text
    assert "subject_id" not in text
    assert "Subject-level endpoints" in text
    assert figure_artifact_registry.mermaid_layout_issues(source) == []


def test_figure_best_candidate_restores_lower_penalty_version(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    source = figures / "evaluation_design.mmd"
    output = figures / "evaluation_design.pdf"
    source.write_text("best source", encoding="utf-8")
    output.write_bytes(b"best pdf")
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [{"id": "evaluation_design"}]}),
        encoding="utf-8",
    )
    (figures / "FIGURE_MANIFEST.json").write_text(
        json.dumps({
            "figures": [{
                "id": "evaluation_design",
                "source_path": "figures/evaluation_design.mmd",
                "output_path": "figures/evaluation_design.pdf",
                "metadata": {},
            }],
        }),
        encoding="utf-8",
    )

    saved = figure_artifact_registry.preserve_best_candidate(
        tmp_path,
        "evaluation_design",
        ["diagram occupies only 29% of raster width"],
    )
    source.write_text("worse source", encoding="utf-8")
    output.write_bytes(b"worse pdf")
    restored = figure_artifact_registry.preserve_best_candidate(
        tmp_path,
        "evaluation_design",
        [
            "mermaid labels project to an unreadable median size at paper width (3.0 pt)",
            "diagram occupies only 20% of raster width",
        ],
    )

    assert saved["action"] == "saved"
    assert restored["action"] == "restored"
    assert source.read_text(encoding="utf-8") == "best source"
    assert output.read_bytes() == b"best pdf"


def test_figure_best_candidate_never_restores_retired_backend(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    source = figures / "evaluation_design.mmd"
    output = figures / "evaluation_design.pdf"
    source.write_text("retired mermaid source", encoding="utf-8")
    output.write_bytes(b"retired pdf")
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [{
            "id": "evaluation_design",
            "recommended_backend": "rich_svg",
        }]}),
        encoding="utf-8",
    )
    (figures / "FIGURE_MANIFEST.json").write_text(
        json.dumps({"figures": [{
            "id": "evaluation_design",
            "type": "mermaid",
            "source_path": "figures/evaluation_design.mmd",
            "output_path": "figures/evaluation_design.pdf",
            "metadata": {},
        }]}),
        encoding="utf-8",
    )

    result = figure_artifact_registry.preserve_best_candidate(
        tmp_path,
        "evaluation_design",
        ["diagram occupies only 21% of raster width"],
    )

    assert result["action"] == "skipped"
    assert result["candidate_backend"] == "mermaid"
    assert result["authoritative_backend"] == "rich_svg"


def test_figure_source_must_reference_the_frozen_contract(tmp_path: Path) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "diagrams").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Coordinate-conditioned montage consistency",
            "hypothesis": "Submontage consistency improves transfer.",
            "claims": [{"id": "C1", "statement": "Transfer improves."}],
            "mechanisms": [{
                "id": "M1",
                "name": "Submontage consistency",
                "description": "Align paired views.",
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({
            "figures": [{
                "id": "method_architecture",
                "scientific_role": "method",
                "claim_ids": ["C1"],
                "publication_labels": [{"schema": 1, "id": "method.mechanism", "kind": "concept", "display_text": "Submontage consistency"}],
            }],
        }),
        encoding="utf-8",
    )
    source = tmp_path / "figures" / "diagrams" / "method_architecture.mmd"
    output = tmp_path / "figures" / "diagrams" / "method_architecture.png"
    source.write_text(
        "stateDiagram-v2\n[*] --> Idle\nIdle --> Running: start\n"
        "Running --> Completed: success\nRunning --> Failed: error",
        encoding="utf-8",
    )
    Image.new("RGB", (1600, 900), "white").save(output)
    figure_artifact_registry.record(
        output_dir=source.parent,
        figure_type="mermaid",
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
            "scientific_question": "Which mechanism is tested?",
            "intended_comparison": "Declared contrast",
            "visual_encoding": "Mechanism graph",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(tmp_path / "figures")

    assert any("generic template" in issue for issue in issues)
    assert any("omits required domain-facing terms" in issue for issue in issues)
    assert all("omits frozen claim IDs" not in issue for issue in issues)


def test_figure_alignment_accepts_normalized_synonyms_and_claim_binding(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Subject-specific adapter for robust transfer",
            "hypothesis": "Personalized adaptation improves shift resilience.",
            "claims": [{"id": "C1", "statement": "Transfer remains robust."}],
            "mechanisms": [{
                "id": "M1",
                "name": "Subject-specific adapter",
                "description": "Personalizes the shared representation.",
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [{
            "id": "method_architecture",
            "scientific_role": "method",
            "claim_ids": ["C1"],
            "publication_labels": [{"schema": 1, "id": "method.adapter", "kind": "concept", "display_text": "Subject-specific adapter"}],
        }]}),
        encoding="utf-8",
    )
    source = diagrams / "method_architecture.mmd"
    output = diagrams / "method_architecture.png"
    source.write_text(
        "flowchart LR\nA[Personalization branch] --> B[Resilience under shift]",
        encoding="utf-8",
    )
    Image.new("RGB", (1600, 900), "white").save(output)
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
            "paper_selected": True,
            "claim_ids": ["C1"],
            "source_data": ["ideas/SELECTED_IDEA.json"],
            "scientific_question": "How is personalization implemented?",
            "intended_comparison": "Shared versus personalized representation",
            "visual_encoding": "Mechanism graph",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(
        tmp_path / "figures"
    )

    assert not any("omits required domain-facing terms" in issue for issue in issues)
    assert not any("weak semantic overlap" in issue for issue in issues)


def test_figure_alignment_checks_rendered_svg_not_python_implementation(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    plots = tmp_path / "figures" / "plots"
    plots.mkdir(parents=True)
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Robust transfer comparison",
            "hypothesis": "The proposed method improves robust transfer.",
            "claims": [{"id": "C1", "statement": "Transfer improves."}],
            "mechanisms": [],
        }),
        encoding="utf-8",
    )
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [{
            "id": "main_comparison",
            "scientific_role": "result",
            "claim_ids": ["C1"],
        }]}),
        encoding="utf-8",
    )
    source = plots / "main_comparison.py"
    source.write_text(
        "data_path = 'experiments/results/main_comparison.csv'\n"
        "ci_low = 0.70\nci_high = 0.80\n"
        "figure.savefig('plot.pdf', bbox_inches='tight')\n",
        encoding="utf-8",
    )
    svg = plots / "main_comparison.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text>Robust transfer accuracy</text><text>Proposed method</text>'
        '</svg>',
        encoding="utf-8",
    )
    output = plots / "main_comparison.pdf"
    output.write_bytes(b"%PDF-1.4\n% test fixture\n")
    figure_artifact_registry.record(
        output_dir=plots,
        figure_type="matplotlib",
        description="Robust transfer accuracy",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "main_comparison",
            "managed_by": "merak",
            "scientific_role": "result",
            "paper_selected": True,
            "claim_ids": ["C1"],
            "source_data": ["experiments/results/main_comparison.csv"],
            "scientific_question": "Does robust transfer improve?",
            "intended_comparison": "Proposed method versus control",
            "visual_encoding": "Accuracy with uncertainty intervals",
            "uncertainty_encoding": "95% confidence interval",
            "evidence_status": "executed",
            "style_profile": "merak-publication-v1",
            "rendered_variants": {
                "svg": svg.relative_to(tmp_path).as_posix(),
            },
            "rendered_variant_sha256": {
                "svg": hashlib.sha256(svg.read_bytes()).hexdigest()
            },
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(
        tmp_path / "figures"
    )

    assert not any("exposes code symbols or artifact paths" in issue for issue in issues)


def test_figure_alignment_still_rejects_code_tokens_visible_in_svg(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    plots = tmp_path / "figures" / "plots"
    plots.mkdir(parents=True)
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Robust transfer comparison",
            "claims": [{"id": "C1", "statement": "Transfer improves."}],
        }),
        encoding="utf-8",
    )
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [{
            "id": "main_comparison",
            "scientific_role": "result",
            "claim_ids": ["C1"],
        }]}),
        encoding="utf-8",
    )
    source = plots / "main_comparison.py"
    source.write_text("pass\n", encoding="utf-8")
    svg = plots / "main_comparison.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text>experiments/results/main_comparison.csv</text>'
        '</svg>',
        encoding="utf-8",
    )
    output = plots / "main_comparison.pdf"
    output.write_bytes(b"%PDF-1.4\n% test fixture\n")
    figure_artifact_registry.record(
        output_dir=plots,
        figure_type="matplotlib",
        description="Robust transfer accuracy",
        output_path=str(output),
        source_path=str(source),
        metadata={
            "semantic_key": "main_comparison",
            "managed_by": "merak",
            "scientific_role": "result",
            "paper_selected": True,
            "claim_ids": ["C1"],
            "source_data": ["experiments/results/main_comparison.csv"],
            "scientific_question": "Does robust transfer improve?",
            "intended_comparison": "Proposed method versus control",
            "visual_encoding": "Accuracy with uncertainty intervals",
            "uncertainty_encoding": "95% confidence interval",
            "evidence_status": "executed",
            "style_profile": "merak-publication-v1",
            "rendered_variants": {
                "svg": svg.relative_to(tmp_path).as_posix(),
            },
            "rendered_variant_sha256": {
                "svg": hashlib.sha256(svg.read_bytes()).hexdigest()
            },
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(
        tmp_path / "figures"
    )

    assert any("exposes code symbols or artifact paths" in issue for issue in issues)


def test_figure_alignment_rejects_method_workflow_status_and_hash_bookkeeping(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Auditable ranking comparison",
            "claims": [{"id": "C1", "statement": "Rankings can reverse."}],
            "mechanisms": [{
                "id": "M1",
                "name": "Multi-axis ranking",
                "description": "Compare registered endpoints.",
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [{
            "id": "method_architecture",
            "scientific_role": "method",
            "claim_ids": ["C1"],
            "publication_labels": [{"schema": 1, "id": "method.ranking", "kind": "concept", "display_text": "Multi-axis ranking"}],
        }]}),
        encoding="utf-8",
    )
    source = diagrams / "method_architecture.svg"
    output = diagrams / "method_architecture.png"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text>Multi-axis ranking</text><text>Build Ledger Record</text>'
        '<text>Canonical Sha256</text><text>planned inference component</text>'
        '</svg>',
        encoding="utf-8",
    )
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
            "scientific_question": "How are rankings compared?",
            "intended_comparison": "Registered endpoint rankings",
            "visual_encoding": "Scientific mechanism diagram",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(
        tmp_path / "figures"
    )

    assert any("internal provenance implementation" in issue for issue in issues)
    assert any("pending/planned implementation status" in issue for issue in issues)


def test_figure_alignment_accepts_mechanism_aggregation_with_full_source_mapping(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    diagrams = tmp_path / "figures" / "diagrams"
    diagrams.mkdir(parents=True)
    mechanisms = [
        {"id": "M1", "name": "Conditional geometry intervention", "description": "retention, temporal concentration, and channel synchrony"},
        {"id": "M2", "name": "Task and held-out domain interaction", "description": "continuous and event tasks under held-out domains"},
        {"id": "M3", "name": "Shortcut and collapse diagnostics", "description": "collapse, recoverability, and shortcut probes"},
    ]
    for mechanism in mechanisms:
        mechanism["publication_name"] = mechanism["name"]
        mechanism["publication_description"] = mechanism["description"]
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Conditional geometry mechanism map",
            "hypothesis": "Geometry changes held-out task behavior.",
            "claims": [{"id": "C1", "statement": "The interaction is measurable."}],
            "mechanisms": mechanisms,
        }),
        encoding="utf-8",
    )
    components = [
        {"id": "rows", "label": "Rows", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "Rows", "required_visual": True},
        {"id": "main", "label": "main", "lane": "representation_model", "source_path": "experiments/src/train.py", "source_symbol": "main", "required_visual": True},
        {"id": "objective", "label": "compute objectives", "lane": "training_objective", "source_path": "experiments/src/objectives.py", "source_symbol": "compute_objectives", "required_visual": True},
        {"id": "metrics", "label": "metric records", "lane": "evaluation", "source_path": "experiments/src/evaluation.py", "source_symbol": "metric_records", "required_visual": True},
    ]
    asset = {
        "id": "method_architecture",
        "scientific_role": "method",
        "claim_ids": ["C1"],
        "publication_labels": [
            {"schema": 1, "id": f"method.component.{index}", "kind": "concept", "display_text": item["label"]}
            for index, item in enumerate(components, start=1)
        ],
        "architecture_blueprint": {"components": components},
        "scientific_scene": {
            "schema": 1,
            "objects": [
                {
                    "id": item["id"], "kind": "operation", "label": item["label"],
                    "source_path": item["source_path"], "source_symbol": item["source_symbol"],
                }
                for item in components
            ],
            "relations": [{"from": "rows", "to": "main", "kind": "data"}],
        },
        "method_brief": {
            "title": "Conditional geometry mechanism map",
            "problem": "EEG representation learning",
            "mechanism_nodes": mechanisms,
            "reported_endpoints": ["held-out accuracy", "interaction"],
        },
    }
    (tmp_path / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps({"figures": [asset]}),
        encoding="utf-8",
    )
    compilation = scientific_architecture_compiler.compile(asset)
    source = diagrams / "method_architecture.json"
    output = diagrams / "method_architecture.png"
    source.write_text(json.dumps(compilation.spec), encoding="utf-8")
    Image.new("RGB", (1600, 900), "white").save(output)
    figure_artifact_registry.record(
        output_dir=diagrams,
        figure_type="figurespec",
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
            "scientific_question": "Which mechanisms operationalize the idea?",
            "intended_comparison": "Registered mechanism branches",
            "visual_encoding": "Mechanism-first architecture",
            "uncertainty_encoding": "not_applicable",
            "evidence_status": "planned_design",
            "style_profile": "merak-publication-v1",
            "architecture_compiler": compilation.profile,
            "element_mappings": compilation.element_mappings,
        },
    )

    issues = figure_artifact_registry.scientific_alignment_issues(
        tmp_path / "figures"
    )

    assert not any("architecture renders only" in issue for issue in issues)
    assert not any("source omits required domain-facing terms" in issue for issue in issues)
    assert issues == []
