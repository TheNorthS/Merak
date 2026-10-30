from __future__ import annotations

from server.tests._workflow_revision_loop_support import (
    Path as Path,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _accepted as _accepted,
    _rejected as _rejected,
    _start_run_state as _start_run_state,
    asyncio as asyncio,
    json as json,
    pytest as pytest,
    time as time,
)


@pytest.mark.asyncio
async def test_cancellation_exits_revision_loop_without_scientific_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery", started_at=time.time())
    run = WorkflowRun(id="revision-cancel", project_path=str(tmp_path), nodes=[node], status="running")
    state = _start_run_state(tmp_path, run.id, [node])

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def cancel_during_revision(**_kwargs) -> str:
        run.status = "cancelled"
        return "cancelled"

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: _rejected())
    monkeypatch.setattr(engine, "_revise_node_from_gate", cancel_during_revision)
    monkeypatch.setattr(engine, "_emit", noop)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=2,
    )

    assert gate["cancelled"] is True
    assert state.load()["phases"][node.id]["status"] != "failed"


@pytest.mark.asyncio
async def test_explicit_feedback_authorizes_one_guided_round_after_hard_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery", started_at=time.time())
    run = WorkflowRun(
        id="revision-guided",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        checkpoint_feedback="Keep the selected mechanism and fix the missing falsification test.",
        checkpoint_node_id="idea",
    )
    state = _start_run_state(tmp_path, run.id, [node])
    state.record_revision_gate(
        node.id,
        round_number=1,
        cycle=1,
        gate=WorkflowEngine._gate_revision_diagnostics(_rejected("missing falsification")),
    )
    state.set_revision_waiting(
        node.id,
        round_number=1,
        cycle=1,
        gate=WorkflowEngine._gate_revision_diagnostics(_rejected("missing falsification")),
    )
    gates = iter([_rejected("missing falsification"), _accepted()])
    feedback_seen: list[str] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        feedback_seen.append(kwargs["user_feedback"])
        return "guided revision"

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: next(gates))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", noop)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="existing",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=1,
    )

    assert gate["accepted"] is True
    # User-guided remediation is recorded in a new cycle without exceeding the
    # configured automatic revision cap.
    assert gate["revision_round"] == 1
    assert feedback_seen == [
        "Keep the selected mechanism and fix the missing falsification test."
    ]


@pytest.mark.asyncio
async def test_unchanged_gate_and_artifacts_get_two_targeted_repair_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery", started_at=time.time())
    run = WorkflowRun(id="revision-no-progress", project_path=str(tmp_path), nodes=[node], status="running")
    _start_run_state(tmp_path, run.id, [node])
    revision_calls = 0
    events: list[tuple[str, dict]] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**_kwargs) -> str:
        nonlocal revision_calls
        revision_calls += 1
        return "same prose without an artifact edit"

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: _rejected("same gap"))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=5,
    )

    assert gate["waiting"] is True
    assert gate["revision_round"] == 2
    assert revision_calls == 2
    no_progress_events = [
        payload
        for event, payload in events
        if event == "node_revision_no_progress"
    ]
    assert len(no_progress_events) == 2
    assert all(
        payload["target_artifact_changed"] is False
        for payload in no_progress_events
    )
    assert not any(
        event == "node_revision_completed"
        for event, _ in events
    )
    waiting = next(payload for event, payload in events if event == "node_revision_waiting")
    assert waiting["stopped_for_no_progress"] is True
    assert waiting["intervention_kind"] == "platform_repair"
    assert waiting["requires_human_decision"] is False
    platform_event = next(
        payload for event, payload in events
        if event == "node_platform_repair_required"
    )
    assert platform_event["owner_node_id"] == "idea"
    persisted = RunState(str(tmp_path), run.id).revision_state(node.id)
    assert persisted["last_gate"]["requires_human_decision"] is False
    assert persisted["hard_limit"] is False
    assert persisted["stopped_for_no_progress"] is True
    assert persisted["last_gate"]["stopped_for_no_progress"] is True
    assert engine._platform_checkpoint_is_auto_recoverable(persisted) is False


