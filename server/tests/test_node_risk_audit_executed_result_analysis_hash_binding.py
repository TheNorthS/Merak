from __future__ import annotations

from server.tests._node_risk_audit_support import (
    ApiVisualReview as ApiVisualReview,
    CrossModelReviewer as CrossModelReviewer,
    ExperimentHealthMonitor as ExperimentHealthMonitor,
    HealthPolicy as HealthPolicy,
    Path as Path,
    ProjectSnapshot as ProjectSnapshot,
    RunManifestStore as RunManifestStore,
    RuntimeSpec as RuntimeSpec,
    WorkflowEngine as WorkflowEngine,
    _api_review_result as _api_review_result,
    _patch_direct_reviewer_routes as _patch_direct_reviewer_routes,
    _sha256 as _sha256,
    _write_json as _write_json,
    api_visual_reviewer as api_visual_reviewer,
    experiment_runtime as experiment_runtime,
    hashlib as hashlib,
    json as json,
    node_risk_audit_service as node_risk_audit_service,
    os as os,
    pytest as pytest,
    shutil as shutil,
    time as time,
)


def test_executed_result_analysis_hash_binding_survives_copy_and_detects_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    metrics = results / "accepted" / "metrics.csv"
    metrics.parent.mkdir()
    metrics.write_text(
        "run_id,seed,metric\nr1,1,0.5\n",
        encoding="utf-8",
    )
    analysis = results / "analysis.md"
    analysis.write_text(
        "# Analysis\nC1 is bounded to the accepted run with uncertainty and limitations.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "server.services.execution_provenance.execution_provenance_service.proven_result_sources",
        lambda _root, **_kwargs: {metrics.relative_to(tmp_path).as_posix()},
    )
    options = {"run_experiment": True}
    build = node_risk_audit_service.bind_result_analysis_inputs(
        tmp_path,
        options,
    )
    build_path = results / "ANALYSIS_BUILD.json"
    assert build_path.is_file()
    assert build["source_artifact_sha256"][
        metrics.relative_to(tmp_path).as_posix()
    ] == _sha256(metrics)

    copied = tmp_path / "copied-metrics.csv"
    copied.write_bytes(metrics.read_bytes())
    future = time.time() + 120
    os.utime(copied, (future, future))
    shutil.copy2(copied, metrics)
    copied_findings = node_risk_audit_service._audit_results(tmp_path, options)
    assert not any(
        item["id"] == "RESULT-STALE-001" for item in copied_findings
    )

    bound_bytes = build_path.read_bytes()
    metrics.write_text(
        "run_id,seed,metric\nr1,1,0.9\n",
        encoding="utf-8",
    )
    old = analysis.stat().st_mtime - 120
    os.utime(metrics, (old, old))
    changed_findings = node_risk_audit_service._audit_results(tmp_path, options)
    stale = next(
        item for item in changed_findings if item["id"] == "RESULT-STALE-001"
    )
    assert stale["freshness_basis"] == "content_hashes"
    assert metrics.relative_to(tmp_path).as_posix() in stale["changed_inputs"]
    assert build_path.read_bytes() == bound_bytes


