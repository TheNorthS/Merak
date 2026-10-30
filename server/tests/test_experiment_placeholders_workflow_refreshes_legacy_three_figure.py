from __future__ import annotations

from server.tests._experiment_placeholders_support import (
    Path as Path,
    SIMULATION_MANIFEST_SCHEMA as SIMULATION_MANIFEST_SCHEMA,
    SIMULATION_PLOT_FAMILIES as SIMULATION_PLOT_FAMILIES,
    SIMULATION_RENDERER_VERSION as SIMULATION_RENDERER_VERSION,
    WorkflowEngine as WorkflowEngine,
    WorkflowRun as WorkflowRun,
    asyncio as asyncio,
    csv as csv,
    experiment_placeholder_service as experiment_placeholder_service,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    pytest as pytest,
    re as re,
    scientific_asset_service as scientific_asset_service,
)
from server.tests._planned_publication_fixture import author_publication_fixture, render_finite_fixture


@pytest.fixture(autouse=True)
def _finite_render_boundary(monkeypatch):
    """Qualification/pixel tests live separately; this file owns metadata contracts."""
    monkeypatch.setattr(experiment_placeholder_service, "_render", render_finite_fixture)


def test_revalidation_rejects_legacy_three_figure_bundle_without_migration(
    tmp_path: Path,
) -> None:
    author_publication_fixture(tmp_path, method_name="Attention benchmark method",
                               comparators=["Reference condition", "Attention benchmark method"])
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Deep model with attention and robustness evaluation",
            evidence_mode="synthetic_preview",
            target_venue="ICLR",
            research_family="machine_learning",
            study_archetype="algorithm_benchmark",
        )
    )
    simulated_figures = tmp_path / "figures" / "simulated"
    for stem in (
        "simulated_ablation",
        "simulated_training_dynamics",
        "simulated_error_analysis",
        "simulated_efficiency",
    ):
        for suffix in (".py", ".pdf", ".svg", ".png"):
            (simulated_figures / f"{stem}{suffix}").unlink()
    simulated_data = tmp_path / "experiments" / "results" / "simulated"
    for name in ("training_dynamics.csv", "error_analysis.csv"):
        (simulated_data / name).unlink()
    simulation_manifest_path = simulated_data / "SIMULATION_MANIFEST.json"
    legacy_manifest = json.loads(
        simulation_manifest_path.read_text(encoding="utf-8")
    )
    legacy_manifest["schema"] = 1
    legacy_manifest.pop("completeness_pack", None)
    simulation_manifest_path.write_text(
        json.dumps(legacy_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
            "target_venue": "ICLR",
            "research_family": "machine_learning",
            "study_archetype": "algorithm_benchmark",
        },
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="current bundle schema"):
        asyncio.run(WorkflowEngine()._ensure_planned_result_templates(
            run, "Deep model with attention and robustness evaluation"))
    assert all(path.read_bytes() == content for path, content in before.items())
    assert json.loads(simulation_manifest_path.read_text(encoding="utf-8"))["schema"] == 1




def test_planned_result_wrapper_is_idempotent_for_unchanged_inputs(
    tmp_path: Path,
) -> None:
    author_publication_fixture(tmp_path, method_name="Attention benchmark method",
                               comparators=["Reference condition", "Attention benchmark method"])
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
            "target_venue": "ICLR",
            "research_family": "machine_learning",
            "study_archetype": "algorithm_benchmark",
        },
    )
    engine = WorkflowEngine()
    direction = "Deep model with attention and robustness evaluation"
    asyncio.run(engine._ensure_planned_result_templates(run, direction))

    planned = (
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json"
    )
    simulated = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (planned, simulated)
    }

    asyncio.run(engine._ensure_planned_result_templates(run, direction))

    for path, (content, modified_ns) in before.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == modified_ns


