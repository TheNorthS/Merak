from __future__ import annotations

from server.tests._node_risk_audit_support import (
    ApiVisualReview as ApiVisualReview,
    CrossModelReviewer as CrossModelReviewer,
    NODE_CONTRACTS as NODE_CONTRACTS,
    NODE_RISK_CHECKLIST as NODE_RISK_CHECKLIST,
    PENDING_RE as PENDING_RE,
    Path as Path,
    ReviewRound as ReviewRound,
    SIMULATION_SCOPE_RE as SIMULATION_SCOPE_RE,
    SimpleNamespace as SimpleNamespace,
    UNCERTAINTY_RE as UNCERTAINTY_RE,
    _api_review_result as _api_review_result,
    _has_unbounded_supported_claim as _has_unbounded_supported_claim,
    _patch_direct_reviewer_routes as _patch_direct_reviewer_routes,
    _placeholder_excerpt as _placeholder_excerpt,
    _sha256 as _sha256,
    _write_json as _write_json,
    agent_engine as agent_engine,
    api_visual_reviewer as api_visual_reviewer,
    build_review_fix_scope as build_review_fix_scope,
    json as json,
    node_risk_audit_service as node_risk_audit_service,
    pytest as pytest,
)


def test_every_workflow_node_has_a_stage_specific_risk_validator() -> None:
    for node_id in NODE_CONTRACTS:
        assert callable(
            getattr(node_risk_audit_service, f"_audit_{node_id.replace('-', '_')}", None)
        ), node_id


def test_every_workflow_node_exposes_a_concrete_risk_checklist() -> None:
    assert set(NODE_RISK_CHECKLIST) == set(NODE_CONTRACTS)
    assert all(len(checks) >= 3 for checks in NODE_RISK_CHECKLIST.values())
    assert all(all(str(item).strip() for item in checks) for checks in NODE_RISK_CHECKLIST.values())


def test_evidence_boundary_language_is_not_misread_as_a_claim_or_template() -> None:
    safe = (
        "Placeholder/demo figures must not be selected as paper evidence. "
        "The manuscript should not claim that the proposed method significantly "
        "outperforms a baseline before experiments are run."
    )

    assert _placeholder_excerpt(safe) == ""
    assert _placeholder_excerpt(
        "Synthetic preview / planning visualization. NOT FOR SUBMISSION."
    ) == ""
    assert _has_unbounded_supported_claim(safe) is False
    assert _placeholder_excerpt("TODO: insert result") != ""


def test_claim_detection_is_local_to_the_supported_statement() -> None:
    negated = (
        "Our intended delta is not that the proposed architecture has already "
        "outperformed existing models."
    )
    contradicted = (
        "Experiments were not run. Our proposed model significantly "
        "outperforms every baseline."
    )

    assert _has_unbounded_supported_claim(
        negated, current_method_only=True
    ) is False
    assert _has_unbounded_supported_claim(
        contradicted, current_method_only=True
    ) is True
    conditional = (
        "Our mechanism is meaningful only if the proposed model significantly "
        "outperforms the matched control."
    )
    assert _has_unbounded_supported_claim(
        conditional, current_method_only=True
    ) is False


@pytest.mark.parametrize(
    "text",
    [
        "No training runs have been conducted.",
        "The experiments remain to be performed.",
        "Evaluation is yet to be executed.",
        "实验尚未开展，所有结论待验证。",
    ],
)
def test_pending_state_accepts_normal_no_run_wording(text: str) -> None:
    assert PENDING_RE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "We report a 95% CI for every endpoint.",
        "Dispersion is summarized by SD and IQR.",
        "Variance and error bars are shown across conditions.",
    ],
)
def test_uncertainty_detection_accepts_standard_abbreviations(text: str) -> None:
    assert UNCERTAINTY_RE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Findings are bounded to the deterministic simulator and registered conditions.",
        "The controlled study defines the evaluation domain.",
        "结论仅适用于预设场景和受控评估范围。",
    ],
)
def test_simulation_scope_does_not_require_literal_benchmark(text: str) -> None:
    assert SIMULATION_SCOPE_RE.search(text)


