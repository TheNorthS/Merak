from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.services.latex_bundle import latex_source_bundle
from server.services.paper_artifacts import (
    PaperEvidence,
    TABLE_MANIFEST_SCHEMA,
    bind_table_manifest_hashes,
    paper_artifact_builder,
)
from server.services.project_scaffold import get_workflow_artifact_contract
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def test_study_design_table_expands_nested_runtime_contract(
    tmp_path: Path,
) -> None:
    evidence = PaperEvidence(
        root=tmp_path,
        title="Auditable benchmark",
        direction="benchmark",
        idea_text="",
        survey_text="",
        narrative_text="",
        plan_text="",
        analysis_text="",
        run_spec={
            "seeds": [13, 42, 73],
            "matrix": {
                "models": ["linear_reference", "residual_mlp"],
                "protocol_conditions": ["base", "architecture_single_factor"],
                "final_partitions": ["iid_test", "shift_test"],
            },
            "resources": {
                "max_epochs_per_run": 20,
                "hyperparameter_trials_per_model_protocol": 0,
                "efficiency_warmup_iterations": 10,
                "efficiency_measured_iterations": 30,
            },
        },
        resolved_config={
            "method": {
                "calibration": {
                    "method": "temperature_scaling",
                    "fit_partition": "calibration",
                },
                "efficiency_measurement": {
                    "precision": "float32",
                    "batch_size": 32,
                },
            },
            "execution": {"max_epochs": 20},
            "evaluation": {"primary_metric": "balanced_accuracy"},
        },
        selected_idea={
            "mechanisms": [
                {"id": "M1", "name": "记录身份捷径抑制一致性",
                 "publication_name": "Record-identity consistency objective",
                 "publication_description": "Restrict identity shortcuts in representations.",
                 "publication_evaluation": "Compare identity-probe accuracy under matched task utility."},
                {"id": "M2", "name": "频谱—拓扑结构掩码预测",
                 "publication_name": "Spectral-topological masked prediction",
                 "publication_description": "Predict masked spectral and topological observations.",
                 "publication_evaluation": "Compare reconstruction errors under matched masking."},
                {"id": "M3", "name": "严格域外与导联压力测试",
                 "publication_name": "Held-out montage stress evaluation",
                 "publication_description": "Evaluate the declared held-out montage conditions.",
                 "publication_evaluation": "Compare held-out task performance by montage condition."},
                {"id": "M4", "name": "计算匹配因果消融",
                 "publication_name": "Compute-matched causal ablation",
                 "publication_description": "Remove one component with matched compute.",
                 "publication_evaluation": "Compare each independently declared removal."},
            ],
        },
    )

    paper_artifact_builder._write_submission_tables(evidence)
    table = (tmp_path / "paper" / "tables" / "study_design.tex").read_text(
        encoding="utf-8"
    )

    for label in (
        "Candidate models",
        "Study conditions",
        "Protected partitions",
        "Training and tuning budget",
        "Calibration protocol",
        "Compute measurement contract",
    ):
        assert label in table
    assert "Balanced accuracy" in table
    assert "balanced\\_accuracy" not in table
    method_table = (
        tmp_path / "paper" / "tables" / "method_components.tex"
    ).read_text(encoding="utf-8")
    for label in (
        "Record-identity consistency objective",
        "Spectral-topological masked prediction",
        "Held-out montage stress evaluation",
        "Compute-matched causal ablation",
    ):
        assert label in method_table
    assert "Prespecified method component" not in method_table