def test_switching_back_to_design_only_removes_managed_simulation_assets(
    tmp_path: Path,
) -> None:
    author_publication_fixture(tmp_path, method_name="Declared cleanup method",
                               comparators=["Reference condition", "Declared cleanup method"])
    synthetic = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Simulation cleanup regression",
            evidence_mode="synthetic_preview",
        )
    )
    simulation_manifest = tmp_path / synthetic["simulation_manifest"]
    simulation = json.loads(simulation_manifest.read_text(encoding="utf-8"))
    managed_paths = {
        simulation_manifest,
        tmp_path / "experiments" / "results" / "simulated" / "README.md",
        tmp_path / synthetic["synthetic_preview_table"],
        tmp_path / synthetic["synthetic_preview_figures"],
    }
    for item in simulation["data_files"]:
        managed_paths.add(tmp_path / item["path"])
    for item in simulation["figure_files"]:
        managed_paths.add(tmp_path / item["source"])
        managed_paths.update(tmp_path / path for path in item["outputs"].values())
    assert managed_paths and all(path.is_file() for path in managed_paths)

    manual_note = (
        tmp_path / "experiments" / "results" / "simulated" / "manual-note.txt"
    )
    manual_note.write_text("user-owned note", encoding="utf-8")

    design_only = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Simulation cleanup regression",
            evidence_mode="design_only",
        )
    )

    assert design_only["evidence_mode"] == "design_only"
    assert design_only["status"] == "planned_not_executed"
    remaining = sorted(str(path) for path in managed_paths if path.exists())
    assert not remaining, "\n".join(remaining)
    assert manual_note.read_text(encoding="utf-8") == "user-owned note"
    figure_manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert not any(
        (item.get("metadata") or {}).get("evidence_status")
        == "synthetic_preview"
        or "/simulated/" in str(item.get("output_path") or "")
        or "/simulated/" in str(item.get("source_path") or "")
        for item in figure_manifest["figures"]
    )


def test_synthetic_preview_csvs_keep_runtime_metrics_isolated_but_publish_figures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    author_publication_fixture(tmp_path, method_name="Metric isolation method",
                               comparators=["Reference condition", "Metric isolation method"])
    result = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Metric isolation regression",
            evidence_mode="synthetic_preview",
        )
    )
    simulation_manifest = tmp_path / result["simulation_manifest"]
    simulation = json.loads(simulation_manifest.read_text(encoding="utf-8"))
    simulated_sources = {item["path"] for item in simulation["data_files"]}

    # Exercise the runtime-metric boundary even under an accidentally
    # over-broad provenance set. The deterministic benchmark keeps its own
    # sidecar provenance while the complete seven-role evidence remains available;
    # only the authored objective-mechanism portfolio enters the manuscript.
    monkeypatch.setattr(
        scientific_asset_service,
        "_proven_sources",
        lambda _root: simulated_sources,
    )

    assert scientific_asset_service.collect_records(tmp_path) == []
    evidence = paper_artifact_builder.snapshot(tmp_path)
    assert evidence.metrics == []
    assert len(simulation["figure_files"]) == 7
    assert {item["id"] for item in evidence.figures} == {
        "synthetic_preview_main_comparison", "synthetic_preview_ablation",
        "synthetic_preview_robustness", "synthetic_preview_calibration",
    }
    assert all(
        (item.get("metadata") or {}).get("provenance_kind")
        == "deterministic_simulation_preview"
        for item in evidence.figures
    )


def test_placeholder_renderer_does_not_require_async_subprocess_support(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script = tmp_path / "figures" / "placeholders" / "render.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('rendered')\n", encoding="utf-8")

    async def unsupported(*_args, **_kwargs):
        raise NotImplementedError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unsupported)

    success, error = asyncio.run(experiment_placeholder_service._render(script))

    assert success is True
    assert error == ""