def test_paper_stale_prefers_scientific_freeze_hashes_over_copy_mtime(
    tmp_path: Path,
) -> None:
    from server.services.paper_drafting import paper_drafting_service

    main = tmp_path / "paper" / "main.tex"
    main.parent.mkdir(parents=True)
    main.write_text(
        "\\documentclass{article}\\begin{document}"
        "\\section{Introduction}Paper body."
        "\\section{Method}Method."
        "\\section{Results}Results."
        "\\section{Limitations}Limitations."
        "\\section{Conclusion}Conclusion."
        "\\end{document}\n",
        encoding="utf-8",
    )
    upstream = {
        "ideas/SELECTED_IDEA.json": '{"claims": []}\n',
        "experiments/METHOD_CONTRACT.json": '{"status": "complete"}\n',
        "experiments/results/analysis.md": "# Analysis\nBounded result.\n",
        "figures/SCIENTIFIC_ASSET_PLAN.json": '{"assets": []}\n',
        "figures/FIGURE_MANIFEST.json": '{"figures": []}\n',
        "NARRATIVE_REPORT.md": "# Narrative\nBounded narrative.\n",
    }
    for relative, content in upstream.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    paper_drafting_service.freeze_scientific_inputs(
        tmp_path,
        {"run_experiment": False},
    )

    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    copied = tmp_path / "copied-analysis.md"
    copied.write_bytes(analysis.read_bytes())
    future = time.time() + 120
    os.utime(copied, (future, future))
    shutil.copy2(copied, analysis)
    copied_findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": False},
    )
    assert not any(item["id"] == "PAPER-STALE-001" for item in copied_findings)

    analysis.write_text("# Analysis\nChanged scientific conclusion.\n", encoding="utf-8")
    old = main.stat().st_mtime - 120
    os.utime(analysis, (old, old))
    changed_findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": False},
    )
    stale = next(
        item for item in changed_findings if item["id"] == "PAPER-STALE-001"
    )
    assert stale["severity"] == "blocker"
    assert stale["freshness_basis"] == "content_hashes"
    assert "experiments/results/analysis.md" in stale["changed_inputs"]


def test_proven_result_suffix_filter_skips_large_unused_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import server.services.execution_provenance as provenance_module
    from server.services.execution_provenance import execution_provenance_service

    summary = tmp_path / "experiments" / "results" / "accepted" / "summary.csv"
    predictions = summary.with_name("predictions.jsonl")
    summary.parent.mkdir(parents=True)
    summary.write_text("seed,metric\n1,0.5\n", encoding="utf-8")
    predictions.write_text('{"prediction": 1}\n', encoding="utf-8")
    artifacts = {}
    for path in (summary, predictions):
        artifacts[path.relative_to(tmp_path).as_posix()] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        }
    run_path = tmp_path / ".merak" / "experiments" / "accepted" / "run.json"
    run_path.parent.mkdir(parents=True)
    run_path.write_text(
        json.dumps({
            "status": "completed",
            "evidence_eligible": True,
            "result_artifacts": artifacts,
        }),
        encoding="utf-8",
    )
    hashed: list[Path] = []
    original_sha256 = provenance_module._sha256

    def observed_sha256(path: Path) -> str:
        hashed.append(path)
        return original_sha256(path)

    monkeypatch.setattr(provenance_module, "_sha256", observed_sha256)

    proven = execution_provenance_service.proven_result_sources(
        tmp_path,
        suffixes={".csv"},
    )

    assert proven == {summary.relative_to(tmp_path).as_posix()}
    assert summary in hashed
    assert predictions not in hashed


