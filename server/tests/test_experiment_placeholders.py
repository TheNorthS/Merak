from __future__ import annotations

from server.tests._experiment_placeholders_support import (
    Path as Path,
    SIMULATION_MANIFEST_SCHEMA as SIMULATION_MANIFEST_SCHEMA,
    SIMULATION_PLOT_FAMILIES as SIMULATION_PLOT_FAMILIES,
    SIMULATION_RENDERER_VERSION as SIMULATION_RENDERER_VERSION,
    _paired_t_two_sided_p as _paired_t_two_sided_p,
    _publication_component_label as _publication_component_label,
    _publication_metric_label as _publication_metric_label,
    _publication_outcome_label as _publication_outcome_label,
    _sha256 as _sha256,
    asyncio as asyncio,
    csv as csv,
    experiment_placeholder_service as experiment_placeholder_service,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    pytest as pytest,
    re as re,
    simulation_manifest_contract_issues as simulation_manifest_contract_issues,
    subprocess as subprocess,
    sys as sys,
)
from server.tests._planned_publication_fixture import author_publication_fixture, render_finite_fixture


_OBJECTIVE_FIGURE_IDS = {
    "synthetic_preview_main_comparison", "synthetic_preview_ablation",
    "synthetic_preview_robustness", "synthetic_preview_calibration",
}


@pytest.fixture(autouse=True)
def _finite_render_boundary(monkeypatch):
    """These tests inspect source/data contracts, not generated pixels."""
    monkeypatch.setattr(experiment_placeholder_service, "_render", render_finite_fixture)


def test_paired_student_t_probability_is_detectable_with_five_replicates() -> None:
    assert _paired_t_two_sided_p([0.020, 0.021, 0.019, 0.022, 0.018]) < 0.05
    assert _paired_t_two_sided_p([0.0, 0.0, 0.0, 0.0, 0.0]) == 1.0


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "group-disjoint 数据集留出条件下的 balanced_accuracy 和置信区间",
            "Group-disjoint balanced accuracy",
        ),
        (
            "保持下游 endpoint 的 held-out linear identity_probe_accuracy 审计",
            "Held-out identity-probe accuracy",
        ),
        (
            "M2 spectral_mae、topology_mse 与 group-disjoint endpoint 一致性",
            "Spectral and topology reconstruction errors",
        ),
        (
            "channel_subset、contiguous_region 与 montage_degradation_slope",
            "Subject-level accuracy under channel removal",
        ),
    ],
)
def test_publication_outcome_label_maps_cjk_contracts_to_compilable_science(
    source: str,
    expected: str,
) -> None:
    rendered = _publication_outcome_label(source)

    assert expected in rendered
    assert not re.search(r"[\u3400-\u9fff]", rendered)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("记录身份捷径抑制一致性", "Record-identity consistency objective"),
        ("频谱—拓扑结构掩码预测", "Spectral-topological masked prediction"),
        ("严格域外与导联压力测试", "Held-out montage stress evaluation"),
        ("计算匹配因果消融", "Compute-matched causal ablation"),
    ],
)
def test_publication_component_label_preserves_cjk_mechanism_semantics(
    source: str,
    expected: str,
) -> None:
    assert _publication_component_label(source, 1) == expected


def test_publication_metric_label_hides_machine_field_syntax() -> None:
    assert _publication_metric_label("balanced_accuracy") == "Balanced accuracy"
    assert _publication_metric_label("identity_probe_accuracy") == (
        "Identity-probe accuracy"
    )


def test_skipped_experiment_creates_honest_replaceable_templates(tmp_path: Path) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "ideas.md").write_text(
        "# Channel-set invariant EEG model\nUse a montage adapter and frequency conditioner.",
        encoding="utf-8",
    )
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        "# Plan\nCompare a reference baseline, matched-capacity baseline, and proposed method.",
        encoding="utf-8",
    )
    author_publication_fixture(tmp_path, method_name="Channel-set invariant method",
                               comparators=["Reference decoding method", "Channel-set invariant method"])

    result = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Robust EEG decoding under missing channels",
        )
    )

    manifest_path = Path(result["manifest_path"])
    assert manifest_path.is_file()
    plan = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert plan["status"] == "planned_not_executed"
    assert plan["robustness_axis"] == "missing_channel_rate"
    assert "Channel/montage adapter" in plan["components"]

    data_path = tmp_path / "experiments" / "results" / "templates" / "main_comparison.csv"
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["value"] == "" for row in rows)
    assert all(row["ci_low"] == "" and row["ci_high"] == "" for row in rows)
    assert not any(
        column.startswith("demo_")
        for column in rows[0]
    )

    # Match the original paper-writing workflow: without executed metrics,
    # /paper-figure is skipped.  Keep schemas and source templates, but do not
    # render synthetic quantitative artifacts or register them as figures.
    assert plan["figures"] == []
    assert not (tmp_path / "figures" / "FIGURE_MANIFEST.json").exists()
    assert not any(
        (tmp_path / "figures" / "previews").glob("*.pdf")
    )
    assert not any(
        (tmp_path / "figures" / "previews").glob("*.png")
    )

    table_source = tmp_path / "paper" / "tables" / "planned_result_templates.tex"
    assert table_source.is_file()
    table_text = table_source.read_text(encoding="utf-8")
    assert "Registered primary-analysis design" in table_text
    assert "not experimental evidence" not in table_text.casefold()

    evidence = paper_artifact_builder.snapshot(tmp_path)
    assert evidence.metrics == []
    assert evidence.figures == []