def test_clinical_simulation_keeps_domain_controls_and_disclosure(
    tmp_path: Path,
) -> None:
    author_publication_fixture(tmp_path, method_name="Prespecified prognostic model",
        comparators=["Clinical reference", "Conventional model", "Prespecified prognostic model"],
        contribution_type="clinical_biological_mechanism")
    result = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "External validation of a clinical prognostic model",
            evidence_mode="synthetic_preview",
            target_venue="JAMA",
            research_family="clinical_biomedical",
            study_archetype="diagnostic_prognostic",
        )
    )

    assert result["publication_style"]["family"] == "clinical_biomedical"
    assert result["publication_style"]["study_archetype"] == "diagnostic_prognostic"
    assert result["methods"] == [
        "Clinical reference", "Conventional model", "Prespecified prognostic model",
    ]
    assert result["status"] == "synthetic_preview"
    assert len(result["figures"]) == 7
    assert (
        tmp_path / "paper" / "tables" / "synthetic_preview_results.tex"
    ).is_file()
    table = (
        tmp_path / "paper" / "tables" / "planned_result_templates.tex"
    ).read_text(encoding="utf-8")
    assert "predictor, calibration, and validation sensitivity" in table
    with (
        tmp_path / "experiments" / "results" / "templates" / "efficiency.csv"
    ).open("r", encoding="utf-8-sig", newline="") as handle:
        resource_rows = list(csv.DictReader(handle))
    assert resource_rows
    assert resource_rows[0]["resource_1_label"] == "Development N"
    assert resource_rows[0]["resource_2_label"] == "External N"
    assert "GPU-hours" not in set(resource_rows[0].values())
    assert not any(
        column.startswith("demo_")
        for column in resource_rows[0]
    )
    with (
        tmp_path / "experiments" / "results" / "simulated" / "efficiency.csv"
    ).open("r", encoding="utf-8-sig", newline="") as handle:
        simulated_resources = list(csv.DictReader(handle))
    assert simulated_resources[0]["resource_1_label"] == "Development N"
    assert simulated_resources[0]["resource_1"]
    assert simulated_resources[0]["status"] == "synthetic_preview"


