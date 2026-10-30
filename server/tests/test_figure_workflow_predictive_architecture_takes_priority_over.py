from __future__ import annotations

from server.tests._figure_workflow_support import (
    ET as ET,
    FigureType as FigureType,
    Path as Path,
    SIMULATION_END_DISCLOSURE as SIMULATION_END_DISCLOSURE,
    WorkflowEngine as WorkflowEngine,
    WorkflowRun as WorkflowRun,
    _author_plan_figures as _author_plan_figures,
    _benchmark_model_suite_svg as _benchmark_model_suite_svg,
    _disable_live_electron_renderer_discovery as _disable_live_electron_renderer_discovery,
    _evaluation_design_svg as _evaluation_design_svg,
    _seed_project as _seed_project,
    asyncio as asyncio,
    csv as csv,
    execution_provenance_service as execution_provenance_service,
    figure_artifact_registry as figure_artifact_registry,
    figure_engine as figure_engine,
    figure_engine_module as figure_engine_module,
    json as json,
    node_risk_audit_service as node_risk_audit_service,
    paper_artifact_builder as paper_artifact_builder,
    paper_compiler as paper_compiler,
    paper_profile_service as paper_profile_service,
    pytest as pytest,
    scientific_architecture_compiler as scientific_architecture_compiler,
    scientific_asset_service as scientific_asset_service,
    time as time,
    validate_submission_start as validate_submission_start,
)
from server.services.scientific_scene_figure import compile_scientific_scene_figure