def test_paper_claim_finding_reports_exact_included_source_location(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper"
    sections = paper / "sections"
    sections.mkdir(parents=True)
    (paper / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}"
        "\\input{sections/results}\\end{document}",
        encoding="utf-8",
    )
    result_section = sections / "results.tex"
    result_section.write_text(
        "\\section{Results}\n"
        "Our proposed model significantly outperforms every matched baseline.\n",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": False},
    )
    claim = next(item for item in findings if item["id"] == "PAPER-CLAIM-001")

    assert claim["evidence"][0] == "paper/sections/results.tex"
    assert claim["locations"] == [{
        "path": "paper/sections/results.tex",
        "line": 2,
        "match": "outperforms",
        "context": "Our proposed model significantly outperforms every matched baseline.",
    }]
    assert "paper/sections/results.tex:2" in claim["message"]
    assert "paper/sections/results.tex:2" in claim["remediation"]

    result_section.write_text(
        "\\section{Results}\n"
        "Our mechanism is meaningful only if the proposed model significantly "
        "outperforms every matched baseline.\n",
        encoding="utf-8",
    )
    conditional_findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": False},
    )
    assert not any(
        item["id"] == "PAPER-CLAIM-001"
        for item in conditional_findings
    )


def test_domain_placeholder_term_is_not_treated_as_template_text() -> None:
    scientific_prose = (
        "The fixed-channel baseline handles absent channels with a conventional "
        "missing-channel placeholder and receives no observability mask."
    )

    assert _placeholder_excerpt(scientific_prose) == ""
    assert _placeholder_excerpt("This section contains placeholder content.") != ""


def test_bounded_missing_evidence_is_not_treated_as_template_text() -> None:
    bounded_limitation = (
        "方法合同仍将真实数据集身份、合法 shift 与硬件身份列为待补充项；"
        "若这些项目缺失，不能扩大结论的外部有效性。"
    )

    assert _placeholder_excerpt(bounded_limitation) == ""
    assert _placeholder_excerpt("结果部分仍待补充。") != ""


def test_paper_graphic_is_resolved_from_main_document_directory(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper"
    sections = paper / "sections"
    figures = tmp_path / "figures" / "diagrams"
    sections.mkdir(parents=True)
    figures.mkdir(parents=True)
    (figures / "method.png").write_bytes(b"rendered figure")
    (paper / "main.tex").write_text(
        "\\documentclass{article}\\usepackage{graphicx}"
        "\\begin{document}\\input{sections/method}\\end{document}",
        encoding="utf-8",
    )
    (sections / "method.tex").write_text(
        "\\includegraphics{../figures/diagrams/method.png}",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": False},
    )

    assert not any(item["id"] == "PAPER-FIG-001" for item in findings)


@pytest.mark.asyncio
async def test_review_loop_stops_when_fix_does_not_change_manuscript(
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
    review_calls: list[dict] = []
    fix_calls: list[dict] = []

    async def fake_review(**kwargs) -> ApiVisualReview:
        review_calls.append(kwargs)
        return _api_review_result(
            tmp_path,
            {
                "score": 5,
                "verdict": "needs_work",
                "strengths": ["Bounded claims."],
                "weaknesses": ["Clarify the protocol."],
                "action_items": ["Revise the protocol wording."],
            },
            1,
        )

    async def fake_run(**kwargs) -> str:
        fix_calls.append(kwargs)
        return "No source edit was made."

    _patch_direct_reviewer_routes(monkeypatch)
    monkeypatch.setattr(
        api_visual_reviewer,
        "review_manuscript",
        fake_review,
    )
    monkeypatch.setattr(
        agent_engine,
        "create_session",
        lambda **_kwargs: SimpleNamespace(id="review-test", project_path=""),
    )
    monkeypatch.setattr(agent_engine, "run", fake_run)

    state = await CrossModelReviewer().run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=4,
        evidence_mode="synthetic_preview",
    )

    assert len(review_calls) == 1
    assert len(fix_calls) == 1
    assert len(state.rounds) == 1
    assert state.current_round == 1
    assert state.bounded_complete is True
    assert state.is_complete is True
    assert state.fallback_reason == "revision_produced_no_source_change"


@pytest.mark.asyncio
async def test_complete_synthetic_review_can_be_publication_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Complete benchmark\\end{document}",
        encoding="utf-8",
    )

    async def fake_review(**_kwargs) -> ApiVisualReview:
        return _api_review_result(
            tmp_path,
            {
                "score": 7.0,
                "verdict": "ready",
                "strengths": ["Complete reproducible benchmark."],
                "weaknesses": [],
                "action_items": [],
            },
            1,
        )

    _patch_direct_reviewer_routes(monkeypatch)
    monkeypatch.setattr(api_visual_reviewer, "review_manuscript", fake_review)
    state = await CrossModelReviewer().run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=2,
        evidence_mode="synthetic_preview",
    )

    assert state.threshold_met is True
    assert state.publication_ready is True