@pytest.mark.parametrize(
    (
        "research_family",
        "study_archetype",
        "expected_domain",
        "expected_roles",
        "progression_kind",
        "progression_axis",
        "case_kind",
        "case_axis",
    ),
    [
        (
            "clinical_biomedical",
            "diagnostic_prognostic",
            "clinical",
            {
                "clinical_effect_comparison",
                "specification_sensitivity",
                "validation_trajectory",
                "population_robustness",
                "subgroup_analysis",
                "clinical_utility",
                "feasibility_burden",
            },
            "validation_trajectory",
            "validation_fraction",
            "subgroup_analysis",
            "subgroup",
        ),
        (
            "theoretical_formal",
            "formal_theory",
            "formal",
            {
                "theorem_guarantee_comparison",
                "assumption_necessity",
                "proof_progression",
                "assumption_relaxation",
                "counterexample_analysis",
                "guarantee_coverage",
                "proof_complexity",
            },
            "proof_progression",
            "proof_stage",
            "counterexample_analysis",
            "counterexample_regime",
        ),
        (
            "qualitative_humanities",
            "qualitative_mixed",
            "qualitative",
            {
                "theme_comparison",
                "triangulation_sensitivity",
                "saturation_progression",
                "negative_case_robustness",
                "divergent_case_analysis",
                "source_coverage",
                "auditability_burden",
            },
            "saturation_progression",
            "cases_reviewed",
            "divergent_case_analysis",
            "divergent_case",
        ),
    ],
)
def test_non_algorithmic_simulation_assets_are_domain_adapted(
    tmp_path: Path,
    monkeypatch,
    research_family: str,
    study_archetype: str,
    expected_domain: str,
    expected_roles: set[str],
    progression_kind: str,
    progression_axis: str,
    case_kind: str,
    case_axis: str,
) -> None:
    async def render_without_matplotlib(script: Path) -> tuple[bool, str]:
        script.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% domain test\n")
        script.with_suffix(".svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            encoding="utf-8",
        )
        script.with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return True, ""

    monkeypatch.setattr(
        experiment_placeholder_service,
        "_render",
        render_without_matplotlib,
    )
    author_publication_fixture(tmp_path, method_name="Declared primary analysis", comparators=["Declared reference analysis", "Declared primary analysis"], contribution_type={"clinical": "clinical_biological_mechanism", "formal": "theory_proof", "qualitative": "qualitative_framework"}[expected_domain])

    result = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            f"{expected_domain} domain simulation benchmark",
            evidence_mode="synthetic_preview",
            research_family=research_family,
            study_archetype=study_archetype,
        )
    )
    manifest_path = tmp_path / result["simulation_manifest"]
    simulation = json.loads(manifest_path.read_text(encoding="utf-8"))

    stable_roles = [
        "main_comparison",
        "component_ablation",
        "training_dynamics",
        "robustness_sensitivity",
        "error_analysis",
        "calibration_risk_coverage",
        "efficiency_tradeoff",
    ]
    stable_ids = {
        "synthetic_preview_main_comparison",
        "synthetic_preview_ablation",
        "synthetic_preview_training_dynamics",
        "synthetic_preview_robustness",
        "synthetic_preview_error_analysis",
        "synthetic_preview_calibration",
        "synthetic_preview_efficiency",
    }
    assert simulation["completeness_pack"] == stable_roles
    assert simulation["asset_domain"] == expected_domain
    assert {item["domain_role"] for item in simulation["asset_roles"]} == expected_roles
    assert len(simulation["domain_asset_profile"]) == 7
    assert {
        item["domain_role"] for item in simulation["domain_asset_profile"]
    } == expected_roles
    assert simulation["progression_kind"] == progression_kind
    assert simulation["progression_axis"] == progression_axis
    assert simulation["error_slice_kind"] == case_kind
    assert simulation["case_analysis_axis"] == case_axis
    assert {item["id"] for item in simulation["figure_files"]} == stable_ids

    progression_csv = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "training_dynamics.csv"
    )
    case_csv = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "error_analysis.csv"
    )
    with progression_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        progression_rows = list(csv.DictReader(handle))
    with case_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        case_rows = list(csv.DictReader(handle))
    assert progression_rows and progression_axis in progression_rows[0]
    assert "epoch" not in progression_rows[0]
    assert "training_loss" not in progression_rows[0]
    assert case_rows and case_axis in case_rows[0]
    assert "error_slice" not in case_rows[0]

    figure_by_id = {
        item["id"]: item for item in simulation["figure_files"]
    }
    for profile in simulation["domain_asset_profile"]:
        figure = figure_by_id[profile["semantic_id"]]
        assert figure["domain_asset_role"] == profile["domain_role"]
        assert figure["analysis_subtype"] == profile["analysis_subtype"]
        assert figure["axis_field"] == profile["axis_field"]
        assert figure["label"].startswith("fig:preview-")
        assert set(figure["outputs"]) == {"pdf", "svg", "png"}
        assert all(
            (tmp_path / relative_path).is_file()
            for relative_path in figure["outputs"].values()
        )

    rendered_tex = (
        tmp_path / "paper" / "synthetic_preview_figures.tex"
    ).read_text(encoding="utf-8")
    assert "Training dynamics" not in rendered_tex
    assert "Error-slice analysis" not in rendered_tex
    table_tex = (
        tmp_path / "paper" / "tables" / "synthetic_preview_results.tex"
    ).read_text(encoding="utf-8")
    for malformed_caption in (
        "intervals. across",
        "intervals. with",
        "intervals. over",
        "intervals. for",
    ):
        assert malformed_caption not in table_tex.casefold()
    assert set(re.findall(r"\\label\{([^}]+)\}", table_tex)) == {
        "clinical": {"tab:preview-main-results", "tab:preview-error-analysis", "tab:preview-calibration", "tab:preview-robustness-calibration"},
        "formal": {"tab:preview-main-results", "tab:preview-ablation", "tab:preview-robustness-calibration"},
        "qualitative": {"tab:preview-main-results", "tab:preview-error-analysis", "tab:preview-calibration"},
    }[expected_domain]
    for script_name in (
        "simulated_error_analysis.py",
        "simulated_calibration.py",
    ):
        source = (
            tmp_path / "figures" / "simulated" / script_name
        ).read_text(encoding="utf-8")
        assert "lower is better" in source.casefold()


