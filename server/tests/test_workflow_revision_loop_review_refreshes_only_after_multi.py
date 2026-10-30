from __future__ import annotations

from server.tests._workflow_revision_loop_support import (
    Path as Path,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _accepted as _accepted,
    _start_run_state as _start_run_state,
    _write_review_layout_routing_fixture as _write_review_layout_routing_fixture,
    asyncio as asyncio,
    json as json,
    pytest as pytest,
)


@pytest.mark.asyncio
async def test_review_refreshes_only_after_multi_owner_upstream_chain_is_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old review findings cannot send the workflow back to lit twice."""
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="review-consumer-refresh-chain",
        project_path=str(tmp_path),
        nodes=[review],
        status="running",
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [
            {"id": "lit", "name": "Literature", "skill": "/research-lit"},
            {"id": "narrative", "name": "Narrative", "skill": "/research-refine"},
            {"id": "review", "name": "Review", "skill": "/auto-review-loop"},
        ],
        {"options": {}},
    )
    for phase_id in ("lit", "narrative"):
        state.set_status(phase_id, "done")
        state.accept(phase_id, f"before-{phase_id}", "deterministic:test")

    old_lit_finding = {
        "accepted": False,
        "reason": "old managed review finding",
        "details": {
            "managed_review": True,
            "review_findings": [{
                "id": "REVIEW-LIT-001",
                "severity": "blocker",
                "category": "peer_review",
                "owner_node": "lit",
                "message": "Add a direct ranking-stability precedent.",
                "target_files": ["literature/survey.md"],
            }],
        },
    }
    stale_narrative_finding = {
        "accepted": False,
        "reason": "narrative stale after literature repair",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "UPSTREAM-NARRATIVE-STALE",
                    "severity": "blocker",
                    "category": "upstream_integrity",
                    "upstream_node": "narrative",
                    "owner_node": "narrative",
                    "message": "Narrative source bundle is stale.",
                    "target_files": ["NARRATIVE_REPORT.md"],
                }],
            },
        },
    }
    review_gate_count = 0
    review_prepare_count = 0
    revised_owners: list[str] = []
    review_refreshes: list[str] = []
    events: list[str] = []

    async def prepare(candidate, _run, result, *_args, **_kwargs) -> str:
        nonlocal review_prepare_count
        if candidate.id == "review":
            review_prepare_count += 1
            _run.options.setdefault("_node_preflight_findings", {})[
                "review"
            ] = (
                stale_narrative_finding["details"]["node_risk_audit"][
                    "findings"
                ]
                if review_prepare_count == 2
                else []
            )
        return result

    def acceptance(candidate, *_args, **_kwargs):
        nonlocal review_gate_count
        if candidate.id == "review":
            review_gate_count += 1
            if review_gate_count == 1:
                return old_lit_finding
            if review_gate_count == 2:
                # The persisted managed verdict still points at literature.
                # Live preflight must override it and route the newly stale
                # narrative dependency instead of repairing literature twice.
                return old_lit_finding
            return {**_accepted(), "verdict_id": "fresh-review"}
        return {**_accepted(), "verdict_id": f"repaired-{candidate.id}"}

    async def revise(**kwargs) -> str:
        revised_owners.append(kwargs["node"].id)
        return f"repaired {kwargs['node'].id}"

    async def refresh_review(*_args, **_kwargs) -> str:
        review_refreshes.append("review")
        return "fresh managed review"

    async def emit(_run, event: str, _payload: dict) -> None:
        events.append(event)

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def no_restart(**_kwargs) -> str:
        return ""

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_execute_review_node", refresh_review)
    monkeypatch.setattr(
        engine,
        "_changed_nonempty_node_artifacts",
        lambda *_args, **_kwargs: ["changed"],
    )
    monkeypatch.setattr(engine, "_prepare_research_loop_restart", no_restart)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=review,
        run=run,
        initial_result="old review",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=6,
    )

    assert gate["accepted"] is True
    assert revised_owners == ["lit", "narrative"]
    assert review_refreshes == ["review"]
    assert review_prepare_count == 3
    assert events.count("consumer_snapshot_refresh_required") == 2
    assert events.count("consumer_snapshot_refreshed") == 1
    revision = state.revision_state("review")
    assert revision.get("consumer_refresh_required") is not True


@pytest.mark.asyncio
async def test_failed_upstream_owner_revalidation_never_accepts_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="failed-owner-revalidation",
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
    downstream_rejected = {
        "accepted": False,
        "reason": "upstream paper invalid",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "UPSTREAM-PAPER-001",
                    "severity": "blocker",
                    "upstream_node": "paper",
                    "plain_message": "Paper remains invalid.",
                    "target_files": ["paper/main.tex"],
                }],
            },
        },
    }
    owner_rejected = {
        "accepted": False,
        "reason": "paper contract still invalid",
        "summary": "paper contract still invalid after targeted repair",
        "details": {"issues": ["paper contract still invalid"]},
    }
    prepared: list[str] = []

    async def prepare(node, _run, result, *_args, **_kwargs) -> str:
        prepared.append(node.id)
        return result

    async def revise(**kwargs) -> str:
        assert kwargs["node"].id == "paper"
        return "attempted paper repair"

    async def noop(*_args, **_kwargs) -> None:
        return None

    def acceptance(node, *_args, **_kwargs):
        return owner_rejected if node.id == "paper" else downstream_rejected

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", noop)

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

    assert gate["accepted"] is False
    assert gate["waiting"] is True
    assert gate["revision_owner_id"] == "paper"
    assert prepared == ["review", "paper"]
    assert state.load()["phases"]["paper"]["status"] == "pending"


def test_revision_targets_preserve_dot_merak_and_explicit_repair_scope() -> None:
    engine = WorkflowEngine()
    assert engine._revision_target_files(
        [".merak/NARRATIVE_BUILD.json"]
    ) == [".merak/NARRATIVE_BUILD.json"]
    assert engine._revision_target_files(
        "experiments/results/analysis.md；"
        "experiments/results/simulated/claim_evidence.csv，"
        "experiments/results/simulated/SIMULATION_MANIFEST.json"
    ) == [
        "experiments/results/analysis.md",
        "experiments/results/simulated/claim_evidence.csv",
        "experiments/results/simulated/SIMULATION_MANIFEST.json",
    ]

    diagnostics = engine._gate_revision_diagnostics({
        "accepted": False,
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "FIG-QUALITY-001",
                    "severity": "blocker",
                    "message": "method figure needs repair",
                    "evidence": [
                        "figures/FIGURE_SPECS.json",
                        "ideas/SELECTED_IDEA.json",
                    ],
                    "target_files": ["figures/FIGURE_SPECS.json"],
                    "asset_ids": ["method_architecture"],
                }],
            },
        },
    })
    assert diagnostics["repair_scope"]["target_files"] == [
        "figures/FIGURE_SPECS.json"
    ]
    assert diagnostics["repair_scope"]["asset_ids"] == [
        "method_architecture"
    ]


def test_non_english_mechanism_with_incidental_ascii_term_is_not_false_negative() -> None:
    assert WorkflowEngine._paper_covers_mechanism(
        "协议替代解释消融",
        "Control policy and protocol-alternative explanation ablation.",
        [
            "在共享预算下改变架构或训练 recipe，区分模型差异与协议差异。",
        ],
    )


@pytest.mark.asyncio
async def test_audit_results_repair_detects_simulated_package_change_and_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    definitions = engine._get_default_nodes()
    audit = next(node for node in definitions if node.id == "audit")
    results = next(node for node in definitions if node.id == "results")
    options = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
        "max_research_loop_cycles": 3,
    }
    run = WorkflowRun(
        id="audit-results-simulation-restart",
        project_path=str(tmp_path),
        nodes=definitions,
        status="running",
        options=options,
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [
            {"id": node.id, "name": node.name, "skill": node.skill}
            for node in definitions
        ],
        {"options": options},
    )
    for node in definitions:
        state.set_status(node.id, "done")
        state.accept(node.id, f"before-{node.id}", "deterministic:test")

    simulated = tmp_path / "experiments" / "results" / "simulated"
    simulated.mkdir(parents=True)
    manifest = simulated / "SIMULATION_MANIFEST.json"
    manifest.write_text('{"schema": 5, "data_files": []}\n', encoding="utf-8")
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.write_text("old analysis\n", encoding="utf-8")

    rejected = {
        "accepted": False,
        "reason": "simulation evidence package is incomplete",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "AUDIT-RESULTS-001",
                    "severity": "blocker",
                    "upstream_node": "results",
                    "plain_message": "run-level paired evidence is missing",
                    "target_files": [
                        "experiments/results/simulated/SIMULATION_MANIFEST.json"
                    ],
                }],
            },
        },
    }
    accepted_results = {
        **_accepted(),
        "verdict_id": "results-after-rebuild",
    }
    gates = iter([rejected, accepted_results])
    events: list[tuple[str, dict]] = []

    async def prepare(node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def revise(**kwargs) -> str:
        assert kwargs["node"].id == "results"
        (simulated / "run_level_results.csv").write_text(
            "method,seed,score\nproposed,1,0.91\n",
            encoding="utf-8",
        )
        manifest.write_text(
            '{"schema": 6, "data_files": '
            '[{"path": "experiments/results/simulated/run_level_results.csv"}]}\n',
            encoding="utf-8",
        )
        return "simulated evidence package rebuilt"

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: next(gates),
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=audit,
        run=run,
        initial_result="audit pending",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts=options,
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=2,
    )

    assert gate["accepted"] is False
    assert gate["restart_required"] is True
    assert gate["restart_from_node"] == "narrative"
    assert gate["revision_owner_id"] == "results"
    assert results.artifact_baseline[
        "experiments/results/simulated"
    ]["kind"] == "directory"
    assert state.load()["phases"]["narrative"]["status"] == "pending"
    assert any(event == "research_loop_restarted" for event, _ in events)


@pytest.mark.asyncio
async def test_stale_paper_freeze_refreshes_consumer_without_replaying_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    definitions = engine._get_default_nodes()
    paper = next(node for node in definitions if node.id == "paper")
    run = WorkflowRun(
        id="stale-freeze-owner-revalidation",
        project_path=str(tmp_path),
        nodes=definitions,
        status="running",
        options={"run_experiment": False},
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [
            {"id": node.id, "name": node.name, "skill": node.skill}
            for node in definitions
        ],
        {"options": run.options},
    )
    for node in definitions:
        state.set_status(node.id, "done")
        state.accept(node.id, f"before-{node.id}", "deterministic:test")
    rejected = {
        "accepted": False,
        "reason": "staged paper is stale",
        "summary": "scientific inputs changed after paper freeze",
        "details": {
            "node_risk_audit": {
                "findings": [{
                    "id": "PAPER-FREEZE-STALE",
                    "severity": "blocker",
                    "message": (
                        "scientific inputs changed after paper freeze: "
                        "experiments/results/analysis.md"
                    ),
                    "owner_node": "results",
                    "target_files": ["experiments/results/analysis.md"],
                }]
            }
        },
    }
    revision_calls = 0
    paper_refreshed = False

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        nonlocal revision_calls, paper_refreshed
        revision_calls += 1
        assert kwargs["node"].id == "paper"
        paper_refreshed = True
        return "paper rebound to current scientific inputs"

    def acceptance(node, *_args, **_kwargs):
        if node.id == "paper" and paper_refreshed:
            return {
                "accepted": True,
                "verdict_id": "paper-current",
                "reviewer": "deterministic:test",
                "summary": "Paper is bound to current scientific inputs.",
                "details": {},
            }
        return rejected

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", noop)

    gate, _ = await engine._run_node_revision_loop(
        node=paper,
        run=run,
        initial_result="staged paper",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={"run_experiment": False},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert revision_calls == 1
    assert gate["accepted"] is True
    persisted = state.load()
    assert persisted["phases"]["results"]["status"] == "accepted"
    assert persisted["phases"]["narrative"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_downstream_builder_is_deferred_until_upstream_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="deferred-figure-builder",
        project_path=str(tmp_path),
        options={"run_experiment": False},
    )
    node = WorkflowNode(id="figure", name="Figure", skill="/paper-figure")
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        "server.services.generated_source_repair.generated_source_repair_service.repair_python_sources",
        lambda *_args, **_kwargs: {"repaired": [], "unresolved": [], "report_path": ""},
    )
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.protected_upstream_findings",
        lambda *_args, **_kwargs: [{
            "severity": "blocker",
            "upstream_node": "exp-design",
            "plain_message": "实验代码无法解析。",
        }],
    )

    async def must_not_generate(*_args, **_kwargs) -> None:
        raise AssertionError("figure generation must wait for upstream repair")

    async def capture(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_ensure_figure_artifacts", must_not_generate)
    monkeypatch.setattr(engine, "_emit", capture)

    result = await engine._prepare_node_for_gate(
        node,
        run,
        "unchanged",
        "test direction",
        "draft",
        run.options,
    )

    assert result == "unchanged"
    assert events == [(
        "node_preparation_deferred",
        {
            "node_id": "figure",
            "owner_node_ids": ["exp-design"],
            "issues": ["实验代码无法解析。"],
        },
    )]


@pytest.mark.asyncio
async def test_deterministic_upstream_repair_refreshes_persisted_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiments" / "src" / "train.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        '"""Short title.\n"""Detailed module documentation.\n"""\n\ndef train():\n    return 1\n',
        encoding="utf-8",
    )
    design = WorkflowNode(id="exp-design", name="Design", skill="/experiment-plan")
    figure = WorkflowNode(id="figure", name="Figure", skill="/paper-figure")
    run = WorkflowRun(
        id="repair-revalidation",
        project_path=str(tmp_path),
        nodes=[design, figure],
        options={"run_experiment": False},
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [
            {"id": "exp-design", "name": "Design", "skill": "/experiment-plan"},
            {"id": "figure", "name": "Figure", "skill": "/paper-figure"},
        ],
        {"options": run.options},
    )
    state.set_status("exp-design", "done")
    state.accept("exp-design", "old-verdict", "deterministic:old")
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        engine := WorkflowEngine(),
        "_acceptance_gate",
        lambda *_args, **_kwargs: {
            "accepted": True,
            "verdict_id": "repaired-verdict",
            "reviewer": "deterministic:repair-test",
            "summary": "Repaired source passed the experiment-design gate.",
        },
    )
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.protected_upstream_findings",
        lambda *_args, **_kwargs: [],
    )

    async def no_figures(*_args, **_kwargs) -> None:
        return None

    async def capture(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_ensure_figure_artifacts", no_figures)
    monkeypatch.setattr(engine, "_emit", capture)

    await engine._prepare_node_for_gate(
        figure,
        run,
        "existing",
        "test direction",
        "draft",
        run.options,
    )

    persisted = state.load()["phases"]["exp-design"]
    assert persisted["status"] == "accepted"
    assert persisted["verdict_id"] == "repaired-verdict"
    assert persisted["details"]["source_repair_revalidated"] is True
    assert any(event == "upstream_owner_revalidated" for event, _ in events)


@pytest.mark.asyncio
async def test_review_node_uses_bounded_cross_model_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_root = tmp_path / "paper"
    paper_root.mkdir(parents=True)
    (paper_root / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}Draft\\end{document}",
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="review-coordinator",
        project_path=str(tmp_path),
        options={
            "review_internal_rounds": 99,
            "review_difficulty": "nightmare",
            "run_experiment": False,
        },
    )
    captured: dict = {}
    transport_options: dict = {}
    from server.workflows.review_audit import review_source_bundle
    reviewed_source_hash, _ = review_source_bundle(tmp_path)

    class FakeState:
        run_id = "review-coordinator"
        final_score = 6.0
        final_verdict = "almost"
        rounds = [object()]
        is_complete = True
        reviewer_model = "reviewer-model"
        executor_model = "executor-model"
        source_bundle_sha256 = reviewed_source_hash

    async def fake_transport_retry(**kwargs):
        transport_options.update(kwargs["opts"])
        return await kwargs["operation"]()

    async def fake_loop(**kwargs):
        captured.update(kwargs)

        async def completed_operation() -> str:
            return "reviewed"

        assert await kwargs["transport_retry"](
            "round-1-review",
            completed_operation,
        ) == "reviewed"
        return FakeState()

    monkeypatch.setattr(
        engine,
        "_execute_with_model_transport_retry",
        fake_transport_retry,
    )
    monkeypatch.setattr(
        "server.services.skill_orchestrator.skill_orchestrator.full_policy",
        lambda _skill_name: "bounded review policy",
    )
    monkeypatch.setattr(
        "server.workflows.review_audit.cross_model_reviewer.run_review_loop",
        fake_loop,
    )

    result = await engine._execute_review_node(
        WorkflowNode(id="review", name="Review", skill="/auto-review-loop"),
        run,
        "draft",
        run.options,
    )
    payload = json.loads(result)

    assert captured["max_rounds"] == 4
    assert captured["difficulty"] == "nightmare"
    assert captured["run_id"] == "review-coordinator"
    assert captured["evidence_mode"] == "design_only"
    assert payload["managed_by"] == "cross_model_review_loop"
    assert payload["rounds"] == 1
    assert transport_options["model_transport_max_attempts"] == 2
    from server.workflows.review_audit import REVIEW_MODEL_CALL_TIMEOUT_SECONDS

    assert transport_options["model_transport_retry_window_seconds"] == max(
        900.0,
        REVIEW_MODEL_CALL_TIMEOUT_SECONDS + 300.0,
    )
    persisted = json.loads(
        (tmp_path / "review-stage" / "REVIEW_STATE.json").read_text(
            encoding="utf-8"
        )
    )
    from server.workflows.review_audit import review_source_bundle

    expected_hash, _ = review_source_bundle(tmp_path)
    assert persisted["source_bundle_sha256"] == expected_hash
    assert "paper/main.tex" in persisted["sources"]