def test_latex_bundle_follows_main_dependency_graph_and_local_assets(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper"
    main = _write(
        paper / "main.tex",
        "\\documentclass{venue}\\usepackage{localstyle}\n"
        "\\graphicspath{{../figures/}}\n"
        "\\begin{document}\\input{sections/body}\n"
        "\\input{tables/results}\\addbibresource{../literature/references.bib}\n"
        "\\end{document}\n",
    )
    section = _write(
        paper / "sections" / "body.tex",
        "\\includegraphics{result}\n",
    )
    table = _write(paper / "tables" / "results.tex", "A & B \\\\\n")
    style = _write(paper / "localstyle.sty", "\\ProvidesPackage{localstyle}\n")
    venue = _write(paper / "venue.cls", "\\ProvidesClass{venue}\n")
    graphic = _write(tmp_path / "figures" / "result.png", b"png-data")
    bibliography = _write(
        tmp_path / "literature" / "references.bib",
        "@article{x,title={X}}\n",
    )
    unused = _write(paper / "sections" / "unused.tex", "unused draft\n")

    first_hash, first_paths = latex_source_bundle(paper)
    relative = {path.relative_to(tmp_path).as_posix() for path in first_paths}
    assert relative == {
        "paper/main.tex",
        "paper/sections/body.tex",
        "paper/tables/results.tex",
        "paper/localstyle.sty",
        "paper/venue.cls",
        "figures/result.png",
        "literature/references.bib",
    }

    unused.write_text("changed but unreachable\n", encoding="utf-8")
    unchanged_hash, _ = latex_source_bundle(paper)
    assert unchanged_hash == first_hash

    section.write_text("\\includegraphics{result}\nchanged\n", encoding="utf-8")
    changed_hash, _ = latex_source_bundle(paper)
    assert changed_hash != first_hash
    assert all(path.is_file() for path in (main, table, style, venue, graphic, bibliography))


def test_current_table_manifest_binds_hashes_and_detects_stale_data(
    tmp_path: Path,
) -> None:
    from server.services.paper_artifacts import build_table_manifest

    data = _write(tmp_path / "paper/tables/result.csv", "m,v\nA,1\n")
    latex = _write(tmp_path / "paper/tables/result.tex", "A & 1\n")
    manifest = build_table_manifest(tmp_path, [{
        "id": "result", "data_path": "paper/tables/result.csv",
        "latex_path": "paper/tables/result.tex",
    }])
    checked, issues, changed = bind_table_manifest_hashes(tmp_path, manifest)
    assert issues == [] and changed is False
    assert checked["schema"] == TABLE_MANIFEST_SCHEMA
    assert checked["tables"][0]["data_sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()
    assert checked["tables"][0]["latex_sha256"] == hashlib.sha256(latex.read_bytes()).hexdigest()
    data.write_text("m,v\nA,2\n", encoding="utf-8")
    _, issues, changed = bind_table_manifest_hashes(tmp_path, manifest)
    assert changed is False
    assert any("data_sha256 does not match" in issue for issue in issues)


def test_figure_acceptance_snapshot_binds_outputs_sources_previews_and_variants(
    tmp_path: Path,
) -> None:
    output = _write(tmp_path / "figures" / "plots" / "result.png", b"output")
    source = _write(tmp_path / "figures" / "plots" / "result.py", "plot()\n")
    preview = _write(tmp_path / "figures" / "plots" / "preview.png", b"preview")
    svg = _write(tmp_path / "figures" / "plots" / "result.svg", "<svg/>\n")
    protocol = _write(
        tmp_path / "figures" / "reviews" / "review.json",
        '{"verdict":"accept"}\n',
    )
    source_data = _write(
        tmp_path / "experiments" / "results" / "metrics.csv",
        "metric,value\nrmse,1\n",
    )
    for relative, payload in (
        ("figures/SCIENTIFIC_ASSET_PLAN.json", {"assets": []}),
        ("figures/FIGURE_SPECS.json", {"figures": []}),
        (
            "figures/FIGURE_MANIFEST.json",
            {
                "figures": [{
                    "output_path": output.relative_to(tmp_path).as_posix(),
                    "source_path": source.relative_to(tmp_path).as_posix(),
                    "preview_path": preview.relative_to(tmp_path).as_posix(),
                    "metadata": {
                        "source_data": [source_data.relative_to(tmp_path).as_posix()],
                        "rendered_variants": {
                            "svg": svg.relative_to(tmp_path).as_posix(),
                        },
                        "protocol_artifacts": {
                            "review": protocol.relative_to(tmp_path).as_posix(),
                        },
                    },
                }],
            },
        ),
    ):
        _write(tmp_path / relative, json.dumps(payload))

    run = WorkflowRun(id="figure-snapshot", project_path=str(tmp_path))
    gate = {"details": {}}
    WorkflowEngine()._bind_gate_artifact_snapshot(
        WorkflowNode(id="figure", name="Figure", skill="/research-figure"),
        run,
        gate,
    )

    snapshot = gate["details"]["artifact_snapshot"]
    assert gate["details"]["artifact_snapshot_schema"] == 2
    for path in (output, source, preview, svg, protocol, source_data):
        assert path.relative_to(tmp_path).as_posix() in snapshot


def test_paper_snapshot_and_revision_signature_cover_staged_dependencies(
    tmp_path: Path,
) -> None:
    section = _write(tmp_path / "paper" / "sections" / "introduction.tex", "draft one\n")
    _write(
        tmp_path / "paper" / "DRAFT_STATE.json",
        json.dumps({"status": "writing", "reviewed_at": 1, "attempts": 1}),
    )
    _write(
        tmp_path / "paper" / "SECTION_REVIEWS.json",
        json.dumps({"Introduction": {"accepted": False, "reviewed_at": 1}}),
    )
    engine = WorkflowEngine()
    first = engine._revision_artifact_signature(str(tmp_path), "paper")

    state = tmp_path / "paper" / "DRAFT_STATE.json"
    state.write_text(
        json.dumps({"status": "writing", "reviewed_at": 2, "attempts": 9}),
        encoding="utf-8",
    )
    metadata_only = engine._revision_artifact_signature(str(tmp_path), "paper")
    assert metadata_only == first

    section.write_text("draft two with falsifiable contribution\n", encoding="utf-8")
    semantic_change = engine._revision_artifact_signature(str(tmp_path), "paper")
    assert semantic_change != first


def test_paper_acceptance_snapshot_binds_run_contract_and_analysis(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Paper\\end{document}\n",
    )
    run_spec = _write(
        tmp_path / "experiments" / "RUN_SPEC.json",
        '{"schema": 1}\n',
    )
    analysis = _write(
        tmp_path / "experiments" / "results" / "analysis.md",
        "# Analysis\n\nResult one.\n",
    )
    freeze = _write(
        tmp_path / "paper" / "SCIENTIFIC_FREEZE.json",
        '{"schema_version": 1, "inputs": {}}\n',
    )
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="paper", name="Paper", skill="/paper-write"),
        WorkflowRun(id="paper-inputs", project_path=str(tmp_path)),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    for path in (run_spec, analysis, freeze):
        assert path.relative_to(tmp_path).as_posix() in snapshot
    analysis.write_text("# Analysis\n\nResult two.\n", encoding="utf-8")
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)


