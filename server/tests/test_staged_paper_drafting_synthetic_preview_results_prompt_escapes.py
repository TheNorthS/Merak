from __future__ import annotations

from server.tests._staged_paper_drafting_support import (
    CONSISTENCY_CONTRACT_VERSION as CONSISTENCY_CONTRACT_VERSION,
    PaperDraftingService as PaperDraftingService,
    Path as Path,
    SECTION_SPECS as SECTION_SPECS,
    SIMULATION_END_DISCLOSURE as SIMULATION_END_DISCLOSURE,
    SkillPlan as SkillPlan,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _complete_synthetic_results_section as _complete_synthetic_results_section,
    find_visible_code_artifact_references as find_visible_code_artifact_references,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    pytest as pytest,
    re as re,
    seed_project as seed_project,
    skill_orchestrator as skill_orchestrator,
    visible_latex_prose as visible_latex_prose,
)


def test_synthetic_preview_results_prompt_escapes_latex_references(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    _selected_result_reference_fixture(tmp_path)
    service = PaperDraftingService()
    (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    service.prepare(tmp_path, {
        "target_venue": "ICLR",
        "research_mode": "from_scratch",
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    })

    prompt = service.build_stage_prompt(
        tmp_path,
        "results",
        {
            "target_venue": "ICLR",
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    assert r"\input{synthetic_preview_figures}" in prompt
    assert r"\input{tables/synthetic_preview_results}" in prompt
    for label in ("fig:preview-main-comparison", "tab:preview-main-results"):
        assert rf"\ref{{{label}}}" in prompt
    for unselected in ("tab:paired-reversals", "tab:preview-efficiency", "tab:preview-error-analysis"):
        assert rf"\ref{{{unselected}}}" not in prompt
    for analytical_requirement in (
        "method comparison",
        "uncertainty",
        "performance--resource",
        "findings of",
        "do not add warning banners",
    ):
        assert analytical_requirement in prompt
    assert "SYNTHETIC PREVIEW -- NOT FOR SUBMISSION" not in prompt


def _selected_result_reference_fixture(tmp_path: Path) -> None:
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [{
        "id": "main", "metadata": {"label": "fig:preview-main-comparison", "scientific_role": "result",
                                    "caption": "Primary comparison with uncertainty intervals."},
    }]}), encoding="utf-8")
    table = tmp_path / "paper/tables/synthetic_preview_results.tex"
    table.write_text(r"\begin{table}\caption{Primary comparison}\label{tab:preview-main-results}\end{table}", encoding="utf-8")
    (table.parent / "TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": [{
        "id": "main", "label": "tab:preview-main-results", "scientific_role": "result",
        "caption": "Primary comparison", "latex_path": "paper/tables/synthetic_preview_results.tex",
    }]}), encoding="utf-8")


