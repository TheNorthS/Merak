from __future__ import annotations
from server.services.paper_candidate_io import candidate_path

from server.tests._staged_paper_drafting_support import (
    AUTHOR_STAGE_ORDER as AUTHOR_STAGE_ORDER,
    PaperDraftingError as PaperDraftingError,
    PaperDraftingService as PaperDraftingService,
    Path as Path,
    SECTION_CONTRACT_SCHEMA_VERSION as SECTION_CONTRACT_SCHEMA_VERSION,
    json as json,
    pytest as pytest,
    seed_project as seed_project,
)


def test_literature_bibliography_refresh_preserves_sections_and_reopens_consistency(
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
    introduction = paths["sections"] / "01_introduction.tex"
    introduction.write_text(
        "\\section{Introduction}\nA stable accepted section.\n",
        encoding="utf-8",
    )
    service.mark_stage(
        paths,
        "introduction",
        "completed",
        attempt=1,
        review={"passed": True, "issues": []},
    )
    paths["cross_review"].write_text(
        "## Final Consistency Verdict\nPASS\n",
        encoding="utf-8",
    )
    service.mark_stage(
        paths,
        "consistency",
        "completed",
        attempt=3,
        review={"passed": True, "issues": []},
    )
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state["stages"]["assembly"] = {
        "status": "completed",
        "attempts": 1,
        "review_passed": True,
    }
    paths["state"].write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    references = tmp_path / "literature" / "references.bib"
    references.write_text(
        references.read_text(encoding="utf-8")
        + "\n@article{newref, title={New verified evidence}, "
        "author={New Author}, year={2026}, url={https://example.org/new}}\n",
        encoding="utf-8",
    )

    refreshed = service.prepare(tmp_path, options)

    assert refreshed["stages"]["introduction"]["status"] == "completed"
    assert refreshed["stages"]["introduction"]["attempts"] == 1
    assert refreshed["stages"]["consistency"]["status"] == "pending"
    assert refreshed["stages"]["consistency"]["attempts"] == 0
    assert refreshed["stages"]["assembly"]["status"] == "pending"
    assert refreshed["stages"]["assembly"]["attempts"] == 0
    prompt = service.build_stage_prompt(tmp_path, "consistency", options)
    assert "at least 30\ndistinct verified keys" in prompt
    assert "do not create citation dumps" in prompt


@pytest.mark.asyncio
async def test_targeted_revision_does_not_reuse_locally_valid_stale_stage(
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
                    "A Targeted Revision Study\n",
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

    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "targeted repair completed"

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

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        revision_issues=[
            "paper/sections/05_results.tex:2: Undefined control sequence."
        ],
    )

    assert result["status"] == "completed"
    assert calls == ["results", "consistency"]


@pytest.mark.asyncio
async def test_validator_upgrade_cannot_bypass_exhausted_real_scientific_feedback(
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
            output.write_text(
                "A Validator Upgrade Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
                encoding="utf-8",
            )
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=1,
            review={"passed": True, "issues": []},
        )

    stale_issue = (
        "synthetic results preview lacks analytical prose about "
        "component-ablation interpretation"
    )
    revision_issues = [
        "Target artifact: paper/sections/05_results.tex",
        stale_issue,
    ]
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state["stages"]["results"].update({
        "status": "revision_required",
        "review_passed": False,
        "review_issues": [stale_issue],
        "contract_version": SECTION_CONTRACT_SCHEMA_VERSION - 1,
        "directed_issue_signature": service.directed_issue_signature(
            revision_issues
        ),
        "directed_attempts": service.DIRECTED_REPAIR_ATTEMPTS,
    })
    paths["state"].write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "targeted repair completed"

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

    with pytest.raises(PaperDraftingError, match="component-ablation interpretation"):
        await service.draft(
            tmp_path, "robust representation", {"max_revision_rounds": 3}, fake_invoke,
            revision_issues=revision_issues,
        )
    assert calls == []
    final_state = json.loads(paths["state"].read_text(encoding="utf-8"))
    assert final_state["stages"]["results"]["status"] != "completed"
    assert not final_state["stages"]["results"]["review_passed"]


@pytest.mark.asyncio
async def test_global_method_finding_reopens_an_already_accepted_method(
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
            output.write_text(
                "A Global Finding Repair Study\n"
                if output.name == "TITLE.txt"
                else f"accepted {stage_id}\n",
                encoding="utf-8",
            )
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
        for output in service.stage_outputs(paths, stage_id):
            candidate_path(output, writing=True).write_text(
                candidate_path(output).read_text(encoding="utf-8") + "repaired globally\n",
                encoding="utf-8",
            )
        return "targeted global repair completed"

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {
            "passed": True, "issues": [], "stage_id": stage_id,
        },
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
        revision_issues=[
            "Method: method does not cover required mechanism: "
            "acquisition-invariant representation"
        ],
    )

    assert result["status"] == "completed"
    assert calls == ["method", "consistency"]


@pytest.mark.asyncio
async def test_targeted_revision_preserves_unchanged_downstream_sections(
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
            output.write_text(
                "A Scoped Repair Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
                encoding="utf-8",
            )
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
        if stage_id == "results":
            candidate_path(paths["sections"] / "05_results.tex", writing=True).write_text(
                "repaired results\n",
                encoding="utf-8",
            )
        return "targeted repair completed"

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

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        revision_issues=[
            "paper/sections/05_results.tex: replace an unsupported statement."
        ],
    )

    assert result["status"] == "completed"
    assert calls == ["results", "consistency"]


@pytest.mark.asyncio
async def test_targeted_introduction_repair_rewrites_section_and_assembles_main(
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
            output.write_text(
                "A Falsifiable Introduction Repair Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
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
        "\\section{Introduction}\n"
        "One broad contribution without a rejection condition.\n",
        encoding="utf-8",
    )
    if paths["main"].is_file():
        paths["main"].unlink()
    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        if stage_id == "introduction":
            candidate_path(introduction, writing=True).write_text(
                "\\section{Introduction}\n"
                "We state two falsifiable contributions with explicit rejection "
                "conditions and bounded evidence.\n",
                encoding="utf-8",
            )
        return "targeted repair completed"

    def validate_stage(_root: Path, stage_id: str) -> dict:
        passed = (
            "two falsifiable contributions" in candidate_path(introduction).read_text(
                encoding="utf-8"
            )
            if stage_id == "introduction"
            else True
        )
        return {
            "passed": passed,
            "issues": (
                []
                if passed
                else [
                    "introduction lacks two or more falsifiable contributions"
                ]
            ),
            "stage_id": stage_id,
        }

    monkeypatch.setattr(service, "validate_stage", validate_stage)
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
            "Target artifact: paper/sections/01_introduction.tex",
            "introduction lacks two or more falsifiable contributions",
        ],
    )

    assert result["status"] == "completed"
    assert calls == ["introduction", "consistency"]
    assert "two falsifiable contributions" in introduction.read_text(
        encoding="utf-8"
    )
    assert paths["main"].is_file()
    assert "01_introduction" in paths["main"].read_text(encoding="utf-8")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    assert state["stages"]["introduction"]["status"] == "completed"
    assert state["stages"]["assembly"]["status"] == "completed"