def test_paper_acceptance_snapshot_excludes_derived_evidence_map(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}paper\\end{document}\n",
    )
    evidence_map = _write(
        tmp_path / ".merak" / "research_audit" / "PAPER_EVIDENCE_MAP.json",
        '{"schema":2,"updated_at":1}\n',
    )
    gate = {"details": {}}
    engine = WorkflowEngine()

    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="paper", name="Paper", skill="/domain-paper-write"),
        WorkflowRun(id="paper-snapshot", project_path=str(tmp_path)),
        gate,
    )

    evidence_key = evidence_map.relative_to(tmp_path).as_posix()
    assert evidence_key not in gate["details"]["artifact_snapshot"]
    evidence_map.write_text(
        '{"schema":2,"updated_at":2}\n',
        encoding="utf-8",
    )
    assert not engine._artifact_snapshot_issues(
        tmp_path,
        gate["details"]["artifact_snapshot"],
    )


def test_revision_signature_uses_option_dependent_no_run_and_literature_paths(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "experiments" / "src" / "train.py", "print(1)\n")
    _write(tmp_path / "experiments" / "configs" / "main.yaml", "seed: 1\n")
    engine = WorkflowEngine()
    no_run = {"run_experiment": False}
    first = engine._revision_artifact_signature(str(tmp_path), "exp-run", no_run)
    source.write_text("print(2)\n", encoding="utf-8")
    second = engine._revision_artifact_signature(str(tmp_path), "exp-run", no_run)
    assert second != first

    zotero = _write(
        tmp_path / "literature" / "zotero_context.json",
        json.dumps({"items": ["A"]}),
    )
    lit_options = {
        "enable_zotero": True,
        "research_strategy": {"literature_sources": ["zotero"]},
    }
    lit_first = engine._revision_artifact_signature(str(tmp_path), "lit", lit_options)
    zotero.write_text(json.dumps({"items": ["A", "B"]}), encoding="utf-8")
    lit_second = engine._revision_artifact_signature(str(tmp_path), "lit", lit_options)
    assert lit_second != lit_first


def test_revision_scope_ignores_review_report_operational_metadata(
    tmp_path: Path,
) -> None:
    report = _write(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        json.dumps({"reviewed_at": 1, "attempts": 1, "issues": ["same"]}),
    )
    paper = _write(tmp_path / "paper" / "main.tex", "stable manuscript\n")
    diagnostics = {
        "repair_scope": {
            "target_files": [
                report.relative_to(tmp_path).as_posix(),
                paper.relative_to(tmp_path).as_posix(),
            ],
        },
    }
    engine = WorkflowEngine()
    first = engine._revision_scope_signature(str(tmp_path), "review", diagnostics)
    report.write_text(
        json.dumps({"reviewed_at": 2, "attempts": 4, "issues": ["same"]}),
        encoding="utf-8",
    )
    assert (
        engine._revision_scope_signature(str(tmp_path), "review", diagnostics)
        == first
    )
    paper.write_text("semantic manuscript change\n", encoding="utf-8")
    assert (
        engine._revision_scope_signature(str(tmp_path), "review", diagnostics)
        != first
    )


