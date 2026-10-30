from __future__ import annotations

from server.tests._staged_paper_drafting_support import (
    ADMIN_RE as ADMIN_RE,
    AUTHOR_STAGE_ORDER as AUTHOR_STAGE_ORDER,
    DISPLAY_MATH_RE as DISPLAY_MATH_RE,
    PAPER_STAGE_ORDER as PAPER_STAGE_ORDER,
    PaperDraftingService as PaperDraftingService,
    Path as Path,
    SECTION_SPECS as SECTION_SPECS,
    citation_keys as citation_keys,
    final_consistency_verdict as final_consistency_verdict,
    find_internal_contract_references as find_internal_contract_references,
    find_visible_code_artifact_references as find_visible_code_artifact_references,
    json as json,
    pytest as pytest,
    re as re,
    reference_keys as reference_keys,
    seed_project as seed_project,
    synthetic_analysis_requirements as synthetic_analysis_requirements,
    word_count as word_count,
)


def test_word_count_handles_cjk_manuscript_without_spaces() -> None:
    chinese = "研究方法通过冻结切分与配对估计检验跨轴排序稳定性。" * 60

    assert word_count(chinese) >= 600
    assert word_count("English evidence " + chinese) == word_count(chinese) + 2


def test_contract_reference_detection_preserves_domain_identifiers() -> None:
    text = (
        "Signals from EEG electrodes C3, C4, F3, and F4 were re-referenced. "
        "The C3 channel was absent in one montage."
    )

    assert find_internal_contract_references(text, {"C3", "C4", "F3", "F4"}) == []
    assert find_internal_contract_references(
        "Claim C3 depends on mechanism M2 and requirement I4; falsification F1 is decisive.",
        {"C3", "M2", "I4", "F1"},
    ) == ["C3", "F1", "I4", "M2"]
    assert find_internal_contract_references(
        r"Claim~\texttt{C4} and contract IDs C3, M2 remain internal.",
        {"C3", "C4", "M2"},
    ) == ["C3", "C4", "M2"]


def test_publication_language_rejects_code_symbols_but_preserves_model_names() -> None:
    assert find_visible_code_artifact_references(
        "CBraMod and CrossDomainTransformer improve macro-F1."
    ) == []
    hits = find_visible_code_artifact_references(
        "We call ObjectiveModel.forward from experiments/src/models.py and "
        "store source_run_id."
    )
    assert "ObjectiveModel.forward" in hits
    assert "experiments/src/models.py" in hits
    assert "source_run_id" in hits


def test_publication_language_preserves_math_subscripts_but_rejects_texttt_code() -> None:
    assert find_visible_code_artifact_references(
        r"For each axis $a$, let $o_a$, $p_m$, $q_a$, and $z_m(x)$ denote estimands."
    ) == []
    hits = find_visible_code_artifact_references(
        r"The implementation uses $\texttt{linear_reference}$ and source_run_id."
    )
    assert "linear_reference" in hits
    assert "source_run_id" in hits


def test_publication_language_preserves_display_equation_subscripts() -> None:
    latex = r"""
    \begin{equation}
    \mathcal{L}_{\mathrm{con}}=-\frac{1}{2B}\sum_{i=1}^{B}
    \log\frac{e^{s_{ii}}}{\sum_j e^{s_{ij}}}.
    \end{equation}
    \begin{align}
    y_{ck} &= \sum_t b_t, & q_a &= z_m(x).
    \end{align}
    """

    assert find_visible_code_artifact_references(latex) == []


def test_publication_language_ignores_nonvisible_latex_asset_arguments() -> None:
    latex = (
        r"Figure~\ref{fig:method_architecture} explains the method. "
        r"\includegraphics[width=\linewidth]{figures/diagrams/method_architecture.pdf} "
        r"\input{tables/method_components}"
    )

    assert find_visible_code_artifact_references(latex) == []