def test_synthetic_authoring_inputs_strip_sidecar_warnings_and_protocol_prompt(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    (tmp_path / "figures" / "FIGURE_MANIFEST.json").write_text(
        json.dumps({
            "figures": [{
                "id": "synthetic_preview_main_comparison",
                "output_path": "figures/simulated/main.pdf",
                "metadata": {
                    "scientific_role": "result",
                    "label": "fig:preview-main-comparison",
                    "caption": "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS",
                    "disclosure": "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS",
                    "submission_eligible": False,
                    "evidence_status": "synthetic_preview",
                },
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "paper" / "tables" / "TABLE_MANIFEST.json").write_text(
        json.dumps({
            "schema": 3,
            "tables": [{
                "id": "main_results_preview",
                "caption": "Primary result and uncertainty structure preview.",
                "label": "tab:preview-main-results",
                "latex_path": "paper/tables/synthetic_preview_results.tex",
                "data_path": "experiments/results/simulated/main_comparison.csv",
                "scientific_role": "result",
                "evidence_status": "synthetic_preview",
                "submission_eligible": False,
                "uncertainty_encoding": "Illustrative uncertainty visibly marked and not evidence.",
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "paper/tables/synthetic_preview_results.tex").write_text(
        r"\begin{table}\caption{Primary comparison}\label{tab:preview-main-results}\end{table}", encoding="utf-8",
    )
    service.prepare(tmp_path, {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    })

    results_prompt = service.build_stage_prompt(tmp_path, "results", {})
    front_prompt = service.build_stage_prompt(tmp_path, "front_matter", {})
    authoring_path = tmp_path / "paper" / "AUTHORING_ASSET_MANIFEST.json"
    authoring_text = authoring_path.read_text(encoding="utf-8")
    authoring = json.loads(authoring_text)

    assert "paper/AUTHORING_ASSET_MANIFEST.json" in results_prompt
    assert "figures/FIGURE_MANIFEST.json" not in results_prompt
    assert "paper/tables/TABLE_MANIFEST.json" not in results_prompt
    assert authoring["figures"][0]["caption"] == (
        "Primary comparison with uncertainty intervals."
    )
    assert authoring["tables"][0]["caption"] == (
        "Primary comparison with uncertainty intervals."
    )
    for forbidden in (
        "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS",
        "structure preview",
        "visibly marked",
        "not evidence",
        "submission_eligible",
        "disclosure",
    ):
        assert forbidden.casefold() not in authoring_text.casefold()
    assert "summarize the registered quantitative benchmark findings" in front_prompt
    assert "do not call the paper a protocol" in front_prompt
    assert "do not add provenance" in front_prompt
    assert "internal evidence-mode language" in front_prompt
    assert "Methods provenance sentence" not in front_prompt
    assert "do not add visible watermarks, draft stamps" in front_prompt
    assert "warning banners or boxes, corner badges or ribbons" in front_prompt


def test_synthetic_results_review_requires_every_selected_asset_and_real_analysis(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    _selected_result_reference_fixture(tmp_path)
    service = PaperDraftingService()
    (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    service.prepare(tmp_path, {
        "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark",
    })
    results_path = tmp_path / "paper" / "sections" / "05_results.tex"
    results_path.write_text(
        _complete_synthetic_results_section(),
        encoding="utf-8",
    )

    complete = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )
    assert complete["passed"] is True, complete

    results_path.write_text(
        _complete_synthetic_results_section().replace(
            r"Figure~\ref{fig:preview-main-comparison} is paired with the "
            "registered analysis.",
            "The error panel is registered.",
        ),
        encoding="utf-8",
    )
    missing_asset = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )
    assert any(
        "fig:preview-main-comparison" in issue
        for issue in missing_asset["issues"]
    )


def test_synthetic_results_review_accepts_plural_component_ablation_analysis(
    tmp_path: Path,
) -> None:
    """Regression for a valid Results section rejected on plural wording."""
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark",
    })
    text = _complete_synthetic_results_section().replace(
        "The component ablation is a matched removal analysis: the largest "
        "delta indicates the strongest component contribution under fixed "
        "resource accounting.",
        "Matched component ablations compare component removals: the largest "
        "delta identifies the strongest pathway effect under fixed resource "
        "accounting.",
    )
    (tmp_path / "paper" / "sections" / "05_results.tex").write_text(
        text,
        encoding="utf-8",
    )

    review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )

    assert review["passed"] is True, review


def test_staged_target_routing_requires_exact_canonical_section_path() -> None:
    service = PaperDraftingService()

    assert (
        service.stage_for_project_relative_target(
            "paper/sections/05_results.tex"
        )
        == "results"
    )
    assert (
        service.stage_for_project_relative_target(
            r"F:\project\paper\sections\03_method.tex"
        )
        == "method"
    )
    assert (
        service.stage_for_project_relative_target(
            "paper/tables/synthetic_preview_results.tex"
        )
        == ""
    )
    assert (
        service.stage_for_project_relative_target(
            "paper/tables/method_components.tex"
        )
        == ""
    )
    assert service.revision_target_paths([
        "Target artifact: paper/tables/synthetic_preview_results.tex",
        "paper/sections/05_results.tex:22: layout finding",
    ]) == [
        "paper/tables/synthetic_preview_results.tex",
        "paper/sections/05_results.tex",
    ]


def test_synthetic_results_review_rejects_reference_only_prose(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    _selected_result_reference_fixture(tmp_path)
    figure_manifest = tmp_path / "figures/FIGURE_MANIFEST.json"
    selected = json.loads(figure_manifest.read_text(encoding="utf-8"))
    selected["figures"].extend([
        {"id": "progression", "metadata": {"label": "fig:preview-training-dynamics", "scientific_role": "training_dynamics", "paper_selected": True}},
        {"id": "resource", "metadata": {"label": "fig:preview-efficiency", "scientific_role": "efficiency", "paper_selected": True}},
    ])
    figure_manifest.write_text(json.dumps(selected), encoding="utf-8")
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark",
    })
    text = _complete_synthetic_results_section()
    for phrase in (
        "training dynamics trajectory",
        "plateau",
        "epochs",
        "convergence",
        "uncertainty band",
        "stress curve",
        "failure analysis",
        "worst-case error slice",
        "performance--resource trade-off",
        "training trend",
    ):
        text = text.replace(phrase, "registered panel")
    text = text.replace(
        "The planned interpretation compares matched conditions, examines "
        "interval overlap, and records uncertainty at the independent run.",
        "The planned interpretation follows the registered protocol.",
    )
    (tmp_path / "paper" / "sections" / "05_results.tex").write_text(
        text,
        encoding="utf-8",
    )

    review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )

    assert any(
        "training trend or convergence behavior" in issue
        for issue in review["issues"]
    )
    assert any(
        "performance-resource trade-off" in issue
        for issue in review["issues"]
    )


def test_synthetic_results_review_accepts_resource_frontier_analysis(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "research_family": "machine_learning",
        "study_archetype": "systems_testbed",
    })
    text = _complete_synthetic_results_section().replace(
        "The efficiency panel defines a performance--resource trade-off across compute,\n"
        "latency, memory, throughput, and parameter count. The full configuration reaches\n"
        "the strongest endpoint at higher cost, while lighter variants occupy more\n"
        "efficient operating points.",
        "The efficiency panel quantifies the performance--resource frontier. The full\n"
        "configuration has the strongest endpoint, while lighter variants occupy efficient\n"
        "operating points across latency, memory, throughput, energy, and parameter count.",
    )
    (tmp_path / "paper" / "sections" / "05_results.tex").write_text(
        text,
        encoding="utf-8",
    )

    review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": True},
        [],
    )

    assert not any(
        "performance-resource trade-off" in issue
        for issue in review["issues"]
    )


def test_simulation_results_review_allows_benchmark_finding_language(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark",
    })
    (tmp_path / "paper" / "sections" / "05_results.tex").write_text(
        _complete_synthetic_results_section()
        + "\n\nThe results show that our method outperforms the baseline.",
        encoding="utf-8",
    )

    review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )

    assert review["passed"] is True, review