def test_paper_contract_declares_table_manifest() -> None:
    contract = get_workflow_artifact_contract("project", "paper")
    assert any(
        Path(path).as_posix().endswith("paper/tables/TABLE_MANIFEST.json")
        for path in contract["required"]
    )


def test_paper_gate_rejects_table_content_changed_after_manifest_binding(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Text\\end{document}\n",
    )
    _write(
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json",
        json.dumps({"evidence_mode": "design_only", "assets": []}),
    )
    tables = []
    for table_id in ("study_design", "method_components"):
        data = _write(
            tmp_path / "paper" / "tables" / f"{table_id}.csv",
            "name,value\nA,1\n",
        )
        latex = _write(
            tmp_path / "paper" / "tables" / f"{table_id}.tex",
            "\\begin{tabular}{ll}A&1\\\\\\end{tabular}\n",
        )
        tables.append({
            "id": table_id,
            "scientific_role": table_id,
            "data_path": data.relative_to(tmp_path).as_posix(),
            "latex_path": latex.relative_to(tmp_path).as_posix(),
            "data_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
            "latex_sha256": hashlib.sha256(latex.read_bytes()).hexdigest(),
            "source_data": [data.relative_to(tmp_path).as_posix()],
        })
    _write(
        tmp_path / "paper" / "tables" / "TABLE_MANIFEST.json",
        json.dumps({"schema": TABLE_MANIFEST_SCHEMA, "tables": tables}),
    )
    (tmp_path / tables[0]["data_path"]).write_text(
        "name,value\nA,2\n",
        encoding="utf-8",
    )

    gate = WorkflowEngine()._paper_acceptance_gate(str(tmp_path))
    issues = gate.get("details", {}).get("issues", [])
    assert any("data_sha256 does not match" in issue for issue in issues)


def test_managed_experiment_snapshot_binds_declared_raw_evidence(
    tmp_path: Path,
) -> None:
    raw_metric = _write(
        tmp_path / "experiments" / "results" / "seed_1" / "metrics.json",
        '{"rmse": 1.0}\n',
    )
    _write(tmp_path / "experiments" / "RUN_SPEC.json", '{"outputs": {}}\n')
    manifest = _write(
        tmp_path / ".merak" / "experiments" / "job" / "run.json",
        json.dumps({
            "status": "completed",
            "current_attempt": 1,
            "attempts": [{
                "attempt": 1,
                "status": "completed",
                "result_artifacts": {
                    raw_metric.relative_to(tmp_path).as_posix(): {
                        "sha256": hashlib.sha256(raw_metric.read_bytes()).hexdigest(),
                        "bytes": raw_metric.stat().st_size,
                    },
                },
            }],
        }),
    )
    run = WorkflowRun(
        id="managed-raw",
        project_path=str(tmp_path),
        options={"run_experiment": True},
    )
    gate = {"details": {"manifest_paths": [str(manifest)]}}
    engine = WorkflowEngine()
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="exp-run", name="Run", skill="/experiment-bridge"),
        run,
        gate,
    )

    snapshot = gate["details"]["artifact_snapshot"]
    raw_key = raw_metric.relative_to(tmp_path).as_posix()
    assert raw_key in snapshot
    raw_metric.write_text('{"rmse": 2.0}\n', encoding="utf-8")
    assert any(
        raw_key in issue
        for issue in engine._artifact_snapshot_issues(tmp_path, snapshot)
    )