def test_predictive_architecture_takes_priority_over_mechanism_story() -> None:
    compilation = scientific_architecture_compiler.compile({
        "architecture_blueprint": {
            "components": [
                {"id": "data", "label": "Grouped input", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "load_data"},
                {"id": "encoder", "label": "Residual encoder", "display_name": "Residual encoder", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier.encoder", "operation": "residual blocks"},
                {"id": "head", "label": "Task Head", "display_name": "Task head", "lane": "evaluation", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier.task_head", "operation": "linear logits"},
            ],
            "tensor_flow": [
                {"from": "data", "to": "encoder", "flow_kind": "data"},
                {"from": "encoder", "to": "head", "flow_kind": "data"},
            ],
            "inference_paths": [["data", "encoder", "head"]],
        },
        "method_brief": {
            "title": "Residual benchmark classifier",
            "mechanism_nodes": [
                {"name": "Matched comparison", "description": "Shared opportunity."},
                {"name": "Evidence ledger", "description": "Traceable outcomes."},
            ],
        },
    })

    labels = " ".join(node["label"] for node in compilation.spec["nodes"])
    assert "Residual encoder" in labels
    assert "Task head" in labels
    assert compilation.profile.get("semantic_aggregation") is not True


def test_comparative_predictive_study_renders_model_suite_architecture() -> None:
    compilation = scientific_architecture_compiler.compile({
        "architecture_blueprint": {
            "components": [
                {"id": "data", "label": "Grouped input", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "load_data"},
                {"id": "residual", "label": "ResidualBlock", "display_name": "Residual Block", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "ResidualBlock", "operation": "LayerNorm to Linear with skip connection"},
                {"id": "classifier", "label": "BenchmarkClassifier", "display_name": "Benchmark Classifier", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier"},
                {"id": "head", "label": "Task Head", "lane": "evaluation", "source_path": "experiments/src/models.py", "source_symbol": "BenchmarkClassifier.task_head"},
            ],
            "tensor_flow": [
                {"from": "data", "to": "classifier", "flow_kind": "data"},
                {"from": "classifier", "to": "head", "flow_kind": "data"},
            ],
            "model_configuration": {
                "model_suite": ["linear_reference", "mlp_reference", "residual_mlp"],
                "hidden_dim": 256,
                "depth": 3,
                "num_classes": 2,
                "dropout": 0.0,
            },
        },
        "method_brief": {
            "title": "Auditable multi-axis benchmark",
            "mechanism_nodes": [
                {"name": "Ranking", "description": "Paired comparison."},
                {"name": "Ledger", "description": "Traceable results."},
            ],
        },
    })

    labels = {node["label"] for node in compilation.spec["nodes"]}
    assert compilation.profile["visual_grammar"] == "benchmark_model_suite"
    assert {
        "Linear Reference", "Mlp Reference", "Residual Mlp",
        "Residual block stack", "Shared task interface",
    } <= labels
    assert figure_artifact_registry.figurespec_layout_issues_payload(
        compilation.spec
    ) == []


def test_predictive_architecture_rejects_protocol_storyboard() -> None:
    metadata = {
        "architecture_blueprint": {
            "components": [
                {
                    "source_symbol": "ResidualBlock",
                    "operation": "LayerNorm and linear layers with skip connection",
                },
                {"source_symbol": "BenchmarkClassifier.task_head"},
            ],
        },
    }

    issues = figure_artifact_registry.predictive_architecture_semantic_issues(
        metadata,
        "Matched data, protocol controls, calibration, and evidence ledger",
    )
    assert any("not a model architecture" in issue for issue in issues)
    assert any("prediction/head path" in issue for issue in issues)

    assert figure_artifact_registry.predictive_architecture_semantic_issues(
        metadata,
        "Input projection, residual block stack with skip connection, task head, "
        "logits, and calibrated probabilities",
    ) == []


def test_benchmark_svg_expands_residual_path_and_keeps_baselines_secondary() -> None:
    svg, mappings = _benchmark_model_suite_svg({
        "architecture_blueprint": {
            "model_configuration": {
                "model_suite": ["linear_reference", "mlp_reference", "residual_mlp"],
                "hidden_dim": 256,
                "depth": 3,
                "num_classes": 2,
                "dropout": 0.0,
            },
        },
    })

    for phrase in (
        "Linear reference", "Dense MLP reference", "FOCAL RESIDUAL MLP",
        "Residual block × 3", "identity skip connection", "Task head",
        "Temperature calibration",
    ):
        assert phrase in svg
    assert "seven" not in svg.casefold()
    assert {item["element_id"] for item in mappings} >= {
        "partitioned_data", "residual_stack", "task_head", "calibration_branch",
    }


def test_evaluation_design_svg_has_balanced_scientific_stages() -> None:
    svg, mappings = _evaluation_design_svg({
        "method_brief": {
            "mechanism_nodes": [{"publication_name": "Predictive encoder"}],
            "study_conditions": ["remove prediction objective"],
            "evaluation_contract": {
                "focal_condition": "Predictive encoder",
                "primary_comparator": "temporal-only",
                "comparators_or_controls": ["temporal-only"],
                "primary_outcomes": ["external-test macro-F1"],
                "statistics": "paired seed comparison",
            },
            "evaluation_protocol": {
                "primary_split": "external_test", "analysis_unit": "subject",
                "require_subject_isolation": True,
                "require_session_isolation": True,
            },
        },
    })
    ET.fromstring(svg)
    for phrase in (
        "Subject/session isolation required", "Intact mechanism",
        "Matched removal", "Alternative control", "Held-out test",
        "Paired contrasts", "Primary endpoint",
    ):
        assert phrase in svg
    assert "subject_id" not in svg
    assert len(mappings) == 8


def test_scientific_architecture_compiler_renders_factorized_latents_as_topology() -> None:
    components = [
        {"id": "dataset", "label": "Paired dataset", "lane": "data_and_sampling", "source_path": "experiments/src/data.py", "source_symbol": "Dataset"},
        {"id": "encoder", "label": "Shared encoder", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "Encoder"},
        {"id": "state", "label": "State projector", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "state_projector"},
        {"id": "acq", "label": "Acquisition projector", "lane": "representation_model", "source_path": "experiments/src/models.py", "source_symbol": "acquisition_projector"},
        {"id": "loss", "label": "Factorized objective", "lane": "training_objective", "source_path": "experiments/src/objectives.py", "source_symbol": "Objective"},
        {"id": "audit", "label": "Pareto audit", "lane": "evaluation", "source_path": "experiments/src/evaluation.py", "source_symbol": "pareto_audit"},
    ]
    compilation = scientific_architecture_compiler.compile({
        "architecture_blueprint": {
            "components": components,
            "implementation_status": "contract_mapped",
        },
        "method_brief": {
            "title": "Acquisition Counterfactual Invariance Pretraining (ACIP): a deliberately long manuscript title that must not overflow the figure",
            "problem": "Cross-domain predictive representation learning",
            "mechanism_nodes": [
                {"name": "Traceable counterfactual views", "description": "Registered paired views from one parent sample."},
                {"name": "State-acquisition factorization", "description": "z_state carries task state while z_acq predicts acquisition metadata."},
                {"name": "Utility-nuisance Pareto audit", "description": "Joint held-out task utility and nuisance probes."},
            ],
        },
    })

    node_labels = {item["label"] for item in compilation.spec["nodes"]}
    assert {
        "Task-bearing state", "Acquisition state", "Task head", "Acquisition head",
    } <= node_labels
    assert {"z_state", "z_acq"}.isdisjoint(node_labels)
    assert compilation.profile["visual_grammar"] == "factorized_representation"
    assert compilation.profile["grammar_version"] == 4
    assert compilation.spec["title"] == "ACIP Method Architecture"
    assert figure_artifact_registry.figurespec_layout_issues_payload(
        compilation.spec
    ) == []
    groups = {
        str(item["id"]): dict(item.get("bounds") or {})
        for item in compilation.spec["groups"]
    }
    top_group_ids = (
        "factor_data_group",
        "factor_views_group",
        "factor_model_group",
        "factor_heads_group",
        "factor_readouts_group",
    )
    assert {groups[group_id]["y"] for group_id in top_group_ids} == {165}
    assert {groups[group_id]["height"] for group_id in top_group_ids} == {375}
    assert (
        groups["factor_training_group"]["y"]
        == groups["factor_evaluation_group"]["y"]
    )
    assert (
        groups["factor_training_group"]["height"]
        == groups["factor_evaluation_group"]["height"]
    )


def test_method_architecture_reconciles_stale_blueprint_symbols(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    metadata = {
        "scientific_role": "method",
        "architecture_blueprint": {
            "implementation_status": "contract_mapped",
            "components": [
                {
                    "id": "live_train",
                    "label": "Training entrypoint",
                    "lane": "representation_model",
                    "source_path": "experiments/src/train.py",
                    "source_symbol": "train",
                },
                {
                    "id": "stale_epoch",
                    "label": "Old epoch loop",
                    "lane": "representation_model",
                    "source_path": "experiments/src/train.py",
                    "source_symbol": "_run_epoch",
                },
            ],
        },
        "method_brief": {
            "title": "Factorized Predictive Method (FPM)",
            "problem": "Predictive representation learning",
            "mechanism_nodes": [
                {"name": "Traceable paired views", "description": "Paired counterfactual views."},
                {"name": "State-acquisition factorization", "description": "z_state and z_acq encode separate factors."},
                {"name": "Utility-nuisance audit", "description": "Held-out Pareto audit."},
            ],
        },
        "generator_skill": "figure-spec",
        "skill": "figure-spec",
        "skill_invocation_verified": True,
    }

    result = asyncio.run(figure_engine.generate(
        description="Source-grounded factorized model architecture",
        artifact_name="method_architecture",
        figure_type=FigureType.FIGURESPEC,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code="",
        metadata=metadata,
    ))

    assert result.success is True, result.error
    ignored = result.metadata["stale_architecture_components_ignored"]
    assert [item["component_id"] for item in ignored] == ["stale_epoch"]
    payload = json.loads(Path(result.source_path).read_text(encoding="utf-8"))
    assert {"Task-bearing state", "Acquisition state"} <= {
        item["label"] for item in payload["nodes"]
    }


def test_method_architecture_generation_uses_authored_scene_and_rejects_generic_override(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    (tmp_path / "experiments" / "src" / "models.py").write_text(
        "from torch import nn\n\n"
        "class Encoder(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.stem = nn.Conv1d(8, 32, 7)\n"
        "        self.blocks = nn.ModuleList([nn.Conv1d(32, 32, 3)])\n"
        "        self.pool = nn.AdaptiveAvgPool1d(1)\n"
        "        self.projection = nn.Linear(32, 16)\n"
        "    def forward(self, x):\n"
        "        h = self.stem(x)\n"
        "        for block in self.blocks:\n"
        "            h = block(h)\n"
        "        return self.projection(self.pool(h).squeeze(-1))\n\n"
        "class Decoder(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.layer = nn.Linear(16, 8)\n"
        "    def forward(self, z):\n"
        "        return self.layer(z)\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "data.py").write_text(
        "class SplitAudit: pass\n"
        "def load_manifest(path): return path\n"
        "def grouped_split(frame): return frame\n"
        "def topology_mask(adjacency): return adjacency\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "src" / "objectives.py").write_text(
        "def temporal_nt_xent(first, second): return first\n",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps({
            "schema": 2,
            "scientific_scene": {
                "schema": 1,
                "objects": [
                    {"id": "observations", "kind": "input", "label": "Observed signal views", "source_path": "experiments/src/data.py", "source_symbol": "load_manifest"},
                    {"id": "shared_encoder", "kind": "operation", "label": "Shared contrastive encoder", "source_path": "experiments/src/models.py", "source_symbol": "Encoder"},
                    {"id": "masked_decoder", "kind": "operation", "label": "Masked signal reconstruction", "source_path": "experiments/src/models.py", "source_symbol": "Decoder"},
                    {"id": "contrastive_objective", "kind": "measurement", "label": "Temporal contrastive objective", "source_path": "experiments/src/objectives.py", "source_symbol": "temporal_nt_xent"},
                ],
                "relations": [{"from": "observations", "to": "shared_encoder", "kind": "data"},
                              {"from": "shared_encoder", "to": "masked_decoder", "kind": "data"},
                              {"from": "shared_encoder", "to": "contrastive_objective", "kind": "data"}],
            },
            "implementation_checks": [{
                "id": "I1",
                "description": "Two augmentation views use a shared contrastive encoder and topology-masked reconstruction.",
                "evidence": [
                    {"path": "experiments/src/models.py", "symbols": ["Encoder", "Decoder"]},
                    {"path": "experiments/src/data.py", "symbols": ["load_manifest", "grouped_split", "topology_mask", "SplitAudit"]},
                    {"path": "experiments/src/objectives.py", "symbols": ["temporal_nt_xent"]},
                    {"path": "experiments/configs/main.yaml", "config_keys": ["augmentations", "mask_ratio"]},
                ],
            }],
            "evaluation_contract": {
                "primary_outcomes": ["classification accuracy", "AUROC", "ECE"],
            },
        }),
        encoding="utf-8",
    )
    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    generic_spec = {
        "canvas": {"width": 900, "height": 400},
        "nodes": [
            {"id": "input", "label": "Input", "x": 150, "y": 200},
            {"id": "model", "label": "Model", "x": 450, "y": 200},
            {"id": "output", "label": "Output", "x": 750, "y": 200},
        ],
        "edges": [
            {"from": "input", "to": "model"},
            {"from": "model", "to": "output"},
        ],
    }

    metadata = {**method, "generator_skill": "figure-spec", "skill": "figure-spec",
                "skill_invocation_verified": True}
    rejected = asyncio.run(figure_engine.generate(
        description="Source-grounded method architecture", artifact_name="method_architecture",
        figure_type=FigureType.FIGURESPEC, output_dir=str(tmp_path / "figures" / "diagrams"),
        code=json.dumps(generic_spec), metadata=metadata,
    ))
    assert rejected.success is False
    assert "generic Input/Model/Output" in (rejected.error or "")
    compilation = compile_scientific_scene_figure(method)
    metadata.update(element_mappings=compilation.element_mappings,
                    architecture_compiler=compilation.profile)
    result = asyncio.run(figure_engine.generate(
        description="Source-grounded method architecture",
        artifact_name="method_architecture",
        figure_type=FigureType.FIGURESPEC,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code=json.dumps(compilation.spec),
        metadata=metadata,
    ))

    assert result.success is True, result.error
    payload = json.loads(Path(result.source_path).read_text(encoding="utf-8"))
    assert {"Input", "Model", "Output"}.isdisjoint({
        item["label"] for item in payload["nodes"]
    })
    assert {item["id"] for item in payload["nodes"]} == {
        item["id"] for item in method["scientific_scene"]["objects"]
    }
    assert len({item.get("visual_kind") for item in payload["nodes"]}) >= 2
    assert result.metadata["architecture_compiler"]["compiler"] == (
        "scientific-scene-figurespec-v2"
    )


def test_method_architecture_preserves_source_mapped_mechanism_spec(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    source = tmp_path / "experiments" / "src" / "models.py"
    source.write_text(
        "\n".join(f"def source_{index}(): return {index}" for index in range(8)),
        encoding="utf-8",
    )
    components = [
        {
            "id": f"implementation_{index}",
            "label": label,
            "source_path": "experiments/src/models.py",
            "source_symbol": f"low_level_{index}",
            "required_visual": True,
        }
        for index, label in enumerate(
            ["main", "run", "forward", "init", "step", "dispatch", "persist", "audit"]
        )
    ]
    mechanism_names = [
        "Montage-conditioned channel representation",
        "Selective jointly-observable neighborhood alignment",
        "Coordinate-conditioned masked prediction",
        "Nuisance and counterfactual controls",
    ]
    nodes = [
        {
            "id": f"mechanism_{index}",
            "label": name,
            "sublabel": "source-grounded scientific mechanism with held-out evaluation",
            "x": 175 + (index % 4) * 350,
            "y": 220 + (index // 4) * 270,
            "width": 270,
            "height": 120,
            "visual_kind": "module_stack" if index < 4 else "audit",
        }
        for index, name in enumerate([*mechanism_names, *mechanism_names])
    ]
    authored_spec = {
        "canvas": {"width": 1400, "height": 700},
        "title": "Mechanism-resolved architecture",
        "nodes": nodes,
        "edges": [
            {"from": f"mechanism_{index}", "to": f"mechanism_{index + 1}"}
            for index in range(7)
        ],
        "groups": [
            {
                "label": "MODEL AND OBJECTIVES",
                "node_ids": [f"mechanism_{index}" for index in range(4)],
            },
            {
                "label": "CONTROLS AND EVALUATION",
                "node_ids": [f"mechanism_{index}" for index in range(4, 8)],
            },
        ],
    }
    mappings = [
        {
            "element_id": f"mechanism_{index}",
            "source_path": "experiments/src/models.py",
            "source_symbol": f"source_{index}",
            "semantic_role": "aggregated scientific mechanism",
        }
        for index in range(8)
    ]

    result = asyncio.run(figure_engine.generate(
        description="Source-mapped mechanism architecture",
        artifact_name="method_architecture",
        figure_type=FigureType.FIGURESPEC,
        output_dir=str(tmp_path / "figures" / "diagrams"),
        code=json.dumps(authored_spec),
        metadata={
            "scientific_role": "method",
            "architecture_blueprint": {"components": components},
            "method_brief": {
                "mechanism_nodes": [
                    {"name": name} for name in mechanism_names
                ],
            },
            "element_mappings": mappings,
            "generator_skill": "figure-spec",
            "skill": "figure-spec",
            "skill_invocation_verified": True,
        },
    ))

    assert result.success is True, result.error
    payload = json.loads(Path(result.source_path).read_text(encoding="utf-8"))
    assert {item["id"] for item in payload["nodes"]} == {
        f"mechanism_{index}" for index in range(8)
    }
    profile = result.metadata["architecture_compiler"]
    assert profile["compiler"] == "model-authored-source-grounded-v1"
    assert profile["semantic_aggregation"] is True
    assert set(profile["covered_mechanism_names"]) == set(mechanism_names)
    assert set(profile["covered_component_ids"]) == {
        item["id"] for item in components
    }
    assert figure_artifact_registry.raster_layout_issues(
        Path(result.output_path).with_suffix(".png")
    ) == []
    assert "Selective jointly-observable neighborhood alignment" not in (
        result.svg_content or ""
    )


def test_synthetic_architecture_ignores_failed_physical_training_check(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    (tmp_path / "experiments" / "IMPLEMENTATION_BLUEPRINT.json").write_text(
        json.dumps({"schema": 1, "implementation_family": "machine_learning"}),
        encoding="utf-8",
    )
    quality = tmp_path / ".merak" / "quality"
    quality.mkdir(parents=True)
    (quality / "training_check.json").write_text(
        json.dumps({
            "verdict": "FAIL",
            "blocking": True,
            "findings": [{"id": "TC-IMPL-001", "severity": "blocker"}],
        }),
        encoding="utf-8",
    )

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="synthetic_preview",
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")

    assert method["evidence_status"] == "implemented_design"
    assert method["architecture_blueprint"]["implementation_status"] == "simulation_verified"
    assert not any(
        "runtime training check" in issue
        for issue in method["architecture_blueprint"]["completeness_issues"]
    )


def test_stale_training_check_does_not_downgrade_newer_implementation(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    quality = tmp_path / ".merak" / "quality"
    quality.mkdir(parents=True)
    (quality / "training_check.json").write_text(
        json.dumps({"verdict": "FAIL", "blocking": True}),
        encoding="utf-8",
    )
    blueprint = tmp_path / "experiments" / "IMPLEMENTATION_BLUEPRINT.json"
    blueprint.write_text(
        json.dumps({"schema": 1, "implementation_family": "machine_learning"}),
        encoding="utf-8",
    )

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="design_only",
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    assert method["architecture_blueprint"]["implementation_status"] == "contract_mapped"
    assert not method["architecture_blueprint"]["completeness_issues"]


@pytest.mark.parametrize(
    ("implementation_family", "diagram_kind", "check_label", "distinction"),
    [
        (
            "formal_verification",
            "simulation_verified_formal_reasoning_architecture",
            "runtime implementation check",
            "proof obligations or claims",
        ),
        (
            "external_protocol",
            "simulation_verified_protocol_analysis_architecture",
            "runtime implementation check",
            "procedure, estimand, coding, or analysis internals",
        ),
        (
            "computational_general",
            "simulation_verified_computational_method_architecture",
            "runtime implementation check",
            "algorithm/numerical-method internals",
        ),
    ],
)
def test_non_ml_architecture_uses_domain_specific_contracts(
    tmp_path: Path,
    implementation_family: str,
    diagram_kind: str,
    check_label: str,
    distinction: str,
) -> None:
    _seed_project(tmp_path)
    (tmp_path / "experiments" / "IMPLEMENTATION_BLUEPRINT.json").write_text(
        json.dumps({"schema": 1, "implementation_family": implementation_family}),
        encoding="utf-8",
    )
    quality = tmp_path / ".merak" / "quality"
    quality.mkdir(parents=True)
    (quality / "training_check.json").write_text(
        json.dumps({"verdict": "FAIL", "blocking": True}),
        encoding="utf-8",
    )

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="synthetic_preview",
    )
    method = next(item for item in plan["assets"] if item["id"] == "method_architecture")
    blueprint = method["architecture_blueprint"]

    assert blueprint["diagram_kind"] == diagram_kind
    assert distinction in blueprint["required_distinctions"]
    assert not any(check_label in issue for issue in blueprint["completeness_issues"])
    serialized = json.dumps(blueprint).casefold()
    assert "runtime training check" not in serialized
    assert "backward" not in serialized
    assert "optimizer" not in serialized


def test_synthetic_preview_creates_quarantined_paper_completeness_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = WorkflowEngine()
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    asyncio.run(
        engine._ensure_figure_artifacts(
            run,
            "Artifact-grounded research agent",
            "Artifact-grounded research agent",
        )
    )

    asset_plan = json.loads(
        (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").read_text(encoding="utf-8")
    )
    _author_plan_figures(tmp_path, asset_plan)
    evidence = paper_artifact_builder.prepare(
        tmp_path,
        "Artifact-grounded research agent",
    )
    main_path = paper_artifact_builder.write_fallback(evidence)
    main = main_path.read_text(encoding="utf-8")
    test_profile = paper_profile_service.build(
        evidence_mode="synthetic_preview",
        submission_eligible=True,
        research_family="machine_learning",
        study_archetype="algorithm_benchmark",
    )
    # This regression isolates the preview-role boundary. Other tests enforce
    # full ICLR word and bibliography budgets.
    test_profile["main_text_words"] = [800, 5500]
    test_profile["minimum_unique_bibliography_entries"] = 5
    test_profile["minimum_unique_citations"] = 5
    (tmp_path / "paper" / "PAPER_PROFILE.json").write_text(
        json.dumps(test_profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(encoding="utf-8")
    )

    assert asset_plan["evidence_mode"] == "synthetic_preview"
    assert asset_plan["requested_evidence_mode"] == "synthetic_preview"
    assert asset_plan["quantitative_figure_policy"] == "complete_benchmark"
    assert asset_plan["submission_eligible"] is True
    planned_quantitative = [
        item for item in asset_plan["assets"]
        if item.get("evidence_status") == "synthetic_preview"
    ]
    expected_selected = {"synthetic_preview_main_comparison", "synthetic_preview_robustness",
                         "synthetic_preview_efficiency", "synthetic_preview_training_dynamics"}
    assert {item["id"] for item in planned_quantitative} == expected_selected
    simulation = json.loads((tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json").read_text(encoding="utf-8"))
    assert len(simulation["figure_files"]) == 7
    assert all(
        item.get("generation_phase") == "phase_2a"
        and item.get("generation_policy") == "reuse"
        and item.get("recommended_backend") == "matplotlib"
        and item.get("recommended_skill") == "paper-figure"
        and item.get("canonical_asset") is True
        for item in planned_quantitative
    )
    figure_prompt = engine._input_figure(
        "Artifact-grounded research agent",
        {},
        run,
    )
    assert "current contracts" in figure_prompt
    assert "runtime-owned FIGURE_SPECS.json is schema 4" in figure_prompt
    assert "Do not open editor tabs" in figure_prompt
    assert main.count(SIMULATION_END_DISCLOSURE) == 1
    assert main.index(SIMULATION_END_DISCLOSURE) > main.index(r"\section{Conclusion}")
    assert "SYNTHETIC PREVIEW -- NOT FOR SUBMISSION" not in main
    assert "NOT EXPERIMENTAL" not in main
    assert "draftwatermark" not in main
    assert "SetWatermark" not in main
    assert "\\input{synthetic_preview_figures}" in main
    assert "\\input{tables/synthetic_preview_results}" in main
    preview_entries = [
        item for item in manifest["figures"]
        if (item.get("metadata") or {}).get("evidence_status")
        == "synthetic_preview"
    ]
    assert len(preview_entries) == 7
    required_scientific_metadata = {
        "scientific_role",
        "scientific_question",
        "claim_ids",
        "source_data",
        "intended_comparison",
        "visual_encoding",
        "uncertainty_encoding",
        "style_profile",
        "provenance_kind",
    }
    assert all(
        all((item.get("metadata") or {}).get(field) for field in required_scientific_metadata)
        for item in preview_entries
    )
    assert all(
        (item.get("metadata") or {}).get("style_profile")
        == figure_engine_module.PUBLICATION_STYLE_PROFILE
        and (item.get("metadata") or {}).get("claim_ids") == ["C1"]
        for item in preview_entries
    )
    assert {item["id"] for item in preview_entries if (item.get("metadata") or {}).get("paper_selected")} == expected_selected
    assert all(item.get("output_path") for item in preview_entries)
    selected_quantitative = [
        item for item in manifest["figures"]
        if (item.get("metadata") or {}).get("paper_selected") is not False
        and (item.get("metadata") or {}).get("evidence_status")
        == "synthetic_preview"
    ]
    assert {item["id"] for item in selected_quantitative} == expected_selected
    paper_findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    assert not [
        item
        for item in paper_findings
        if item.get("id") in {
            "PAPER-CLAIM-001",
            "PAPER-SIM-001",
            "PAPER-SIM-002",
            "PAPER-SIM-003",
        }
    ]
    gate = engine._paper_acceptance_gate(str(tmp_path))
    assert gate["accepted"] is True, gate
    # The acceptance gate must reject a simulation package whose nested table
    # binding is stale, even when the manifest itself remains valid JSON.
    simulation_manifest_path = (
        tmp_path / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json"
    )
    simulation_manifest = json.loads(simulation_manifest_path.read_text(encoding="utf-8-sig"))
    correct_paper_table_sha256 = simulation_manifest["paper_table_sha256"]
    simulation_manifest["paper_table_sha256"] = "0" * 64
    simulation_manifest_path.write_text(
        json.dumps(simulation_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    stale_binding_gate = engine._paper_acceptance_gate(str(tmp_path))
    assert stale_binding_gate["accepted"] is False
    assert any(
        "paper_table_sha256" in issue
        for issue in stale_binding_gate["details"]["issues"]
    )
    simulation_manifest["paper_table_sha256"] = correct_paper_table_sha256
    simulation_manifest_path.write_text(
        json.dumps(simulation_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert {
        "main_comparison",
        "robustness_or_error_analysis",
        "calibration_or_efficiency",
    }.issubset(set(gate["details"]["figure_roles"]))
    assert set(gate["details"]["structural_preview_figures"]) == expected_selected

    for watermark_command in (
        r"\usepackage{draftwatermark}",
        r"\usepackage[printwatermark]{xwatermark}",
        r"\SetWatermarkText{DRAFT}",
    ):
        main_path.write_text(
            main.replace(
                "\\begin{document}",
                watermark_command + "\n\\begin{document}",
                1,
            ),
            encoding="utf-8",
        )
        watermark_gate = engine._paper_acceptance_gate(str(tmp_path))
        assert watermark_gate["accepted"] is False
        assert any(
            "watermark or draft-stamp" in issue
            for issue in watermark_gate["details"]["issues"]
        )

    main_path.write_text(main, encoding="utf-8")
    assert evidence.metrics == []
    start_issues = validate_submission_start(
        ["lit", "idea", "novelty", "exp-design", "exp-run", "results",
         "narrative", "figure", "paper", "review", "audit", "compile"],
        "submission",
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    assert start_issues == []
    compiled = asyncio.run(
        paper_compiler.compile(str(tmp_path / "paper"), "main.tex")
    )
    assert compiled.success is True, compiled.log_output

    # A preview entry cannot satisfy structure by metadata alone. Its simulation
    # manifest digest must remain intact and bound to the referenced output.
    manifest_path = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    tampered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    main_preview = next(
        item for item in tampered_manifest["figures"]
        if item.get("id") == "synthetic_preview_main_comparison"
    )
    main_preview["metadata"]["simulation_manifest_sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(tampered_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tampered_gate = engine._paper_acceptance_gate(str(tmp_path))
    assert tampered_gate["accepted"] is False
    assert any(
        "main_comparison" in issue
        for issue in tampered_gate["details"]["issues"]
    )


def test_project_directory_name_does_not_change_result_role(tmp_path: Path) -> None:
    root = tmp_path / "no_component_project"
    _seed_project(root)
    metrics = root / "experiments" / "results" / "main_comparison.csv"
    with metrics.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["status", "method", "seed", "split", "metric", "value"],
        )
        writer.writeheader()
        for method in ("Reference", "Proposed"):
            for seed, value in ((1, 0.70), (2, 0.72), (3, 0.71)):
                writer.writerow({
                    "status": "completed",
                    "method": method,
                    "seed": seed,
                    "split": "test",
                    "metric": "accuracy",
                    "value": value,
                })
    now = time.time()
    execution_provenance_service.record(
        root,
        "path-role-regression",
        "Bash",
        {"command": "python experiments/src/train.py"},
        True,
        now - 1,
        now,
        "[exit code: 0]",
    )

    records = scientific_asset_service.collect_records(root)

    assert len(records) == 6
    assert {item.role for item in records} == {"result"}