@pytest.mark.asyncio
async def test_managed_review_does_not_start_an_outer_revision_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="managed-review-stop",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [node])
    revised = False

    async def prepare(*_args, **_kwargs) -> str:
        return "review output"

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def should_not_revise(**_kwargs):
        nonlocal revised
        revised = True
        raise AssertionError("the outer workflow must not add another review loop")

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_emit", noop)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: {
            "accepted": False,
            "reason": "review gate did not reach score>=6 with verdict ready/almost",
            "summary": "score=5, verdict=needs_work",
            "details": {"managed_review": True, "issues": ["unresolved review action"]},
        },
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", should_not_revise)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="review output",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert gate["waiting"] is True
    assert revised is False


@pytest.mark.asyncio
async def test_empty_managed_review_state_after_transport_is_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="empty-managed-review-retry",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [node])
    gate_calls = 0
    revision_calls = 0

    async def prepare(*_args, **_kwargs) -> str:
        return "review output"

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**_kwargs) -> str:
        nonlocal revision_calls
        revision_calls += 1
        if revision_calls == 1:
            raise TimeoutError("review provider temporarily unavailable")
        return "fresh structured review"

    def acceptance(*_args, **_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls < 3:
            return {
                "accepted": False,
                "reason": "structured review state is missing or has no rounds",
                "summary": "review state has no structured review rounds",
                "details": {
                    "managed_review": True,
                    "issues": [
                        "Persist at least one structured review round with weaknesses and action items."
                    ],
                    "findings": [{
                        "id": "REVIEW-STATE-002",
                        "severity": "blocker",
                        "owner_node": "review",
                        "message": "Review state has no structured review rounds.",
                        "target_files": ["review-stage/REVIEW_STATE.json"],
                    }],
                },
            }
        return {
            "accepted": True,
            "verdict_id": "review:after-transport",
            "reviewer": "cross-model:reviewer",
            "summary": "fresh review accepted",
            "details": {},
        }

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_emit", noop)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="empty review state",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert gate["accepted"] is True
    assert revision_calls == 2


def test_pdf_layout_findings_ignore_stale_or_unreviewed_snapshots(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="table")

    stale = dict(state)
    stale["source_bundle_sha256"] = "stale-source"
    assert WorkflowEngine._review_layout_revision_findings(
        str(tmp_path), stale
    ) == []

    unreviewed = dict(state)
    unreviewed["rounds"] = []
    assert WorkflowEngine._review_layout_revision_findings(
        str(tmp_path), unreviewed
    ) == []