@pytest.mark.asyncio
async def test_one_revision_transaction_repairs_multiple_named_sections(
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
            output.write_text(
                "A Multi-target Repair Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
                encoding="utf-8",
            )
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
        return "directed repair completed"

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

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        revision_issues=[
            "Target artifact: paper/sections/03_method.tex",
            "Target artifact: paper/sections/05_results.tex",
            "Align the method and result interpretation with the evidence.",
        ],
    )

    assert result["status"] == "completed"
    assert calls == ["method", "results", "consistency"]


@pytest.mark.asyncio
async def test_stale_local_section_status_is_revalidated_without_model_call(
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
            output.write_text(
                "A Revalidated Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
                encoding="utf-8",
            )
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
        return "unexpected model call"

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

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        revision_issues=[
            "Staged manuscript did not satisfy the quality contract: "
            "staged-paper: Method: Method has not passed its local section contract."
        ],
    )

    assert result["status"] == "completed"
    assert "method" not in calls


@pytest.mark.asyncio
async def test_new_directed_issue_gets_one_attempt_after_historical_budget_exhausted(
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
            output.write_text(
                "A Directed Repair Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
                encoding="utf-8",
            )
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=3 if stage_id == "experiments" else 1,
            review={"passed": True, "issues": []},
        )

    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "directed repair completed"

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

    result = await service.draft(
        tmp_path,
        "robust representation",
        {"max_revision_rounds": 3},
        fake_invoke,
        revision_issues=[
            "experiments: section unfocused (1670; preferred maximum 1150)"
        ],
    )

    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    experiments = state["stages"]["experiments"]
    assert result["status"] == "completed"
    assert calls == ["experiments", "consistency"]
    assert experiments["attempts"] == 4
    assert experiments["directed_attempts"] == 1
    assert experiments["directed_issue_signature"]
    assert state["stages"]["consistency"]["status"] == "completed"
    assert state["stages"]["assembly"]["status"] == "completed"


