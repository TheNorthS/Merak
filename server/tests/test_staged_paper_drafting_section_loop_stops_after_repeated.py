from __future__ import annotations

from server.tests._staged_paper_drafting_support import (
    AUTHOR_STAGE_ORDER as AUTHOR_STAGE_ORDER,
    PaperDraftingError as PaperDraftingError,
    PaperDraftingService as PaperDraftingService,
    Path as Path,
    RunState as RunState,
    SECTION_SPECS as SECTION_SPECS,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    pytest as pytest,
    seed_project as seed_project,
    zipfile as zipfile,
)


@pytest.mark.asyncio
async def test_section_loop_stops_after_repeated_semantic_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    calls: list[str] = []
    events: list[str] = []

    def fake_validate(_project_path: Path, stage_id: str) -> dict:
        if stage_id == "introduction":
            return {
                "passed": False,
                "issues": ["introduction lacks two falsifiable contributions"],
            }
        return {"passed": True, "issues": []}

    async def fake_invoke(stage_id: str, *_args) -> str:
        calls.append(stage_id)
        for output in service.stage_outputs(service.paths(tmp_path), stage_id):
            from server.services.paper_candidate_io import candidate_path
            output = candidate_path(output, writing=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                (
                    "\\section{Introduction}\n"
                    "The same invalid introduction remains unchanged.\n"
                    if stage_id == "introduction"
                    else f"accepted {stage_id}\n"
                ),
                encoding="utf-8",
            )
        return "authored"

    async def capture(event: str, _payload: dict) -> None:
        events.append(event)

    monkeypatch.setattr(service, "validate_stage", fake_validate)

    with pytest.raises(PaperDraftingError) as exc_info:
        await service.draft(
            tmp_path,
            "robust representation",
            {"max_revision_rounds": 6},
            fake_invoke,
            capture,
        )

    assert exc_info.value.stage_id == "introduction"
    assert calls.count("introduction") == 3
    assert "paper_stage_stalled" in events
    assert "paper_stage_no_progress_retry" in events


@pytest.mark.asyncio
async def test_section_attempt_budget_is_cumulative_across_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"max_revision_rounds": 3})
    paths = service.paths(tmp_path)
    for stage_id in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"persisted {stage_id}\n", encoding="utf-8")
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state["stages"]["discussion"].update({
        "status": "revision_required",
        "attempts": 3,
        "review_passed": False,
        "review_issues": ["discussion still lacks a required interpretation"],
    })
    paths["state"].write_text(json.dumps(state), encoding="utf-8")
    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "unexpected invocation"

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {
            "passed": stage_id != "discussion",
            "issues": ["discussion still lacks a required interpretation"],
        },
    )

    with pytest.raises(PaperDraftingError) as exc_info:
        await service.draft(
            tmp_path,
            "robust representation",
            {"max_revision_rounds": 3},
            fake_invoke,
        )

    assert exc_info.value.stage_id == "discussion"
    assert calls == []


@pytest.mark.asyncio
async def test_resume_revalidates_existing_stage_before_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"max_revision_rounds": 3})
    paths = service.paths(tmp_path)
    for stage_id in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.name == "TITLE.txt":
                output.write_text("A Specific Resumable Scientific Study\n", encoding="utf-8")
            else:
                output.write_text(f"persisted {stage_id}\n", encoding="utf-8")
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state["stages"]["discussion"].update({
        "status": "revision_required",
        "attempts": 3,
        "review_passed": False,
        "review_issues": ["obsolete validator finding"],
    })
    paths["state"].write_text(json.dumps(state), encoding="utf-8")
    calls: list[str] = []
    events: list[tuple[str, dict]] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "unexpected invocation"

    async def capture(event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {"passed": True, "issues": [], "stage_id": stage_id},
    )
    monkeypatch.setattr(
        service,
        "validate_complete_draft",
        lambda _root, **_kwargs: {"passed": True, "issues": []},
    )

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        capture,
    )

    assert result["status"] == "completed"
    assert calls == []
    assert any(
        event == "paper_stage_reused"
        and payload["stage_id"] == "discussion"
        and payload.get("revalidated") is True
        for event, payload in events
    )