def test_workflow_snapshot_scans_completed_prefix_and_marks_future_nodes_not_started(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text(
        "# Survey\nSearch protocol, limitations, and evidence gaps.",
        encoding="utf-8",
    )
    (literature / "references.bib").write_text(
        "\n".join(
            f"@article{{ref{index}, title={{Study {index}}}, "
            f"author={{Author {index}}}, year={{2024}}, "
            f"url={{https://example.org/{index}}}}}"
            for index in range(5)
        ),
        encoding="utf-8",
    )
    ideas = tmp_path / "ideas" / "ideas.md"
    ideas.parent.mkdir()
    ideas.write_text(
        "# Ideas\n## Idea 1\nHypothesis, mechanism, nearest work, falsification, feasibility.",
        encoding="utf-8",
    )

    snapshot = node_risk_audit_service.audit_workflow(
        tmp_path,
        {"run_experiment": False},
        through_node="idea",
        persist=True,
    )

    assert snapshot["nodes"]["lit"]["status"] in {"clear", "advisory"}
    assert snapshot["nodes"]["idea"]["status"] in {"clear", "advisory"}
    assert snapshot["nodes"]["novelty"]["status"] == "not_started"
    assert (tmp_path / ".merak" / "WORKFLOW_RISK_SNAPSHOT.json").is_file()


def test_nonblocking_potential_risks_do_not_reject_an_accepted_gate(tmp_path: Path) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text("# Survey\nA short catalogue.", encoding="utf-8")
    (literature / "references.bib").write_text(
        "\n".join(
            f"@article{{ref{index}, title={{Study {index}}}, "
            f"author={{Author {index}}}, year={{2024}}, "
            f"url={{https://example.org/{index}}}}}"
            for index in range(5)
        ),
        encoding="utf-8",
    )
    gate = {
        "accepted": True,
        "verdict_id": "test",
        "reviewer": "deterministic:test",
        "summary": "base gate passed",
    }

    audited = node_risk_audit_service.apply_gate(
        gate,
        tmp_path,
        "lit",
        {"run_experiment": False, "research_strategy": {"literature_max_papers": 1}},
    )

    assert audited["accepted"] is True
    assert audited.get("warnings")


def test_revision_diagnostics_expose_plain_risk_and_remediation() -> None:
    gate = {
        "accepted": False,
        "reason": "node-specific research risk audit failed",
        "details": {
            "node_risk_audit": {
                "report_path": ".merak/quality/compile-risk.json",
                "findings": [{
                    "plain_message": "PDF 与当前源文件不一致。",
                    "remediation": "重新编译当前源文件。",
                }],
            },
        },
    }
    diagnostics = WorkflowEngine._gate_revision_diagnostics(gate)
    assert "PDF 与当前源文件不一致。" in diagnostics["issues"]
    assert diagnostics["risk_remediations"] == ["重新编译当前源文件。"]


@pytest.mark.asyncio
async def test_managed_runtime_excludes_results_older_than_current_attempt(
    tmp_path: Path,
) -> None:
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    old_metric = tmp_path / "experiments" / "results" / "old_metrics.csv"
    config.parent.mkdir(parents=True)
    old_metric.parent.mkdir(parents=True)
    config.write_text("seed: 1\n", encoding="utf-8")
    old_metric.write_text("method,accuracy\nold,0.9\n", encoding="utf-8")
    old_time = time.time() - 120
    os.utime(old_metric, (old_time, old_time))

    spec = RuntimeSpec(
        run_id="attempt-window",
        project_path=str(tmp_path),
        command="python train.py",
    )
    store = RunManifestStore(tmp_path, spec.run_id)
    snapshot = ProjectSnapshot(spec, store).build()
    attempt, _ = store.begin_attempt(spec, snapshot["snapshot_hash"])

    new_metric = tmp_path / "experiments" / "results" / "new_metrics.csv"
    new_metric.write_text("method,accuracy\nnew,0.8\n", encoding="utf-8")
    log = tmp_path / "experiments" / "logs" / "train.log"
    log.parent.mkdir(parents=True)
    log.write_text("completed\n", encoding="utf-8")

    await experiment_runtime._finalize(
        spec,
        store,
        attempt,
        "completed",
        0,
        [],
        ExperimentHealthMonitor(HealthPolicy()),
        log,
        str(new_metric.parent),
        "",
        None,
    )
    manifest = store.load()
    artifacts = manifest["result_artifacts"]
    assert old_metric.relative_to(tmp_path).as_posix() not in artifacts
    assert new_metric.relative_to(tmp_path).as_posix() in artifacts
    assert manifest["config_hashes"]["experiments/configs/main.yaml"] == _sha256(config)


@pytest.mark.asyncio
async def test_review_transport_retries_but_does_not_reuse_text_only_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Draft\\end{document}",
        encoding="utf-8",
    )
    review_calls = 0
    transport_labels: list[str] = []

    async def fake_review(**_kwargs) -> ApiVisualReview:
        nonlocal review_calls
        review_calls += 1
        if review_calls == 1:
            raise RuntimeError("OpenAI API error 502: upstream unavailable")
        return _api_review_result(
            tmp_path,
            {
                "score": 6.5,
                "verdict": "almost",
                "strengths": ["Bounded claims."],
                "weaknesses": [],
                "action_items": [],
            },
            2,
        )

    async def retry_transport(label: str, operation) -> str:
        transport_labels.append(label)
        try:
            return await operation()
        except RuntimeError as exc:
            assert "502" in str(exc)
            return await operation()

    _patch_direct_reviewer_routes(monkeypatch)
    monkeypatch.setattr(
        api_visual_reviewer,
        "review_manuscript",
        fake_review,
    )
    reviewer = CrossModelReviewer()

    state = await reviewer.run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=4,
        evidence_mode="executed",
        run_id="transport-review",
        transport_retry=retry_transport,
    )

    assert review_calls == 2
    assert transport_labels == ["round-1-review"]
    assert state.is_complete is True
    assert state.phase == "completed"
    saved = json.loads(
        (tmp_path / "review-stage" / "REVIEW_STATE.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["phase"] == "completed"
    assert saved["source_bundle_sha256"]
    saved["rounds"][-1]["visual_review"].pop(
        "_review_trace_path",
        None,
    )
    (tmp_path / "review-stage" / "REVIEW_STATE.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    async def prove_text_only_state_is_revalidated(
        **_kwargs,
    ) -> ApiVisualReview:
        raise AssertionError(
            "text-only completed review state was correctly revalidated"
        )

    monkeypatch.setattr(
        api_visual_reviewer,
        "review_manuscript",
        prove_text_only_state_is_revalidated,
    )
    with pytest.raises(
        AssertionError,
        match="correctly revalidated",
    ):
        await reviewer.run_review_loop(
            paper_path=str(paper),
            project_path=str(tmp_path),
            max_rounds=4,
            evidence_mode="executed",
            run_id="transport-review",
            transport_retry=retry_transport,
        )


def test_synthetic_reviewer_prompt_treats_manuscript_as_complete_benchmark() -> None:
    prompt = CrossModelReviewer()._get_reviewer_prompt(
        "hard",
        evidence_mode="synthetic_preview",
    )

    assert "完整的固定基准研究" in prompt
    assert "不是 planned / pre-experiment 协议稿" in prompt
    assert "主对比、消融、训练或收敛动态" in prompt
    assert "不要仅因结果来自固定基准" in prompt
    assert "不得把未运行物理训练" in prompt
    assert "只允许在 Conclusion 后、参考文献前出现统一 Simulation Study Disclosure" in prompt
    assert "若结论超出定义基准，或把基准结果冒充未经声明的外部测量，必须 major_revision" in prompt
    assert "不得添加 NOT FOR SUBMISSION 警告、预览标签、水印" in prompt
    assert "所有模式均不得建议或添加可见水印、草稿印章" in prompt


@pytest.mark.parametrize("disclosure_count", [0, 2])
def test_simulation_paper_risk_audit_requires_one_final_disclosure(
    tmp_path: Path,
    disclosure_count: int,
) -> None:
    from server.services.simulation_policy import (
        SIMULATION_END_DISCLOSURE,
        SIMULATION_END_DISCLOSURE_TITLE,
    )

    paper = tmp_path / "paper"
    paper.mkdir()
    disclosures = "\n".join(
        SIMULATION_END_DISCLOSURE
        for _ in range(disclosure_count)
    )
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{abstract}A benchmark study.\\end{abstract}\n"
        "\\section{Introduction}Problem and contribution.\n"
        "\\section{Method}Registered mechanism.\n"
        "\\section{Experimental Setup}Registered benchmark conditions.\n"
        "\\section{Results}Within the benchmark, the full method leads.\n"
        "\\section{Limitations}Benchmark scope is limited.\n"
        "\\section{Conclusion}The benchmark supports the mechanism.\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n{disclosures}\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert any(item.get("id") == "PAPER-SIM-001" for item in findings)


def test_simulation_paper_risk_audit_accepts_one_final_disclosure(
    tmp_path: Path,
) -> None:
    from server.services.simulation_policy import (
        SIMULATION_END_DISCLOSURE,
        SIMULATION_END_DISCLOSURE_TITLE,
    )

    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Introduction}Problem and contribution.\n"
        "\\section{Methods}Registered mechanism.\n"
        "\\section{Results}Benchmark-bounded findings.\n"
        "\\section{Conclusion}The benchmark supports the mechanism.\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert not any(
        item.get("id") in {"PAPER-SIM-001", "PAPER-SIM-003"}
        for item in findings
    )