def test_synthetic_table_manifest_and_fallback_use_simulated_assets(tmp_path: Path) -> None:
    from server.tests._scientific_slide_fixture import write_current_publication_table_bundle

    outputs = write_current_publication_table_bundle(tmp_path)
    before = {path: path.read_bytes() for path in (tmp_path / "experiments").rglob("*.csv")}
    evidence = paper_artifact_builder.prepare(tmp_path, "Finite local comparison")
    table_manifest = json.loads((tmp_path / "paper/tables/TABLE_MANIFEST.json").read_text(encoding="utf-8"))
    previews = {item["label"]: item for item in table_manifest["tables"] if item.get("evidence_status") == "synthetic_preview"}
    expected = {
        "tab:preview-main-results": ("result", "experiments/results/simulated/main_comparison.csv"),
        "tab:preview-ablation": ("ablation", "experiments/results/simulated/ablation.csv"),
        "tab:preview-robustness-calibration": ("robustness", "experiments/results/simulated/robustness.csv"),
        "tab:preview-calibration": ("calibration", "experiments/results/simulated/calibration.csv"),
    }
    assert set(previews) == set(expected)
    for label, (role, data_path) in expected.items():
        assert previews[label]["scientific_role"] == role
        assert previews[label]["data_path"] == data_path
        assert previews[label]["source_data"] == [data_path] and previews[label]["rows"] == 2
    assert all(path.read_bytes() == content for path, content in before.items())
    assert json.loads(outputs["simulation_manifest"].read_text(encoding="utf-8"))["schema"] == 11
    manuscript = paper_artifact_builder.write_fallback(evidence).read_text(encoding="utf-8")
    for label in expected:
        assert rf"\ref{{{label}}}" in manuscript
    for absent in ("tab:paired-reversals", "tab:claim-evidence", "tab:preview-error-analysis", "tab:preview-efficiency"):
        assert rf"\ref{{{absent}}}" not in manuscript
    from server.services.paper_fallback_manuscript import _synthetic_result_prose
    prose = _synthetic_result_prose(tmp_path)
    assert "strongest" not in prose and "outperforms" not in prose and "loss after" not in prose
    assert "strongest primary endpoint" not in manuscript
    assert "controlled removal reduces performance" not in manuscript
    assert manuscript.count(SIMULATION_END_DISCLOSURE) == 1
    assert manuscript.index(SIMULATION_END_DISCLOSURE) > manuscript.index(r"\section{Conclusion}")
    assert "SYNTHETIC PREVIEW -- NOT FOR SUBMISSION" not in manuscript