def test_other_accepted_snapshots_bind_raw_results_trace_and_compile_source(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()

    analysis = _write(
        tmp_path / "experiments" / "results" / "analysis.md",
        "analysis\n",
    )
    raw = _write(
        tmp_path / "experiments" / "results" / "predictions.csv",
        "y,p\n1,1\n",
    )
    results_gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="results", name="Results", skill="/analyze-results"),
        WorkflowRun(id="results", project_path=str(tmp_path), options={
            "run_experiment": False, "non_experiment_evidence_mode": "existing_results",
        }),
        results_gate,
    )
    raw.write_text("y,p\n1,0\n", encoding="utf-8")
    assert engine._artifact_snapshot_issues(
        tmp_path,
        results_gate["details"]["artifact_snapshot"],
    )

    paper = _write(tmp_path / "paper" / "main.tex", "reviewed source\n")
    trace = tmp_path / "review-stage" / "trace"
    trace_meta = _write(trace / "meta.json", '{"model":"reviewer"}\n')
    _write(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        json.dumps({"_review_trace_path": str(trace)}),
    )
    review_gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="review", name="Review", skill="/auto-review-loop"),
        WorkflowRun(id="review", project_path=str(tmp_path)),
        review_gate,
    )
    trace_meta.write_text('{"model":"another"}\n', encoding="utf-8")
    assert engine._artifact_snapshot_issues(
        tmp_path,
        review_gate["details"]["artifact_snapshot"],
    )

    _write(tmp_path / "paper" / "main.pdf", b"%PDF-1.4\n")
    _write(tmp_path / "paper" / "PAPER_BUILD.json", '{"status":"built"}\n')
    compile_gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="compile", name="Compile", skill="/paper-compile"),
        WorkflowRun(id="compile", project_path=str(tmp_path)),
        compile_gate,
    )
    paper.write_text("changed compile source\n", encoding="utf-8")
    assert engine._artifact_snapshot_issues(
        tmp_path,
        compile_gate["details"]["artifact_snapshot"],
    )
    assert analysis.is_file()


def test_accepted_results_snapshot_persists_analysis_input_hash_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    metric = _write(
        tmp_path / "experiments" / "results" / "accepted" / "metrics.csv",
        "run_id,seed,metric\nr1,1,0.5\n",
    )
    _write(
        tmp_path / "experiments" / "results" / "analysis.md",
        "# Analysis\nBounded result with uncertainty and limitations.\n",
    )
    monkeypatch.setattr(
        "server.services.execution_provenance.execution_provenance_service.proven_result_sources",
        lambda _root, **_kwargs: {metric.relative_to(tmp_path).as_posix()},
    )
    gate = {"details": {}}
    WorkflowEngine()._bind_gate_artifact_snapshot(
        WorkflowNode(id="results", name="Results", skill="/analyze-results"),
        WorkflowRun(
            id="results-binding",
            project_path=str(tmp_path),
            options={"run_experiment": True},
        ),
        gate,
    )

    build_path = tmp_path / "experiments" / "results" / "ANALYSIS_BUILD.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    assert build["analysis_sha256"]
    assert build["source_artifact_sha256"][
        metric.relative_to(tmp_path).as_posix()
    ] == hashlib.sha256(metric.read_bytes()).hexdigest()
    assert gate["details"]["analysis_source_bundle_sha256"]
    assert "experiments/results" in gate["details"]["artifact_snapshot"]


def test_attempt_record_semantics_are_preserved_but_timing_churn_is_ignored(
    tmp_path: Path,
) -> None:
    manifest = _write(
        tmp_path / ".merak" / "experiments" / "job" / "run.json",
        json.dumps({
            "status": "completed",
            "current_attempt": 1,
            "retry_count": 0,
            "attempts": [{
                "attempt": 1,
                "status": "completed",
                "started_at": 1,
                "finished_at": 2,
                "result_artifacts": {
                    "experiments/results/metrics.json": {"sha256": "a" * 64},
                },
            }],
        }),
    )
    engine = WorkflowEngine()
    options = {"run_experiment": False, "non_experiment_evidence_mode": "existing_results"}
    first = engine._revision_artifact_signature(str(tmp_path), "results", options)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["retry_count"] = 7
    payload["attempts"][0]["started_at"] = 10
    payload["attempts"][0]["finished_at"] = 20
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    timing_only = engine._revision_artifact_signature(str(tmp_path), "results", options)
    assert timing_only == first

    payload["attempts"][0]["status"] = "failed"
    payload["attempts"][0]["result_artifacts"][
        "experiments/results/metrics.json"
    ]["sha256"] = "b" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    semantic_change = engine._revision_artifact_signature(str(tmp_path), "results", options)
    assert semantic_change != first


