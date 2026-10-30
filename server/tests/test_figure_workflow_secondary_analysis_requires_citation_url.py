from __future__ import annotations

from server.tests._figure_workflow_support import (
    Path as Path,
    WorkflowEngine as WorkflowEngine,
    WorkflowRun as WorkflowRun,
    _author_plan_figures as _author_plan_figures,
    _build_figures as _build_figures,
    _disable_live_electron_renderer_discovery as _disable_live_electron_renderer_discovery,
    _seed_project as _seed_project,
    asyncio as asyncio,
    csv as csv,
    execution_provenance_service as execution_provenance_service,
    figure_artifact_registry as figure_artifact_registry,
    hashlib as hashlib,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    re as re,
    scientific_asset_service as scientific_asset_service,
    time as time,
)


def test_secondary_analysis_requires_citation_url_and_matching_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    secondary_dir = tmp_path / "experiments" / "results" / "secondary"
    secondary_dir.mkdir()
    data_path = secondary_dir / "public_benchmark.csv"
    with data_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["status", "method", "seed", "split", "metric", "value"],
        )
        writer.writeheader()
        for method, offset in (("Reference", 0.0), ("Proposed", 0.04)):
            for seed, value in ((1, 0.70), (2, 0.72), (3, 0.71)):
                writer.writerow({
                    "status": "completed",
                    "method": method,
                    "seed": seed,
                    "split": "test",
                    "metric": "accuracy",
                    "value": value + offset,
                })
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    (tmp_path / "experiments" / "results" / "SECONDARY_EVIDENCE.json").write_text(
        json.dumps({
            "schema": 1,
            "sources": [{
                "data_path": data_path.relative_to(tmp_path).as_posix(),
                "sha256": digest,
                "source_url": "https://example.org/public-benchmark",
                "citation_key": "paper1",
            }],
        }),
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "secondary_analysis",
        },
    )
    asyncio.run(
        engine._ensure_figure_artifacts(
            run,
            "Artifact-grounded research agent",
            "Artifact-grounded research agent",
        )
    )
    plan = json.loads(
        (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").read_text(encoding="utf-8")
    )

    assert plan["evidence_mode"] == "secondary_analysis"
    assert plan["submission_eligible"] is True
    assert plan["secondary_sources"] == [
        "experiments/results/secondary/public_benchmark.csv"
    ]
    assert any(item["id"] == "main_comparison" for item in plan["assets"])
    _author_plan_figures(tmp_path, plan)
    asyncio.run(engine._ensure_figure_artifacts(
        run,
        "Model-authored secondary-analysis figures completed",
        "Artifact-grounded research agent",
    ))
    assert engine._figure_acceptance_gate(str(tmp_path))["accepted"] is True

    evidence = paper_artifact_builder.prepare(tmp_path, "Artifact-grounded research agent")
    paper_artifact_builder.write_fallback(evidence)
    incomplete_gate = engine._paper_acceptance_gate(str(tmp_path))
    assert incomplete_gate["accepted"] is False
    assert any(
        "core scientific" in issue or "selected profile" in issue
        for issue in incomplete_gate["details"]["issues"]
    )

    source_manifest = json.loads(
        (tmp_path / "experiments" / "results" / "SECONDARY_EVIDENCE.json").read_text(
            encoding="utf-8"
        )
    )
    source_manifest["sources"][0]["sha256"] = "0" * 64
    (tmp_path / "experiments" / "results" / "SECONDARY_EVIDENCE.json").write_text(
        json.dumps(source_manifest), encoding="utf-8"
    )
    invalid_plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="secondary_analysis",
    )
    assert invalid_plan["submission_eligible"] is False
    assert any("SHA256 does not match" in issue for issue in invalid_plan["missing_requirements"])


def test_fallback_paper_uses_structured_contracts_not_raw_research_notes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    (tmp_path / "ideas" / "ideas.md").write_text(
        "# Raw Idea Log\nUnified Scoring Rubric\nIdea 1 is selected because it.\n",
        encoding="utf-8",
    )
    (tmp_path / "literature" / "survey.md").write_text(
        "# Search Protocol\nQueries executed. Unknown from search snippet.\n",
        encoding="utf-8",
    )
    _build_figures(tmp_path)

    evidence = paper_artifact_builder.prepare(tmp_path, "Artifact-grounded research agent")
    paper = paper_artifact_builder.write_fallback(evidence).read_text(encoding="utf-8")

    assert "Unified Scoring Rubric" not in paper
    assert "Idea 1 is selected because it" not in paper
    assert "Queries executed" not in paper
    assert "\\begin{equation}" in paper
    assert "publication\\_ready" not in paper
    assert not re.search(r"(?<![A-Za-z0-9])(?:C|M|F|I)\d+(?![A-Za-z0-9])", paper)


