from __future__ import annotations

from server.tests._node_risk_audit_support import (
    Path as Path,
    SIMULATION_PLOT_FAMILIES as SIMULATION_PLOT_FAMILIES,
    SIMULATION_RENDERER_VERSION as SIMULATION_RENDERER_VERSION,
    WorkflowEngine as WorkflowEngine,
    _sha256 as _sha256,
    _write_json as _write_json,
    json as json,
    node_risk_audit_service as node_risk_audit_service,
    os as os,
    pytest as pytest,
    scientific_evidence_service as scientific_evidence_service,
    time as time,
)


def test_compile_and_slide_build_records_are_hash_bound(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    slides = tmp_path / "slides"
    figures = tmp_path / "figures"
    paper.mkdir()
    slides.mkdir()
    figures.mkdir()
    graphic = figures / "result_plot.png"
    graphic.write_bytes(b"initial graphic")
    (paper / "main.tex").write_text(
        "\\documentclass{article}\\usepackage{graphicx}\\begin{document}"
        "\\includegraphics{../figures/result_plot.png}\\end{document}",
        encoding="utf-8",
    )
    (paper / "main.pdf").write_bytes(b"%PDF-1.4\nverified paper")
    (paper / "PAPER_BUILD.json").write_text(
        json.dumps({
            "page_contract": {
                "minimum_pages": 7,
                "maximum_pages": 9,
                "actual_pages": 2,
                "within_preferred_range": False,
                "warning": "stale",
            }
        }),
        encoding="utf-8",
    )
    frames = "".join(
        f"\\begin{{frame}}{{S{i}}}x\\end{{frame}}" for i in range(15)
    )
    (slides / "main.tex").write_text(
        "\\documentclass{beamer}\\begin{document}"
        + frames
        + "\\includegraphics{../figures/result_plot.png}"
        + "\\end{document}",
        encoding="utf-8",
    )
    import pymupdf
    with pymupdf.open() as deck:
        deck.new_page().insert_text((40, 60), 'Verified slide content', fontsize=18)
        deck.save(slides / 'main.pdf')
    for name in ("SLIDE_OUTLINE.md", "speaker_notes.md", "TALK_SCRIPT.md"):
        (slides / name).write_text("Research talk: motivation, method, evidence and limitations.", encoding="utf-8")

    engine = WorkflowEngine()
    engine._refresh_compiled_artifact_record(
        paper,
        "PAPER_BUILD.json",
        "main.pdf",
        pages=8,
        compile_time_ms=1234,
        warning_count=2,
    )
    engine._refresh_compiled_artifact_record(
        slides, "SLIDE_BUILD.json", "main.pdf"
    )

    paper_findings = node_risk_audit_service._audit_compile(tmp_path, {})
    slide_findings = node_risk_audit_service._audit_ppt(tmp_path, {})
    assert not [item for item in paper_findings if item["severity"] == "blocker"]
    assert not [item for item in slide_findings if item["severity"] == "blocker"]
    paper_build = json.loads(
        (paper / "PAPER_BUILD.json").read_text(encoding="utf-8")
    )
    assert "figures/result_plot.png" in paper_build["compile"]["source_files"]
    assert paper_build["compile"]["pages"] == 8
    assert paper_build["compile"]["compile_time_ms"] == 1234
    assert paper_build["compile"]["warning_count"] == 2
    assert paper_build["page_contract"]["actual_pages"] == 8
    assert paper_build["page_contract"]["within_preferred_range"] is True
    assert paper_build["page_contract"]["warning"] == ""

    graphic.write_bytes(b"revised graphic")
    newer = time.time() + 5
    os.utime(graphic, (newer, newer))

    paper_ids = {
        item["id"] for item in node_risk_audit_service._audit_compile(tmp_path, {})
    }
    slide_ids = {
        item["id"] for item in node_risk_audit_service._audit_ppt(tmp_path, {})
    }
    assert "COMPILE-HASH-001" in paper_ids
    assert "COMPILE-STALE-001" not in paper_ids
    assert "PPT-BUILD-002" in slide_ids
    assert "PPT-STALE-001" not in slide_ids


def test_ppt_audit_surfaces_text_density_and_tiny_font(tmp_path: Path) -> None:
    slides = tmp_path / "slides"
    slides.mkdir()
    dense_text = " ".join(f"finding{index}" for index in range(140))
    (slides / "main.tex").write_text(
        "\\documentclass{beamer}\n"
        "\\begin{document}\n"
        "\\begin{frame}{Dense evidence}\\tiny\n"
        f"{dense_text}\n"
        "\\end{frame}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_ppt(
        tmp_path,
        {"run_experiment": False},
    )
    ids = {item["id"] for item in findings}

    assert "PPT-LEGIBILITY-001" in ids
    assert "PPT-LEGIBILITY-002" in ids


def test_managed_runtime_manifest_owns_metrics_without_agent_tool_event(
    tmp_path: Path,
) -> None:
    metrics = tmp_path / "experiments" / "results" / "run-1" / "metrics.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text(
        "status,method,split,seed,accuracy\n"
        "completed,reference,test,1,0.70\n"
        "completed,proposed,test,1,0.75\n",
        encoding="utf-8",
    )
    relative = metrics.relative_to(tmp_path).as_posix()
    _write_json(
        tmp_path / ".merak" / "experiments" / "managed-1" / "run.json",
        {
            "status": "completed",
            "run_id": "managed-1",
            "result_artifacts": {
                relative: {
                    "sha256": _sha256(metrics),
                    "mtime": metrics.stat().st_mtime,
                    "bytes": metrics.stat().st_size,
                }
            },
        },
    )

    valid, issues, details = scientific_evidence_service.validate_executed_metrics(
        tmp_path
    )

    assert valid is True, issues
    assert relative in details["proven_sources"]
    assert details["managed_runtime_ids"] == ["managed-1"]