@pytest.mark.asyncio
async def test_missing_main_tex_reassembles_without_consistency_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"max_revision_rounds": 3})
    paths = service.paths(tmp_path)
    for stage_id in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.name == "TITLE.txt":
                output.write_text(
                    "A Specific Deterministically Assembled Study\n",
                    encoding="utf-8",
                )
            else:
                output.write_text(f"persisted {stage_id}\n", encoding="utf-8")
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )
    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "unexpected invocation"

    monkeypatch.setattr(
        service,
        "validate_complete_draft",
        lambda _root, **_kwargs: {"passed": True, "issues": []},
    )

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        revision_issues=[
            f"Staged manuscript did not satisfy the quality contract: "
            f"Missing or empty {tmp_path / 'paper' / 'main.tex'}"
        ],
    )

    assert result["status"] == "completed"
    assert (tmp_path / "paper" / "main.tex").is_file()
    assert calls == []


@pytest.mark.asyncio
async def test_introduction_failure_survives_missing_main_and_stops_targeted_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the repeated paper/main.tex-missing workflow log."""
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
        "paper_section_revision_rounds": 1,
        "revision_no_progress_limit": 2,
    }
    service.prepare(tmp_path, options)
    paper_artifact_builder.prepare(tmp_path, "layout rebind")
    paths = service.paths(tmp_path)
    paths["blueprint"].write_text(
        "# Contribution blueprint\nA frozen accepted blueprint.\n",
        encoding="utf-8",
    )
    service.mark_stage(
        paths,
        "blueprint",
        "completed",
        attempt=1,
        review={"passed": True, "issues": []},
    )
    introduction = paths["sections"] / "01_introduction.tex"
    invalid_introduction = (
        "\\section{Introduction}\n"
        "We introduce one broad contribution without a rejection condition.\n"
    )
    stage_invocations: list[str] = []
    revision_batches: list[list[str]] = []
    events: list[tuple[str, dict]] = []

    def validate_stage(_root: Path, stage_id: str) -> dict:
        if stage_id == "introduction":
            return {
                "passed": False,
                "issues": [
                    "introduction lacks two or more falsifiable contributions"
                ],
                "stage_id": stage_id,
            }
        return {"passed": True, "issues": [], "stage_id": stage_id}

    async def invoke_stage(
        stage_id: str,
        _prompt: str,
        _contract: str,
    ) -> str:
        stage_invocations.append(stage_id)
        assert stage_id == "introduction"
        from server.services.paper_candidate_io import candidate_path
        candidate = candidate_path(introduction, writing=True)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(invalid_introduction, encoding="utf-8")
        return "wrote unchanged introduction"

    async def staged_paper(**kwargs) -> str:
        revision_issues = list(kwargs.get("revision_issues") or [])
        if revision_issues:
            revision_batches.append(revision_issues)
        try:
            result = await service.draft(
                tmp_path,
                "robust representation",
                options,
                invoke_stage,
                revision_issues=revision_issues,
            )
            return json.dumps(result, ensure_ascii=False)
        except PaperDraftingError as exc:
            return json.dumps({
                "status": "revision_required",
                "failed_stage": exc.stage_id,
                "issues": exc.issues,
            }, ensure_ascii=False)

    monkeypatch.setattr(service, "validate_stage", validate_stage)
    initial_result = await staged_paper(revision_issues=[])
    assert not paths["main"].exists()

    engine = WorkflowEngine()
    node = WorkflowNode(
        id="paper",
        name="Paper",
        skill="/domain-paper-write",
    )
    run = WorkflowRun(
        id="staged-introduction-no-progress",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options=options,
    )
    RunState(str(tmp_path), run.id).start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"options": options},
    )

    async def prepare(
        _node,
        _run,
        result,
        *_args,
        **_kwargs,
    ) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: engine._paper_acceptance_gate(
            str(tmp_path),
            require_staged=True,
            paper_options=options,
        ),
    )
    monkeypatch.setattr(engine, "_execute_staged_paper", staged_paper)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result=initial_result,
        research_direction="robust representation",
        effort="balanced",
        assurance="draft",
        opts=options,
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=6,
    )

    final_gate = engine._paper_acceptance_gate(
        str(tmp_path),
        require_staged=True,
        paper_options=options,
    )
    diagnostics = engine._gate_revision_diagnostics(final_gate)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    waiting = next(
        payload
        for event, payload in events
        if event == "node_revision_waiting"
    )

    assert gate["waiting"] is True
    assert waiting["stopped_for_no_progress"] is True
    assert gate["revision_round"] == 2
    assert final_gate["reason"] == "staged paper section requires revision"
    assert "Missing or empty" not in final_gate["summary"]
    assert final_gate["details"]["failed_stage"] == "introduction"
    assert diagnostics["findings"][0]["id"].startswith(
        "PAPER-STAGE-INTRODUCTION-"
    )
    assert diagnostics["repair_scope"]["target_files"] == [
        "paper/sections/01_introduction.tex"
    ]
    assert len(revision_batches) == 2
    assert all(
        any("01_introduction.tex" in issue for issue in batch)
        for batch in revision_batches
    )
    assert stage_invocations == ["introduction", "introduction"]
    assert state["stages"]["blueprint"]["status"] == "completed"
    assert state["stages"]["blueprint"]["review_passed"] is True
    assert not paths["main"].exists()


@pytest.mark.asyncio
async def test_completed_stage_and_downstream_stages_revalidate_after_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    for stage_id in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.name == "TITLE.txt":
                output.write_text("A Specific Resumable Scientific Study\n", encoding="utf-8")
            else:
                output.write_text(f"persisted {stage_id}\n", encoding="utf-8")
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )
    introduction = paths["sections"] / "01_introduction.tex"
    introduction.write_text("externally revised introduction\n", encoding="utf-8")
    calls: list[str] = []
    events: list[tuple[str, dict]] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "unexpected invocation"

    async def capture(event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {"passed": True, "issues": [], "stage_id": stage_id},
    )
    monkeypatch.setattr(
        service,
        "validate_complete_draft",
        lambda _root, **_kwargs: {"passed": True, "issues": []},
    )

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        capture,
    )

    assert result["status"] == "completed"
    assert calls == []
    revalidated = {
        payload["stage_id"]
        for event, payload in events
        if event == "paper_stage_reused" and payload.get("revalidated") is True
    }
    assert "introduction" in revalidated
    assert "related_work" in revalidated
    assert "consistency" in revalidated


def test_reconcile_reviewed_artifacts_rebinds_staged_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    for stage_id in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.name == "TITLE.txt":
                output.write_text(
                    "A Specific Reviewed Scientific Study\n",
                    encoding="utf-8",
                )
            else:
                output.write_text(
                    f"persisted {stage_id}\n",
                    encoding="utf-8",
                )
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )

    introduction = paths["sections"] / "01_introduction.tex"
    introduction.write_text(
        "reviewer-approved introduction\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {
            "passed": True,
            "issues": [],
            "stage_id": stage_id,
        },
    )
    monkeypatch.setattr(
        service,
        "validate_complete_draft",
        lambda _root, **_kwargs: {
            "passed": True,
            "issues": [],
            "evidence_mode": "design_only",
        },
    )

    def fake_assemble(_root: Path) -> Path:
        paths["main"].write_text(
            "\\documentclass{article}\\begin{document}"
            "reviewed\\end{document}",
            encoding="utf-8",
        )
        return paths["main"]

    monkeypatch.setattr(service, "assemble", fake_assemble)

    result = service.reconcile_reviewed_artifacts(tmp_path)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    reviews = json.loads(paths["reviews"].read_text(encoding="utf-8"))

    assert result["passed"] is True
    assert state["status"] == "completed"
    assert state["main_sha256"] == result["main_sha256"]
    assert service.stage_is_current(paths, state, "introduction") is True
    assert state["stages"]["consistency"]["review_passed"] is True
    assert reviews["cross_section"]["passed"] is True
    assert "Final Consistency Verdict" in paths["cross_review"].read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("venue", "marker", "asset"),
    [
        ("ICLR", r"\usepackage{iclr2026_conference,times}", "iclr2026_conference.sty"),
        ("NeurIPS", r"\usepackage{neurips_2026}", "neurips_2026.sty"),
        ("ICML", r"\icmltitle{", "icml2026.sty"),
        ("CVPR", r"\usepackage[review]{cvpr}", "cvpr.sty"),
        ("ACL", r"\usepackage[review]{acl}", "acl.sty"),
        ("AAAI", r"\def\aaaianonymous{true}", "aaai2026.sty"),
    ],
)
def test_assembly_uses_bundled_anonymous_venue_template(
    tmp_path: Path,
    venue: str,
    marker: str,
    asset: str,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": venue})
    paths = service.paths(tmp_path)
    paths["title"].write_text("Topology-Aware Robust Representation Learning\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text(
        "A bounded evaluation protocol for robust representation learning.\n",
        encoding="utf-8",
    )
    for spec in SECTION_SPECS:
        (paths["sections"] / spec.filename).write_text(
            f"\\section{{{spec.title}}}\nSubstantive section content.\n",
            encoding="utf-8",
        )

    main_path = service.assemble(tmp_path)
    main = main_path.read_text(encoding="utf-8")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))

    assert marker in main
    assert (paths["paper"] / asset).is_file()
    assert state["venue_template"]["mode"] == "anonymous_review"
    assert state["venue_template"]["official_assets_bundled"] is True


def test_assembly_canonicalizes_project_relative_figure_path(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    paths = service.paths(tmp_path)
    paths["title"].write_text("Auditable Model Comparison\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text(
        "A bounded evaluation protocol.\n",
        encoding="utf-8",
    )
    figure = tmp_path / "figures" / "diagrams" / "method_architecture.pdf"
    figure.parent.mkdir(parents=True, exist_ok=True)
    figure.write_bytes(b"%PDF-1.4\n")
    for spec in SECTION_SPECS:
        content = f"\\section{{{spec.title}}}\nSubstantive section content.\n"
        if spec.id == "method":
            content += (
                "\\includegraphics[width=\\textwidth]"
                "{figures/diagrams/method_architecture.pdf}\n"
            )
        (paths["sections"] / spec.filename).write_text(content, encoding="utf-8")

    service.assemble(tmp_path)

    method = (paths["sections"] / "03_method.tex").read_text(encoding="utf-8")
    assert "{../figures/diagrams/method_architecture.pdf}" in method
    assert "{figures/diagrams/method_architecture.pdf}" not in method


def test_assembly_canonicalizes_project_relative_paper_input(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    paths = service.paths(tmp_path)
    paths["title"].write_text("Auditable Model Comparison\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text(
        "A bounded evaluation protocol.\n",
        encoding="utf-8",
    )
    generated = paths["paper"] / "generated_evaluation_figures.tex"
    generated.write_text(
        "\\begin{figure}\\label{fig:evaluation-design}\\end{figure}\n",
        encoding="utf-8",
    )
    table = paths["paper"] / "tables" / "study_design.tex"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(
        "\\begin{table}\\label{tab:study-design}\\end{table}\n",
        encoding="utf-8",
    )
    for spec in SECTION_SPECS:
        content = f"\\section{{{spec.title}}}\nSubstantive section content.\n"
        if spec.id == "experiments":
            content += (
                "\\input{paper/generated_evaluation_figures.tex}\n"
                "\\input{paper/tables/study_design.tex}\n"
            )
        (paths["sections"] / spec.filename).write_text(content, encoding="utf-8")

    service.assemble(tmp_path)

    experiments = (paths["sections"] / "04_experiments.tex").read_text(
        encoding="utf-8"
    )
    assert "\\input{generated_evaluation_figures.tex}" in experiments
    assert "\\input{tables/study_design.tex}" in experiments
    assert "\\input{paper/" not in experiments


def test_assembly_includes_uncopied_evaluation_figure_projection_once(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    paths = service.paths(tmp_path)
    paths["title"].write_text("Auditable Held-Out Evaluation\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text(
        "A bounded evaluation protocol.\n", encoding="utf-8"
    )
    generated = paths["paper"] / "generated_evaluation_figures.tex"
    graphic = tmp_path / "figures/diagrams/evaluation_design.pdf"
    graphic.parent.mkdir(parents=True, exist_ok=True)
    graphic.write_bytes(b"%PDF-canonical evaluation fixture")
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({
        "schema": 1, "figures": [{"id": "evaluation_design",
            "output_path": "figures/diagrams/evaluation_design.pdf", "metadata": {
                "label": "fig:evaluation-design", "scientific_role": "evaluation_design",
                "paper_selected": True, "manuscript_eligible": True}}],
    }), encoding="utf-8")
    generated.write_text(
        "\\begin{figure}\\includegraphics{../figures/diagrams/evaluation_design.pdf}"
        "\\label{fig:evaluation-design}\\end{figure}\n",
        encoding="utf-8",
    )
    for spec in SECTION_SPECS:
        content = f"\\section{{{spec.title}}}\nSubstantive section content.\n"
        if spec.id == "experiments":
            content += "Figure~\\ref{fig:evaluation-design} defines the protocol.\n"
        (paths["sections"] / spec.filename).write_text(content, encoding="utf-8")

    main = service.assemble(tmp_path).read_text(encoding="utf-8")

    assert main.count("\\input{assembly_experiments_figures}") == 1
    assert main.index("\\input{sections/04_experiments}") < main.index("\\input{assembly_experiments_figures}")
    assert main.index("\\input{assembly_experiments_figures}") < main.index("\\input{sections/05_results}")


def test_assembly_uses_field_specific_policy_for_non_ml_venue(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "target_venue": "Nature Methods",
        "research_family": "clinical_biomedical",
        "study_archetype": "diagnostic_prognostic",
    })
    paths = service.paths(tmp_path)
    paths["title"].write_text("Externally Validated Risk Estimation\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text(
        "A prespecified external validation study with calibrated risk estimates.\n",
        encoding="utf-8",
    )
    for spec in SECTION_SPECS:
        (paths["sections"] / spec.filename).write_text(
            f"\\section{{{spec.title}}}\nSubstantive section content.\n",
            encoding="utf-8",
        )

    main = service.assemble(tmp_path).read_text(encoding="utf-8")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    profile = json.loads(paths["style"].read_text(encoding="utf-8"))

    assert state["venue_template"]["key"] == "nature_science"
    assert state["venue_template"]["mode"] == "venue_family_policy"
    assert "\\bibliographystyle{unsrtnat}" in main
    assert profile["built_in_exemplars"] == []


def test_assembly_installs_and_tracks_user_supplied_tex_template(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    template_dir = tmp_path / "official-template"
    template_dir.mkdir()
    template_class = template_dir / "journal-review.cls"
    template_class.write_text(
        "\\NeedsTeXFormat{LaTeX2e}\n"
        "\\ProvidesClass{journal-review}\n"
        "\\LoadClass[11pt]{article}\n",
        encoding="utf-8",
    )
    template_main = template_dir / "main.tex"
    template_main.write_text(
        "\\documentclass{journal-review}\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}\n"
        "{{MERAK_CONTENT}}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "target_venue": "Example Journal",
        "venue_template_path": str(template_dir),
        "research_family": "experimental_natural_science",
        "study_archetype": "controlled_experiment",
    })
    paths = service.paths(tmp_path)
    paths["title"].write_text("Controlled Perturbation Study\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text(
        "A controlled perturbation study with replicate-level uncertainty.\n",
        encoding="utf-8",
    )
    for spec in SECTION_SPECS:
        (paths["sections"] / spec.filename).write_text(
            f"\\section{{{spec.title}}}\nSubstantive section content.\n",
            encoding="utf-8",
        )

    main = service.assemble(tmp_path).read_text(encoding="utf-8")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))

    assert "\\documentclass{journal-review}" in main
    assert "{{MERAK_CONTENT}}" not in main
    assert "\\input{sections/05_results}" in main
    assert (paths["paper"] / "journal-review.cls").is_file()
    assert state["venue_template"]["key"] == "custom"
    assert state["venue_template"]["mode"] == "user_supplied_template"
    assert state["venue_template"]["source_sha256"]

    template_class.write_text(
        template_class.read_text(encoding="utf-8") + "% updated\n",
        encoding="utf-8",
    )
    report = service.gate_report(tmp_path, {})
    assert any(
        "venue template changed after manuscript assembly" in issue
        for issue in report["issues"]
    )


def test_user_supplied_zip_template_is_safely_snapshotted(
    tmp_path: Path,
) -> None:
    paper_root = tmp_path / "paper"
    paper_root.mkdir()
    archive_path = tmp_path / "journal-template.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "journal/main.tex",
            "\\documentclass{journal-review}\n"
            "\\begin{document}\n{{MERAK_CONTENT}}\n\\end{document}\n",
        )
        archive.writestr(
            "journal/journal-review.cls",
            "\\NeedsTeXFormat{LaTeX2e}\n\\LoadClass{article}\n",
        )
        archive.writestr("../outside.tex", "must not be extracted")

    metadata, template_text, documentclass = (
        PaperDraftingService().install_custom_venue_template(
            paper_root, str(archive_path)
        )
    )

    assert metadata["main_template"] == "journal/main.tex"
    assert metadata["source_sha256"]
    assert "{{MERAK_CONTENT}}" in template_text
    assert documentclass == ""
    assert (paper_root / "journal-review.cls").is_file()
    assert not (tmp_path / "outside.tex").exists()


def test_staged_gate_rejects_unreviewed_monolithic_paper(tmp_path: Path) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    (tmp_path / "paper" / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}"
        + "\\section{Introduction} substantial prose " * 200
        + "\\end{document}",
        encoding="utf-8",
    )

    report = service.gate_report(tmp_path, {})

    assert report["passed"] is False
    assert any("incomplete staged paper phase" in issue for issue in report["issues"])


def test_staged_gate_inherits_saved_options_for_sparse_gate_calls(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "target_venue": "ICLR",
        "research_mode": "from_scratch",
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    })

    sparse_report = service.gate_report(tmp_path, {})
    changed_report = service.gate_report(tmp_path, {"run_experiment": True})

    assert not any(
        "stale relative to scientific inputs" in issue
        for issue in sparse_report["issues"]
    )
    assert any(
        "stale relative to scientific inputs" in issue
        for issue in changed_report["issues"]
    )