def test_schema_upgrade_removes_legacy_demo_columns_and_preserves_real_values(
    tmp_path: Path,
) -> None:
    author_publication_fixture(tmp_path, method_name="Declared template method", comparators=["Reference condition", "Declared template method"])

    first = asyncio.run(experiment_placeholder_service.ensure(tmp_path, "migration"))
    assert first["schema"] == 5
    data_path = (
        tmp_path / "experiments" / "results" / "templates" / "main_comparison.csv"
    )
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["value"] = "0.812"
    rows[0]["ci_low"] = "0.790"
    rows[0]["ci_high"] = "0.834"
    rows[0]["source_run_id"] = "run-verified"
    fieldnames = [*rows[0], "demo_value", "demo_ci_low", "demo_ci_high"]
    for row in rows:
        row["demo_value"] = "0.999"
        row["demo_ci_low"] = "0.998"
        row["demo_ci_high"] = "1.000"
    with data_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    second = asyncio.run(experiment_placeholder_service.ensure(tmp_path, "migration"))

    assert second["schema"] == 5
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        refreshed = list(csv.DictReader(handle))
    assert refreshed[0]["value"] == "0.812"
    assert refreshed[0]["ci_low"] == "0.790"
    assert refreshed[0]["ci_high"] == "0.834"
    assert refreshed[0]["source_run_id"] == "run-verified"
    assert not any(column.startswith("demo_") for column in refreshed[0])