@pytest.mark.asyncio
async def test_same_directed_issue_does_not_reset_budget_when_counters_change(
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
            output.write_text(
                "A Bounded Directed Repair Study\n"
                if output.name == "TITLE.txt"
                else f"persisted {stage_id}\n",
                encoding="utf-8",
            )
        service.mark_stage(
            paths,
            stage_id,
            "completed",
            attempt=3 if stage_id == "experiments" else 1,
            review={"passed": True, "issues": []},
        )

    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        return "still too long"

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {
            "passed": stage_id != "experiments",
            "issues": ["experiments section remains unfocused"],
            "stage_id": stage_id,
        },
    )

    with pytest.raises(PaperDraftingError):
        await service.draft(
            tmp_path,
            "robust representation",
            {"max_revision_rounds": 3},
            fake_invoke,
            revision_issues=[
                "experiments: section unfocused (1670; preferred maximum 1150)"
            ],
        )

    with pytest.raises(PaperDraftingError):
        await service.draft(
            tmp_path,
            "robust representation",
            {"max_revision_rounds": 3},
            fake_invoke,
            revision_issues=[
                "experiments: section unfocused (1600; preferred maximum 1150)"
            ],
        )

    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    assert calls == ["experiments"]
    assert state["stages"]["experiments"]["directed_attempts"] == 1


@pytest.mark.asyncio
async def test_same_directed_issue_can_repair_a_changed_artifact_state(
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
            output.write_text("Accepted fixture content\n", encoding="utf-8")
        service.mark_stage(paths, stage_id, "completed", attempt=1, review={"passed": True, "issues": []})
    target = paths["sections"] / "04_experiments.tex"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("first artifact state\n", encoding="utf-8")
    calls: list[str] = []

    async def fake_invoke(stage_id: str, _prompt: str, _contract: str) -> str:
        calls.append(stage_id)
        candidate_path(target, writing=True).write_text(
            f"changed artifact state {len(calls)}\n",
            encoding="utf-8",
        )
        return "changed but still requires review"

    monkeypatch.setattr(
        service,
        "validate_stage",
        lambda _root, stage_id: {
            "passed": stage_id != "experiments",
            "issues": ["experiments section remains unfocused"],
        },
    )

    issues = ["experiments: section remains unfocused"]
    with pytest.raises(PaperDraftingError):
        await service.draft(
            tmp_path,
            "robust representation",
            {"max_revision_rounds": 3},
            fake_invoke,
            revision_issues=issues,
        )
    assert target.read_text(encoding="utf-8") == "first artifact state\n"
    target.write_text("User supplied a new canonical artifact state\n", encoding="utf-8")
    with pytest.raises(PaperDraftingError):
        await service.draft(
            tmp_path,
            "robust representation",
            {"max_revision_rounds": 3},
            fake_invoke,
            revision_issues=issues,
        )

    assert [stage_id for stage_id in calls if stage_id == "experiments"] == [
        "experiments",
        "experiments",
    ]


def test_scientific_freeze_changes_once_per_upstream_transaction(
    tmp_path: Path,
) -> None:
    seed_project(tmp_path)
    service = PaperDraftingService()
    options = {
        "target_venue": "ICLR",
        "run_experiment": False,
        "non_experiment_evidence_mode": "design_only",
    }

    first_state = service.prepare(tmp_path, options)
    paths = service.paths(tmp_path)
    first_freeze = json.loads(paths["freeze"].read_text(encoding="utf-8"))
    first_bytes = paths["freeze"].read_bytes()

    repeated_state = service.prepare(tmp_path, options)
    repeated_freeze = json.loads(paths["freeze"].read_text(encoding="utf-8"))

    assert first_freeze["generation"] == 1
    assert first_freeze["freeze_id"] == repeated_freeze["freeze_id"]
    assert paths["freeze"].read_bytes() == first_bytes
    assert first_state["scientific_freeze_id"] == first_freeze["freeze_id"]
    assert repeated_state["scientific_freeze_id"] == first_freeze["freeze_id"]
    assert service.validate_scientific_freeze(tmp_path, options)["passed"] is True

    narrative = tmp_path / "NARRATIVE_REPORT.md"
    narrative.write_text(
        narrative.read_text(encoding="utf-8") + "\nA bounded upstream revision.\n",
        encoding="utf-8",
    )
    stale = service.validate_scientific_freeze(tmp_path, options)
    assert stale["passed"] is False
    assert "NARRATIVE_REPORT.md" in stale["changed_inputs"]

    refreshed_state = service.prepare(tmp_path, options)
    refreshed = json.loads(paths["freeze"].read_text(encoding="utf-8"))

    assert refreshed["generation"] == 2
    assert refreshed["freeze_id"] != first_freeze["freeze_id"]
    assert refreshed["previous_freeze_id"] == first_freeze["freeze_id"]
    assert refreshed_state["scientific_freeze_id"] == refreshed["freeze_id"]
    assert refreshed["changed_inputs"] == ["NARRATIVE_REPORT.md"]
    assert service.validate_scientific_freeze(tmp_path, options)["passed"] is True
