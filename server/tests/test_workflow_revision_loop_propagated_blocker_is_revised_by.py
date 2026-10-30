from __future__ import annotations

from server.tests._workflow_revision_loop_support import (
    NodeStatus as NodeStatus,
    Path as Path,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _accepted as _accepted,
    _start_run_state as _start_run_state,
    asyncio as asyncio,
    json as json,
    pytest as pytest,
    time as time,
)


@pytest.mark.asyncio
async def test_propagated_blocker_is_revised_by_responsible_upstream_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    design = WorkflowNode(
        id="exp-design",
        name="Experiment design",
        skill="/experiment-plan",
    )
    figure = WorkflowNode(
        id="figure",
        name="Figure",
        skill="/paper-figure",
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="upstream-owner",
        project_path=str(tmp_path),
        nodes=[design, figure],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [design, figure])
    rejected = {
        "accepted": False,
        "reason": "node-specific research risk audit failed",
        "summary": "upstream design is invalid",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "severity": "blocker",
                    "upstream_node": "exp-design",
                    "plain_message": "实验设计代码无法解析。",
                    "remediation": "修复实验设计代码。",
                }]
            }
        },
    }
    gates = iter([rejected, _accepted(), _accepted()])
    revised_by: list[str] = []
    prepared: list[str] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        prepared.append(_node.id)
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        revised_by.append(kwargs["node"].id)
        return "upstream repaired"

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: next(gates),
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", noop)

    gate, _ = await engine._run_node_revision_loop(
        node=figure,
        run=run,
        initial_result="figure ready",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=2,
    )

    assert gate["accepted"] is True
    assert revised_by == ["exp-design"]
    assert prepared == ["figure", "exp-design", "figure"]


def test_resumed_subset_routes_blocker_to_registered_upstream_owner() -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(id="resumed-owner", nodes=[review])
    gate = {
        "accepted": False,
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "severity": "blocker",
                    "upstream_node": "paper",
                    "plain_message": "The paper contains an unsupported claim.",
                }],
            },
        },
    }

    owner = engine._revision_owner_for_gate(review, run, gate)

    assert owner.id == "paper"
    assert owner.id not in {item.id for item in run.nodes}


def test_explicit_risk_owner_routes_without_upstream_alias() -> None:
    engine = WorkflowEngine()
    audit = WorkflowNode(id="audit", name="Audit", skill="/experiment-audit")
    run = WorkflowRun(id="explicit-owner", nodes=[audit])
    gate = {
        "accepted": False,
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "severity": "blocker",
                    "owner_node": "results",
                    "plain_message": "Result provenance is inconsistent.",
                }],
            },
        },
    }

    owner = engine._revision_owner_for_gate(audit, run, gate)

    assert owner.id == "results"


def test_advisory_owner_does_not_steal_audit_blocker_repair() -> None:
    engine = WorkflowEngine()
    audit = WorkflowNode(id="audit", name="Audit", skill="/experiment-audit")
    run = WorkflowRun(id="audit-owner-priority", nodes=[audit])
    gate = {
        "accepted": False,
        "details": {
            "node_risk_audit": {
                "findings": [
                    {
                        "severity": "warning",
                        "owner_node": "audit",
                        "plain_message": "A citation lookup was unavailable.",
                    },
                    {
                        "severity": "blocker",
                        "upstream_node": "exp-run",
                        "plain_message": "Result seed provenance is inconsistent.",
                    },
                ],
            },
        },
    }

    owner = engine._revision_owner_for_gate(audit, run, gate)

    assert owner.id == "exp-run"


def test_downstream_freshness_owner_does_not_steal_upstream_repair() -> None:
    engine = WorkflowEngine()
    audit = WorkflowNode(id="audit", name="Audit", skill="/experiment-audit")
    run = WorkflowRun(id="audit-upstream-priority", nodes=[audit])
    gate = {
        "accepted": False,
        "details": {
            "node_risk_audit": {
                "findings": [
                    {
                        "severity": "blocker",
                        "owner_node": "audit",
                        "plain_message": "Audit source bundle is stale.",
                    },
                    {
                        "severity": "blocker",
                        "upstream_node": "narrative",
                        "plain_message": "Narrative is stale after result repair.",
                    },
                    {
                        "severity": "blocker",
                        "upstream_node": "review",
                        "plain_message": "Review is stale after result repair.",
                    },
                ],
            },
        },
    }

    owner = engine._revision_owner_for_gate(
        audit,
        run,
        gate,
        owner_rounds={"audit": 0, "narrative": 2, "review": 1},
    )

    assert owner.id == "narrative"