def test_platform_diagnostic_manifest_is_not_submission_evidence(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / ".merak" / "experiments" / "diagnostic-1" / "run.json",
        {
            "status": "completed",
            "run_id": "diagnostic-1",
            "evidence_eligible": False,
            "submission_eligible": True,
            "purpose": "platform_runtime_diagnostic",
            "attempts": [{"attempt": 1, "status": "completed"}],
        },
    )

    findings = node_risk_audit_service._audit_exp_run(
        tmp_path,
        {"run_experiment": True},
    )

    assert "RUN-MANIFEST-001" not in {item["id"] for item in findings}
    _, _, details = scientific_evidence_service.validate_executed_metrics(tmp_path)
    assert details["managed_runtime_ids"] == []


def test_experiment_code_integrity_uses_ast_without_importing_dependencies(
    tmp_path: Path,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text(
        "import package_that_is_not_installed\n\ndef train():\n    return 1\n",
        encoding="utf-8",
    )
    config.write_text("seed: 1\n", encoding="utf-8")

    valid = WorkflowEngine()._experiment_code_integrity_gate(str(tmp_path))
    assert valid["passed"] is True

    source.write_text("def broken(:\n    pass\n", encoding="utf-8")
    invalid = WorkflowEngine()._experiment_code_integrity_gate(str(tmp_path))
    assert invalid["passed"] is False
    assert "Python syntax error" in invalid["issues"][0]


def test_downstream_risk_audit_revalidates_objective_upstream_blockers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    source.parent.mkdir(parents=True)
    source.write_text("def broken(:\n", encoding="utf-8")

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "figure",
        {"run_experiment": False},
        persist=False,
    )

    assert any(
        item["id"].startswith("UPSTREAM-EXP-DESIGN-")
        and "cannot be parsed" in item["message"]
        for item in report["findings"]
    )