def test_eeg_simulation_preserves_registered_ablation_and_stress_semantics(
    tmp_path: Path,
) -> None:
    """Domain-specific rendering must not replace the project's experiment contract."""
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Acquisition-invariant EEG representation learning",
            "claims": [{"id": "C1", "statement": "Registered controls differ."}],
            "mechanisms": [
                {"id": "M1", "name": "Paired acquisition consistency"},
                {"id": "M2", "name": "Acquisition representation"},
                {"id": "M3", "name": "State nuisance suppression"},
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        """experiment:
  primary_metric: balanced_accuracy
evaluation:
  stress_tests:
    - id: missing_channel
      missing_ratios: [0.1, 0.3, 0.5]
""",
        encoding="utf-8",
    )

    author_publication_fixture(tmp_path, method_name="Acquisition-invariant method", comparators=["Acquisition reference", "Acquisition-invariant method"])

    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "EEG acquisition invariance under missing channels",
            evidence_mode="synthetic_preview",
        )
    )

    simulated = tmp_path / "experiments" / "results" / "simulated"
    with (simulated / "ablation.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        ablations = list(csv.DictReader(handle))
    settings = [row["component_setting"] for row in ablations]
    assert settings == [
        "Acquisition-invariant method",
        "Without Paired acquisition consistency",
        "Without Acquisition representation",
        "Without State nuisance suppression",
    ]
    assert not any(
        token in " ".join(settings).casefold()
        for token in ("time-domain", "frequency-domain", "spatial attention")
    )

    with (simulated / "robustness.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        robustness = list(csv.DictReader(handle))
    assert robustness
    assert "missing_channel_rate" in robustness[0]
    assert "shift_axis" not in robustness[0]
    robustness_script = (
        tmp_path / "figures" / "simulated" / "simulated_robustness.py"
    ).read_text(encoding="utf-8")
    assert "missing_channel_rate" in robustness_script
    assert "Cross-device and cross-session transfer" not in robustness_script


def test_synthetic_publication_assets_translate_cjk_only_mechanism_labels(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps(
            {
                "title": "Auditable ranking study",
                "claims": [{"id": "C1", "statement": "Rankings can differ."}],
                "mechanisms": [
                    {"id": "M1", "name": "预注册多轴排序估计"},
                    {"id": "M2", "name": "运行级证据账本"},
                    {"id": "M3", "name": "协议替代解释消融"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        "experiment:\n  primary_metric: accuracy\n",
        encoding="utf-8",
    )
    templates = tmp_path / "experiments" / "results" / "templates"
    templates.mkdir(parents=True)
    (templates / "ablation.csv").write_text(
        "row_id,status,component_setting,value,ci_low,ci_high\n"
        "ablation-1,planned,Full system,0.812,0.790,0.834\n"
        "ablation-2,planned,Without 预注册多轴排序估计,0.790,0.770,0.810\n",
        encoding="utf-8-sig",
    )

    author_publication_fixture(tmp_path, method_name="Auditable ranking method", comparators=["Ranking reference", "Auditable ranking method"], public_mechanisms=["Prespecified multi-axis ranking", "Run-level evidence ledger", "Single-factor protocol ablation"], contribution_type="system_architecture")

    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Auditable ranking under distribution shift",
            evidence_mode="synthetic_preview",
            target_venue="ICLR",
            research_family="machine_learning",
            study_archetype="systems_testbed",
        )
    )

    ablation_csv = (
        tmp_path / "experiments" / "results" / "simulated" / "ablation.csv"
    ).read_text(encoding="utf-8-sig")
    preview_tex = (
        tmp_path / "paper" / "tables" / "synthetic_preview_results.tex"
    ).read_text(encoding="utf-8")
    ablation_script = (
        tmp_path / "figures" / "simulated" / "simulated_ablation.py"
    ).read_text(encoding="utf-8")
    planned_ablation = (templates / "ablation.csv").read_text(
        encoding="utf-8-sig"
    )

    assert "Without Prespecified multi-axis ranking" in ablation_csv
    assert "Without Run-level evidence ledger" in ablation_csv
    assert "Without Single-factor protocol ablation" in ablation_csv
    assert r"\label{tab:preview-ablation}" not in preview_tex
    assert "Without Prespecified multi-axis ranking" in planned_ablation
    assert "0.790" in planned_ablation
    assert not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", preview_tex)
    assert not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", ablation_script)


def test_planned_tables_follow_structured_ablation_and_claim_contracts(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "ideas.md").write_text("# Raw notes\nFrequency keyword noise.", encoding="utf-8")
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Contract-driven method",
            "problem_statement": "A controlled research problem.",
            "hypothesis": "The declared mechanism changes a measured outcome.",
            "claims": [
                {"id": "C1", "statement": "Safe and naive protocols differ."},
                {"id": "C2", "statement": "Consistency improves stability."},
            ],
            "mechanisms": [
                {"id": "M1", "name": "Coordinate conditioning", "description": "Use metadata."},
                {"id": "M2", "name": "View consistency", "description": "Align paired views."},
            ],
            "falsification_conditions": ["Reject C1 if estimates match.", "Reject C2 if controls match."],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        """experiment:
  primary_metric: macro_f1
  baselines:
    - id: coordinate_only
    - id: fixed_encoder
  ablations:
    - id: no_consistency
    - id: no_coordinates
evaluation:
  stress_tests:
    - id: missing_channel
      missing_ratios: [0.1, 0.5]
""",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text("# Plan\nPending.", encoding="utf-8")
    (tmp_path / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps({
            "claim_evidence_plan": [
                {"idea_claim_id": "C1", "outcomes": ["Safe-versus-naive estimate shift"], "failure_conditions": ["Estimates match"]},
                {"idea_claim_id": "C2", "outcomes": ["Full-versus-reduced view stability"], "failure_conditions": ["Controls match"]},
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "RUN_SPEC.json").write_text("{}", encoding="utf-8")
    (tmp_path / "experiments" / "results").mkdir()
    (tmp_path / "experiments" / "results" / "analysis.md").write_text("Not run; pending.", encoding="utf-8")

    author_publication_fixture(tmp_path, method_name="Contract-driven method", comparators=["Coordinate Only", "Fixed Encoder", "Contract-driven method"], public_evaluations=["Safe-versus-naive estimate shift", "Full-versus-reduced view stability"])

    result = asyncio.run(experiment_placeholder_service.ensure(tmp_path, "contract test"))
    assert result["ablation_settings"] == ["Contract-driven method", "No Consistency", "No Coordinates"]
    assert result["methods"] == ["Coordinate Only", "Fixed Encoder", "Contract-driven method"]
    assert result["robustness_axis"] == "missing_channel_rate"
    planned = (tmp_path / "paper" / "tables" / "planned_result_templates.tex").read_text(encoding="utf-8")
    assert "Frequency" not in planned
    assert "No Consistency" in planned

    paper_artifact_builder.prepare(tmp_path, "contract test")
    component_rows = list(csv.DictReader(
        (tmp_path / "paper" / "tables" / "method_components.csv").open(
            "r", encoding="utf-8-sig", newline=""
        )
    ))
    assert component_rows[0]["component"] == "Coordinate conditioning"
    assert component_rows[0]["evaluation"] == "Safe-versus-naive estimate shift"
    assert component_rows[1]["component"] == "View consistency"
    assert component_rows[1]["evaluation"] == "Full-versus-reduced view stability"