def test_new_upstream_integrity_blocker_supersedes_stale_review_owner() -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(id="review-rebuild-chain", nodes=[review])
    gate = {
        "accepted": False,
        "details": {
            "review_findings": [{
                "id": "REVIEW-LIT-001",
                "severity": "blocker",
                "category": "peer_review",
                "owner_node": "lit",
                "message": "The closest-protocol comparison is incomplete.",
            }],
            "node_risk_audit": {
                "findings": [{
                    "id": "UPSTREAM-NARRATIVE-STALE",
                    "severity": "blocker",
                    "category": "upstream_integrity",
                    "upstream_node": "narrative",
                    "owner_node": "narrative",
                    "plain_message": (
                        "Narrative is stale after the literature repair."
                    ),
                }],
            },
        },
    }

    owner = engine._revision_owner_for_gate(
        review,
        run,
        gate,
        owner_rounds={"lit": 1, "narrative": 0},
    )

    assert owner.id == "narrative"


def test_resumed_paper_subset_prefers_causal_experiment_owner() -> None:
    engine = WorkflowEngine()
    paper = WorkflowNode(id="paper", name="Paper", skill="/domain-paper-write")
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    audit = WorkflowNode(id="audit", name="Audit", skill="/experiment-audit")
    run = WorkflowRun(
        id="resumed-scientific-owner-priority",
        nodes=[paper, review, audit],
    )
    gate = {
        "accepted": False,
        "details": {
            "node_risk_audit": {
                "findings": [
                    {
                        "severity": "blocker",
                        "owner_node": "paper",
                        "plain_message": "The manuscript repeats an unsupported result.",
                    },
                    {
                        "severity": "blocker",
                        "upstream_node": "results",
                        "plain_message": "Registered paired axes are incomplete.",
                    },
                    {
                        "severity": "blocker",
                        "upstream_node": "exp-run",
                        "plain_message": "The run ledger is missing provenance joins.",
                    },
                ],
            },
        },
    }

    owner = engine._revision_owner_for_gate(
        audit,
        run,
        gate,
        owner_rounds={"paper": 0, "results": 1, "exp-run": 2},
    )

    assert owner.id == "exp-run"


def test_stale_paper_consumer_repairs_paper_not_changed_results() -> None:
    engine = WorkflowEngine()
    paper = WorkflowNode(id="paper", name="Paper", skill="/domain-paper-write")
    run = WorkflowRun(id="stale-paper-consumer", nodes=[paper])
    gate = {
        "accepted": False,
        "reason": "paper quality gate needs revision",
        "summary": (
            "staged-paper: scientific inputs changed after paper freeze: "
            "NARRATIVE_REPORT.md, experiments/results/analysis.md, "
            "figures/FIGURE_MANIFEST.json; staged-paper: staged paper state "
            "is stale relative to scientific inputs"
        ),
    }

    owner = engine._revision_owner_for_gate(paper, run, gate)

    assert owner.id == "paper"