def test_explicit_synthetic_preview_renders_disclosed_isolated_simulation(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "title": "Foundation model benchmark",
            "claims": [
                {
                    "id": "C1",
                    "statement": "The method improves the primary outcome.",
                    "measurable_endpoints": ["held-out macro F1"],
                },
                {
                    "id": "C2",
                    "statement": "The components improve robustness.",
                    "measurable_endpoints": ["stress-test degradation"],
                },
            ],
            "mechanisms": [
                {"name": f"Mechanism {index}"}
                for index in range(1, 6)
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        """model:
  baselines: [task_baseline, published_method, matched_control]
experiment:
  primary_metric: macro_f1
evaluation:
  metrics: [macro_f1, balanced_accuracy, ece]
""",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "RUN_SPEC.json").write_text(
        json.dumps({"seeds": [13, 42, 73, 101, 202]}),
        encoding="utf-8",
    )

    preexisting_dir = tmp_path / "figures" / "previews"
    author_publication_fixture(tmp_path, method_name="Foundation benchmark method",
        comparators=["Task reference", "Published comparison", "Matched control", "Foundation benchmark method"],
        public_mechanisms=["Signal representation", "Context prediction", "Feature matching", "Structured masking", "Task readout"])
    preexisting_dir.mkdir(parents=True)
    for suffix in (".pdf", ".svg", ".png"):
        (preexisting_dir / f"main_comparison_preview{suffix}").write_bytes(b"user-owned")

    result = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Deep learning foundation model",
            evidence_mode="synthetic_preview",
            target_venue="ICLR",
        )
    )

    assert result["schema"] == 5
    assert result["status"] == "synthetic_preview"
    assert result["evidence_mode"] == "synthetic_preview"
    assert result["submission_eligible"] is False
    assert result["manuscript_eligible"] is True
    assert len(result["figures"]) == 7
    assert all(
        (item.get("metadata") or {}).get("evidence_status")
        == "synthetic_preview"
        for item in result["figures"]
    )
    assert {item["id"] for item in result["figures"] if item["metadata"]["paper_selected"]} == _OBJECTIVE_FIGURE_IDS
    assert result["publication_style"]["family"] == "machine_learning"
    for suffix in (".pdf", ".svg", ".png"):
        assert (preexisting_dir / f"main_comparison_preview{suffix}").read_bytes() == b"user-owned"
    script = (
        tmp_path / "figures" / "previews" / "main_comparison_preview.py"
    ).read_text(encoding="utf-8")
    assert "font.family" in script and "sans-serif" in script
    assert "svg.fonttype" in script
    assert ".grid(" not in script
    assert "demo_" not in script
    assert "raise SystemExit" in script
    for stem in (
        "main_comparison_preview",
        "robustness_curve_preview",
        "calibration_risk_coverage_preview",
    ):
        source = tmp_path / "figures" / "previews" / f"{stem}.py"
        assert "demo_" not in source.read_text(encoding="utf-8")
        rendered = subprocess.run(
            [sys.executable, str(source)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rendered.returncode != 0
        assert "No figure rendered" in rendered.stderr
        for suffix in (".pdf", ".svg", ".png"):
            output = tmp_path / "figures" / "previews" / f"{stem}{suffix}"
            if stem == "main_comparison_preview":
                assert output.read_bytes() == b"user-owned"
            else:
                assert not output.is_file()
    for stem in (
        "simulated_main_comparison",
        "simulated_ablation",
        "simulated_training_dynamics",
        "simulated_robustness",
        "simulated_error_analysis",
        "simulated_calibration",
        "simulated_efficiency",
    ):
        for suffix in (".py", ".pdf", ".svg", ".png"):
            assert (
                tmp_path / "figures" / "simulated" / f"{stem}{suffix}"
            ).is_file()
    preview_table = (
        tmp_path / "paper" / "tables" / "synthetic_preview_results.tex"
    )
    preview_figures = tmp_path / "paper" / "synthetic_preview_figures.tex"
    assert preview_table.is_file()
    assert preview_figures.is_file()
    preview_table_text = preview_table.read_text(encoding="utf-8")
    preview_figure_text = preview_figures.read_text(encoding="utf-8")
    assert "NOT EXPERIMENTAL EVIDENCE" not in preview_table_text
    assert "Primary comparison with 95\\% scenario intervals" in preview_table_text
    assert "\\toprule" in preview_table_text
    assert "\\textbf{" in preview_table_text
    assert "Contribution & Evidence role" not in preview_table_text
    assert r"\label{tab:claim-evidence}" not in preview_table_text
    assert not re.search(r"(?m)^C\d+\s*&", preview_table_text)
    for malformed_caption in (
        "intervals. across",
        "intervals. with",
        "intervals. over",
        "intervals. for",
    ):
        assert malformed_caption not in preview_table_text.casefold()
    for script_name in (
        "simulated_error_analysis.py",
        "simulated_calibration.py",
    ):
        source = (
            tmp_path / "figures" / "simulated" / script_name
        ).read_text(encoding="utf-8")
        assert "lower is better" in source.casefold()
    for label in (
        "tab:preview-main-results",
        "tab:preview-ablation",
        "tab:preview-robustness-calibration",
        "tab:preview-calibration",
    ):
        assert label in preview_table_text
    assert r"\label{tab:preview-efficiency}" not in preview_table_text
    assert r"\label{tab:preview-error-analysis}" not in preview_table_text
    assert "not experimental results" not in preview_figure_text.casefold()
    assert "Primary method comparison with 95\\% scenario intervals" in preview_figure_text
    included_stems = {
        "simulated_main_comparison",
        "simulated_ablation",
        "simulated_robustness",
        "simulated_calibration",
    }
    for stem in included_stems:
        assert stem in preview_figure_text
    for stem in ("simulated_training_dynamics", "simulated_error_analysis", "simulated_efficiency"):
        assert stem not in preview_figure_text
    simulation_manifest = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    simulation = json.loads(simulation_manifest.read_text(encoding="utf-8"))
    assert simulation_manifest_contract_issues(simulation) == []
    assert simulation["schema"] == SIMULATION_MANIFEST_SCHEMA
    assert simulation["renderer_version"] == SIMULATION_RENDERER_VERSION
    assert simulation["explicit_user_mode"] == "synthetic_preview"
    assert simulation["paper_selected"] is True
    assert simulation["manuscript_eligible"] is True
    assert simulation["submission_eligible"] is False
    assert simulation["replicate_contract"]["seed_ids"] == [13, 42, 73, 101, 202]
    assert simulation["registered_pair_contract"]["complete"] is True
    assert simulation["evidence_package"]["provenance_join_contract"]["coverage"] == 1.0
    assert simulation["completeness_pack"] == [
        "main_comparison",
        "component_ablation",
        "training_dynamics",
        "robustness_sensitivity",
        "error_analysis",
        "calibration_risk_coverage",
        "efficiency_tradeoff",
    ]
    assert simulation["visual_quality"]["png_dpi"] >= 300
    assert simulation["visual_quality"]["vector_outputs"] == ["pdf", "svg"]
    assert simulation["visual_quality"]["in_figure_disclosure"] is False
    assert simulation["visual_quality"]["repeated_caption_disclosure"] is False
    assert simulation["visual_quality"]["methods_disclosure"] == ""
    assert "machine-readable sidecars" in simulation["scientific_policy"]
    simulated_readme = (
        tmp_path / "experiments" / "results" / "simulated" / "README.md"
    ).read_text(encoding="utf-8")
    template_readme = (
        tmp_path / "experiments" / "results" / "templates" / "README.md"
    ).read_text(encoding="utf-8")
    assert "visibly marked" not in simulated_readme.casefold()
    assert "visibly marked" not in template_readme.casefold()
    assert "warning labels or watermarks" in simulated_readme
    assert "warning labels" in template_readme
    assert "watermarks" in template_readme
    # Publication aggregates are accompanied by claim evidence and a complete
    # run-level audit package (replicates, paired decisions, ledger, latency).
    assert len(simulation["data_files"]) >= 25
    assert simulation["claim_evidence_contract"]["data_file"] == (
        "experiments/results/simulated/claim_evidence.csv"
    )
    claim_rows = simulation["claim_evidence_contract"]["rows"]
    assert claim_rows
    assert {row["claim_id"] for row in claim_rows} == set(simulation["claim_ids"])
    with (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "claim_evidence.csv"
    ).open("r", encoding="utf-8-sig", newline="") as handle:
        claim_evidence_rows = list(csv.DictReader(handle))
    assert claim_evidence_rows
    assert {
        row["seed"] for row in claim_evidence_rows
    } == {"13|42|73|101|202"}
    assert {row["claim_status"] for row in claim_evidence_rows} == {"unresolved"}
    assert {row["supports_claim"] for row in claim_evidence_rows} == {"false"}
    assert all(row["decision"] for row in claim_evidence_rows)
    assert {row["decision_complete"] for row in claim_evidence_rows} == {"false"}
    assert {row["single_factor_matched"] for row in claim_evidence_rows} == {"false"}
    evidence_package = simulation["evidence_package"]
    for key in (
        "run_level_results", "paired_comparisons", "run_ledger", "latency_samples"
    ):
        evidence_path = tmp_path / evidence_package[key]
        assert evidence_path.is_file() and evidence_path.stat().st_size > 0
    for claim_id, evidence in simulation["claim_evidence_map"].items():
        assert evidence["required_outcomes"]
        assert evidence["evidence_row_ids"]
        assert set(evidence["evidence_row_ids"]) <= {
            row["row_id"] for row in claim_rows if row["claim_id"] == claim_id
        }
        assert simulation["claim_evidence_contract"]["data_file"] in evidence["data_files"]
    mismatched = json.loads(json.dumps(simulation))
    mismatched["claim_evidence_map"]["C1"]["evidence_row_ids"] = list(
        mismatched["claim_evidence_map"]["C2"]["evidence_row_ids"]
    )
    assert any(
        "C1 is not bound exactly to its claim-specific evidence rows" in issue
        for issue in simulation_manifest_contract_issues(mismatched)
    )
    incomplete_family = json.loads(json.dumps(simulation))
    incomplete_family["registered_pair_contract"]["observed_comparison_count"] -= 1
    assert any(
        "unordered-pair by axis comparison family is incomplete" in issue
        for issue in simulation_manifest_contract_issues(incomplete_family)
    )
    incomplete_join = json.loads(json.dumps(simulation))
    incomplete_join["evidence_package"]["provenance_join_contract"].update({
        "coverage": 0.9,
        "complete": False,
    })
    assert any(
        "provenance joins are incomplete" in issue
        for issue in simulation_manifest_contract_issues(incomplete_join)
    )
    assert len(simulation["figure_files"]) == 7
    assert {
        item["plot_family"] for item in simulation["figure_files"]
    } == set(SIMULATION_PLOT_FAMILIES.values())
    assert {
        item["plot_family"] for item in simulation["domain_asset_profile"]
    } == set(SIMULATION_PLOT_FAMILIES.values())
    ablation_script = (
        tmp_path / "figures" / "simulated" / "simulated_ablation.py"
    ).read_text(encoding="utf-8")
    error_script = (
        tmp_path / "figures" / "simulated" / "simulated_error_analysis.py"
    ).read_text(encoding="utf-8")
    efficiency_script = (
        tmp_path / "figures" / "simulated" / "simulated_efficiency.py"
    ).read_text(encoding="utf-8")
    assert "Performance degradation relative to" in ablation_script
    assert "barh" in ablation_script
    assert "EEG error rates" in error_script and "imshow" in error_script
    assert "scatter" in efficiency_script and "Pareto frontier" in efficiency_script
    simulation_manifest_sha256 = _sha256(simulation_manifest)
    assert result["simulation_manifest_sha256"] == simulation_manifest_sha256
    for item in simulation["data_files"]:
        path = tmp_path / item["path"]
        assert path.is_file()
        assert item["sha256"] == _sha256(path)
    for item in simulation["figure_files"]:
        source = tmp_path / item["source"]
        assert item["source_sha256"] == _sha256(source)
        source_text = source.read_text(encoding="utf-8")
        assert "fig.text(" not in source_text
        assert "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS" not in source_text
        for kind, relative in item["outputs"].items():
            output = tmp_path / relative
            assert output.is_file()
            assert item["output_sha256"][kind] == _sha256(output)

    figure_manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    preview_entries = {
        item["id"]: item
        for item in figure_manifest["figures"]
        if (item.get("metadata") or {}).get("evidence_status")
        == "synthetic_preview"
    }
    simulation_figures = {
        item["id"]: item for item in simulation["figure_files"]
    }
    assert preview_entries.keys() == simulation_figures.keys()
    for figure_id, entry in preview_entries.items():
        metadata = entry["metadata"]
        manifest_item = simulation_figures[figure_id]
        assert entry["paper_ready"] is (figure_id in _OBJECTIVE_FIGURE_IDS)
        assert metadata["paper_selected"] is (figure_id in _OBJECTIVE_FIGURE_IDS)
        assert metadata["manuscript_eligible"] is True
        assert metadata["submission_eligible"] is False
        assert metadata["explicit_user_mode"] == "synthetic_preview"
        assert metadata["simulation_id"] == simulation["simulation_id"]
        assert metadata["simulation_kind"] == simulation["simulation_kind"]
        assert metadata["simulation_manifest_sha256"] == simulation_manifest_sha256
        assert metadata["rendered_variants"] == manifest_item["outputs"]
        assert metadata["rendered_variant_sha256"] == manifest_item["output_sha256"]
        assert set(metadata["source_data_sha256"]) == set(metadata["source_data"])
        for relative, digest in metadata["source_data_sha256"].items():
            assert digest == _sha256(tmp_path / relative)
    with (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "main_comparison.csv"
    ).open("r", encoding="utf-8-sig", newline="") as handle:
        simulated_rows = list(csv.DictReader(handle))
    assert simulated_rows
    assert all(row["value"] and row["ci_low"] and row["ci_high"] for row in simulated_rows)
    assert all(
        row["source_run_id"].startswith("simulation:")
        and row["status"] == "synthetic_preview"
        for row in simulated_rows
    )
    assert not any(column.startswith("demo_") for column in simulated_rows[0])


def test_semantic_domain_planner_infers_accuracy_and_multitask_assets(tmp_path: Path) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "ideas.md").write_text(
        "# Vision foundation model\nImage classification across ImageNet-C and DomainNet.",
        encoding="utf-8",
    )
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "status": "accepted",
            "title": "Vision foundation model",
            "problem_statement": "Image classification across ImageNet-C and DomainNet",
            "claims": [{"id": "C1", "statement": "Robust image classification"}],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        "experiment:\n  primary_metric: accuracy\n", encoding="utf-8",
    )
    author_publication_fixture(tmp_path, method_name="Vision foundation method",
                               comparators=["Vision task reference", "Vision foundation method"])
    result = asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path, "Deep learning image classification benchmark", evidence_mode="synthetic_preview"
        )
    )
    simulation = json.loads(
        (tmp_path / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert result["primary_metric"].casefold() == "accuracy"
    assert simulation["specialized_domain"] == "vision"
    assert simulation["replicate_contract"]["seed_count"] == 5
    assert simulation["replicate_contract"]["unit"] == "random_seed"
    assert set(simulation["claim_evidence_map"]) == set(simulation["claim_ids"])
    for evidence in simulation["claim_evidence_map"].values():
        assert evidence["figure_ids"]
        assert evidence["data_files"]
        assert evidence["table"].endswith("synthetic_preview_results.tex")
    result_table = (
        tmp_path / "paper" / "tables" / "synthetic_preview_results.tex"
    ).read_text(encoding="utf-8")
    assert "% MERAK_PRIMARY_MATRIX_CAPTION:" in result_table and "Method &" in result_table
    assert "ImageNet-C" in result_table
    assert simulation["asset_roles"][0]["domain_role"] == "cross_dataset_task_matrix"
    with (tmp_path / "experiments" / "results" / "simulated" / "main_comparison.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len({row["dataset"] for row in rows}) >= 5
    assert "ImageNet-C" in " ".join(row["dataset"] for row in rows)
    assert all(row["seed_count"] == "5" for row in rows)
    assert all(len(row["seed_values"].split("|")) == 5 for row in rows)
    assert all(row["effect_vs_reference"] for row in rows)
    assert all(row["task_rank"] and row["mean_task_rank"] for row in rows)
    assert all(row["task_wins"] and row["worst_task_value"] for row in rows)
    assert simulation["progression_axis"] == "label_fraction"
    ablation_text = (
        tmp_path / "experiments" / "results" / "simulated" / "ablation.csv"
    ).read_text(encoding="utf-8")
    assert "time-domain" not in ablation_text
    assert "multi-scale features" in ablation_text
    ablation_script = (
        tmp_path / "figures" / "simulated" / "simulated_ablation.py"
    ).read_text(encoding="utf-8")
    assert "group_order" in ablation_script
    assert "group.title()" in ablation_script and "Patch(" in ablation_script
    calibration_script = (
        tmp_path / "figures" / "simulated" / "simulated_calibration.py"
    ).read_text(encoding="utf-8")
    assert "Task-level calibration" in calibration_script
    assert "Selective prediction" in calibration_script
    for data_file in simulation["data_files"]:
        if not data_file["path"].endswith(".csv"):
            continue
        with (tmp_path / data_file["path"]).open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            analysis_rows = list(csv.DictReader(handle))
        assert analysis_rows
        if "seed_count" in analysis_rows[0]:
            assert all(row["seed_count"] == "5" for row in analysis_rows)
            assert all(len(row["seed_values"].split("|")) == 5 for row in analysis_rows)
        else:
            assert all(row.get("seed") or row.get("paired_seed_ids") for row in analysis_rows)


def test_literature_domain_terms_do_not_override_selected_generic_study(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "ideas" / "ideas.md").write_text(
        "Nearest neighbors include ImageNet-C, DomainNet, EEG, and language benchmarks.",
        encoding="utf-8",
    )
    (tmp_path / "ideas" / "novelty_report.md").write_text(
        "Vision and EEG examples are prior work only.", encoding="utf-8"
    )
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "status": "accepted",
            "title": "Auditable multi-axis algorithm benchmark",
            "problem_statement": "Compare generic algorithms under registered shift and resource axes",
            "claims": [{"id": "C1", "statement": "Rankings vary across registered axes"}],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        "experiment:\n  primary_metric: accuracy\nmethod:\n  model_suite: [linear, mlp, residual]\n  efficiency_measurement:\n    software_image: runtime_required\n",
        encoding="utf-8",
    )

    author_publication_fixture(tmp_path, method_name="Registered algorithm comparison", comparators=["Linear", "Mlp", "Residual"])

    asyncio.run(experiment_placeholder_service.ensure(
        tmp_path,
        "Generic algorithm comparison with ranking stability",
        evidence_mode="synthetic_preview",
    ))
    manifest = json.loads((
        tmp_path / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json"
    ).read_text(encoding="utf-8"))
    assert manifest["specialized_domain"] == ""
    main_csv = (tmp_path / "experiments" / "results" / "simulated" / "main_comparison.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "ImageNet-C" not in main_csv
    assert "DomainNet" not in main_csv


def test_simulation_materializes_registered_models_axes_and_provenance(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "status": "accepted",
            "claims": [{
                "id": "C1",
                "statement": "At least one registered cross-axis ranking reversal occurs.",
                "measurable_endpoints": [
                    "registered paired i.i.d. and target-axis effects",
                    "reversal flags",
                    "Holm decisions",
                ],
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        """data:
  manifest: data/manifest.csv
method:
  model_suite: [linear_reference, mlp_reference, residual_mlp]
  ablations:
    allowed_single_factors: [architecture, recipe, calibration]
    matched_fields: [data_version, split_hash, seed_set, precision, batch_size]
  ranking_registry:
    alpha: 0.05
    paired_model_comparisons: all_unordered_pairs
    axes:
      - {axis_id: iid_accuracy, metric_key: accuracy, direction: maximize, mpid: 0.010}
      - {axis_id: worst_shift_accuracy, metric_key: worst_shift_accuracy, direction: maximize, mpid: 0.010}
      - {axis_id: shifted_nll, metric_key: shifted_nll, direction: minimize, mpid: 0.010}
      - {axis_id: shifted_brier, metric_key: shifted_brier, direction: minimize, mpid: 0.010}
      - {axis_id: latency_p95_ms, metric_key: latency_p95_ms, direction: minimize, mpid: 0.10}
      - {axis_id: peak_memory_bytes, metric_key: peak_memory_bytes, direction: minimize, mpid: 1048576}
  calibration:
    method: temperature_scaling
  efficiency_measurement:
    precision: float32
    batch_size: 32
    warmup_iterations: 10
    measured_iterations: 30
experiment:
  primary_metric: accuracy
execution:
  max_epochs: 20
evaluation:
  metrics: [accuracy, nll, brier]
""",
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "RUN_SPEC.json").write_text(
        json.dumps({
            "seeds": [13, 42, 73, 101, 202],
            "matrix": {
                "models": ["linear_reference", "mlp_reference", "residual_mlp"],
            },
        }),
        encoding="utf-8",
    )

    author_publication_fixture(tmp_path, method_name="Registered algorithm comparison", comparators=["Linear Reference", "Mlp Reference", "Residual Mlp"], contribution_type="system_architecture")

    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "Auditable multi-axis classification benchmark",
            evidence_mode="synthetic_preview",
            study_archetype="systems_testbed",
        )
    )
    simulated = tmp_path / "experiments" / "results" / "simulated"
    manifest = json.loads((simulated / "SIMULATION_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["registered_pair_contract"]["complete"] is True
    assert manifest["registered_pair_contract"]["pairing"] == "all_unordered_pairs"
    assert manifest["registered_pair_contract"]["expected_comparison_count"] == 18
    assert manifest["registered_pair_contract"]["holm_family_size"] == 15
    assert manifest["registered_pair_contract"]["reference_row_count"] == 3
    assert manifest["registered_pair_contract"]["test_method"] == "paired_student_t_two_sided"
    assert manifest["progression_contract"] == {
        "axis": "epoch",
        "levels": [1, 5, 10, 20],
        "configured_training_horizon": 20,
        "horizon_source": "execution.max_epochs",
    }
    assert manifest["evidence_package"]["provenance_join_contract"]["coverage"] == 1.0

    with (simulated / "training_dynamics.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        training_rows = list(csv.DictReader(handle))
    assert {int(row["epoch"]) for row in training_rows} == {1, 5, 10, 20}
    assert max(int(row["epoch"]) for row in training_rows) == 20

    with (simulated / "paired_comparisons.csv").open(encoding="utf-8-sig", newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 18
    assert {row["axis_id"] for row in pairs} == {
        "iid_accuracy", "worst_shift_accuracy", "shifted_nll",
        "shifted_brier", "latency_p95_ms", "peak_memory_bytes",
    }
    assert {row["reference_model_id"] for row in pairs} == {
        "linear_reference", "mlp_reference",
    }
    assert {row["candidate_model_id"] for row in pairs} == {
        "mlp_reference", "residual_mlp",
    }
    assert all(row["paired_effects"] and row["paired_ci_low"] and row["paired_ci_high"] for row in pairs)
    assert all(row["p_value"] and row["holm_adjusted_p"] and row["decision"] for row in pairs)
    target_pairs = [row for row in pairs if row["in_holm_family"] == "true"]
    reference_pairs = [row for row in pairs if row["in_holm_family"] == "false"]
    assert len(target_pairs) == 15
    assert len(reference_pairs) == 3
    assert {row["family_size"] for row in pairs} == {"15"}
    assert {row["test_method"] for row in pairs} == {"paired_student_t_two_sided"}
    assert all(row["holm_adjusted_p"] == "1.000000" for row in reference_pairs)
    qualifying = [row for row in target_pairs if row["reversal_status"] == "qualifying_reversal"]
    assert all(row["target_ci_supports_direction"] == "true" for row in qualifying)
    assert all(row["iid_ci_supports_direction"] == "true" for row in qualifying)
    table_text = (tmp_path / "paper" / "tables" / "synthetic_preview_results.tex").read_text(
        encoding="utf-8"
    )
    assert r"\label{tab:paired-reversals}" not in table_text
    assert "qualifying_cross_axis_reversal" not in table_text
    from server.services.simulation_table_projection import _paired_body
    paired_table = _paired_body(pairs)
    for target_axis in (
        "Worst-shift accuracy",
        "Shifted NLL",
        "Shifted Brier score",
        "p95 latency (ms)",
        "Peak memory (MiB)",
    ):
        assert paired_table.count(target_axis) == 3
    assert "67108864.000000" not in paired_table
    assert "0.000000" not in paired_table
    assert "Auxiliary accuracy (higher)" in table_text
    assert "Worst-shift accuracy (higher)" in table_text
    assert "Calibration error (lower)" in table_text

    with (simulated / "claim_evidence.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        claim_rows = list(csv.DictReader(handle))
    assert {row["claim_id"] for row in claim_rows} == {"C1"}
    # Complete statistics alone do not bind this natural-language claim to an
    # explicit decision rule. Positive rule cases are exercised independently.
    assert {row["claim_status"] for row in claim_rows} == {"unresolved"}
    assert {row["supports_claim"] for row in claim_rows} == {"false"}
    assert {row["decision_complete"] for row in claim_rows} == {"false"}

    with (simulated / "run_ledger.csv").open(encoding="utf-8-sig", newline="") as handle:
        ledger = list(csv.DictReader(handle))
    required = {
        "data_version", "manifest_sha256", "split_sha256", "config_sha256",
        "calibrator_id", "software_image", "hardware_contract_id",
        "checkpoint_artifact_path", "checkpoint_artifact_sha256",
        "prediction_artifact_path", "prediction_artifact_sha256",
        "measurement_artifact_path", "measurement_artifact_sha256",
    }
    assert required <= set(ledger[0])
    assert all(all(row[key] for key in required) for row in ledger)
    evidence_package = manifest["evidence_package"]
    for key in (
        "data_manifest", "raw_checkpoints", "raw_predictions", "raw_measurements",
        "generator_source", "scenario_parameters", "reconstruction_tool",
    ):
        assert (tmp_path / evidence_package[key]).is_file()
    assert "paired Student-t" in evidence_package["reconstruction_contract"]
    assert "15 non-i.i.d." in evidence_package["reconstruction_contract"]
    assert simulation_manifest_contract_issues(manifest) == []

    with (simulated / "ablation.csv").open(encoding="utf-8-sig", newline="") as handle:
        ablations = list(csv.DictReader(handle))
    assert {row["changed_factor"] for row in ablations} == {
        "none", "architecture", "recipe", "calibration",
    }
    assert {row["parameters_m"] for row in ablations} == {"13.20"}
    assert all(row["single_factor_matched"] == "true" for row in ablations)
    assert all(row["matched_controls"] for row in ablations)
    assert all(row["worst_shift_effect_vs_full"] for row in ablations)
    assert all(row["calibration_error_change_vs_full"] for row in ablations)
    assert all(row["reversal_count_change_vs_full"] for row in ablations)

    with (simulated / "efficiency.csv").open(encoding="utf-8-sig", newline="") as handle:
        efficiency = list(csv.DictReader(handle))
    assert all(row["latency_p50_ms"] and row["latency_p95_ms"] for row in efficiency)
    assert all(row["peak_memory_bytes"] and row["throughput_per_s"] for row in efficiency)
    assert all(row["measurement_repetitions"] == "30" for row in efficiency)


def test_primary_metric_axis_matches_main_table_and_preserves_mechanism_names(
    tmp_path: Path,
) -> None:
    (tmp_path / "ideas").mkdir(parents=True)
    (tmp_path / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "status": "accepted",
            "claims": [{"id": "C1", "statement": "Matched comparison."}],
            "mechanisms": [
                {"id": "M1", "name": "记录身份捷径抑制一致性"},
                {"id": "M2", "name": "频谱—拓扑结构掩码预测"},
                {"id": "M3", "name": "严格域外与导联压力测试"},
                {"id": "M4", "name": "计算匹配因果消融"},
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "experiments" / "configs").mkdir(parents=True)
    (tmp_path / "experiments" / "configs" / "main.yaml").write_text(
        """method:
  model_suite: [published_baseline, matched_capacity_baseline, full_method]
  ranking_registry:
    axes:
      - {axis_id: balanced_accuracy, metric_key: balanced_accuracy, direction: maximize, mpid: 0.01}
evaluation:
  primary_metric: balanced_accuracy
""",
        encoding="utf-8",
    )

    author_publication_fixture(tmp_path, method_name="Registered algorithm comparison", comparators=["Reference model", "Capacity-matched control", "Registered algorithm comparison"], public_mechanisms=["Record-identity consistency objective", "Spectral-topological masked prediction", "Held-out montage stress evaluation", "Compute-matched causal ablation"])

    asyncio.run(experiment_placeholder_service.ensure(
        tmp_path,
        "General matched algorithm benchmark",
        evidence_mode="synthetic_preview",
        study_archetype="algorithm_benchmark",
    ))

    simulated = tmp_path / "experiments" / "results" / "simulated"
    with (simulated / "main_comparison.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        main_rows = list(csv.DictReader(handle))
    with (simulated / "paired_comparisons.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        pairs = list(csv.DictReader(handle))
    manifest = json.loads(
        (simulated / "SIMULATION_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert simulation_manifest_contract_issues(manifest) == []
    assert manifest["registered_pair_contract"]["holm_family_size"] == 0
    assert manifest["registered_pair_contract"]["reference_row_count"] == 3
    groups: dict[str, list[float]] = {}
    for row in main_rows:
        groups.setdefault(row["method"], []).append(float(row["value"]))
    means = {
        key: sum(values) / len(values)
        for key, values in groups.items()
    }
    full_pair = next(
        row for row in pairs
        if row["candidate_method"] == "Full Method"
        and row["reference_method"] == "Matched Capacity Baseline"
    )
    expected = means["Full Method"] - means["Matched Capacity Baseline"]
    assert float(full_pair["oriented_mean_effect"]) == pytest.approx(
        expected, abs=1e-6
    )
    assert full_pair["in_holm_family"] == "false"
    main_script = (
        tmp_path / "figures" / "simulated" / "simulated_main_comparison.py"
    ).read_text(encoding="utf-8")
    assert "Balanced accuracy (higher is better)" in main_script
    assert "balanced_accuracy (higher is better)" not in main_script
    ablation_text = (simulated / "ablation.csv").read_text(encoding="utf-8-sig")
    for label in (
        "Record-identity consistency objective",
        "Spectral-topological masked prediction",
        "Held-out montage stress evaluation",
        "Compute-matched causal ablation",
    ):
        assert label in ablation_text
    assert "Prespecified method component" not in ablation_text