def test_simulation_paper_risk_audit_rejects_framing_outside_final_disclosure(
    tmp_path: Path,
) -> None:
    from server.services.simulation_policy import (
        SIMULATION_END_DISCLOSURE,
        SIMULATION_END_DISCLOSURE_TITLE,
    )

    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Introduction}This simulation preview studies a mechanism.\n"
        "\\section{Conclusion}The benchmark supports the mechanism.\n"
        f"\\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}\n"
        f"{SIMULATION_END_DISCLOSURE}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert any(item.get("id") == "PAPER-SIM-003" for item in findings)


@pytest.mark.parametrize(
    ("evidence_mode", "watermark_command"),
    [
        ("synthetic_preview", r"\usepackage{draftwatermark}"),
        ("design_only", r"\usepackage[printwatermark]{xwatermark}"),
        ("executed", r"\SetWatermarkText{DRAFT}"),
    ],
)
def test_paper_risk_audit_rejects_watermarks_in_every_evidence_mode(
    tmp_path: Path,
    evidence_mode: str,
    watermark_command: str,
) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        f"{watermark_command}\n"
        "\\begin{document}\n"
        "\\section{Methods}Registered study.\n"
        "\\section{Results}Bounded findings.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {
            "run_experiment": evidence_mode == "executed",
            "non_experiment_evidence_mode": evidence_mode,
        },
    )

    assert any(item.get("id") == "PAPER-WATERMARK-001" for item in findings)