@pytest.mark.asyncio
async def test_stale_paper_refresh_does_not_forward_manifest_targets_to_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    paper = WorkflowNode(id="paper", name="Paper", skill="/domain-paper-write")
    run = WorkflowRun(
        id="stale-paper-full-refresh",
        project_path=str(tmp_path),
        nodes=[paper],
    )
    captured: dict[str, object] = {}

    async def fake_staged_paper(**kwargs):
        captured.update(kwargs)
        return "refreshed"

    monkeypatch.setattr(engine, "_execute_staged_paper", fake_staged_paper)
    async def refreshed_runtime(*_args, **_kwargs):
        return {"passed": True, "issues": []}

    # This unit isolates author target routing after successful runtime refresh.
    # Separate real refresh regressions verify source freshness and refusal.
    monkeypatch.setattr("server.workflows.paper_repair_runtime.refresh_paper_runtime_inputs", refreshed_runtime)
    monkeypatch.setattr(engine, "_paper_acceptance_gate", lambda *_args, **_kwargs: {
        "accepted": False, "reason": "Section remains unfinished", "details": {
            "issues": ["Finish the already declared results argument"],
            "findings": [{"id": "FIXTURE-RESULTS", "owner_node": "paper", "category": "authoring",
                          "message": "Finish the already declared results argument", "target_files": ["paper/sections/05_results.tex"]}],
        },
    })
    diagnostics = {
        "reason": "artifact preparation or verification failed",
        "issues": [
            "staged-paper: scientific inputs changed after paper freeze: "
            "experiments/results/analysis.md, figures/FIGURE_MANIFEST.json, "
            "paper/tables/TABLE_MANIFEST.json; staged paper state is stale "
            "relative to scientific inputs"
        ],
        "repair_scope": {
            "target_files": [
                "experiments/results/analysis.md",
                "figures/FIGURE_MANIFEST.json",
                "paper/tables/TABLE_MANIFEST.json",
            ]
        },
    }

    result = await engine._revise_node_from_gate(
        node=paper,
        run=run,
        diagnostics=diagnostics,
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="benchmark",
        effort="balanced",
        assurance="draft",
        opts={},
    )

    assert result == "refreshed"
    assert "Target artifact: paper/sections/05_results.tex" in captured["revision_issues"]
    assert all("MANIFEST" not in issue and "analysis.md" not in issue for issue in captured["revision_issues"])


@pytest.mark.parametrize(
    ("target", "expected_owner"),
    [
        ("paper/synthetic_preview_figures.tex", "figure"),
        ("paper/generated_result_figures.tex", "figure"),
        ("paper/tables/synthetic_preview_results.tex", "results"),
        ("./tables/synthetic_preview_results.tex", "results"),
    ],
)
def test_generated_paper_projection_routes_to_its_producer(
    target: str,
    expected_owner: str,
) -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/domain-review-loop")
    run = WorkflowRun(id="generated-projection-owner", nodes=[review])
    gate = {
        "accepted": False,
        "details": {
            "review_findings": [{
                "severity": "blocker",
                "owner_node": "paper",
                "message": f"[owner=paper] [target={target}] repair projection",
                "target_files": [target],
            }],
        },
    }

    owner = engine._revision_owner_for_gate(review, run, gate)

    assert owner.id == expected_owner


def test_generated_results_table_layout_stays_with_bounded_paper_repair() -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/domain-review-loop")
    run = WorkflowRun(id="generated-table-layout-owner", nodes=[review])
    gate = {
        "accepted": False,
        "details": {
            "review_findings": [{
                "severity": "blocker",
                "category": "visual_layout",
                "owner_node": "paper",
                "message": "PDF table text is too small.",
                "target_files": [
                    "paper/tables/synthetic_preview_results.tex"
                ],
            }],
        },
    }

    owner = engine._revision_owner_for_gate(review, run, gate)

    assert owner.id == "paper"


def test_audit_idle_timeout_exceeds_model_transport_budget() -> None:
    from server.workflows.review_audit import REVIEW_MODEL_CALL_TIMEOUT_SECONDS

    assert 420 > REVIEW_MODEL_CALL_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("finding", "expected_owner"),
    [
        (
            "experiments/src/train.py lacks the declared matched baseline and ablation registry.",
            "exp-design",
        ),
        (
            "The training job failed and no successful run log or checkpoint exists.",
            "exp-run",
        ),
        (
            "Report per-seed uncertainty, confidence intervals, and metric provenance.",
            "results",
        ),
        (
            "The prior-art discussion is missing a central citation.",
            "lit",
        ),
    ],
)
def test_structured_peer_review_routes_to_scientific_owner(
    finding: str,
    expected_owner: str,
) -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="peer-review-owner",
        nodes=[review],
        options={"run_experiment": True},
    )
    gate = {
        "accepted": False,
        "details": {
            "review_findings": [{
                "severity": "blocker",
                "message": finding,
                "target_files": engine._revision_target_files(finding),
            }],
            "issues": [finding],
        },
    }

    owner = engine._revision_owner_for_gate(review, run, gate)

    assert owner.id == expected_owner