def test_section_review_does_not_treat_math_subscripts_as_code(
    tmp_path: Path,
) -> None:
    section = tmp_path / "paper" / "sections" / "03_method.tex"
    section.parent.mkdir(parents=True)
    section.write_text(
        r"\section{Method}" + "\n\n"
        + (r"For each axis $a$, $g_a$, $m_a$, $x_i$, and $y_i$ denote "
           r"scientific quantities in the registered estimand. " * 80),
        encoding="utf-8",
    )

    review = PaperDraftingService().section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "method"),
        {"mode": "executed", "submission_eligible": True},
        [],
    )

    assert not any(
        "implementation symbols or artifact paths" in issue
        for issue in review["issues"]
    )


def test_component_control_prose_satisfies_ablation_interpretation() -> None:
    pattern = synthetic_analysis_requirements("algorithm_benchmark")[
        "component-ablation interpretation"
    ]
    prose = (
        "Matched component controls isolate one factor at a time. "
        "The architecture control reduces accuracy while the calibration "
        "control changes proper-score behavior."
    )

    assert re.search(pattern, prose.casefold())


def test_falsifiable_contributions_accept_normal_scientific_outcome_language() -> None:
    prose = r"""
    This paper makes three falsifiable contributions.
    \textbf{First}, it defines a paired decision rule; absence of the required
    direction contradicts the reversal hypothesis.
    \textbf{Second}, it defines traceability, which fails for any endpoint
    whose source record cannot be recovered.
    \textbf{Third}, it isolates one factor, and this interpretation is
    falsified whenever a control changes more than the declared factor.
    """

    structure = PaperDraftingService.falsifiable_contribution_structure(prose)
    assert structure == {"contributions": 3, "falsification_conditions": 3}


def test_admin_marker_detection_does_not_reject_scientific_not_evidence_phrase() -> None:
    assert ADMIN_RE.search(
        "The observed failures are not evidence for validity under shift."
    ) is None
    assert ADMIN_RE.search("Preview only: NOT EVIDENCE") is not None
    assert ADMIN_RE.search("Workflow gate status remains internal") is not None


@pytest.mark.parametrize(
    ("venue", "family", "expected"),
    [
        ("TMLR", "machine_learning", "generic_journal"),
        ("IEEE TPAMI", "machine_learning", "ieee_acm_journal"),
        ("Bioinformatics", "computational_biology", "biomedical_journal"),
        ("Annals of Mathematics", "theoretical_formal", "mathematics_theory"),
        ("Qualitative Research", "qualitative_humanities", "social_qualitative"),
    ],
)
def test_venue_family_policy_does_not_force_every_field_into_ml_layout(
    venue: str,
    family: str,
    expected: str,
) -> None:
    assert PaperDraftingService.canonical_venue_family(
        venue, {"family": family}
    ) == expected


def test_final_consistency_verdict_ignores_historical_fail_mentions() -> None:
    assert final_consistency_verdict(
        "Previous FAIL was repaired.\n## Final Consistency Verdict\n**PASS.**"
    ) == "PASS"
    assert final_consistency_verdict(
        "## Final Consistency Verdict\n**FAIL.** unresolved contradiction"
    ) == "FAIL"
    assert final_consistency_verdict("## Checks Performed\nNo verdict yet.") == ""


def test_latex_semantic_parsers_support_biblatex_grouped_refs_and_display_math() -> None:
    text = (
        r"\parencite[see][p. 4]{ref1,ref2} "
        r"\textcite{ref3} \autocite*{ref4} \footcite{ref5} "
        r"\cref{fig:a,fig:b} \autoref{tab:a} "
        r"\crefrange{fig:c}{fig:e}"
    )

    assert citation_keys(text) == {"ref1", "ref2", "ref3", "ref4", "ref5"}
    assert reference_keys(text) == {
        "fig:a", "fig:b", "tab:a", "fig:c", "fig:e",
    }
    assert DISPLAY_MATH_RE.search(r"\[f(x)=x^2\]")
    assert DISPLAY_MATH_RE.search(
        r"\begin{multline}a+b+c=d\\+e\end{multline}"
    )