def test_downstream_preflight_includes_upstream_cross_node_drift(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "ideas" / "SELECTED_IDEA.json",
        {
            "schema": 1,
            "status": "accepted",
            "title": "Frozen idea A",
            "hypothesis": "A falsifiable hypothesis.",
            "claims": [{"id": "C1", "statement": "Claim one."}],
            "mechanisms": [{"id": "M1", "name": "Mechanism", "description": "Description."}],
            "falsification_conditions": ["Reject if the control matches."],
        },
    )
    _write_json(
        tmp_path / "experiments" / "METHOD_CONTRACT.json",
        {"selected_idea": "Different idea", "status": "implemented"},
    )

    findings = node_risk_audit_service.protected_upstream_findings(
        tmp_path,
        "figure",
        {"run_experiment": False},
    )

    assert any(
        item.get("upstream_node") == "exp-design"
        and "METHOD_CONTRACT" in str(item.get("message"))
        for item in findings
    )


def test_transitive_literature_blocker_reaches_late_stage_preflight(tmp_path: Path) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text("# Survey\nSearch protocol.", encoding="utf-8")
    (literature / "references.bib").write_text(
        "@article{dup, title={A}, year={2024}, url={https://example/a}}\n"
        "@article{dup, title={B}, year={2025}, url={https://example/b}}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service.preflight_node(
        tmp_path,
        "paper",
        {"run_experiment": False, "gpu_target": "none"},
    )

    assert any(
        item.get("upstream_node") == "lit"
        and "Duplicate BibTeX keys" in str(item.get("message"))
        for item in findings
    )


def test_exp_design_detects_run_command_that_references_a_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    plan = tmp_path / "experiments" / "EXPERIMENT_PLAN.md"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text("def train():\n    return 1\n", encoding="utf-8")
    config.write_text("seed: 1\n", encoding="utf-8")
    plan.write_text("# Plan\nLeakage control, baseline, ablation, statistics, falsification.", encoding="utf-8")
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {"command": "python experiments/src/missing.py --config experiments/configs/main.yaml", "seeds": [1, 2]},
    )
    monkeypatch.setattr(
        "server.services.method_contract.method_contract_service.validate_method_contract",
        lambda *_args, **_kwargs: (True, [], {}),
    )

    findings = node_risk_audit_service._audit_exp_design(tmp_path, {"run_experiment": True})

    assert any(item["id"] == "DESIGN-RUN-004" for item in findings)


def test_exp_design_accepts_structured_preflight_command_when_experiment_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text("def main():\n    return 0\n", encoding="utf-8")
    config.write_text("seed: 1\n", encoding="utf-8")
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {
            "commands": [
                {
                    "command": (
                        "python experiments/src/train.py "
                        "--config experiments/configs/main.yaml --dry-run"
                    ),
                    "executes_training": False,
                }
            ],
            "seeds": [1, 2],
        },
    )
    monkeypatch.setattr(
        "server.services.method_contract.method_contract_service.validate_method_contract",
        lambda *_args, **_kwargs: (True, [], {}),
    )

    findings = node_risk_audit_service._audit_exp_design(
        tmp_path,
        {"run_experiment": False},
    )

    ids = {item["id"] for item in findings}
    assert "DESIGN-RUN-002" not in ids
    assert "DESIGN-RUN-004" not in ids


def test_exp_design_accepts_named_seed_lists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text("def main():\n    return 0\n", encoding="utf-8")
    config.write_text("seed: 1\n", encoding="utf-8")
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {
            "command": (
                "python experiments/src/train.py "
                "--config experiments/configs/main.yaml --seed {seed}"
            ),
            "seed_list": {
                "pilot": [101, 202],
                "decisive": [101, 202, 303, 404, 505],
            },
        },
    )
    monkeypatch.setattr(
        "server.services.method_contract.method_contract_service.validate_method_contract",
        lambda *_args, **_kwargs: (True, [], {}),
    )

    findings = node_risk_audit_service._audit_exp_design(
        tmp_path,
        {"run_experiment": True},
    )

    ids = {item["id"] for item in findings}
    assert "DESIGN-REP-001" not in ids
    assert "DESIGN-REP-002" not in ids