@pytest.mark.asyncio
async def test_changed_bytes_do_not_reset_unresolved_finding_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    target = tmp_path / "figures" / "diagram.svg"
    target.parent.mkdir(parents=True)
    target.write_text("<svg>initial</svg>", encoding="utf-8")
    node = WorkflowNode(
        id="figure", name="Figure", skill="/paper-figure", started_at=time.time()
    )
    run = WorkflowRun(
        id="revision-byte-churn", project_path=str(tmp_path), nodes=[node], status="running"
    )
    _start_run_state(tmp_path, run.id, [node])
    revision_calls = 0
    events: list[tuple[str, dict]] = []
    rejected = {
        "accepted": False,
        "reason": "figure quality gate failed",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "FIG-LABEL-001",
                    "severity": "blocker",
                    "message": "Rendered figure labels are missing.",
                    "owner_node": "figure",
                    "target_files": ["figures/diagram.svg"],
                }]
            }
        },
    }

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**_kwargs) -> str:
        nonlocal revision_calls
        revision_calls += 1
        target.write_text(
            f"<svg>byte-level redraw {revision_calls}</svg>", encoding="utf-8"
        )
        return "redrawn"

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: rejected)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={"revision_no_progress_limit": 2},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=6,
    )

    assert revision_calls == 2
    assert gate["waiting"] is True
    waiting = next(payload for event, payload in events if event == "node_revision_waiting")
    assert waiting["stopped_for_no_progress"] is True
    assert waiting["revision_progress"]["target_changed"] is True
    assert "Artifacts changed" in waiting["summary"]
    assert "no structured finding was resolved" in waiting["summary"]
    assert waiting["stall_classification"] == "ineffective_content_change"


@pytest.mark.asyncio
async def test_resumed_revision_restores_semantic_no_progress_before_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="idea",
        name="Idea",
        skill="/idea-discovery",
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="revision-resume-progress",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    state = _start_run_state(tmp_path, run.id, [node])
    rejected = {
        "accepted": False,
        "reason": "node-specific research risk audit failed",
        "summary": "same unresolved contribution finding",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "IDEA-CONTRIB-001",
                    "severity": "blocker",
                    "message": "same unresolved contribution finding",
                    "owner_node": "idea",
                    "target_files": ["ideas/ideas.md"],
                }]
            }
        },
    }
    diagnostics = engine._revision_diagnostics_for_owner(
        engine._gate_revision_diagnostics(rejected),
        "idea",
        "idea",
    )
    scope_signature = engine._revision_scope_signature(
        str(tmp_path),
        "idea",
        diagnostics,
        {},
    )
    state.set_revision_waiting(
        "idea",
        round_number=1,
        cycle=1,
        gate={
            **diagnostics,
            "revision_progress": {
                "finding_ids": ["IDEA-CONTRIB-001"],
                "scope_signature": scope_signature,
                "consecutive_no_progress": 1,
            },
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature=engine._revision_artifact_signature(
            str(tmp_path), "idea", {}
        ),
        artifact_owner_id="idea",
        runtime_signature=engine._revision_runtime_signature(
            str(tmp_path), "idea", {}
        ),
        owner_rounds={"idea": 1},
    )
    revision_calls = 0

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**_kwargs) -> str:
        nonlocal revision_calls
        revision_calls += 1
        return "must not run"

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: rejected)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", noop)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="unchanged",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=5,
    )

    assert gate["waiting"] is True
    assert gate["revision_round"] == 1
    assert revision_calls == 0
    persisted = state.revision_state("idea")
    assert persisted["last_gate"]["revision_progress"][
        "consecutive_no_progress"
    ] == 2