def test_synthetic_tables_without_frozen_manifest_fail_without_inventing_contract(tmp_path: Path) -> None:
    from server.tests._scientific_slide_fixture import write_current_publication_table_bundle

    outputs = write_current_publication_table_bundle(tmp_path)
    outputs["simulation_manifest"].unlink()
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    evidence = paper_artifact_builder.snapshot(tmp_path, "Finite local comparison")
    from server.services.paper_submission_tables import write_submission_tables
    # Snapshot reconciliation is a separate figure owner concern; this test
    # exercises the table producer's no-invented-manifest failure boundary.
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises((ValueError, FileNotFoundError)):
        write_submission_tables(evidence)
    assert not outputs["simulation_manifest"].exists()
    assert all(path.read_bytes() == content for path, content in before.items())


def test_workflow_paper_gate_requires_reviewed_staged_state(tmp_path: Path) -> None:
    seed_project(tmp_path)
    PaperDraftingService().prepare(tmp_path, {})
    engine = WorkflowEngine()

    gate = engine._paper_acceptance_gate(
        str(tmp_path),
        require_staged=True,
        paper_options={},
    )

    assert gate["accepted"] is False
    staged = gate["details"]["staged_drafting"]
    assert staged["passed"] is False
    assert any("incomplete staged paper phase" in issue for issue in staged["issues"])


@pytest.mark.asyncio
async def test_workflow_staged_executor_scopes_each_skill_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    engine = WorkflowEngine()
    events: list[tuple[str, dict]] = []
    invocations: list[dict] = []

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    async def fake_invoke_skill(_name: str, _prompt: str, **kwargs) -> str:
        invocations.append(kwargs)
        return "section written"

    async def fake_draft(
        _project_path,
        _direction,
        _options,
        invoke_stage,
        emit_stage,
        **_kwargs,
    ) -> dict:
        await emit_stage("paper_stage_started", {
            "stage_id": "introduction",
            "stage_label": "Introduction",
            "stage_index": 2,
            "stage_total": 12,
            "attempt": 1,
            "maximum_attempts": 2,
        })
        await invoke_stage(
            "introduction",
            "write only the introduction",
            "Permitted write targets: paper/sections/01_introduction.tex",
        )
        await emit_stage("paper_stage_reviewed", {
            "stage_id": "introduction",
            "stage_label": "Introduction",
            "stage_index": 2,
            "stage_total": 12,
            "attempt": 1,
            "passed": True,
            "issues": [],
        })
        return {"status": "completed", "main_path": str(tmp_path / "paper" / "main.tex")}

    from server.agent import tools as agent_tools
    from server.services.paper_artifacts import paper_artifact_builder
    from server.services.paper_drafting import paper_drafting_service

    monkeypatch.setattr(engine, "_ensure_agent_tools", lambda: None)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(agent_tools, "invoke_skill", fake_invoke_skill)
    monkeypatch.setattr(paper_artifact_builder, "prepare", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paper_drafting_service, "draft", fake_draft)
    monkeypatch.setattr(
        skill_orchestrator,
        "select",
        lambda *_args, **_kwargs: SkillPlan(node_id="paper", primary="paper-write"),
    )
    monkeypatch.setattr(
        skill_orchestrator,
        "record",
        lambda *_args, **_kwargs: tmp_path / ".merak" / "skill-plan.json",
    )
    monkeypatch.setattr(skill_orchestrator, "mark_execution", lambda *_args, **_kwargs: None)

    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(id="paper-run", project_path=str(tmp_path), nodes=[node])
    result = await engine._execute_staged_paper(
        node=node,
        run=run,
        research_direction="robust representation",
        opts={},
    )

    assert json.loads(result)["status"] == "completed"
    assert len(invocations) == 1
    assert invocations[0]["allowed_tools_override"] == ["Read", "Write", "Edit", "Glob", "Grep"]
    assert "Permitted write targets" in invocations[0]["invocation_contract"]
    assert any(event == "paper_stage_started" for event, _ in events)
    assert any(event == "paper_stage_reviewed" for event, _ in events)