def test_paper_gate_rejects_assets_that_are_appended_without_prose_use(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    engine = _build_figures(tmp_path)
    evidence = paper_artifact_builder.prepare(tmp_path, "Artifact-grounded research agent")
    main_path = paper_artifact_builder.write_fallback(evidence)
    content = main_path.read_text(encoding="utf-8")
    content = content.replace(
        "\\ref{fig:method-architecture}",
        "the method asset",
    )
    main_path.write_text(content, encoding="utf-8")

    gate = engine._paper_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert any(
        "never referenced in prose: fig:method-architecture" in issue
        for issue in gate["details"]["issues"]
    )


def test_executed_evidence_generates_quantitative_figure_and_result_table(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MERAK_ENABLE_EXTERNAL_FIGURE_RENDERERS", raising=False)
    _seed_project(tmp_path)
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.write_text(
        "# Analysis\nExecuted matched comparison; uncertainty is reported across seeds.",
        encoding="utf-8",
    )
    metrics = tmp_path / "experiments" / "results" / "main_comparison.csv"
    rows = [
        {
            "status": "completed",
            "method": method,
            "seed": str(seed),
            "split": "test",
            "metric": "macro_f1",
            "value": f"{value:.3f}",
        }
        for method, values in {
            "Matched baseline": (0.61, 0.63, 0.62),
            "Proposed method": (0.68, 0.70, 0.69),
        }.items()
        for seed, value in enumerate(values, start=1)
    ]
    with metrics.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    now = time.time()
    execution_provenance_service.record(
        tmp_path,
        "figure-evidence",
        "Bash",
        {"command": "python experiments/src/train.py --config experiments/configs/main.yaml"},
        True,
        now - 1,
        now,
        "[exit code: 0]",
    )

    engine = WorkflowEngine()
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={"run_experiment": True},
    )
    executed_plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=True,
        requested_evidence_mode="executed",
    )
    _author_plan_figures(tmp_path, executed_plan)
    asyncio.run(
        engine._ensure_figure_artifacts(
            run,
            "Executed matched comparison",
            "Artifact-grounded research agent",
        )
    )

    plan = json.loads(
        (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").read_text(encoding="utf-8")
    )
    assert plan["evidence_mode"] == "executed"
    assert not plan["missing_requirements"]
    assert any(item["id"] == "main_comparison" for item in plan["assets"])

    manifest = json.loads(
        (tmp_path / "figures" / "FIGURE_MANIFEST.json").read_text(encoding="utf-8")
    )
    main_figure = next(
        item for item in manifest["figures"]
        if (item.get("metadata") or {}).get("semantic_key") == "main_comparison"
    )
    assert main_figure["paper_ready"] is True
    assert main_figure["editable"] is True
    assert main_figure["metadata"]["evidence_status"] == "executed"
    assert main_figure["metadata"]["source_data"] == [
        "experiments/results/main_comparison.csv"
    ]

    evidence = paper_artifact_builder.prepare(tmp_path, "Artifact-grounded research agent")
    paper = paper_artifact_builder.write_fallback(evidence).read_text(encoding="utf-8")
    assert "\\input{tables/main_results}" in paper
    assert "\\ref{fig:main-comparison}" in paper
    table_manifest = json.loads(
        (tmp_path / "paper" / "tables" / "TABLE_MANIFEST.json").read_text(encoding="utf-8")
    )
    main_table = next(item for item in table_manifest["tables"] if item["id"] == "main_results")
    assert main_table["evidence_status"] == "executed"
    assert main_table["uncertainty_encoding"]
    assert engine._figure_acceptance_gate(str(tmp_path))["accepted"] is True
    incomplete_gate = engine._paper_acceptance_gate(str(tmp_path))
    assert incomplete_gate["accepted"] is False
    assert any(
        "core scientific" in issue or "selected profile" in issue
        for issue in incomplete_gate["details"]["issues"]
    )


def test_design_only_does_not_silently_promote_prior_runtime_results(
    tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    metrics = tmp_path / "experiments" / "results" / "prior_metrics.csv"
    metrics.write_text(
        "status,method,seed,split,metric,value\n"
        "completed,Reference,1,test,accuracy,0.70\n"
        "completed,Proposed,1,test,accuracy,0.74\n",
        encoding="utf-8",
    )
    now = time.time()
    execution_provenance_service.record(
        tmp_path,
        "prior-run",
        "Bash",
        {"command": "python train.py"},
        True,
        now - 1,
        now,
        "[exit code: 0]",
    )

    plan = scientific_asset_service.build_plan(
        tmp_path,
        experiment_requested=False,
        requested_evidence_mode="design_only",
    )

    assert plan["evidence_mode"] == "design_only"
    assert plan["submission_eligible"] is False
    assert all(item["id"] != "main_comparison" for item in plan["assets"])


def test_figure_gate_rejects_retired_skipped_empty_phase_2b_without_migration(
    tmp_path: Path,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir(parents=True)
    (figures / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "schema": 2,
            "evidence_mode": "design_only",
            "submission_eligible": False,
            "experiment_requested": False,
            "illustration_mode": "false",
            "assets": [
                {
                    "id": "method_architecture",
                    "kind": "figure",
                    "generation_phase": "phase_2b",
                    "generation_policy": "skip",
                    "required": False,
                    "manuscript_eligible": False,
                },
                {
                    "id": "evaluation_design",
                    "kind": "figure",
                    "generation_phase": "phase_2b",
                    "generation_policy": "skip",
                    "required": False,
                    "manuscript_eligible": False,
                },
            ],
        }),
        encoding="utf-8",
    )
    (figures / "FIGURE_SPECS.json").write_text(
        json.dumps({
            "schema": 3,
            "evidence_mode": "design_only",
            "illustration_mode": "false",
            "generator_policy": "original-paper-writing-phase2-v2",
            "figures": [],
        }),
        encoding="utf-8",
    )
    figure_artifact_registry.reconcile(figures)
    before = {path: path.read_bytes() for path in figures.iterdir() if path.is_file()}

    gate = WorkflowEngine()._figure_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert all(path.read_bytes() == content for path, content in before.items())