@pytest.mark.asyncio
async def test_persisted_no_progress_checkpoint_needs_change_or_feedback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def persist_waiting(project: Path, run_id: str) -> RunState:
        engine = WorkflowEngine()
        node = WorkflowNode(
            id="idea",
            name="Idea",
            skill="/idea-discovery",
        )
        state = _start_run_state(project, run_id, [node])
        state.set_revision_waiting(
            node.id,
            round_number=2,
            cycle=1,
            gate={
                "reason": "targeted revision produced no semantic progress",
                "summary": (
                    "The same structured findings and target-artifact "
                    "fingerprints remained unchanged."
                ),
                "issues": ["same unresolved idea finding"],
                "intervention_kind": "platform_repair",
                "requires_human_decision": False,
                "hard_limit": False,
                "stopped_for_no_progress": True,
            },
            artifact_signature=engine._revision_artifact_signature(
                str(project),
                node.id,
                {"research_quality_mode": "rigorous"},
            ),
            runtime_signature=engine._revision_runtime_signature(
                str(project),
                node.id,
                {"research_quality_mode": "rigorous"},
            ),
            artifact_owner_id=node.id,
        )
        return state

    unchanged_root = tmp_path / "unchanged"
    persisted = persist_waiting(unchanged_root, "no-progress-unchanged")
    revision = persisted.revision_state("idea")
    assert WorkflowEngine._is_platform_repair_revision_checkpoint(
        revision
    ) is True
    assert WorkflowEngine._is_terminal_revision_checkpoint(revision) is True
    unchanged_engine = WorkflowEngine()
    unchanged_resumed: dict = {}

    async def reopen_platform_repair(**kwargs) -> str:
        unchanged_resumed.update(kwargs)
        return "no-progress-unchanged"

    monkeypatch.setattr(unchanged_engine, "execute", reopen_platform_repair)
    result = await unchanged_engine.resume_persisted_run(
        "no-progress-unchanged", str(unchanged_root),
    )
    assert result == "no-progress-unchanged"
    assert unchanged_resumed["node_ids"] == ["idea"]
    reopened = RunState(
        str(unchanged_root), "no-progress-unchanged"
    ).revision_state("idea")
    assert reopened["waiting"] is False

    feedback_root = tmp_path / "feedback"
    persist_waiting(feedback_root, "no-progress-feedback")
    resumed: dict = {}
    feedback_engine = WorkflowEngine()

    async def fake_execute(**kwargs) -> str:
        resumed.update(kwargs)
        return "no-progress-feedback"

    monkeypatch.setattr(feedback_engine, "execute", fake_execute)
    result = await feedback_engine.resume_persisted_run(
        "no-progress-feedback",
        str(feedback_root),
        checkpoint_feedback=(
            "Rewrite the two falsifiable contributions in the target section."
        ),
    )

    assert result == "no-progress-feedback"
    assert resumed["node_ids"] == ["idea"]
    assert resumed["pipeline_options"]["resume_feedback"].startswith(
        "Rewrite the two falsifiable contributions"
    )


def test_revision_diagnostics_preserve_finding_targets_and_remediation() -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "reason": "node-specific research risk audit failed",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "FIG-EXEC-003",
                    "severity": "blocker",
                    "category": "figure",
                    "message": (
                        "required scientific figure was not rendered: "
                        "robustness_sensitivity"
                    ),
                    "plain_message": "稳健性图尚未生成。",
                    "evidence": [
                        "figures/SCIENTIFIC_ASSET_PLAN.json",
                        "experiments/results/aggregates/robustness_sensitivity.csv",
                    ],
                    "remediation": "Render only the failed semantic asset.",
                    "owner_node": "figure",
                }],
            },
        },
    })

    finding = diagnostics["findings"][0]
    assert finding["id"] == "FIG-EXEC-003"
    assert finding["owner_node"] == "figure"
    assert finding["remediation"] == "Render only the failed semantic asset."
    assert finding["asset_ids"] == ["robustness_sensitivity"]
    assert diagnostics["repair_scope"]["asset_ids"] == [
        "robustness_sensitivity"
    ]
    assert (
        "experiments/results/aggregates/robustness_sensitivity.csv"
        in diagnostics["repair_scope"]["target_files"]
    )


def test_revision_diagnostics_preserve_structured_issues_from_every_gate_layer() -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "issues": [{
            "id": "GATE-OWNER-001",
            "message": "The selected idea record is inconsistent.",
            "owner_node": "novelty",
            "target_files": ["ideas/SELECTED_IDEA.json"],
            "remediation": "Refresh the frozen novelty decision.",
        }],
        "details": {
            "issues": [{
                "id": "DETAIL-OWNER-001",
                "plain_message": "The narrative plan is stale.",
                "message": "NARRATIVE_REPORT.md hash mismatch.",
                "upstream_node": "narrative",
                "target_files": ["NARRATIVE_REPORT.md"],
                "remediation": "Regenerate the narrative from current evidence.",
            }],
            "research_quality": {
                "issues": [{
                    "id": "QUALITY-OWNER-001",
                    "message": "The review state is stale.",
                    "owner_node": "review",
                    "target_files": ["review-stage/REVIEW_STATE.json"],
                    "remediation": "Rerun bounded review.",
                }],
            },
        },
    })

    findings = {item["id"]: item for item in diagnostics["findings"]}
    assert set(findings) == {
        "GATE-OWNER-001",
        "DETAIL-OWNER-001",
        "QUALITY-OWNER-001",
    }
    assert findings["GATE-OWNER-001"]["owner_node"] == "novelty"
    assert findings["DETAIL-OWNER-001"]["upstream_node"] == "narrative"
    assert findings["DETAIL-OWNER-001"]["owner_node"] == "narrative"
    assert findings["QUALITY-OWNER-001"]["remediation"] == "Rerun bounded review."
    assert "ideas/SELECTED_IDEA.json" in diagnostics["repair_scope"]["target_files"]
    assert "NARRATIVE_REPORT.md" in diagnostics["repair_scope"]["target_files"]
    assert all(not issue.lstrip().startswith("{") for issue in diagnostics["issues"])