def test_consistency_stage_reviews_only_its_report_and_routes_section_repairs(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    paths = service.paths(tmp_path)

    outputs = service.stage_outputs(paths, "consistency")
    write_targets = service.stage_write_targets(paths, "consistency")
    contract = service.invocation_contract("consistency", write_targets)

    assert outputs == [paths["cross_review"]]
    assert write_targets == [paths["cross_review"]]
    assert paths["sections"] / "01_introduction.tex" not in write_targets
    assert str(paths["sections"] / "01_introduction.tex") not in contract
    assert str(paths["main"]) not in contract
    assert "Targets that already exist" in contract
    assert "Targets that do not exist yet" in contract
    assert "Do not call Read on a target listed as not existing" in contract


def test_invocation_contract_marks_new_targets_for_write_before_read(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.tex"
    existing.write_text("draft", encoding="utf-8")
    missing = tmp_path / "missing.tex"

    contract = PaperDraftingService.invocation_contract(
        "results",
        [existing, missing],
    )

    existing_section, missing_section = contract.split(
        "Targets that already exist and may be read before editing:", maxsplit=1
    )[1].split("Targets that do not exist yet:", maxsplit=1)
    assert str(existing) in existing_section
    assert str(missing) not in existing_section
    assert str(missing) in missing_section
    assert "create it directly, then re-read it" in contract


def test_prepare_resets_only_stale_consistency_contract_budget(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    paths = service.paths(tmp_path)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state["stages"]["introduction"] = {
        "status": "completed",
        "attempts": 2,
    }
    state["stages"]["consistency"] = {
        "status": "revision_required",
        "attempts": 6,
        "contract_version": CONSISTENCY_CONTRACT_VERSION - 1,
        "review_issues": ["old bounded-write failure"],
    }
    paths["state"].write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    refreshed = service.prepare(tmp_path, {"target_venue": "ICLR"})

    assert refreshed["stages"]["introduction"]["attempts"] == 2
    assert refreshed["stages"]["consistency"] == {
        "status": "pending",
        "attempts": 0,
        "review_passed": False,
        "review_issues": [],
        "contract_version": CONSISTENCY_CONTRACT_VERSION,
    }


@pytest.mark.asyncio
async def test_interrupted_paper_stage_does_not_consume_section_revision(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "max_revision_rounds": 3,
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }
    service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    service.mark_stage(paths, "blueprint", "running", attempt=1)
    events: list[tuple[str, dict]] = []

    async def invoke_stage(stage_id: str, _prompt: str, _contract: str) -> str:
        assert stage_id == "blueprint"
        raise RuntimeError("OpenAI API error 502: upstream unavailable")

    async def emit(event: str, payload: dict) -> None:
        events.append((event, payload))

    with pytest.raises(RuntimeError, match="502"):
        await service.draft(
            tmp_path,
            "test direction",
            options,
            invoke_stage,
            emit,
        )

    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    blueprint = state["stages"]["blueprint"]
    assert blueprint["status"] == "pending"
    assert blueprint["attempts"] == 0
    assert "paper_stage_resumed" in [event for event, _ in events]
    assert "paper_stage_interrupted" in [event for event, _ in events]


def test_falsifiable_contributions_accept_prose_and_require_rejection_conditions() -> None:
    prose = (
        "We make three falsifiable contributions. First, we specify a geometric "
        "encoder; it is rejected if a matched non-geometric control performs the same. "
        "Second, we define a robustness protocol; it is rejected if rankings remain "
        "unchanged under the declared shift. Third, we provide a leakage audit; it is "
        "rejected if split provenance cannot be reproduced."
    )
    structure = PaperDraftingService.falsifiable_contribution_structure(prose)
    assert structure == {"contributions": 3, "falsification_conditions": 3}

    marketing = (
        "First, we propose a novel encoder. Second, we provide a broad benchmark. "
        "Third, we introduce an effective training recipe."
    )
    weak = PaperDraftingService.falsifiable_contribution_structure(marketing)
    assert weak["contributions"] == 3
    assert weak["falsification_conditions"] == 0


def test_falsifiable_contributions_accept_roman_numeral_enumeration() -> None:
    prose = (
        "Our contributions are falsifiable. "
        "(i) We introduce a shortcut-suppression objective. This contribution "
        "is rejected if identity predictability does not decrease. "
        "(ii) We provide a leakage-safe evaluation. Its mechanism claim is "
        "rejected if structural improvements do not align with transfer. "
        "(iii) We test held-out stress behavior; a worse stress slope than the "
        "matched control would refute the robustness contribution."
    )

    structure = PaperDraftingService.falsifiable_contribution_structure(prose)

    assert structure == {"contributions": 3, "falsification_conditions": 3}


def test_falsifiable_contributions_accept_pronouns_and_condition_first_prose() -> None:
    """Regression for an accepted Introduction that was stuck for six rounds."""
    prose = (
        "This paper makes four falsifiable contributions. "
        "First, it formulates transfer as a factorization hypothesis: if a "
        "compute-matched monolithic baseline has the same worst-shift behavior, "
        "the transfer claim is rejected. "
        "Second, it introduces shared and subject-specific pathways: if removal "
        "does not change transfer or nuisance leakage, the mechanism claim is "
        "rejected. "
        "Third, it defines a diagnostic protocol; this protocol rejects apparent "
        "gains when preprocessing leakage or unequal budgets explain them. "
        "Fourth, it evaluates deployment failure modes: the robustness claims "
        "are rejected if nuisance suppression degrades subgroup performance."
    )

    structure = PaperDraftingService.falsifiable_contribution_structure(prose)

    assert structure == {"contributions": 4, "falsification_conditions": 4}


def test_falsifiable_contributions_accept_open_academic_verbs_and_negative_evidence() -> None:
    """Regression for the multi-axis benchmark Introduction in run 1979db377d3c."""
    prose = (
        "The framework makes three falsifiable contributions. "
        "First, it turns representativeness into a matched-pair test. The "
        "hypothesis is supported only if one pair satisfies the reversal rule; "
        "if no pair qualifies, the stronger hypothesis is rejected. "
        "Second, it makes auditability an endpoint-level requirement. A missing "
        "link renders an estimate ineligible, and this contribution is falsified "
        "for any endpoint that cannot meet traceability. "
        "Third, it tests whether ordering differences follow from protocol choice. "
        "An unmatched contrast cannot support the explanation, while a legal "
        "contrast below the threshold is negative evidence for the sensitivity."
    )

    structure = PaperDraftingService.falsifiable_contribution_structure(prose)

    assert structure == {"contributions": 3, "falsification_conditions": 3}

    numbered = (
        "The framework makes three falsifiable contributions. "
        "(1) Registered rank-stability test. It is supported only if a pair "
        "reverses and is falsified otherwise. "
        "(2) Endpoint auditability. A missing link falsifies auditability for "
        "that endpoint. "
        "(3) Matched protocol-sensitivity test. Sensitivity is unsupported "
        "below the threshold and an unmatched contrast is ineligible."
    )
    assert PaperDraftingService.falsifiable_contribution_structure(numbered) == {
        "contributions": 3,
        "falsification_conditions": 3,
    }


def test_falsifiable_contributions_accept_latex_items_with_rejection_rules() -> None:
    """Regression for the real enumerated Introduction in run 1979db377d3c."""
    prose = r"""
    \paragraph{Falsifiable contributions.}
    \begin{enumerate}
      \item A rank-stability estimand. It is rejected if no pair meets all
      three conditions and the leader remains non-dominated.
      \item Endpoint-level auditability. A missing or contract-mismatched
      link rejects auditability for that endpoint.
      \item A matched protocol-sensitivity test. Sensitivity is supported
      only when an eligible contrast changes the decision; it is rejected
      when valid contrasts remain below the threshold.
    \end{enumerate}
    """

    assert PaperDraftingService.falsifiable_contribution_structure(prose) == {
        "contributions": 3,
        "falsification_conditions": 3,
    }


def test_visible_latex_prose_excludes_template_package_names() -> None:
    source = (
        r"\documentclass{article}"
        "\n"
        r"\usepackage{iclr2027_conference,times}"
        "\n"
        r"\title{Auditable Multi-Axis Evaluation}"
    )

    prose = visible_latex_prose(source)

    assert "iclr2027_conference" not in prose
    assert "Auditable Multi-Axis Evaluation" in prose
    assert find_visible_code_artifact_references(prose) == []