@pytest.mark.parametrize(
    "text",
    [
        (
            "(1) We introduce a subject-specific adaptation mechanism; "
            "the mechanism would fail if transfer does not improve. "
            "(2) We provide a matched-control evaluation; the claim would be "
            "unsupported when calibration deteriorates."
        ),
        (
            "First, our framework introduces an adaptive encoder whose claim "
            "would not hold if robustness decreases. Second, our evaluation "
            "provides a matched ablation whose conclusion would fail when the "
            "control performs equivalently."
        ),
        (
            r"\begin{itemize}"
            r"\item We define a calibrated objective that would fail if coverage drops."
            r"\item We test a shift protocol that would be unsupported when errors rise."
            r"\end{itemize}"
        ),
    ],
)
def test_falsifiable_contributions_accept_normal_academic_list_wording(
    text: str,
) -> None:
    structure = PaperDraftingService.falsifiable_contribution_structure(text)

    assert structure["contributions"] >= 2
    assert structure["falsification_conditions"] >= 2


def test_prepare_profiles_real_exemplars_without_moving_existing_main(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    main = tmp_path / "paper" / "main.tex"
    main.write_text(
        "\\documentclass{article}\\begin{document}legacy\\end{document}",
        encoding="utf-8",
    )
    service = PaperDraftingService()

    state = service.prepare(tmp_path, {"target_venue": "ICLR"})
    profile = json.loads(
        (tmp_path / "paper" / "PAPER_STYLE_PROFILE.json").read_text(
            encoding="utf-8"
        )
    )

    assert [item["name"] for item in profile["built_in_exemplars"]] == [
        "LaBraM",
        "BIOT",
        "CBraMod",
    ]
    assert state["stages"]["introduction"]["status"] == "pending"
    assert main.read_text(encoding="utf-8") == (
        "\\documentclass{article}\\begin{document}legacy\\end{document}"
    )
    assert not list((tmp_path / "paper" / "revisions").glob("legacy_monolithic_*.tex"))


def test_prepare_archives_prose_and_revokes_acceptance_when_science_changes(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {"target_venue": "ICLR"}
    service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    blueprint = paths["blueprint"]
    introduction = paths["sections"] / "01_introduction.tex"
    blueprint.write_text("# Research Question\nOld blueprint.\n", encoding="utf-8")
    introduction.write_text(
        "\\section{Introduction}\nOld accepted introduction.\n",
        encoding="utf-8",
    )
    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text(
        narrative.read_text(encoding="utf-8") + "\nA scientific revision.\n",
        encoding="utf-8",
    )

    refreshed = service.prepare(tmp_path, options)

    assert refreshed["stages"]["blueprint"]["status"] == "pending"
    assert refreshed["explanation_refresh_requires_model_review"] is True
    assert not refreshed["stages"]["blueprint"]["review_passed"]
    assert blueprint.read_text(encoding="utf-8").endswith("Old blueprint.\n")
    assert "Old accepted introduction" in introduction.read_text(encoding="utf-8")
    archives = list(
        (paths["paper"] / "revisions").glob(
            "source_refresh_*/CONTRIBUTION_BLUEPRINT.md"
        )
    )
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8").endswith("Old blueprint.\n")
    archived_intro = archives[0].parent / "sections" / "01_introduction.tex"
    assert archived_intro.is_file()
    assert "Old accepted introduction" in archived_intro.read_text(encoding="utf-8")


def test_blueprint_validation_rejects_duplicate_required_headings(
    tmp_path: Path,
) -> None:
    service = PaperDraftingService()
    blueprint = tmp_path / "CONTRIBUTION_BLUEPRINT.md"
    headings = (
        "Research Question",
        "Closest-Work Gap",
        "One-Sentence Contribution",
        "Mechanism Logic",
        "Claims and Required Evidence",
        "Alternative Explanations",
        "Section Narrative",
        "Evidence Boundary",
    )
    blocks = [f"# {heading}\n" + ("evidence " * 120) for heading in headings]
    blocks.append("# Research Question\n" + ("duplicate " * 120))
    blueprint.write_text("\n\n".join(blocks), encoding="utf-8")

    review = service.validate_blueprint(blueprint)

    assert review["passed"] is False
    assert any(
        "duplicates heading: research question" in issue
        for issue in review["issues"]
    )


@pytest.mark.asyncio
async def test_draft_quarantines_legacy_duplicate_blueprint_before_invocation(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    blueprint = service.paths(tmp_path)["blueprint"]
    headings = (
        "Research Question",
        "Closest-Work Gap",
        "One-Sentence Contribution",
        "Mechanism Logic",
        "Claims and Required Evidence",
        "Alternative Explanations",
        "Section Narrative",
        "Evidence Boundary",
    )
    blueprint.write_text(
        "\n\n".join(
            [f"# {heading}\n" + ("evidence " * 120) for heading in headings]
            + ["# Research Question\n" + ("duplicate " * 120)]
        ),
        encoding="utf-8",
    )

    async def interrupted_invocation(*_args: object) -> str:
        assert not blueprint.exists()
        raise RuntimeError("stop after quarantine assertion")

    with pytest.raises(RuntimeError, match="quarantine assertion"):
        await service.draft(
            tmp_path,
            "bounded study",
            {"target_venue": "ICLR"},
            interrupted_invocation,
        )

    assert list(
        (tmp_path / "paper" / "revisions").glob(
            "invalid_blueprint_*.md"
        )
    )


def test_paper_profile_prepare_is_byte_stable_when_contract_is_unchanged(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "research_family": "machine_learning",
        "study_archetype": "systems_testbed",
    }

    service.build_style_profile(tmp_path, options)
    profile = tmp_path / "paper" / "PAPER_PROFILE.json"
    first_bytes = profile.read_bytes()
    first_mtime = profile.stat().st_mtime_ns
    service.build_style_profile(tmp_path, options)

    assert profile.read_bytes() == first_bytes
    assert profile.stat().st_mtime_ns == first_mtime


def test_derived_asset_churn_does_not_invalidate_accepted_sections(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {"target_venue": "ICLR"}
    initial = service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    section = paths["sections"] / "01_introduction.tex"
    section.write_text("\\section{Introduction}\nPersisted draft.\n", encoding="utf-8")
    service.mark_stage(
        paths,
        "introduction",
        "completed",
        attempt=1,
        review={"passed": True, "issues": []},
    )
    derived_updates = {
        tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json": {
            "evidence_mode": "design_only",
            "submission_eligible": False,
            "layout_revision": "mechanism-architecture-v3",
        },
        tmp_path / "figures" / "FIGURE_MANIFEST.json": {
            "updated_at": 12345,
            "figures": [{
                "id": "method_architecture",
                "output_path": "figures/diagrams/method_architecture.png",
                "sha256": "render-only-change",
            }],
        },
        tmp_path / "paper" / "tables" / "TABLE_MANIFEST.json": {
            "tables": [{
                "id": "main_comparison",
                "output_path": "paper/tables/main_comparison.tex",
                "sha256": "derived-table-change",
            }],
        },
    }
    for path, payload in derived_updates.items():
        path.write_text(json.dumps(payload), encoding="utf-8")

    state = service.prepare(tmp_path, options)

    assert state["source_signature"] != initial["source_signature"]
    assert state["authoring_signature"] == initial["authoring_signature"]
    assert set(state["authoring_inputs"]) == set(
        PaperDraftingService.AUTHORING_SOURCE_PATHS
    )
    assert not set(state["authoring_inputs"]) & set(
        PaperDraftingService.DERIVED_SOURCE_PATHS
    )
    assert state["stages"]["introduction"]["status"] == "completed"
    assert state["stages"]["introduction"]["output_hashes"]["01_introduction.tex"]


def test_cross_section_validation_resolves_labels_from_input_tables(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    (tmp_path / "paper" / "tables" / "study_design.tex").write_text(
        "\\begin{table}\\caption{Study design}"
        "\\label{tab:study-design}\\end{table}\n",
        encoding="utf-8",
    )
    (tmp_path / "paper" / "sections" / "04_experiments.tex").write_text(
        "\\section{Experimental Setup}\n"
        "\\input{tables/study_design}\n"
        "Table~\\ref{tab:study-design} defines the comparison.\n",
        encoding="utf-8",
    )

    report = service.validate_complete_draft(tmp_path, require_main=False)

    assert not any(
        "undefined references" in issue and "tab:study-design" in issue
        for issue in report["issues"]
    )


def test_cross_section_validation_sees_tables_added_by_deterministic_assembly(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    table_dir = tmp_path / "paper" / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    (table_dir / "study_design.tex").write_text(
        "\\begin{table}\\caption{Study design}"
        "\\label{tab:study-design}\\end{table}\n",
        encoding="utf-8",
    )
    (table_dir / "TABLE_MANIFEST.json").write_text(json.dumps({
        "schema": 3, "tables": [{"id": "study_design", "label": "tab:study-design",
            "scientific_role": "study_design", "latex_path": "paper/tables/study_design.tex",
            "paper_selected": True}],
    }), encoding="utf-8")
    experiments = tmp_path / "paper" / "sections" / "04_experiments.tex"
    experiments.write_text(
        "\\section{Experimental Setup}\n"
        "Table~\\ref{tab:study-design} defines the comparison.\n",
        encoding="utf-8",
    )

    report = service.validate_complete_draft(tmp_path, require_main=False)

    assert not any(
        "undefined references" in issue and "tab:study-design" in issue
        for issue in report["issues"]
    )


def test_cross_section_validation_rejects_included_but_unreferenced_assets(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    (tmp_path / "paper" / "tables" / "method_components.tex").write_text(
        "\\begin{table}\\caption{Components}"
        "\\label{tab:method-components}\\end{table}\n",
        encoding="utf-8",
    )
    method = tmp_path / "paper" / "sections" / "03_method.tex"
    method.write_text(
        "\\section{System Design}\n"
        "\\input{tables/method_components}\n"
        "The components define the controlled comparison.\n",
        encoding="utf-8",
    )

    report = service.validate_complete_draft(tmp_path, require_main=False)

    assert any(
        "scientific assets included but never referenced in prose" in issue
        and "tab:method-components" in issue
        for issue in report["issues"]
    )

    method.write_text(
        method.read_text(encoding="utf-8")
        + "Table~\\ref{tab:method-components} summarizes the components.\n",
        encoding="utf-8",
    )
    repaired = service.validate_complete_draft(tmp_path, require_main=False)
    assert not any(
        "tab:method-components" in issue
        and "never referenced" in issue
        for issue in repaired["issues"]
    )


@pytest.mark.parametrize(
    ("mode", "expected_passed"),
    [("synthetic_preview", False), ("executed", False)],
)
def test_cross_section_reviewer_failure_blocks_every_evidence_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_passed: bool,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    contracts = json.loads(paths["contracts"].read_text(encoding="utf-8"))
    contracts["evidence"] = {"mode": mode, "submission_eligible": True}
    paths["contracts"].write_text(json.dumps(contracts), encoding="utf-8")
    paths["cross_review"].write_text(
        "## Checks Performed\nAll deterministic relationships were checked.\n\n"
        "## Final Consistency Verdict\n**FAIL.** Future external validation is absent.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        service,
        "validate_complete_draft",
        lambda _root, **_kwargs: {
            "passed": True,
            "issues": [],
            "section_reviews": {},
        },
    )

    report = service.validate_stage(tmp_path, "consistency")

    assert report["passed"] is expected_passed
    assert report["reviewer_verdict"] == "FAIL"
    assert report["reviewer_scope_advisory"] is False


@pytest.mark.asyncio
async def test_draft_invokes_one_skill_session_per_stage_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    calls: list[str] = []
    events: list[tuple[str, dict]] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        from server.agent.tools.file_tools import file_read, file_write
        calls.append(stage_id)
        paths = service.paths(tmp_path)
        for output in service.stage_outputs(paths, stage_id):
            content = "A Specific Topology-Aware Study\n" if output.name == "TITLE.txt" else f"generated {stage_id}\n"
            await file_write(str(output), content)
            assert await file_read(str(output)) == content
            if stage_id != "consistency":
                assert not output.exists(), "Unreviewed candidate must not change canonical text"
        return f"generated {stage_id}"

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
        lambda _root, **_kwargs: {"passed": True, "issues": []},
    )

    async def capture_event(event: str, payload: dict) -> None:
        events.append((event, payload))

    first = await service.draft(
        tmp_path,
        "robust representation",
        {},
        fake_invoke,
        capture_event,
    )
    assert calls == list(AUTHOR_STAGE_ORDER)
    assert "\\input{sections/01_introduction}" in (
        tmp_path / "paper" / "main.tex"
    ).read_text(encoding="utf-8")
    assert first["status"] == "completed"
    assert events[-2][0] == "paper_stage_started"
    assert events[-2][1]["stage_id"] == "assembly"
    assert events[-2][1]["stage_total"] == len(PAPER_STAGE_ORDER)
    assert events[-1][0] == "paper_stage_reviewed"
    assert events[-1][1]["passed"] is True

    calls.clear()
    events.clear()
    second = await service.draft(
        tmp_path,
        "robust representation",
        {},
        fake_invoke,
        capture_event,
    )
    assert calls == []
    assert second["main_sha256"] == first["main_sha256"]
    assert [payload["stage_id"] for event, payload in events if event == "paper_stage_reused"] == list(AUTHOR_STAGE_ORDER)


def test_non_empirical_section_rejects_claimed_superiority(tmp_path: Path) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "05_results.tex"
    section.write_text(
        "\\section{Results}\n"
        "Our model outperforms every baseline. "
        + "planned protocol ablation robustness failure uncertainty " * 90
        + "\\cite{ref1}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "results")

    assert review["passed"] is False
    assert any("superiority" in issue for issue in review["issues"])
    assert any("must not be titled Results" in issue for issue in review["issues"])


@pytest.mark.parametrize(
    "mechanism_analysis",
    [
        "Matched ablations isolate the proposed mechanism.",
        "Component removals isolate the proposed mechanism.",
        "The registered variants remove the auxiliary objective.",
        "A leave-one-component-out analysis isolates the proposed mechanism.",
        "The proposed method is compared with matched controls.",
        "The w/o objective variant is evaluated under the same budget.",
    ],
)
def test_algorithm_results_accept_common_mechanism_isolation_wording(
    tmp_path: Path,
    mechanism_analysis: str,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "05_results.tex"
    section.write_text(
        "\\section{Planned Evaluation Protocol}\n"
        "\\paragraph{Primary analysis.}\n"
        f"The planned protocol uses the following comparison: {mechanism_analysis} "
        "All estimates remain pending until the registered runs finish. "
        "\\paragraph{Robustness analysis.}\n"
        "Stress tests and failure analysis cover held-out shifts. "
        + "The registered comparison remains planned and reports uncertainty. " * 95
        + "\\cite{ref1,ref2}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "results")

    assert (
        "results/planned analyses omit the domain's primary control or "
        "sensitivity analysis"
    ) not in review["issues"]


def test_algorithm_results_do_not_treat_bare_component_mention_as_ablation(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "05_results.tex"
    section.write_text(
        "\\section{Planned Evaluation Protocol}\n"
        "The planned model contains several components. "
        "Stress tests and failure analysis cover held-out shifts. "
        + "The registered comparison remains planned and reports uncertainty. " * 95
        + "\\cite{ref1,ref2}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "results")

    assert (
        "results/planned analyses omit the domain's primary control or "
        "sensitivity analysis"
    ) in review["issues"]


def test_non_empirical_section_allows_rejected_state_of_the_art_claim(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "01_introduction.tex"
    section.write_text(
        "\\section{Introduction}\n"
        "However, the unresolved deployment gap remains. "
        "We propose a falsifiable protocol rather than a universal "
        "state-of-the-art claim. "
        "\\begin{enumerate}\\item Test layout stress. "
        "\\item Test calibration.\\end{enumerate}\n\n"
        + "The study separates mechanism evidence from benchmark rank. " * 90
        + "\\cite{ref1}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "introduction")

    assert not any("superiority" in issue for issue in review["issues"])


def test_introduction_accepts_we_address_as_an_approach_preview(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "01_introduction.tex"
    section.write_text(
        "\\section{Introduction}\n"
        "However, the unresolved transfer gap remains. "
        "We address this question with a controlled source-mixture benchmark "
        "that fixes the encoder and varies only the sampling policy. "
        "The study makes two falsifiable contributions. First, the policy claim "
        "fails if neither registered endpoint improves. Second, the mechanism "
        "claim fails if direct diagnostics disagree with the external-source effect. "
        + "The scope is bounded by the declared sources and matched budget. " * 90
        + "\\cite{ref1,ref2,ref3,ref4,ref5,ref6,ref7}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "introduction")

    assert "introduction does not preview the approach" not in review["issues"]


def test_discussion_accepts_plural_alternatives_and_negative_outcomes(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "06_discussion.tex"
    section.write_text(
        "\\section{Discussion}\n"
        "Several alternative explanations remain, including capacity, split "
        "leakage, and unequal tuning budgets. "
        + "Matched controls separate mechanism effects from these explanations. " * 45
        + "\\cite{ref1}.\n\n"
        "Negative outcomes are informative: if the proposed mechanism matches "
        "the strongest baseline, the mechanism claim must be narrowed. "
        + "The interpretation remains bounded by the declared population and stress regime. " * 45
        + "\\cite{ref2}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "discussion")

    assert review["passed"] is True, review


def test_discussion_accepts_negative_evidence_and_absent_reversals(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "06_discussion.tex"
    section.write_text(
        "\\section{Discussion}\n"
        "Several alternative explanations remain, including model diversity, "
        "stress strength, and statistical power. "
        + "Matched controls constrain these explanations within the declared scope. " * 45
        + "\\cite{ref1}.\n\n"
        "The absence of a qualifying reversal is informative negative evidence, "
        "but it is not a universal robustness guarantee. "
        + "This interpretation remains bounded by the registered model suite and endpoints. " * 45
        + "\\cite{ref2}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "discussion")

    assert review["passed"] is True, review


def test_limitations_accepts_plural_validity_threats_and_mitigation(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    section = tmp_path / "paper" / "sections" / "07_limitations.tex"
    section.write_text(
        "\\section{Limitations}\n"
        "Shared representations and finite model diversity are concrete "
        "construct-validity threats within the registered benchmark. "
        + "These boundary conditions restrict external generalization. " * 14
        + "\\cite{ref1}.\n\n"
        "We mitigate internal threats with matched controls and leakage-safe "
        "splits; future validation requires independent workloads and devices. "
        + "The mitigation remains bounded by the declared evidence. " * 14
        + "\\cite{ref2}.\n",
        encoding="utf-8",
    )

    review = service.validate_stage(tmp_path, "limitations")

    assert review["passed"] is True, review