def test_review_fix_scope_bounds_actions_and_existing_targets(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    (paper / "sections").mkdir(parents=True)
    (paper / "tables").mkdir(parents=True)
    main = paper / "main.tex"
    main.write_text("\\input{sections/04_experiments}", encoding="utf-8")
    for relative in (
        "sections/03_method.tex",
        "sections/04_experiments.tex",
        "tables/study_design.tex",
    ):
        (paper / relative).write_text("Draft", encoding="utf-8")

    review_round = ReviewRound(
        round_number=1,
        score=5.5,
        verdict="needs_work",
        action_items=[
            "paper/tables/study_design.tex: freeze datasets, endpoints, and splits.",
            "paper/sections/03_method.tex: formalize the decoder and loss.",
            "paper/sections/04_experiments.tex: define the bootstrap protocol.",
            "methods/missing_contract: document the baseline evaluation budget.",
            "paper/sections/99_nonexistent.tex: this fifth item must be deferred.",
        ],
    )

    actions, targets = build_review_fix_scope(tmp_path, main, review_round)
    relative_targets = [path.relative_to(tmp_path).as_posix() for path in targets]

    assert len(actions) == 4
    assert len(targets) <= 3
    assert relative_targets == [
        "paper/tables/study_design.tex",
        "paper/sections/03_method.tex",
        "paper/sections/04_experiments.tex",
    ]
    assert all(path.is_file() for path in targets)


@pytest.mark.asyncio
async def test_review_fix_is_targeted_and_bypasses_outer_transport_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    section = tmp_path / "paper" / "sections" / "04_experiments.tex"
    section.parent.mkdir(parents=True)
    paper.write_text("\\input{sections/04_experiments}", encoding="utf-8")
    section.write_text("Protocol draft", encoding="utf-8")
    review_calls: list[dict] = []
    fix_calls: list[dict] = []
    transport_labels: list[str] = []
    session_index = 0

    async def fake_review(**kwargs) -> ApiVisualReview:
        review_calls.append(kwargs)
        return _api_review_result(
            tmp_path,
            {
                "score": 5.5,
                "verdict": "needs_work",
                "strengths": ["Bounded claims."],
                "weaknesses": ["Protocol needs precision."],
                "action_items": [
                    "paper/sections/04_experiments.tex: define the primary endpoint.",
                    "paper/sections/04_experiments.tex: define the bootstrap unit.",
                ],
            },
            1,
        )

    async def fake_run(**kwargs) -> str:
        fix_calls.append(kwargs)
        return "No edit was required."

    async def retry_transport(label: str, operation) -> str:
        transport_labels.append(label)
        return await operation()

    def create_session(**_kwargs):
        nonlocal session_index
        session_index += 1
        return SimpleNamespace(
            id=f"targeted-review-{session_index}",
            project_path="",
            max_iterations=100,
        )

    _patch_direct_reviewer_routes(monkeypatch)
    monkeypatch.setattr(
        api_visual_reviewer,
        "review_manuscript",
        fake_review,
    )
    monkeypatch.setattr(agent_engine, "create_session", create_session)
    monkeypatch.setattr(agent_engine, "run", fake_run)

    state = await CrossModelReviewer().run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=3,
        evidence_mode="synthetic_preview",
        transport_retry=retry_transport,
    )

    assert transport_labels == ["round-1-review"]
    assert len(review_calls) == 1
    assert len(fix_calls) == 1
    assert fix_calls[0]["tools"] == ["Read", "Edit"]
    assert "paper/sections/04_experiments.tex" in fix_calls[0]["user_message"]
    assert "不得调用 Write" in fix_calls[0]["user_message"]
    assert "当前是完整的固定基准研究" in fix_calls[0]["user_message"]
    assert "可以修订对已注册主对比" in fix_calls[0]["user_message"]
    assert "任何模式都不得添加可见水印、草稿印章" in fix_calls[0]["user_message"]
    assert "当前未运行实验。只能完善" not in fix_calls[0]["user_message"]
    assert state.fallback_reason == "revision_produced_no_source_change"