def test_peer_review_target_owner_overrides_contradictory_owner_label() -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(id="review-target-owner", nodes=[review])
    action = (
        "[owner=lit] [target=paper/sections/01_introduction.tex] "
        "Add a direct nearest-work comparison to the introduction."
    )
    diagnostics = engine._gate_revision_diagnostics({
        "accepted": False,
        "details": {
            "review_findings": [{
                "id": "REVIEW-1-1",
                "severity": "blocker",
                "category": "peer_review",
                "owner_node": "lit",
                "message": action,
                "target_files": ["paper/sections/01_introduction.tex"],
            }],
            "issues": [action],
        },
    })

    owner = engine._revision_owner_for_gate(
        review,
        run,
        {
            "accepted": False,
            "details": {
                "review_findings": diagnostics["findings"],
                "issues": diagnostics["issues"],
            },
        },
    )

    assert diagnostics["findings"][0]["owner_node"] == "paper"
    assert owner.id == "paper"


def test_unexecuted_experiment_finding_is_advisory_when_runtime_disabled() -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="peer-review-no-runtime",
        nodes=[review],
        options={"run_experiment": False},
    )
    finding = "The experiment was not run and no successful run log exists."

    owner = engine._revision_owner_for_gate(
        review,
        run,
        {
            "accepted": False,
            "details": {
                "review_findings": [{"message": finding}],
                "issues": [finding],
            },
        },
    )

    assert owner.id == "review"


@pytest.mark.asyncio
async def test_upstream_change_reopens_and_expands_entire_downstream_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    definitions = engine._get_default_nodes()
    state = RunState(str(tmp_path), "research-loop-rebuild")
    state.start(
        [
            {
                "id": node.id,
                "name": node.name,
                "skill": node.skill,
            }
            for node in definitions
        ],
        {"options": {"run_experiment": True}},
    )
    for node in definitions:
        state.set_status(node.id, "done")
        state.accept(node.id, f"before-{node.id}", "deterministic:test")
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="research-loop-rebuild",
        project_path=str(tmp_path),
        nodes=[review],
        status="running",
        options={"run_experiment": True},
    )
    events: list[tuple[str, dict]] = []

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_emit", emit)
    opts = {"run_experiment": True, "max_research_loop_cycles": 3}

    restart_from = await engine._prepare_research_loop_restart(
        run=run,
        run_state=state,
        owner_id="exp-design",
        reason="review found an invalid baseline implementation",
        opts=opts,
    )

    persisted = state.load()
    assert persisted is not None
    assert restart_from == "exp-run"
    assert persisted["phases"]["exp-design"]["status"] == "accepted"
    assert persisted["phases"]["exp-run"]["status"] == "pending"
    assert persisted["phases"]["results"]["status"] == "pending"
    assert persisted["phases"]["ppt"]["status"] == "pending"
    assert persisted["phases"]["lit"]["status"] == "accepted"
    assert [node.id for node in run.nodes] == [node.id for node in definitions]
    assert next(node for node in run.nodes if node.id == "exp-design").status == NodeStatus.COMPLETED
    assert next(node for node in run.nodes if node.id == "exp-run").status == NodeStatus.IDLE
    assert opts["_research_loop_cycle"] == 1
    assert any(event == "research_loop_restarted" for event, _ in events)