def test_exp_design_does_not_use_structured_dry_run_for_real_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text("def main():\n    return 0\n", encoding="utf-8")
    config.write_text("seed: 1\n", encoding="utf-8")
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {
            "commands": [
                {
                    "command": (
                        "python experiments/src/train.py "
                        "--config experiments/configs/main.yaml --dry-run"
                    ),
                    "executes_training": False,
                }
            ],
            "seeds": [1, 2],
        },
    )
    monkeypatch.setattr(
        "server.services.method_contract.method_contract_service.validate_method_contract",
        lambda *_args, **_kwargs: (True, [], {}),
    )

    findings = node_risk_audit_service._audit_exp_design(
        tmp_path,
        {"run_experiment": True},
    )

    assert any(item["id"] == "DESIGN-RUN-002" for item in findings)


def test_exp_run_rejects_submission_blocked_synthetic_preview(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json",
        {
            "status": "synthetic_preview",
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        },
    )

    findings = node_risk_audit_service._audit_exp_run(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert any(item["id"] == "RUN-PLANNED-005" for item in findings)


def test_exp_run_accepts_manuscript_eligible_synthetic_preview(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json",
        {
            "status": "synthetic_preview",
            "evidence_mode": "synthetic_preview",
            "manuscript_eligible": True,
            "submission_eligible": False,
        },
    )

    findings = node_risk_audit_service._audit_exp_run(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert not any(item["id"] == "RUN-PLANNED-005" for item in findings)


def test_exp_design_rejects_reachable_scaffold_only_for_real_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    plan = tmp_path / "experiments" / "EXPERIMENT_PLAN.md"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text(
        "def train():\n"
        "    raise NotImplementedError('real training missing')\n\n"
        "def main():\n"
        "    train()\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    config.write_text(
        "project:\n  code_check_only: true\nexperiment:\n  dry_run: true\n",
        encoding="utf-8",
    )
    plan.write_text(
        "# Plan\nLeakage control, baseline, ablation, statistics, falsification.",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {
            "execution_mode": "code_check_only",
            "do_not_run_scientific_training": True,
            "command": (
                "python experiments/src/train.py "
                "--config experiments/configs/main.yaml --dry-run"
            ),
            "seeds": [1, 2],
        },
    )
    monkeypatch.setattr(
        "server.services.method_contract.method_contract_service.validate_method_contract",
        lambda *_args, **_kwargs: (True, [], {}),
    )

    executed = node_risk_audit_service._audit_exp_design(
        tmp_path,
        {"run_experiment": True},
    )
    planned = node_risk_audit_service._audit_exp_design(
        tmp_path,
        {"run_experiment": False},
    )

    executed_ids = {item["id"] for item in executed}
    assert {
        "DESIGN-EXEC-001",
        "DESIGN-EXEC-002",
        "DESIGN-EXEC-003",
        "DESIGN-EXEC-004",
        "DESIGN-EXEC-005",
    } <= executed_ids
    assert not any(item["id"].startswith("DESIGN-EXEC-") for item in planned)


def test_exp_design_rejects_deterministic_no_training_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    plan = tmp_path / "experiments" / "EXPERIMENT_PLAN.md"
    source.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    source.write_text(
        "def main():\n"
        "    raise RuntimeError("
        "'The deterministic fallback contains no scientific training implementation.'"
        ")\n",
        encoding="utf-8",
    )
    config.write_text(
        "experiment:\n  dry_run: false\n  implementation_status: scaffold_only\n",
        encoding="utf-8",
    )
    plan.write_text(
        "# Plan\nLeakage control, baseline, ablation, statistics, falsification.",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "experiments" / "RUN_SPEC.json",
        {
            "command": (
                "python experiments/src/train.py "
                "--config experiments/configs/main.yaml"
            ),
            "seeds": [1, 2],
        },
    )
    monkeypatch.setattr(
        "server.services.method_contract.method_contract_service.validate_method_contract",
        lambda *_args, **_kwargs: (True, [], {}),
    )

    findings = node_risk_audit_service._audit_exp_design(
        tmp_path,
        {"run_experiment": True},
    )
    ids = {item["id"] for item in findings}

    assert "DESIGN-EXEC-004" in ids
    assert "DESIGN-EXEC-005" in ids


def test_result_analysis_freshness_tracks_machine_readable_results(tmp_path: Path) -> None:
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    metrics = tmp_path / "experiments" / "results" / "metrics.csv"
    analysis.parent.mkdir(parents=True)
    analysis.write_text(
        "# Analysis\nC1 is pending. Limitations and uncertainty are retained.",
        encoding="utf-8",
    )
    old = time.time() - 30
    os.utime(analysis, (old, old))
    metrics.write_text("run_id,seed,metric\nr1,1,0.5\n", encoding="utf-8")

    findings = node_risk_audit_service._audit_results(
        tmp_path,
        {"run_experiment": False},
    )

    assert any(item["id"] == "RESULT-STALE-001" for item in findings)


def test_simulation_result_freshness_prefers_manifest_hash_after_copy_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This fixture intentionally exercises legacy schema-5 freshness binding,
    # not the current schema-11 package contract covered by dedicated tests.
    monkeypatch.setattr(
        "server.services.risk_stage_results.simulation_manifest_contract_issues",
        lambda _manifest: [],
    )
    results = tmp_path / "experiments" / "results"
    simulated = results / "simulated"
    simulated.mkdir(parents=True)
    role_files = {
        "main_comparison": ("main_comparison.csv", "synthetic_preview_main_comparison", "method", "maximize"),
        "component_ablation": ("ablation.csv", "synthetic_preview_ablation", "component", "maximize"),
        "training_dynamics": ("training_dynamics.csv", "synthetic_preview_training_dynamics", "step", "maximize"),
        "robustness_sensitivity": ("robustness.csv", "synthetic_preview_robustness", "severity", "maximize"),
        "error_analysis": ("error_analysis.csv", "synthetic_preview_error_analysis", "slice", "minimize"),
        "calibration_risk_coverage": ("calibration.csv", "synthetic_preview_calibration", "coverage", "minimize"),
        "efficiency_tradeoff": ("efficiency.csv", "synthetic_preview_efficiency", "resource", "maximize"),
    }
    data_paths: list[Path] = []
    for filename, _semantic_id, _axis_field, direction in role_files.values():
        path = simulated / filename
        path.write_text(
            "simulation_seed,method,value,ci_low,ci_high,metric_direction\n"
            f"1729,proposed,0.75,0.72,0.78,{direction}\n",
            encoding="utf-8",
        )
        data_paths.append(path)
    manifest = simulated / "SIMULATION_MANIFEST.json"
    _write_json(
        manifest,
        {
            "schema": 5,
            "renderer_version": SIMULATION_RENDERER_VERSION,
            "primary_metric": "accuracy",
            "metric_direction": "maximize",
            "asset_domain": "algorithmic",
            "evidence_status": "synthetic_preview",
            "manuscript_eligible": True,
            "submission_eligible": False,
            "completeness_pack": list(role_files),
            "claim_ids": ["C1"],
            "claim_evidence_map": {
                "C1": {
                    "figure_ids": ["synthetic_preview_main_comparison"],
                    "data_files": [
                        "experiments/results/simulated/main_comparison.csv"
                    ],
                    "table": "tables/main_comparison.tex",
                }
            },
            "domain_asset_profile": [
                {
                    "stable_role": stable_role,
                    "domain_role": stable_role.replace("_", " "),
                    "semantic_id": semantic_id,
                    "data_file": filename,
                    "analysis_subtype": stable_role,
                    "plot_family": SIMULATION_PLOT_FAMILIES[stable_role],
                    "label": stable_role.replace("_", " ").title(),
                    "axis_field": axis_field,
                    "metric_direction": direction,
                }
                for stable_role, (
                    filename,
                    semantic_id,
                    axis_field,
                    direction,
                ) in role_files.items()
            ],
            "figure_files": [
                {
                    "id": semantic_id,
                    "plot_family": SIMULATION_PLOT_FAMILIES[stable_role],
                }
                for stable_role, (
                    _filename,
                    semantic_id,
                    _axis_field,
                    _direction,
                ) in role_files.items()
            ],
            "data_files": [
                {
                    "path": path.relative_to(tmp_path).as_posix(),
                    "sha256": _sha256(path),
                }
                for path in data_paths
            ],
        },
    )
    analysis = results / "analysis.md"
    analysis.write_text(
        "# Analysis\n"
        "Findings are bounded to the registered conditions and evaluation domain. "
        "The 95% CI retains uncertainty and the limitations include failure cases.\n"
        "The canonical manifest has SHA-256 "
        f"{_sha256(manifest)}.\n",
        encoding="utf-8",
    )
    old = time.time() - 60
    os.utime(analysis, (old, old))
    now = time.time()
    for path in data_paths:
        os.utime(path, (now, now))
    os.utime(manifest, (now, now))

    findings = node_risk_audit_service._audit_results(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert not any(item["id"] == "RESULT-STALE-001" for item in findings)
    assert not any(item["id"] == "RESULT-SIM-001" for item in findings)


def test_simulation_results_accept_claim_evidence_as_eighth_bound_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep this legacy fixture scoped to data-file cardinality and hash binding.
    monkeypatch.setattr(
        "server.services.risk_stage_results.simulation_manifest_contract_issues",
        lambda _manifest: [],
    )
    results = tmp_path / "experiments" / "results"
    simulated = results / "simulated"
    simulated.mkdir(parents=True)
    role_files = {
        "main_comparison": ("main_comparison.csv", "synthetic_preview_main_comparison", "method", "maximize"),
        "component_ablation": ("ablation.csv", "synthetic_preview_ablation", "component", "maximize"),
        "training_dynamics": ("training_dynamics.csv", "synthetic_preview_training_dynamics", "step", "maximize"),
        "robustness_sensitivity": ("robustness.csv", "synthetic_preview_robustness", "severity", "maximize"),
        "error_analysis": ("error_analysis.csv", "synthetic_preview_error_analysis", "slice", "minimize"),
        "calibration_risk_coverage": ("calibration.csv", "synthetic_preview_calibration", "coverage", "minimize"),
        "efficiency_tradeoff": ("efficiency.csv", "synthetic_preview_efficiency", "resource", "maximize"),
    }
    data_paths: list[Path] = []
    for filename, _semantic_id, _axis_field, direction in role_files.values():
        path = simulated / filename
        path.write_text(
            "simulation_seed,method,value,ci_low,ci_high,metric_direction\n"
            f"1729,proposed,0.75,0.72,0.78,{direction}\n",
            encoding="utf-8",
        )
        data_paths.append(path)
    claim_evidence = simulated / "claim_evidence.csv"
    claim_evidence.write_text(
        "simulation_seed,row_id,claim_id,value\n1729,claim-1-1,C1,0.75\n",
        encoding="utf-8",
    )
    data_paths.append(claim_evidence)
    all_data_files = [
        path.relative_to(tmp_path).as_posix() for path in data_paths
    ]
    manifest = simulated / "SIMULATION_MANIFEST.json"
    _write_json(
        manifest,
        {
            "schema": 5,
            "renderer_version": SIMULATION_RENDERER_VERSION,
            "primary_metric": "accuracy",
            "metric_direction": "maximize",
            "asset_domain": "algorithmic",
            "evidence_status": "synthetic_preview",
            "manuscript_eligible": True,
            "submission_eligible": False,
            "completeness_pack": list(role_files),
            "claim_ids": ["C1"],
            "claim_evidence_map": {
                "C1": {
                    "figure_ids": ["synthetic_preview_main_comparison"],
                    "data_files": all_data_files,
                    "required_outcomes": ["registered primary outcome"],
                    "evidence_row_ids": ["claim-1-1"],
                    "table": "tables/main_comparison.tex",
                }
            },
            "claim_evidence_contract": {
                "schema": 1,
                "data_file": claim_evidence.relative_to(tmp_path).as_posix(),
                "rows": [
                    {
                        "row_id": "claim-1-1",
                        "claim_id": "C1",
                        "registered_outcome": "registered primary outcome",
                    }
                ],
            },
            "domain_asset_profile": [
                {
                    "stable_role": stable_role,
                    "domain_role": stable_role.replace("_", " "),
                    "semantic_id": semantic_id,
                    "data_file": filename,
                    "analysis_subtype": stable_role,
                    "plot_family": SIMULATION_PLOT_FAMILIES[stable_role],
                    "label": stable_role.replace("_", " ").title(),
                    "axis_field": axis_field,
                    "metric_direction": direction,
                }
                for stable_role, (
                    filename,
                    semantic_id,
                    axis_field,
                    direction,
                ) in role_files.items()
            ],
            "figure_files": [
                {
                    "id": semantic_id,
                    "plot_family": SIMULATION_PLOT_FAMILIES[stable_role],
                }
                for stable_role, (
                    _filename,
                    semantic_id,
                    _axis_field,
                    _direction,
                ) in role_files.items()
            ],
            "data_files": [
                {
                    "path": path.relative_to(tmp_path).as_posix(),
                    "sha256": _sha256(path),
                }
                for path in data_paths
            ],
        },
    )
    analysis = results / "analysis.md"
    analysis.write_text(
        "# Analysis\n"
        "Findings are bounded to the registered conditions and evaluation domain. "
        "The 95% CI retains uncertainty and limitations include failure cases.\n"
        f"The canonical manifest has SHA-256 {_sha256(manifest)}.\n",
        encoding="utf-8",
    )
    old = time.time() - 60
    os.utime(analysis, (old, old))
    now = time.time()
    for path in data_paths:
        os.utime(path, (now, now))
    os.utime(manifest, (now, now))

    findings = node_risk_audit_service._audit_results(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert not any(item["id"] == "RESULT-SIM-001" for item in findings)
    assert not any(item["id"] == "RESULT-STALE-001" for item in findings)


def test_executed_result_freshness_ignores_failed_history_and_derived_aggregates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "experiments" / "results"
    accepted = results / "decisive" / "accepted" / "summary.csv"
    failed = results / "decisive" / "failed-attempt" / "summary.csv"
    aggregate = results / "aggregates" / "main_comparison.csv"
    analysis = results / "analysis.md"
    for path in (accepted, failed, aggregate):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("run_id,seed,metric\nr1,1,0.5\n", encoding="utf-8")
    analysis.write_text(
        "# Analysis\nC1 has uncertainty and limitations under the accepted run.",
        encoding="utf-8",
    )
    now = time.time()
    os.utime(accepted, (now - 30, now - 30))
    os.utime(analysis, (now - 20, now - 20))
    os.utime(failed, (now, now))
    os.utime(aggregate, (now, now))
    monkeypatch.setattr(
        "server.services.execution_provenance.execution_provenance_service.proven_result_sources",
        lambda _root, **_kwargs: {accepted.relative_to(tmp_path).as_posix()},
    )

    findings = node_risk_audit_service._audit_results(
        tmp_path,
        {"run_experiment": True},
    )

    assert not any(item["id"] == "RESULT-STALE-001" for item in findings)