def test_paper_risk_audit_ignores_commented_watermark_command(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n"
        "% \\usepackage{draftwatermark}\n"
        "\\begin{document}\\section{Methods}Registered study.\\end{document}\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": True},
    )

    assert not any(
        item.get("id") == "PAPER-WATERMARK-001" for item in findings
    )


def test_literature_coverage_matches_final_manuscript_profile(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature"
    paper = tmp_path / "paper"
    literature.mkdir()
    paper.mkdir()
    (literature / "survey.md").write_text(
        "# Survey\nSearch Protocol\nCritical synthesis and evidence gap.\n",
        encoding="utf-8",
    )
    (literature / "references.bib").write_text(
        "\n".join(
            f"@article{{ref{index}, title={{Relevant study {index}}}, "
            f"author={{Author {index}}}, year={{2025}}, "
            f"url={{https://example.org/{index}}}}}"
            for index in range(15)
        ),
        encoding="utf-8",
    )
    _write_json(
        paper / "PAPER_PROFILE.json",
        {
            "target_venue": "ICLR",
            "evidence_mode": "synthetic_preview",
            "research_family": "machine_learning",
            "minimum_unique_bibliography_entries": 30,
        },
    )

    findings = node_risk_audit_service._audit_lit(
        tmp_path,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
            "target_venue": "ICLR",
            "research_strategy": {"literature_max_papers": 35},
        },
    )

    coverage = next(item for item in findings if item["id"] == "LIT-COV-001")
    assert coverage["severity"] == "blocker"
    assert "requires at least 30" in coverage["message"]