@pytest.mark.asyncio
async def test_review_fix_rolls_back_when_it_regresses_staged_paper_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    section = tmp_path / "paper" / "sections" / "04_experiments.tex"
    section.parent.mkdir(parents=True)
    paper.write_text(
        "\\input{sections/04_experiments}",
        encoding="utf-8",
    )
    section.write_text("Validated protocol", encoding="utf-8")
    (tmp_path / "paper" / "DRAFT_STATE.json").write_text(
        "{}",
        encoding="utf-8",
    )
    review_calls: list[dict] = []
    fix_calls = 0

    async def fake_review(**kwargs) -> ApiVisualReview:
        review_calls.append(kwargs)
        return _api_review_result(
            tmp_path,
            {
                "score": 5.5,
                "verdict": "needs_work",
                "strengths": ["Bounded claims."],
                "weaknesses": ["Protocol needs precision."],
                "action_items": [
                    "paper/sections/04_experiments.tex: clarify the endpoint."
                ],
            },
            1,
        )

    async def fake_run(**_kwargs) -> str:
        nonlocal fix_calls
        fix_calls += 1
        section.write_text(
            "Regressed protocol " * 2000,
            encoding="utf-8",
        )
        return "Expanded the protocol."

    def fake_reconcile(_project_path, *, reviewer):
        if "Regressed protocol" in section.read_text(encoding="utf-8"):
            return {
                "passed": False,
                "issues": [
                    "experiments: section unfocused "
                    "(2000; preferred maximum 1150)"
                ],
            }
        return {"passed": True, "issues": [], "reviewer": reviewer}

    _patch_direct_reviewer_routes(monkeypatch)
    monkeypatch.setattr(
        api_visual_reviewer,
        "review_manuscript",
        fake_review,
    )
    monkeypatch.setattr(
        agent_engine,
        "create_session",
        lambda **_kwargs: SimpleNamespace(
            id="transactional-review",
            project_path="",
            max_iterations=8,
        ),
    )
    monkeypatch.setattr(agent_engine, "run", fake_run)
    monkeypatch.setattr(
        "server.services.paper_drafting.paper_drafting_service."
        "reconcile_reviewed_artifacts",
        fake_reconcile,
    )

    state = await CrossModelReviewer().run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=3,
        evidence_mode="synthetic_preview",
    )

    assert len(review_calls) == 1
    assert fix_calls == 1
    assert section.read_text(encoding="utf-8") == "Validated protocol"
    assert state.bounded_complete is True
    assert state.is_complete is True
    assert (
        state.fallback_reason
        == "targeted_fix_rejected_by_paper_contract"
    )
    assert any(
        "section unfocused" in item
        for item in state.rounds[-1].action_items
    )


@pytest.mark.asyncio
async def test_review_fix_progress_has_a_hard_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress: list[str] = []

    async def never_finishes() -> str:
        await __import__("asyncio").sleep(1)
        return "unreachable"

    async def record(message: str) -> None:
        progress.append(message)

    monkeypatch.setattr(
        "server.workflows.review_audit.REVIEW_FIX_HEARTBEAT_SECONDS",
        0.005,
    )
    with pytest.raises(TimeoutError):
        await CrossModelReviewer._run_fix_with_progress(
            never_finishes,
            timeout_seconds=0.02,
            on_progress=record,
            progress_label="targeted review fix",
        )

    assert progress
    assert "still running" in progress[0]


@pytest.mark.parametrize("node_id", tuple(NODE_CONTRACTS))
def test_every_node_fails_closed_with_readable_actions_when_artifacts_are_missing(
    tmp_path: Path,
    node_id: str,
) -> None:
    report = node_risk_audit_service.audit_node(
        tmp_path,
        node_id,
        {"run_experiment": False},
        persist=False,
    )

    blockers = [
        item for item in report["findings"]
        if item.get("severity") == "blocker"
    ]
    assert report["status"] == "blocked", node_id
    assert blockers, node_id
    assert all(str(item.get("plain_message") or "").strip() for item in blockers), node_id
    assert all(str(item.get("remediation") or "").strip() for item in blockers), node_id