def test_managed_exp_run_signature_ignores_timing_but_tracks_run_semantics(
    tmp_path: Path,
) -> None:
    raw_metric = _write(
        tmp_path / "experiments" / "results" / "metrics.json",
        '{"rmse": 1.0}\n',
    )
    _write(tmp_path / "experiments" / "RUN_SPEC.json", '{"schema": 1}\n')
    manifest = _write(
        tmp_path / ".merak" / "experiments" / "job" / "run.json",
        json.dumps({
            "status": "completed",
            "updated_at": 1,
            "mtime": 1,
            "current_attempt": 1,
            "attempts": [{
                "attempt": 1,
                "status": "completed",
                "started_at": 1,
                "finished_at": 2,
                "result_artifacts": {
                    raw_metric.relative_to(tmp_path).as_posix(): {
                        "sha256": hashlib.sha256(raw_metric.read_bytes()).hexdigest(),
                    },
                },
            }],
        }),
    )
    engine = WorkflowEngine()
    options = {"run_experiment": True}
    first = engine._revision_artifact_signature(str(tmp_path), "exp-run", options)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["updated_at"] = 99
    payload["mtime"] = 99
    payload["attempts"][0]["started_at"] = 50
    payload["attempts"][0]["finished_at"] = 60
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        engine._revision_artifact_signature(str(tmp_path), "exp-run", options)
        == first
    )

    payload["attempts"][0]["status"] = "failed"
    payload["attempts"][0]["result_artifacts"][
        raw_metric.relative_to(tmp_path).as_posix()
    ]["sha256"] = "b" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        engine._revision_artifact_signature(str(tmp_path), "exp-run", options)
        != first
    )


def test_figure_revision_signature_tracks_executed_paper_plan(
    tmp_path: Path,
) -> None:
    for relative in (
        "figures/SCIENTIFIC_ASSET_PLAN.json",
        "figures/FIGURE_SPECS.json",
        "figures/FIGURE_MANIFEST.json",
    ):
        _write(tmp_path / relative, '{"assets": [], "figures": []}\n')
    plan = _write(
        tmp_path / "paper" / "PAPER_PLAN.md",
        "# Plan\n\nFigure 1 supports claim C1.\n",
    )
    engine = WorkflowEngine()
    first = engine._revision_artifact_signature(str(tmp_path), "figure")
    plan.write_text(
        "# Plan\n\nFigure 1 now supports falsifiable claim C2.\n",
        encoding="utf-8",
    )
    assert engine._revision_artifact_signature(str(tmp_path), "figure") != first


def test_review_snapshot_and_signature_bind_pdf_preview_layout_and_trace(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Reviewed\\end{document}\n",
    )
    pdf = _write(tmp_path / "paper" / "main.pdf", b"%PDF-review-one\n")
    preview = _write(
        tmp_path / "review-stage" / "previews" / "page-1.png",
        b"preview-one",
    )
    layout = _write(
        tmp_path / "review-stage" / "layout.json",
        '{"status": "clean"}\n',
    )
    trace_meta = _write(
        tmp_path / "review-stage" / "trace" / "meta.json",
        '{"reviewer": "one"}\n',
    )
    _write(
        tmp_path / "review-stage" / "REVIEW_STATE.json",
        json.dumps({
            "preview_path": preview.relative_to(tmp_path).as_posix(),
            "layout_report_path": layout.relative_to(tmp_path).as_posix(),
            "_review_trace_path": trace_meta.parent.relative_to(tmp_path).as_posix(),
        }),
    )
    engine = WorkflowEngine()
    run = WorkflowRun(id="review-closure", project_path=str(tmp_path))
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="review", name="Review", skill="/auto-review-loop"),
        run,
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    assert pdf.relative_to(tmp_path).as_posix() in snapshot
    assert preview.relative_to(tmp_path).as_posix() in snapshot
    assert layout.relative_to(tmp_path).as_posix() in snapshot
    assert trace_meta.parent.relative_to(tmp_path).as_posix() in snapshot
    first = engine._revision_artifact_signature(str(tmp_path), "review")

    pdf.write_bytes(b"%PDF-review-two\n")
    preview.write_bytes(b"preview-two")
    layout.write_text('{"status": "overflow"}\n', encoding="utf-8")
    trace_meta.write_text('{"reviewer": "two"}\n', encoding="utf-8")
    issues = engine._artifact_snapshot_issues(tmp_path, snapshot)
    assert len(issues) >= 4
    assert engine._revision_artifact_signature(str(tmp_path), "review") != first