def test_owner_scope_never_borrows_other_owner_targets() -> None:
    diagnostics = {
        "accepted": False,
        "reason": "multi-owner failure",
        "issues": ["figure gap", "paper gap"],
        "findings": [
            {
                "id": "FIG-NO-TARGET",
                "message": "figure gap",
                "owner_node": "figure",
                "target_files": [],
                "asset_ids": [],
            },
            {
                "id": "PAPER-TARGET",
                "message": "paper gap",
                "owner_node": "paper",
                "target_files": ["paper/tables/results.tex"],
                "asset_ids": ["results"],
            },
        ],
        "repair_scope": {
            "finding_ids": ["FIG-NO-TARGET", "PAPER-TARGET"],
            "target_files": ["paper/tables/results.tex"],
            "asset_ids": ["results"],
        },
    }

    figure_scope = WorkflowEngine._revision_diagnostics_for_owner(
        diagnostics,
        "figure",
    )

    assert [item["id"] for item in figure_scope["findings"]] == [
        "FIG-NO-TARGET"
    ]
    assert figure_scope["repair_scope"] == {
        "finding_ids": ["FIG-NO-TARGET"],
        "target_files": [],
        "asset_ids": [],
    }


def test_unowned_finding_stays_with_origin_node_during_owner_rotation() -> None:
    diagnostics = {
        "accepted": False,
        "reason": "mixed review and paper failure",
        "issues": ["review state missing", "table layout failed"],
        "findings": [
            {
                "id": "REVIEW-STATE",
                "message": "Persist a structured review round.",
                "target_files": ["review-stage/REVIEW_STATE.json"],
            },
            {
                "id": "PAPER-TABLE",
                "owner_node": "paper",
                "message": "The table exceeds the usable text width.",
                "target_files": ["paper/tables/results.tex"],
            },
        ],
    }

    paper_scope = WorkflowEngine._revision_diagnostics_for_owner(
        diagnostics,
        "paper",
        "review",
    )
    review_scope = WorkflowEngine._revision_diagnostics_for_owner(
        diagnostics,
        "review",
        "review",
    )

    assert [item["id"] for item in paper_scope["findings"]] == [
        "PAPER-TABLE"
    ]
    assert paper_scope["repair_scope"]["target_files"] == [
        "paper/tables/results.tex"
    ]
    assert [item["id"] for item in review_scope["findings"]] == [
        "REVIEW-STATE"
    ]
    assert review_scope["repair_scope"]["target_files"] == [
        "review-stage/REVIEW_STATE.json"
    ]


def test_flattened_staged_manuscript_failure_recovers_paper_owner_and_targets() -> None:
    message = (
        "Staged manuscript did not satisfy the quality contract: "
        "staged-paper: Method: Method has not passed its local section "
        "contract.; simulation manuscript must disclose benchmark provenance "
        "exactly once in Methods / Experimental Setup"
    )
    gate = {
        "accepted": False,
        "details": {"issues": [message]},
    }

    diagnostics = WorkflowEngine._gate_revision_diagnostics(gate)
    finding = diagnostics["findings"][0]

    assert finding["id"].startswith("GATE-DETAILS-")
    assert finding["owner_node"] == "paper"
    assert finding["target_files"] == [
        "paper/sections/03_method.tex",
        "paper/sections/04_experiments.tex",
    ]
    assert diagnostics["repair_scope"]["target_files"] == finding["target_files"]

    engine = WorkflowEngine()
    results = WorkflowNode(
        id="results",
        name="Results",
        skill="/analyze-results",
    )
    paper = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(id="flattened-paper-owner", nodes=[results, paper])

    owner = engine._revision_owner_for_gate(paper, run, gate)

    assert owner.id == "paper"