def test_validator_exception_is_a_node_blocker_and_does_not_abort_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        node_risk_audit_service,
        "_audit_idea",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("malformed artifact")),
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "idea",
        {"run_experiment": False},
        persist=False,
    )
    snapshot = node_risk_audit_service.audit_workflow(
        tmp_path,
        {"run_experiment": False},
        through_node="idea",
        persist=False,
    )

    assert report["status"] == "blocked"
    assert any(item["id"] == "IDEA-VALIDATOR-ERROR" for item in report["findings"])
    assert snapshot["status"] == "blocked"
    assert snapshot["nodes"]["lit"]["status"] == "blocked"
    assert snapshot["nodes"]["idea"]["status"] == "blocked"


def test_literature_risk_audit_detects_duplicate_and_unknown_citations(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text(
        "# Survey\nA disputed result \\cite{missing}.",
        encoding="utf-8",
    )
    (literature / "references.bib").write_text(
        "@article{dup, title={A}, year={2024}, url={https://example/a}}\n"
        "@article{dup, title={B}, year={2025}, url={https://example/b}}\n",
        encoding="utf-8",
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "lit",
        {"run_experiment": False, "research_strategy": {"literature_max_papers": 2}},
    )

    ids = {item["id"] for item in report["findings"]}
    assert report["blocking"] is True
    assert "LIT-BIB-002" in ids
    assert "LIT-CITE-001" in ids
    index = json.loads(
        (tmp_path / ".merak" / "NODE_RISK_AUDIT.json").read_text(encoding="utf-8")
    )
    assert index["nodes"]["lit"]["status"] == "blocked"


def test_literature_usage_counts_known_bib_keys_in_markdown_code_spans(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    entries = []
    mentions = []
    for index in range(4):
        key = f"known{index}"
        entries.append(
            f"@article{{{key}, title={{Paper {index}}}, "
            f"author={{Author {index}}}, year={{2024}}, "
            f"url={{https://example.test/{index}}}}}\n"
        )
        mentions.append(f"Method {index} (`{key}`) defines a comparison boundary.")
    (literature / "survey.md").write_text(
        "# Survey\n\n## Search Protocol\n\n"
        + "\n".join(mentions)
        + "\n\n## Evidence Gap\nA falsifiable gap remains.",
        encoding="utf-8",
    )
    (literature / "references.bib").write_text(
        "".join(entries),
        encoding="utf-8",
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "lit",
        {"research_strategy": {"literature_max_papers": 4}},
        persist=False,
    )

    assert not any(
        item["id"] == "LIT-CITE-002" for item in report["findings"]
    )


def test_literature_revision_cannot_drop_keys_used_by_downstream_artifacts(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature"
    ideas = tmp_path / "ideas"
    sections = tmp_path / "paper" / "sections"
    literature.mkdir()
    ideas.mkdir()
    sections.mkdir(parents=True)
    (literature / "survey.md").write_text(
        "# Survey\n\n## Search Protocol\n\nA bounded evidence gap remains.",
        encoding="utf-8",
    )
    (literature / "references.bib").write_text(
        "@article{kept, title={Kept}, author={A}, year={2025}, "
        "url={https://example.test/kept}}\n",
        encoding="utf-8",
    )
    (ideas / "ideas.md").write_text(
        "Prior work [@removed] motivates the selected comparison.",
        encoding="utf-8",
    )
    (sections / "01_introduction.tex").write_text(
        r"Prior work also appears in the manuscript \cite{removed}.",
        encoding="utf-8",
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "lit",
        {"research_strategy": {"literature_max_papers": 1}},
        persist=False,
    )

    finding = next(
        item
        for item in report["findings"]
        if item["id"] == "LIT-DOWNSTREAM-CITE-001"
    )
    assert finding["severity"] == "blocker"
    assert finding["evidence"] == ["literature/references.bib"]
    assert "removed" in finding["message"]


def test_paper_risk_audit_accepts_inline_bibliography_entries(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
Prior work established this baseline \cite{known-inline}, while
\cite{missing-key} remains undefined.
\begin{thebibliography}{9}
\bibitem[Author et al.(2024)]{known-inline}
Author. A traceable inline reference. 2024.
\end{thebibliography}
\end{document}
""",
        encoding="utf-8",
    )

    findings = node_risk_audit_service._audit_paper(
        tmp_path,
        {"run_experiment": False},
    )

    citation_findings = [
        item for item in findings if item["id"] == "PAPER-CITE-001"
    ]
    assert len(citation_findings) == 1
    assert "missing-key" in citation_findings[0]["message"]
    assert "known-inline" not in citation_findings[0]["message"]


def test_literature_risk_rejects_synthetic_fallback_bibliography(
    tmp_path: Path,
) -> None:
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text(
        "# Survey\nSearch protocol and evidence gap.",
        encoding="utf-8",
    )
    (literature / "references.bib").write_text(
        "@misc{workflow_fallback_literature,\n"
        "  title={Workflow fallback literature placeholder},\n"
        "  author={MERAK},\n"
        "  year={2026}\n"
        "}\n",
        encoding="utf-8",
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "lit",
        {"research_strategy": {"literature_max_papers": 1}},
        persist=False,
    )

    assert report["blocking"] is True
    assert any(item["id"] == "LIT-TEMPLATE-002" for item in report["findings"])


def test_idea_and_novelty_surface_unapproved_direction_drift(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / ".merak" / "RESEARCH_WORKFLOW_CONTRACT.json",
        {"direction": "quantum error correction"},
    )
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "ideas.md").write_text(
        "# Ideas\n"
        "## Idea 1: Retail demand forecasting\n"
        "Hypothesis: promotion features improve weekly forecasts.\n"
        "Mechanism: a seasonal feature mixer.\n"
        "Nearest work: a retail forecasting baseline.\n"
        "Falsification: reject if error does not improve.\n"
        "Feasibility: use an available sales dataset.\n",
        encoding="utf-8",
    )
    selected = {
        "title": "Retail demand forecasting with seasonal features",
        "problem_statement": "Forecast product demand.",
        "hypothesis": "Seasonal features reduce forecasting error.",
        "claims": [{"id": "C1", "statement": "Forecast error decreases."}],
        "mechanisms": [{
            "id": "M1",
            "name": "Seasonal feature mixer",
            "description": "Mix promotion and calendar features.",
        }],
        "falsification_conditions": ["Reject C1 if held-out error does not decrease."],
    }
    _write_json(ideas / "SELECTED_IDEA.json", selected)
    (ideas / "novelty_report.md").write_text(
        "# Novelty\n"
        "Retail demand forecasting with seasonal features\n"
        "Nearest work and overlap are compared. The result is uncertain. "
        "Recommendation: select this candidate.\n",
        encoding="utf-8",
    )

    idea_findings = node_risk_audit_service._audit_idea(tmp_path, {})
    novelty_findings = node_risk_audit_service._audit_novelty(tmp_path, {})

    assert any(item["id"] == "IDEA-DIRECTION-001" for item in idea_findings)
    assert any(item["id"] == "NOV-DIRECTION-001" for item in novelty_findings)


def test_planned_results_cannot_claim_empirical_superiority(tmp_path: Path) -> None:
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text(
        "# Results\nExperiments were not run. The proposed method significantly "
        "outperforms all baselines.",
        encoding="utf-8",
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "results",
        {"run_experiment": False},
    )

    assert any(item["id"] == "RESULT-MODE-002" for item in report["findings"])
    assert report["blocking"] is True


def test_placeholder_figure_cannot_remain_paper_eligible(tmp_path: Path) -> None:
    output = tmp_path / "figures" / "placeholders" / "planned_result.pdf"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"%PDF-1.4\nplaceholder")
    _write_json(
        tmp_path / "figures" / "FIGURE_MANIFEST.json",
        {
            "schema": 1,
            "figures": [{
                "id": "planned_result_demo",
                "output_path": "figures/placeholders/planned_result.pdf",
                "output_sha256": _sha256(output),
                "paper_ready": True,
                "metadata": {
                    "evidence_status": "placeholder",
                    "watermark": "DEMO VALUES - NOT EVIDENCE",
                },
            }],
        },
    )

    findings = node_risk_audit_service._audit_figure(
        tmp_path,
        {"run_experiment": False},
    )

    assert any(item["id"] == "FIG-PLACEHOLDER-001" for item in findings)

    from server.services.figure_artifacts import figure_artifact_registry

    reconciled = figure_artifact_registry.reconcile(tmp_path / "figures")
    placeholder = reconciled["figures"][0]
    assert placeholder["paper_ready"] is False
    assert placeholder["metadata"]["paper_selected"] is False
    repaired = node_risk_audit_service._audit_figure(
        tmp_path,
        {"run_experiment": False},
    )
    assert not any(item["id"] == "FIG-PLACEHOLDER-001" for item in repaired)