def test_audit_snapshot_and_signature_bind_raw_results_and_paper_source(
    tmp_path: Path,
) -> None:
    paper = _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Claim one\\end{document}\n",
    )
    raw = _write(
        tmp_path / "experiments" / "results" / "predictions.csv",
        "target,prediction\n1,1\n",
    )
    _write(tmp_path / "experiments" / "RUN_SPEC.json", '{"schema": 1}\n')
    _write(tmp_path / "audit-results" / "AUDIT_RESULTS.json", '{"status":"pass"}\n')
    _write(tmp_path / "audit-results" / "AUDIT_BUILD.json", '{"status":"pass"}\n')
    _write(tmp_path / "paper" / "PROOF_AUDIT.json", '{"status":"pass"}\n')
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="audit", name="Audit", skill="/experiment-audit"),
        WorkflowRun(id="audit-closure", project_path=str(tmp_path)),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    first = engine._revision_artifact_signature(str(tmp_path), "audit")

    raw.write_text("target,prediction\n1,0\n", encoding="utf-8")
    assert engine._revision_artifact_signature(str(tmp_path), "audit") != first
    raw.write_text("target,prediction\n1,1\n", encoding="utf-8")
    paper.write_text(
        "\\documentclass{article}\\begin{document}Claim two\\end{document}\n",
        encoding="utf-8",
    )
    assert engine._revision_artifact_signature(str(tmp_path), "audit") != first
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)


def test_ppt_snapshot_and_signature_bind_slide_bundle_build_and_figure_inputs(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Paper\\end{document}\n",
    )
    figure = _write(tmp_path / "figures" / "plots" / "result.png", b"figure-one")
    figure_manifest = _write(
        tmp_path / "figures" / "FIGURE_MANIFEST.json",
        json.dumps({
            "figures": [{
                "output_path": figure.relative_to(tmp_path).as_posix(),
            }],
        }),
    )
    section = _write(
        tmp_path / "slides" / "sections" / "results.tex",
        "\\begin{frame}Result one\\end{frame}\n",
    )
    _write(
        tmp_path / "slides" / "main.tex",
        "\\documentclass{beamer}\\begin{document}"
        "\\input{sections/results}\\end{document}\n",
    )
    pdf = _write(tmp_path / "slides" / "main.pdf", b"%PDF-slide-one\n")
    build = _write(
        tmp_path / "slides" / "SLIDE_BUILD.json",
        '{"status": "built"}\n',
    )
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="ppt", name="Slides", skill="/paper-talk"),
        WorkflowRun(id="ppt-closure", project_path=str(tmp_path)),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    for path in (section, pdf, build, figure, figure_manifest):
        assert path.relative_to(tmp_path).as_posix() in snapshot
    first = engine._revision_artifact_signature(str(tmp_path), "ppt")

    section.write_text("\\begin{frame}Result two\\end{frame}\n", encoding="utf-8")
    pdf.write_bytes(b"%PDF-slide-two\n")
    build.write_text('{"status": "failed"}\n', encoding="utf-8")
    figure.write_bytes(b"figure-two")
    figure_manifest.write_text(
        json.dumps({
            "figures": [{
                "output_path": figure.relative_to(tmp_path).as_posix(),
                "scientific_role": "updated-result",
            }],
        }),
        encoding="utf-8",
    )
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)
    assert engine._revision_artifact_signature(str(tmp_path), "ppt") != first


def test_literature_snapshot_and_signature_bind_runtime_search_evidence(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "literature" / "survey.md", "# Survey\n")
    _write(
        tmp_path / "literature" / "references.bib",
        "@article{one,title={One},author={A},year={2025}}\n",
    )
    strategy = _write(
        tmp_path / ".merak" / "research_strategy.json",
        json.dumps({"run_id": "run-1", "literature_sources": ["arxiv"]}),
    )
    evidence = _write(
        tmp_path / "literature" / "SEARCH_EVIDENCE.json",
        json.dumps({
            "run_id": "run-1",
            "stages": {
                "lit": {
                    "source_usage": {"arxiv": {"status": "used"}},
                },
            },
        }),
    )
    options = {
        "research_strategy": {"literature_sources": ["arxiv"]},
    }
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="lit", name="Literature", skill="/lit-review"),
        WorkflowRun(
            id="lit-closure",
            project_path=str(tmp_path),
            options=options,
        ),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    for path in (strategy, evidence):
        assert path.relative_to(tmp_path).as_posix() in snapshot
    first = engine._revision_artifact_signature(str(tmp_path), "lit", options)

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["stages"]["lit"]["source_usage"]["arxiv"]["status"] = "failed"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)
    assert engine._revision_artifact_signature(str(tmp_path), "lit", options) != first