@pytest.mark.parametrize(
    ("stage_failure", "expected_targets"),
    [
        (
            "Abstract: abstract omits the primary endpoint",
            ["paper/sections/00_abstract.tex"],
        ),
        (
            "front_matter: title and abstract are not evidence calibrated",
            ["paper/TITLE.txt", "paper/sections/00_abstract.tex"],
        ),
        (
            "Introduction lacks two or more falsifiable contributions",
            ["paper/sections/01_introduction.tex"],
        ),
        (
            "Related Work: related work lacks closest-work positioning",
            ["paper/sections/02_related_work.tex"],
        ),
        (
            "Method: method omits the reproducible procedure",
            ["paper/sections/03_method.tex"],
        ),
        (
            "Experimental Setup: experiments omit leakage controls",
            ["paper/sections/04_experiments.tex"],
        ),
        (
            "Experiments: experimental setup lacks compute details",
            ["paper/sections/04_experiments.tex"],
        ),
        (
            "Results: results omit the registered robustness analysis",
            ["paper/sections/05_results.tex"],
        ),
        (
            "Evaluation Protocol and Planned Analyses: protocol lacks uncertainty",
            ["paper/sections/05_results.tex"],
        ),
        (
            "Discussion: discussion omits alternative explanations",
            ["paper/sections/06_discussion.tex"],
        ),
        (
            "Limitations: limitations omit concrete validity threats",
            ["paper/sections/07_limitations.tex"],
        ),
        (
            "Conclusion: conclusion lacks the decisive next test",
            ["paper/sections/08_conclusion.tex"],
        ),
        (
            "Cross-section consistency: terminology is inconsistent",
            ["paper/CROSS_SECTION_REVIEW.md"],
        ),
        (
            "Venue-aware manuscript assembly: main source is incomplete",
            ["paper/main.tex"],
        ),
    ],
)
def test_flattened_staged_section_names_recover_canonical_targets(
    stage_failure: str,
    expected_targets: list[str],
) -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "details": {
            "issues": [
                "Staged manuscript did not satisfy the quality contract: "
                f"staged-paper: {stage_failure}"
            ],
        },
    })

    finding = diagnostics["findings"][0]
    assert finding["owner_node"] == "paper"
    assert finding["target_files"] == expected_targets
    assert diagnostics["repair_scope"]["target_files"] == expected_targets


@pytest.mark.parametrize(
    ("label", "expected_targets"),
    [
        ("fig:method-architecture", ["paper/sections/03_method.tex"]),
        ("fig:evaluation-design", ["paper/sections/04_experiments.tex"]),
        ("tab:claim-evidence", ["paper/sections/05_results.tex"]),
        ("fig:unknown-scientific-asset", [
            "paper/sections/03_method.tex",
            "paper/sections/04_experiments.tex",
            "paper/sections/05_results.tex",
            "paper/sections/06_discussion.tex",
        ]),
    ],
)
def test_cross_section_asset_findings_route_to_manuscript_prose(
    label: str,
    expected_targets: list[str],
) -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "details": {
            "issues": [
                "Staged manuscript did not satisfy the quality contract: "
                "staged-paper: Cross-section consistency: scientific asset "
                f"is included but never referenced in prose: {label}"
            ],
        },
    })

    finding = diagnostics["findings"][0]
    assert finding["owner_node"] == "paper"
    assert finding["target_files"] == expected_targets
    assert diagnostics["repair_scope"]["target_files"] == expected_targets


@pytest.mark.parametrize(
    ("message", "expected_owner", "expected_targets"),
    [
        (
            "Limitations: limitations omit concrete validity threats",
            "",
            [],
        ),
        (
            "Staged manuscript did not satisfy the quality contract: "
            "staged-paper: Introduction: discuss limitations and results",
            "paper",
            ["paper/sections/01_introduction.tex"],
        ),
        (
            "The manuscript must summarize the discussion and limitations.",
            "paper",
            ["paper/main.tex"],
        ),
    ],
)
def test_manuscript_fallback_avoids_unscoped_section_word_matches(
    message: str,
    expected_owner: str,
    expected_targets: list[str],
) -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "details": {"issues": [message]},
    })

    finding = diagnostics["findings"][0]
    assert finding["owner_node"] == expected_owner
    assert finding["target_files"] == expected_targets


def test_manuscript_fallback_preserves_explicit_paper_target() -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "details": {
            "issues": [{
                "id": "PAPER-EXPLICIT-TARGET-001",
                "message": "staged-paper: Limitations: repair the appendix caveat",
                "owner_node": "paper",
                "target_files": ["paper/sections/09_appendix.tex"],
            }],
        },
    })

    finding = diagnostics["findings"][0]
    assert finding["owner_node"] == "paper"
    assert finding["target_files"] == ["paper/sections/09_appendix.tex"]


def test_manuscript_fallback_does_not_replace_explicit_scientific_owner() -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "details": {
            "issues": [{
                "id": "RESULTS-MANUSCRIPT-001",
                "message": (
                    "The manuscript must be updated after repairing metric "
                    "provenance in the result analysis."
                ),
                "owner_node": "results",
                "target_files": ["experiments/results/analysis.md"],
            }],
        },
    })

    finding = diagnostics["findings"][0]
    assert finding["owner_node"] == "results"
    assert finding["target_files"] == ["experiments/results/analysis.md"]