@pytest.mark.asyncio
async def test_identical_upstream_generation_is_reconciled_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    definitions = engine._get_default_nodes()
    state = RunState(str(tmp_path), "coalesced-research-loop")
    state.start(
        [
            {"id": node.id, "name": node.name, "skill": node.skill}
            for node in definitions
        ],
        {"options": {"run_experiment": True}},
    )
    for node in definitions:
        state.set_status(node.id, "done")
        state.accept(node.id, f"before-{node.id}", "deterministic:test")
    run = WorkflowRun(
        id="coalesced-research-loop",
        project_path=str(tmp_path),
        nodes=list(definitions),
        status="running",
        options={"run_experiment": True},
    )
    events: list[tuple[str, dict]] = []

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_emit", emit)
    opts = {"run_experiment": True, "max_research_loop_cycles": 3}

    first = await engine._prepare_research_loop_restart(
        run=run,
        run_state=state,
        owner_id="figure",
        reason="review found one stale figure generation",
        opts=opts,
    )
    for phase_id in ("paper", "review", "audit", "compile", "ppt"):
        state.set_status(phase_id, "done")
        state.accept(phase_id, f"rebuilt-{phase_id}", "deterministic:test")

    duplicate = await engine._prepare_research_loop_restart(
        run=run,
        run_state=state,
        owner_id="figure",
        reason="the same stale finding was reported again",
        opts=opts,
    )

    persisted = state.load()
    assert first == "paper"
    assert duplicate == ""
    assert len(persisted["reconciliation_transactions"]) == 1
    assert persisted["phases"]["paper"]["status"] == "accepted"
    assert opts["_research_loop_cycle"] == 1
    assert [event for event, _ in events].count("research_loop_restarted") == 1
    assert [event for event, _ in events].count("research_loop_coalesced") == 1


@pytest.mark.asyncio
async def test_review_literature_repair_keeps_frozen_scientific_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    definitions = engine._get_default_nodes()
    state = RunState(str(tmp_path), "late-literature-repair")
    state.start(
        [
            {"id": node.id, "name": node.name, "skill": node.skill}
            for node in definitions
        ],
        {"options": {"run_experiment": False}},
    )
    for node in definitions:
        state.set_status(node.id, "done")
        state.accept(node.id, f"before-{node.id}", "deterministic:test")
    run = WorkflowRun(
        id="late-literature-repair",
        project_path=str(tmp_path),
        nodes=list(definitions),
        status="running",
        options={"run_experiment": False},
    )

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_emit", noop)
    restart_from = await engine._prepare_research_loop_restart(
        run=run,
        run_state=state,
        owner_id="lit",
        consumer_id="review",
        reason="peer review requested a direct Related Work precedent",
        opts={"max_research_loop_cycles": 3},
    )

    phases = state.load()["phases"]
    assert restart_from == "narrative"
    for phase_id in ("idea", "novelty", "exp-design", "exp-run", "results", "figure"):
        assert phases[phase_id]["status"] == "accepted"
    for phase_id in ("narrative", "paper", "review", "audit", "compile", "ppt"):
        assert phases[phase_id]["status"] == "pending"


@pytest.mark.asyncio
async def test_detached_upstream_owner_is_revalidated_before_resume_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="detached-owner-revalidation",
        project_path=str(tmp_path),
        nodes=[review],
        status="running",
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [
            {"id": "paper", "name": "Paper", "skill": "/paper-writing"},
            {"id": "review", "name": "Review", "skill": "/auto-review-loop"},
        ],
        {"options": {}},
    )
    state.set_status("paper", "done")
    state.accept("paper", "paper-before", "deterministic:test")
    rejected = {
        "accepted": False,
        "reason": "upstream paper invalid",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "severity": "blocker",
                    "upstream_node": "paper",
                    "plain_message": "Unsupported empirical claim.",
                }],
            },
        },
    }
    gates = iter([
        rejected,
        {**_accepted(), "verdict_id": "paper-after"},
        {**_accepted(), "verdict_id": "review-after"},
    ])
    prepared: list[str] = []
    refreshed: list[str] = []
    events: list[tuple[str, dict]] = []

    async def prepare(node, _run, result, *_args, **_kwargs) -> str:
        prepared.append(node.id)
        return result

    async def revise(**kwargs) -> str:
        assert kwargs["node"].id == "paper"
        return "paper repaired"

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    async def refresh_review(*_args, **_kwargs) -> str:
        refreshed.append("review")
        return "fresh managed review"

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: next(gates))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_execute_review_node", refresh_review)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=review,
        run=run,
        initial_result="review pending",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=2,
    )

    persisted = state.load()
    assert gate["accepted"] is True
    assert prepared == ["review", "paper", "review"]
    assert persisted is not None
    assert persisted["phases"]["paper"]["status"] == "accepted"
    assert persisted["phases"]["paper"]["verdict_id"] == "paper-after"
    assert refreshed == ["review"]
    assert any(event == "upstream_owner_revalidated" for event, _ in events)
    assert any(event == "consumer_snapshot_refreshed" for event, _ in events)