def test_no_run_snapshot_and_signature_bind_planned_result_manifest(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "experiments" / "src" / "train.py", "print('planned')\n")
    _write(tmp_path / "experiments" / "configs" / "main.yaml", "seed: 1\n")
    manifest = _write(
        tmp_path
        / "experiments"
        / "results"
        / "templates"
        / "PLANNED_RESULT_MANIFEST.json",
        json.dumps({
            "status": "planned_not_executed",
            "evidence_mode": "design_only",
        }),
    )
    options = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="exp-run", name="Run", skill="/run-experiment"),
        WorkflowRun(
            id="no-run-closure",
            project_path=str(tmp_path),
            options=options,
        ),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    assert manifest.relative_to(tmp_path).as_posix() in snapshot
    first = engine._revision_artifact_signature(str(tmp_path), "exp-run", options)

    manifest.write_text(
        json.dumps({
            "status": "synthetic_preview",
            "evidence_mode": "synthetic_preview",
        }),
        encoding="utf-8",
    )
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)
    assert (
        engine._revision_artifact_signature(str(tmp_path), "exp-run", options)
        != first
    )


def test_narrative_snapshot_and_signature_bind_build_sidecar_and_sources(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "NARRATIVE_REPORT.md", "# Narrative\n")
    _write(tmp_path / "paper" / "PAPER_PLAN.md", "# Paper plan\n")
    analysis = _write(
        tmp_path / "experiments" / "results" / "analysis.md",
        "# Analysis\nResult one.\n",
    )
    build = _write(
        tmp_path / ".merak" / "NARRATIVE_BUILD.json",
        json.dumps({
            "sources": [analysis.relative_to(tmp_path).as_posix()],
            "source_bundle_sha256": "a" * 64,
        }),
    )
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="narrative", name="Narrative", skill="/narrative"),
        WorkflowRun(id="narrative-closure", project_path=str(tmp_path)),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    for path in (build, analysis):
        assert path.relative_to(tmp_path).as_posix() in snapshot
    first = engine._revision_artifact_signature(str(tmp_path), "narrative")

    analysis.write_text("# Analysis\nResult two.\n", encoding="utf-8")
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)
    assert (
        engine._revision_artifact_signature(str(tmp_path), "narrative")
        != first
    )


def test_audit_snapshot_and_signature_bind_proof_checker_trace(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Proof\\end{document}\n",
    )
    _write(tmp_path / "experiments" / "RUN_SPEC.json", '{"schema": 1}\n')
    _write(tmp_path / "audit-results" / "AUDIT_RESULTS.json", '{"status":"pass"}\n')
    _write(tmp_path / "audit-results" / "AUDIT_BUILD.json", '{"status":"pass"}\n')
    trace = tmp_path / ".merak" / "proof-checker" / "trace"
    trace_output = _write(trace / "output.txt", "proof accepted\n")
    proof = _write(
        tmp_path / "paper" / "PROOF_AUDIT.json",
        json.dumps({
            "status": "pass",
            "trace_path": trace.relative_to(tmp_path).as_posix(),
        }),
    )
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="audit", name="Audit", skill="/experiment-audit"),
        WorkflowRun(id="proof-trace-closure", project_path=str(tmp_path)),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    assert trace.relative_to(tmp_path).as_posix() in snapshot
    first = engine._revision_artifact_signature(str(tmp_path), "audit")

    trace_output.write_text("proof rejected\n", encoding="utf-8")
    assert engine._artifact_snapshot_issues(tmp_path, snapshot)
    assert engine._revision_artifact_signature(str(tmp_path), "audit") != first
    assert proof.is_file()


def test_paper_snapshot_ignores_later_compile_outputs(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "paper" / "main.tex",
        "\\documentclass{article}\\begin{document}Paper\\end{document}\n",
    )
    build = _write(
        tmp_path / "paper" / "PAPER_BUILD.json",
        '{"status":"built","compile_time_ms":1}\n',
    )
    pdf = _write(tmp_path / "paper" / "main.pdf", b"%PDF-one\n")
    engine = WorkflowEngine()
    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="paper", name="Paper", skill="/paper-write"),
        WorkflowRun(id="paper-before-compile", project_path=str(tmp_path)),
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    assert build.relative_to(tmp_path).as_posix() not in snapshot
    assert pdf.relative_to(tmp_path).as_posix() not in snapshot

    build.write_text(
        '{"status":"built","compile_time_ms":99}\n',
        encoding="utf-8",
    )
    pdf.write_bytes(b"%PDF-two\n")
    assert not engine._artifact_snapshot_issues(tmp_path, snapshot)


def test_downstream_revision_signatures_track_evidence_mode_changes(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    planned = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }
    simulated = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    }

    for node_id in ("results", "figure", "narrative", "paper", "review", "audit", "ppt"):
        assert (
            engine._revision_artifact_signature(str(tmp_path), node_id, planned)
            != engine._revision_artifact_signature(
                str(tmp_path),
                node_id,
                simulated,
            )
        )
