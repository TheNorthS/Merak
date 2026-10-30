from __future__ import annotations

from server.tests._staged_paper_drafting_support import (
    ASSEMBLY_CONTRACT_VERSION as ASSEMBLY_CONTRACT_VERSION,
    AUTHOR_STAGE_ORDER as AUTHOR_STAGE_ORDER,
    CONSISTENCY_CONTRACT_VERSION as CONSISTENCY_CONTRACT_VERSION,
    PaperDraftingService as PaperDraftingService,
    Path as Path,
    SECTION_CONTRACT_SCHEMA_VERSION as SECTION_CONTRACT_SCHEMA_VERSION,
    SECTION_SPECS as SECTION_SPECS,
    SIMULATION_END_DISCLOSURE as SIMULATION_END_DISCLOSURE,
    SIMULATION_END_DISCLOSURE_TITLE as SIMULATION_END_DISCLOSURE_TITLE,
    _complete_synthetic_results_section as _complete_synthetic_results_section,
    hashlib as hashlib,
    json as json,
    paper_artifact_builder as paper_artifact_builder,
    pytest as pytest,
    seed_project as seed_project,
    stable_source_hash as stable_source_hash,
)


def test_table_layout_repair_manifest_renderer_churn_does_not_invalidate_freeze(
    tmp_path: Path,
) -> None:
    """A bounded table edit may refresh renderer hashes, but not science."""
    seed_project(tmp_path)
    table_dir = tmp_path / "paper" / "tables"
    data_path = table_dir / "results.csv"
    latex_path = table_dir / "results.tex"
    data_path.write_text("method,score\nfull,0.70\n", encoding="utf-8")
    latex_path.write_text(
        "\\begin{table}\\caption{Results.}\\label{tab:results}"
        "\\begin{tabular}{lc}full & 0.70\\\\end{tabular}\\end{table}\n",
        encoding="utf-8",
    )
    manifest_path = table_dir / "TABLE_MANIFEST.json"
    manifest = {
        "schema": 3,
        "updated_at": 1.0,
        "tables": [{
            "id": "results",
            "scientific_role": "result",
            "label": "tab:results",
            "caption": "Results.",
            "latex_path": "paper/tables/results.tex",
            "data_path": "paper/tables/results.csv",
            "provenance_kind": "registered_benchmark",
            "latex_sha256": hashlib.sha256(latex_path.read_bytes()).hexdigest(),
            "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        }],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }
    service.prepare(tmp_path, options)

    # Table-only layout repair: LaTeX bytes and renderer metadata change,
    # while registered data and scientific fields remain identical.
    latex_path.write_text(
        "\\begin{table}\\small\\caption{Results.}\\label{tab:results}"
        "\\begin{tabular}{@{}lc@{}}full & 0.70\\\\end{tabular}\\end{table}\n",
        encoding="utf-8",
    )
    manifest["updated_at"] = 2.0
    manifest["tables"][0]["latex_sha256"] = hashlib.sha256(
        latex_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    freeze_after_table = service.validate_scientific_freeze(tmp_path, options)
    assert freeze_after_table["passed"] is True, freeze_after_table
    gate_after_table = service.gate_report(tmp_path, options)
    assert not any(
        "scientific inputs changed after paper freeze" in issue
        for issue in gate_after_table["issues"]
    ), gate_after_table

    # Scientific table metadata is not renderer churn: changing the caption
    # must remain visible to the freeze contract.
    manifest["tables"][0]["caption"] = "Changed scientific caption."
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    freeze_after_semantic_table_change = service.validate_scientific_freeze(
        tmp_path, options
    )
    assert freeze_after_semantic_table_change["passed"] is False
    assert "paper/tables/TABLE_MANIFEST.json" in (
        freeze_after_semantic_table_change["changed_inputs"]
    )

    # Restore the table's scientific metadata before checking an independent
    # upstream analysis drift.
    manifest["tables"][0]["caption"] = "Results."
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # An actual upstream scientific artifact change must remain a freeze error.
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.write_text(
        analysis.read_text(encoding="utf-8")
        + "Changed benchmark interpretation.\n",
        encoding="utf-8",
    )
    freeze_after_upstream = service.validate_scientific_freeze(tmp_path, options)
    assert freeze_after_upstream["passed"] is False
    assert "experiments/results/analysis.md" in freeze_after_upstream["changed_inputs"]
    gate_after_upstream = service.gate_report(tmp_path, options)
    assert any(
        "scientific inputs changed after paper freeze" in issue
        and "experiments/results/analysis.md" in issue
        for issue in gate_after_upstream["issues"]
    ), gate_after_upstream


def test_layout_rebind_updates_stale_latex_hash_without_blessing_semantic_edit(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    _upgrade_table_producer_fixture(tmp_path)
    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }
    service.prepare(tmp_path, options)
    paper_artifact_builder.prepare(tmp_path, "layout rebind")
    manifest_path = tmp_path / "paper" / "tables" / "TABLE_MANIFEST.json"
    before_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table_path = tmp_path / "paper" / "tables" / "study_design.tex"
    original = table_path.read_text(encoding="utf-8")
    table_path.write_text(
        original.replace("\\small\n", "\\small\n\\setlength{\\tabcolsep}{4pt}\n"),
        encoding="utf-8",
    )

    rebound = service.rebind_layout_only_derived_inputs(
        tmp_path,
        options,
        before_manifest=before_manifest,
        target_files=["paper/tables/study_design.tex"],
    )
    assert rebound["passed"] is True, rebound
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in updated_manifest["tables"] if item["id"] == "study_design")
    assert entry["latex_sha256"] == hashlib.sha256(table_path.read_bytes()).hexdigest()
    assert service.validate_scientific_freeze(tmp_path, options)["passed"] is True

    before_semantic_edit = json.loads(manifest_path.read_text(encoding="utf-8"))
    before_semantic_edit["tables"][0]["caption"] = "Changed scientific meaning."
    manifest_path.write_text(
        json.dumps(before_semantic_edit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rejected = service.rebind_layout_only_derived_inputs(
        tmp_path,
        options,
        before_manifest=updated_manifest,
        target_files=["paper/tables/study_design.tex"],
    )
    assert rejected["passed"] is False
    assert any("scientific manifest fields" in item for item in rejected["issues"])






def _upgrade_table_producer_fixture(tmp_path: Path) -> None:
    """Author current public fields; these fixtures test layout, not schema fallback."""
    selected_path = tmp_path / "ideas" / "SELECTED_IDEA.json"
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    for mechanism in selected["mechanisms"]:
        mechanism.update({
            "publication_name": "Predictive encoder",
            "publication_description": "Encodes the observed signal for task prediction.",
            "publication_evaluation": "Compare held-out prediction under matched controls.",
        })
    selected_path.write_text(json.dumps(selected), encoding="utf-8")
    run_spec_path = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
    run_spec.update({"datasets": ["Declared cohort"], "tasks": ["Prediction task"]})
    run_spec_path.write_text(json.dumps(run_spec), encoding="utf-8")
    (tmp_path / "paper/tables/TABLE_MANIFEST.json").write_text(
        json.dumps({"schema": 3, "tables": []}), encoding="utf-8",
    )


def test_builder_preserves_reviewed_table_layout_when_rows_remain_bound(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    _upgrade_table_producer_fixture(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {"target_venue": "ICLR"})
    paper_artifact_builder.prepare(tmp_path, "layout preservation")
    table_path = tmp_path / "paper" / "tables" / "study_design.tex"
    original = table_path.read_text(encoding="utf-8")
    marker = "\\setlength{\\tabcolsep}{3pt}"
    table_path.write_text(
        original.replace("\\small\n", "\\small\n" + marker + "\n"),
        encoding="utf-8",
    )
    paper_artifact_builder.prepare(tmp_path, "layout preservation")
    assert marker in table_path.read_text(encoding="utf-8")


def test_refresh_deterministic_assembly_keeps_synthetic_preview_compilable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_project(tmp_path)
    (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "target_venue": "ICLR",
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    })
    paths = service.paths(tmp_path)
    for stage_id in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.name == "TITLE.txt":
                output.write_text(
                    "A Complete Benchmark Study\n",
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

    monkeypatch.setattr(
        service,
        "validate_complete_draft",
        lambda _root, **_kwargs: {"passed": True, "issues": []},
    )

    refreshed = service.refresh_deterministic_assembly(tmp_path)
    main = paths["main"].read_text(encoding="utf-8")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))

    assert refreshed["passed"] is True
    assert "SYNTHETIC PREVIEW -- NOT FOR SUBMISSION" not in main
    assert "draftwatermark" not in main
    assert "SetWatermark" not in main
    assert rf"\section*{{{SIMULATION_END_DISCLOSURE_TITLE}}}" in main
    assert main.count(SIMULATION_END_DISCLOSURE) == 1
    assert main.index(SIMULATION_END_DISCLOSURE) > main.index(
        r"\input{sections/08_conclusion}"
    )
    assert main.index(SIMULATION_END_DISCLOSURE) < main.index(
        r"\bibliography{references}"
    )
    assert state["main_sha256"] == refreshed["main_sha256"]


def test_synthetic_prompts_reserve_disclosure_for_deterministic_end_matter(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    service = PaperDraftingService()
    service.prepare(tmp_path, {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    })

    contracts = json.loads(
        (tmp_path / "paper" / "SECTION_CONTRACTS.json").read_text(
            encoding="utf-8"
        )
    )
    introduction_contract = next(
        item for item in contracts["sections"]
        if item["id"] == "introduction"
    )
    consistency_prompt = service.build_stage_prompt(
        tmp_path, "consistency", {}
    )
    introduction_prompt = service.build_stage_prompt(
        tmp_path, "introduction", {}
    )

    assert "evidence-bounded scope" in introduction_contract["required_moves"]
    assert "evidence-calibrated preview" not in json.dumps(contracts)
    assert SIMULATION_END_DISCLOSURE not in consistency_prompt
    assert SIMULATION_END_DISCLOSURE not in introduction_prompt
    assert "after the\nConclusion and before the bibliography" in consistency_prompt
    assert "complete simulation-study manuscript" not in introduction_prompt


def test_local_review_rejects_rendered_mode_framing_but_not_internal_paths(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    introduction = tmp_path / "paper" / "sections" / "01_introduction.tex"
    introduction.write_text(
        "\\section{Introduction}\n"
        + (
            "This evidence-calibrated preview states a bounded contribution "
            "with an explicit rejection condition and scientific rationale. "
        ) * 80,
        encoding="utf-8",
    )
    intro_review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "introduction"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )

    assert any(
        "framing outside the assembly-managed end disclosure" in issue
        for issue in intro_review["issues"]
    )
    (tmp_path / "paper" / "sections" / "05_results.tex").write_text(
        _complete_synthetic_results_section(), encoding="utf-8"
    )
    results_review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "results"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )
    assert not any(
        "framing outside the assembly-managed end disclosure" in issue
        for issue in results_review["issues"]
    )


def test_experimental_setup_allows_simulation_provenance_without_repeated_status_framing(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    experiments = tmp_path / "paper" / "sections" / "04_experiments.tex"
    experiments.write_text(
        "\\section{Experimental Setup}\n"
        "The benchmark provenance is \\texttt{merak-structural-simulation-v1} "
        "run with fixed seed 1729.\n"
        + (
            "Subjects form disjoint held-out splits with matched baselines, "
            "optimizer epochs, compute runtime, endpoints, F1 loss, confidence "
            "interval uncertainty, validation, and independent analysis units. "
        ) * 80
        + "Figure~\\ref{fig:evaluation-design} defines the comparison.\n",
        encoding="utf-8",
    )

    review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "experiments"),
        {"mode": "synthetic_preview", "submission_eligible": False},
        [],
    )

    assert not any(
        "framing outside the assembly-managed end disclosure" in issue
        for issue in review["issues"]
    )


def test_experimental_setup_recognizes_data_partitions_and_analysis_units(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    experiments = tmp_path / "paper" / "sections" / "04_experiments.tex"
    experiments.write_text(
        "\\section{Experimental Setup}\n"
        + (
            "Frozen data partitions define independent analysis units and "
            "held-out comparisons. Matched baselines share the workload, "
            "hardware, software, warm-up, and repetition contract. Accuracy, "
            "latency, throughput, memory, confidence intervals, statistical "
            "validation, and sensitivity analyses define the endpoints. "
        ) * 40
        + "Figure~\\ref{fig:evaluation-design} defines the comparison.\n",
        encoding="utf-8",
    )

    review = service.section_review(
        tmp_path,
        next(item for item in SECTION_SPECS if item.id == "experiments"),
        {"mode": "synthetic_preview", "submission_eligible": True},
        [],
    )

    assert "experimental setup omits data or analysis units" not in review["issues"]
    assert "experimental setup omits baselines" not in review["issues"]


def test_failed_consistency_rebinds_valid_edited_method_identity(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    method = paths["sections"] / "03_method.tex"
    experiments = paths["sections"] / "04_experiments.tex"
    abstract = paths["sections"] / "00_abstract.tex"
    method.write_text("\\section{Method}\nOriginal method.\n", encoding="utf-8")
    experiments.write_text(
        "\\section{Experimental Setup}\nOriginal setup.\n",
        encoding="utf-8",
    )
    paths["title"].write_text("A Specific Scientific Study\n", encoding="utf-8")
    abstract.write_text("Original abstract.\n", encoding="utf-8")
    for stage_id in ("method", "experiments", "front_matter"):
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )

    method.write_text("\\section{Method}\nRepaired method.\n", encoding="utf-8")
    experiments.write_text(
        "\\section{Experimental Setup}\nParaphrased provenance.\n",
        encoding="utf-8",
    )
    service.record_review(
        paths,
        "consistency",
        {
            "passed": False,
            "issues": ["canonical provenance sentence is missing"],
            "section_reviews": {
                "method": {"passed": True, "issues": []},
                "experiments": {
                    "passed": False,
                    "issues": ["canonical provenance sentence is missing"],
                },
            },
            "front_matter": {"passed": True, "issues": []},
        },
        1,
    )
    state = service.mark_stage(
        paths,
        "consistency",
        "revision_required",
        attempt=1,
        review={
            "passed": False,
            "issues": ["canonical provenance sentence is missing"],
            "section_reviews": {
                "method": {"passed": True, "issues": []},
                "experiments": {
                    "passed": False,
                    "issues": ["canonical provenance sentence is missing"],
                },
            },
            "front_matter": {"passed": True, "issues": []},
        },
    )

    assert service.stage_is_current(paths, state, "method") is True
    assert state["stages"]["method"]["review_passed"] is True
    assert state["stages"]["experiments"]["status"] == "revision_required"
    assert state["stages"]["experiments"]["review_issues"] == [
        "canonical provenance sentence is missing"
    ]
    reviews = json.loads(paths["reviews"].read_text(encoding="utf-8"))
    assert reviews["sections"]["method"]["passed"] is True


def test_contract_upgrade_forces_old_stages_through_revalidation(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {"target_venue": "ICLR"}
    service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    method = paths["sections"] / "03_method.tex"
    method.write_text("\\section{Method}\nPersisted method.\n", encoding="utf-8")
    service.mark_stage(
        paths,
        "method",
        "completed",
        attempt=2,
        review={"passed": True, "issues": []},
    )
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state["stages"]["method"]["contract_version"] = (
        SECTION_CONTRACT_SCHEMA_VERSION - 1
    )
    state["stages"]["consistency"].update({
        "status": "completed",
        "attempts": 3,
        "review_passed": True,
        "contract_version": CONSISTENCY_CONTRACT_VERSION - 1,
    })
    state["stages"]["assembly"].update({
        "status": "completed",
        "attempts": 1,
        "review_passed": True,
        "contract_version": ASSEMBLY_CONTRACT_VERSION - 1,
    })
    paths["state"].write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    refreshed = service.prepare(tmp_path, options)

    assert refreshed["stages"]["method"]["status"] == "pending"
    assert refreshed["stages"]["method"]["attempts"] == 2
    assert refreshed["stages"]["consistency"]["status"] == "pending"
    assert refreshed["stages"]["consistency"]["attempts"] == 0
    assert refreshed["stages"]["assembly"]["status"] == "pending"
    assert refreshed["stages"]["assembly"]["attempts"] == 0


def test_literature_survey_refresh_reopens_claim_positioning_sections(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    }
    (tmp_path / "figures" / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({
            "evidence_mode": "synthetic_preview",
            "submission_eligible": False,
        }),
        encoding="utf-8",
    )
    service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    for stage_id in (
        "blueprint", "introduction", "related_work", "method", "discussion",
        "consistency",
    ):
        for output in service.stage_outputs(paths, stage_id):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"accepted {stage_id}\n", encoding="utf-8")
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )
    survey = tmp_path / "literature" / "survey.md"
    survey.write_text(
        survey.read_text(encoding="utf-8")
        + "\nNew verified nearest-neighbor evidence.\n",
        encoding="utf-8",
    )

    refreshed = service.prepare(tmp_path, options)

    for stage_id in (
        "blueprint", "introduction", "related_work", "discussion", "consistency",
    ):
        assert refreshed["stages"][stage_id]["status"] == "pending"
        assert refreshed["stages"][stage_id]["attempts"] == 0
    assert refreshed["stages"]["method"]["status"] == "completed"
