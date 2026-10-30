from __future__ import annotations

from server.tests._workflow_checkpoints_support import (
    AgentEngine as AgentEngine,
    NodeStatus as NodeStatus,
    Path as Path,
    RunState as RunState,
    SessionState as SessionState,
    SimpleNamespace as SimpleNamespace,
    WORKFLOW_PHASE_IDS as WORKFLOW_PHASE_IDS,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _write_dependency_skipped_run as _write_dependency_skipped_run,
    asyncio as asyncio,
    get_session_state as get_session_state,
    json as json,
    pytest as pytest,
    skill_orchestrator as skill_orchestrator,
)


def test_bounded_synthetic_review_requires_native_visual_evidence(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({
            "managed_by": "cross_model_review_loop",
            "current_round": 3,
            "max_rounds": 3,
            "final_score": 4.0,
            "final_verdict": "needs_work",
            "is_complete": False,
            "evidence_mode": "synthetic_preview",
            "publication_ready": False,
            "rounds": [
                {
                    "round": number,
                    "score": 4.0,
                    "verdict": "needs_work",
                    "weaknesses": ["Evidence remains pending."],
                    "action_items": ["Keep the limitation visible."],
                }
                for number in range(1, 4)
            ],
        }),
        encoding="utf-8",
    )
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Preview\\end{document}",
        encoding="utf-8",
    )

    gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert gate["reason"] == (
        "managed review lacks current native PDF visual evidence"
    )
    assert gate["details"]["score"] == 4.0
    assert gate["details"]["threshold_met"] is False
    assert gate["details"]["bounded_complete"] is True
    assert gate["details"]["publication_ready"] is False
    assert gate["details"]["visual_evidence"]["required"] is True
    assert gate["details"]["visual_evidence"]["verified"] is False
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["final_score"] == 4.0
    assert persisted["final_verdict"] == "needs_work"
    assert persisted["bounded_complete"] is True
    assert persisted["is_complete"] is True


def test_bounded_empirical_review_still_blocks_below_threshold(tmp_path: Path) -> None:
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({
            "managed_by": "cross_model_review_loop",
            "current_round": 2,
            "max_rounds": 2,
            "final_score": 5.0,
            "final_verdict": "needs_work",
            "evidence_mode": "executed",
            "rounds": [
                {
                    "round": number,
                    "score": 5.0,
                    "verdict": "needs_work",
                    "weaknesses": ["Empirical claim remains unsupported."],
                    "action_items": ["Resolve the evidence conflict."],
                }
                for number in range(1, 3)
            ],
        }),
        encoding="utf-8",
    )
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Paper\\end{document}",
        encoding="utf-8",
    )

    gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert gate["details"]["bounded_complete"] is True
    assert gate["details"]["threshold_met"] is False


def test_review_revalidation_does_not_treat_resume_time_as_review_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="review",
        name="Review",
        skill="/auto-review-loop",
        started_at=9999999999.0,
    )
    run = WorkflowRun(
        id="review-revalidate",
        project_path=str(tmp_path),
        nodes=[node],
        options={"run_experiment": False},
    )
    captured: list[float | None] = []

    monkeypatch.setattr(engine, "_gate_requirements_for_node", lambda *_args: [])
    monkeypatch.setattr(
        engine,
        "_artifact_check",
        lambda *_args, **_kwargs: (True, []),
    )

    def fake_review_gate(
        _project_path: str,
        review_started_at: float | None = None,
    ) -> dict:
        captured.append(review_started_at)
        return {
            "accepted": True,
            "verdict_id": "review:revalidated",
            "reviewer": "cross-model:reviewer",
            "details": {},
        }

    monkeypatch.setattr(engine, "_review_acceptance_gate", fake_review_gate)

    engine._acceptance_gate(
        node,
        run,
        "draft",
        "persisted review summary",
        require_fresh=False,
    )

    assert captured == [None]


def test_stream_chunk_normalization_handles_cumulative_and_duplicate_proxies() -> None:
    existing = "The final review score is 6.5 and the verdict is almost."
    assert AgentEngine._dedupe_stream_text(existing, existing) == ""
    assert AgentEngine._dedupe_stream_text(existing, existing + " Continue.") == " Continue."
    assert AgentEngine._dedupe_stream_text(existing, "verdict is almost. Continue.") == " Continue."
    assert AgentEngine._dedupe_stream_text("ha", "ha") == "ha"


def test_failed_training_review_is_advisory_for_no_run_simulation() -> None:
    assessment = {"blocking": True, "verdict": "FAIL"}

    assert WorkflowEngine._training_check_blocks_current_mode(
        assessment,
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    ) is False
    assert WorkflowEngine._training_check_blocks_current_mode(
        assessment,
        {"run_experiment": True},
    ) is True


def test_execute_run_first_node_does_not_depend_on_node_local_run_experiment(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        engine = WorkflowEngine()
        node = WorkflowNode(id="lit", name="Literature", skill="/research-lit")
        run = WorkflowRun(id="first-node-scope", project_path=str(tmp_path), nodes=[node], status="running")
        engine._runs[run.id] = run

        original_sleep = asyncio.sleep

        async def immediate_sleep(_seconds: float) -> None:
            await original_sleep(0)

        async def fake_execute_node(*_args, **_kwargs) -> str:
            literature = tmp_path / "literature"
            literature.mkdir(parents=True, exist_ok=True)
            (literature / "survey.md").write_text("# Survey\nEvidence.\n", encoding="utf-8")
            (literature / "references.bib").write_text("@misc{test,title={Test}}\n", encoding="utf-8")
            plan = skill_orchestrator.select(
                "lit", "/research-lit", str(tmp_path), {}
            )
            skill_orchestrator.record(str(tmp_path), run.id, plan)
            skill_orchestrator.mark_execution(
                str(tmp_path), run.id, "lit", plan.primary, "completed",
                role="primary", session_id="fake-model-session",
                policy_loaded=True, execution_kind="model_owned",
            )
            return "completed"

        monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
        monkeypatch.setattr(engine, "_execute_node", fake_execute_node)
        monkeypatch.setattr(
            engine,
            "_acceptance_gate",
            lambda *_args, **_kwargs: {
                "accepted": True,
                "verdict_id": "test-scope",
                "reviewer": "test",
            },
        )
        await engine._execute_run(
            run,
            "test direction",
            "lite",
            "draft",
            {"run_experiment": True, "code_review": False, "research_quality_mode": "off"},
        )
        assert node.status == NodeStatus.COMPLETED
        assert run.status == "completed"

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_single_node_run_revalidates_existing_unselected_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    paper = WorkflowNode(
        id="paper",
        name="Paper",
        skill="/paper-write",
        depends_on=["figure"],
    )
    run = WorkflowRun(
        id="paper-subset",
        project_path=str(tmp_path),
        nodes=[paper],
        status="running",
    )
    RunState(str(tmp_path), run.id).start(
        [{"id": paper.id, "name": paper.name, "skill": paper.skill}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "draft",
            "options": {"run_experiment": False},
        },
    )
    events: list[tuple[str, dict]] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    async def staged_paper(**_kwargs) -> str:
        return json.dumps({"status": "completed"})

    async def revision_loop(*, initial_result, **_kwargs):
        RunState(str(tmp_path), run.id).set_status("paper", "done")
        return {
            "accepted": True,
            "verdict_id": "paper:accepted",
            "reviewer": "deterministic:test",
            "details": {},
        }, initial_result

    async def planned_templates(*_args, **_kwargs) -> None:
        return None

    def dependency_gate(node, *_args, **_kwargs):
        assert node.id == "figure"
        return {
            "accepted": True,
            "verdict_id": "figure:existing",
            "reviewer": "deterministic:figure",
            "summary": "Existing figure artifacts passed validation.",
            "details": {},
        }

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(engine, "_acceptance_gate", dependency_gate)
    monkeypatch.setattr(engine, "_execute_staged_paper", staged_paper)
    monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
    monkeypatch.setattr(engine, "_ensure_planned_result_templates", planned_templates)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.audit_workflow",
        lambda *_args, **_kwargs: {"status": "clear", "counts": {}, "findings": []},
    )

    await engine._execute_run(
        run,
        "test",
        "balanced",
        "draft",
        {"run_experiment": False, "code_review": False, "research_quality_mode": "off"},
    )

    assert paper.status == NodeStatus.COMPLETED
    assert run.status == "completed"
    assert any(
        event == "node_dependency_reused" and payload["dependency_id"] == "figure"
        for event, payload in events
    )


def test_dependency_skips_are_resumable_despite_legacy_completed_status(tmp_path: Path, monkeypatch) -> None:
    run_state = _write_dependency_skipped_run(tmp_path)
    expected = WORKFLOW_PHASE_IDS[1:]

    assert run_state.resume_point(WORKFLOW_PHASE_IDS) == "idea"
    assert run_state.resumable_phase_ids() == expected
    assert run_state.complete() is False
    assert run_state.load()["status"] == "incomplete"

    engine = WorkflowEngine()
    snapshot = engine.get_resumable_run_snapshot(str(tmp_path), run_state.run_id)
    assert snapshot is not None
    assert snapshot["current_node"] == "idea"
    assert list(snapshot["nodes_status"]) == WORKFLOW_PHASE_IDS

    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["pipeline_options"]["resume_run_id"]

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed_id = asyncio.run(engine.resume_persisted_run(run_state.run_id, str(tmp_path)))

    assert resumed_id == run_state.run_id
    assert captured["node_ids"] == expected
    assert captured["node_ids"][-1] == "ppt"


def test_resume_reopens_unaccepted_done_downstream_phases() -> None:
    engine = WorkflowEngine()
    state = {
        "phases": {
            "results": {"status": "pending"},
            "narrative": {"status": "done", "verdict_id": ""},
            "figure": {"status": "done", "details": {}},
            "paper": {"status": "done", "verdict_id": ""},
            "review": {"status": "completed", "verdict_id": "review:v1"},
        }
    }

    assert engine._resumable_phase_ids(state) == [
        "results",
        "narrative",
        "figure",
        "paper",
        "review",
    ]


def test_session_endpoint_finds_incomplete_phases_without_session_file(tmp_path: Path) -> None:
    run_state = _write_dependency_skipped_run(tmp_path, "session-fallback")
    assert SessionState(str(tmp_path)).load() is None

    snapshot = asyncio.run(get_session_state(str(tmp_path)))

    assert snapshot["resumable"] is True
    assert snapshot["run_id"] == run_state.run_id
    assert snapshot["recorded_status"] == "completed"
    assert snapshot["current_node"] == "idea"


def test_persisted_run_listing_ignores_run_scoped_json_sidecars(tmp_path: Path) -> None:
    run_state = _write_dependency_skipped_run(tmp_path, "canonical-run")
    runs_dir = tmp_path / ".merak" / "runs"
    sidecar = {
        "run_id": run_state.run_id,
        "status": "unknown",
        "phases": {},
    }
    for suffix in ("skills", "search-evidence", "specialists"):
        (runs_dir / f"{run_state.run_id}.{suffix}.json").write_text(
            json.dumps(sidecar),
            encoding="utf-8",
        )

    runs = WorkflowEngine().list_persisted_runs(str(tmp_path))

    assert [item["run_id"] for item in runs] == [run_state.run_id]
    assert runs[0]["resumable"] is True


def test_resumable_snapshot_ignores_newer_run_scoped_json_sidecar(tmp_path: Path) -> None:
    run_state = _write_dependency_skipped_run(tmp_path, "snapshot-canonical")
    sidecar_path = (
        tmp_path
        / ".merak"
        / "runs"
        / f"{run_state.run_id}.search-evidence.json"
    )
    sidecar_path.write_text(
        json.dumps({
            "run_id": run_state.run_id,
            "status": "running",
            "phases": {
                "fake": {
                    "id": "fake",
                    "name": "Fake sidecar phase",
                    "status": "failed",
                },
            },
        }),
        encoding="utf-8",
    )

    snapshot = WorkflowEngine().get_resumable_run_snapshot(str(tmp_path))

    assert snapshot is not None
    assert snapshot["run_id"] == run_state.run_id
    assert snapshot["current_node"] == "idea"
    assert "fake" not in snapshot["nodes_status"]


def test_cached_phase_cannot_complete_run_with_dependency_skips(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        run_state = _write_dependency_skipped_run(tmp_path, "cached-lit")
        engine = WorkflowEngine()
        lit = WorkflowNode(
            id="lit",
            name="Literature",
            skill="/research-lit",
            status=NodeStatus.COMPLETED,
        )
        run = WorkflowRun(id=run_state.run_id, project_path=str(tmp_path), nodes=[lit], status="running")
        events: list[tuple[str, dict]] = []

        async def on_event(event_type: str, payload: dict) -> None:
            events.append((event_type, payload))

        async def immediate_sleep(_seconds: float) -> None:
            return None

        run.on_event = on_event
        engine._runs[run.id] = run
        monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)

        await engine._execute_run(run, "EEG foundation models", opts={"code_review": False})

        assert run.status == "incomplete"
        assert run_state.load()["status"] == "incomplete"
        session = SessionState(str(tmp_path)).load()
        assert session is not None
        assert session["current_node"] == "idea"
        assert list(session["nodes_status"]) == WORKFLOW_PHASE_IDS
        assert any(event_type == "workflow_incomplete" for event_type, _ in events)
        assert not any(event_type == "workflow_completed" for event_type, _ in events)

    asyncio.run(scenario())


def test_reset_for_reexecution_clears_revision_without_losing_audit_trail(
    tmp_path: Path,
) -> None:
    node = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run_state = RunState(str(tmp_path), "review-reexecution")
    run_state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"options": {}},
    )
    run_state.set_status("review", "done", artifact=str(tmp_path / "review.json"))
    run_state.record_revision_gate(
        "review",
        round_number=2,
        cycle=3,
        gate={"accepted": False, "reason": "stale generated verdict"},
    )

    run_state.reset_for_reexecution(
        "review",
        reason="review source bundle changed after platform repair",
    )

    phase = run_state.load()["phases"]["review"]
    assert phase["status"] == "pending"
    assert phase["error"] == ""
    assert "revision" not in phase["details"]
    assert phase["details"]["reexecution_resets"][-1] == {
        "previous_status": "done",
        "previous_revision_round": 2,
        "previous_revision_cycle": 3,
        "reason": "review source bundle changed after platform repair",
        "timestamp": phase["details"]["reexecution_resets"][-1]["timestamp"],
    }


@pytest.mark.asyncio
async def test_model_transport_retries_are_independent_of_revision_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(
        id="transport-retry-success",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={
            "model_transport_max_attempts": 4,
            "model_transport_retry_window_seconds": 60,
        },
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"direction": "test", "options": run.options},
    )
    events: list[tuple[str, dict]] = []
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("OpenAI API error 502: upstream unavailable")
        return "completed"

    async def no_sleep(**_kwargs) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_sleep_with_transport_heartbeat", no_sleep)
    monkeypatch.setattr(engine, "_emit", emit)

    result = await engine._execute_with_model_transport_retry(
        run=run,
        node_id=node.id,
        operation_name="paper/blueprint",
        stage_id="blueprint",
        operation=operation,
        opts=run.options,
    )

    assert result == "completed"
    assert attempts == 3
    assert [event for event, _ in events].count("node_transport_retry") == 2
    assert [event for event, _ in events].count("node_transport_recovered") == 1
    persisted = state.load()
    revision = persisted["phases"]["paper"].get("details", {}).get("revision", {})
    assert int(revision.get("round") or 0) == 0


@pytest.mark.asyncio
async def test_model_transport_honors_page_level_max_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not expand the UI retry budget to a hidden eight-session loop."""
    engine = WorkflowEngine()
    node = WorkflowNode(id="exp-design", name="Design", skill="/experiment-plan")
    run = WorkflowRun(
        id="transport-page-budget",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={
            "max_retries": 2,
            "model_transport_retry_window_seconds": 60,
        },
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"direction": "test", "options": run.options},
    )
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("OpenAI API error 502: upstream unavailable")

    async def no_sleep(**_kwargs) -> None:
        return None

    async def emit(_run, _event: str, _payload: dict) -> None:
        return None

    monkeypatch.setattr(engine, "_sleep_with_transport_heartbeat", no_sleep)
    monkeypatch.setattr(engine, "_emit", emit)

    with pytest.raises(RuntimeError, match="configured maximum 2"):
        await engine._execute_with_model_transport_retry(
            run=run,
            node_id=node.id,
            operation_name="node/exp-design",
            stage_id=node.id,
            operation=operation,
            opts=run.options,
        )

    assert attempts == 2
    retry = state.load()["phases"][node.id]["details"]["transport_retry"]
    assert retry["max_attempts"] == 2
    assert retry["exhausted"] is True


@pytest.mark.asyncio
async def test_transport_retry_preserves_accepted_owner_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(
        id="transport-retry-accepted-owner",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={"model_transport_max_attempts": 1},
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"direction": "test", "options": run.options},
    )
    state.set_status(node.id, "running")
    state.set_status(node.id, "done")
    state.accept(node.id, "paper-accepted", "deterministic:test")
    assert state.complete({
        "execution_completed": True,
        "submission_ready": True,
        "completion_class": "test-complete",
    }) is True
    before_state = state.load()
    before_phase = before_state["phases"][node.id]
    lifecycle_keys = (
        "status",
        "verdict_id",
        "reviewer",
        "accepted_at",
        "started_at",
        "finished_at",
    )
    before_lifecycle = {
        key: before_phase.get(key)
        for key in lifecycle_keys
    }
    run_lifecycle_keys = (
        "status",
        "finished_at",
        "completion",
        "execution_completed",
        "submission_ready",
        "completion_class",
    )
    before_run_lifecycle = {
        key: before_state.get(key)
        for key in run_lifecycle_keys
    }

    async def operation() -> str:
        raise RuntimeError("502 Bad Gateway")

    async def emit(_run, _event: str, _payload: dict) -> None:
        return None

    monkeypatch.setattr(engine, "_emit", emit)
    with pytest.raises(RuntimeError, match="Model transport exhausted"):
        await engine._execute_with_model_transport_retry(
            run=run,
            node_id=node.id,
            operation_name="review/paper-repair",
            stage_id="paper-repair",
            operation=operation,
            opts=run.options,
        )

    after_state = state.load()
    after_phase = after_state["phases"][node.id]
    assert {
        key: after_phase.get(key)
        for key in lifecycle_keys
    } == before_lifecycle
    assert {
        key: after_state.get(key)
        for key in run_lifecycle_keys
    } == before_run_lifecycle
    retry = after_phase["details"]["transport_retry"]
    assert retry["operation"] == "review/paper-repair"
    assert retry["exhausted"] is True


@pytest.mark.asyncio
async def test_transport_exhaustion_persists_platform_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(
        id="transport-retry-exhausted",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={
            "model_transport_max_attempts": 2,
            "model_transport_retry_window_seconds": 60,
        },
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"direction": "test", "options": run.options},
    )
    events: list[tuple[str, dict]] = []

    async def operation() -> str:
        raise RuntimeError("502 Bad Gateway")

    async def no_sleep(**_kwargs) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_sleep_with_transport_heartbeat", no_sleep)
    monkeypatch.setattr(engine, "_emit", emit)

    with pytest.raises(RuntimeError, match="Model transport exhausted") as captured:
        await engine._execute_with_model_transport_retry(
            run=run,
            node_id=node.id,
            operation_name="paper/blueprint",
            stage_id="blueprint",
            operation=operation,
            opts=run.options,
        )

    await engine._persist_model_transport_checkpoint(
        node=node,
        run=run,
        error=captured.value,
        opts=run.options,
        max_revision_rounds=6,
    )

    phase = state.load()["phases"]["paper"]
    revision = phase["details"]["revision"]
    assert phase["status"] == "awaiting_revision"
    assert revision["transport_exhausted"] is True
    assert revision["intervention_kind"] == "platform_repair"
    assert revision["requires_human_decision"] is False
    assert int(revision.get("round") or 0) == 0
    assert revision["transport_retry_count"] == 1
    assert revision["retry_delay_seconds"] == 60.0
    assert revision["next_retry_at"] > revision["waiting_since"]
    assert revision["max_transport_checkpoint_retries"] == 4
    assert "node_transport_exhausted" in [event for event, _ in events]
    assert "node_revision_waiting" in [event for event, _ in events]


@pytest.mark.asyncio
async def test_transport_window_does_not_charge_model_execution_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="transport-window-expired",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={
            "model_transport_max_attempts": 2,
            "model_transport_retry_window_seconds": 300,
        },
    )
    RunState(str(tmp_path), run.id).start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"options": run.options},
    )
    attempts = 0
    events: list[tuple[str, dict]] = []
    monotonic_values = iter([0.0, 301.0, 302.0, 303.0])

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise asyncio.TimeoutError("native reviewer exceeded 900s")
        return "recovered"

    async def no_sleep(**_kwargs) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(
        "server.workflows.engine.time",
        SimpleNamespace(
            monotonic=lambda: next(monotonic_values),
            time=lambda: 123.0,
        ),
    )
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(engine, "_sleep_with_transport_heartbeat", no_sleep)

    result = await engine._execute_with_model_transport_retry(
        run=run,
        node_id=node.id,
        operation_name="review/round-1-review",
        stage_id="round-1-review",
        operation=operation,
        opts=run.options,
    )

    assert result == "recovered"
    assert attempts == 2
    retries = [payload for event, payload in events if event == "node_transport_retry"]
    assert len(retries) == 1
    assert retries[0]["attempt"] == 1
    assert retries[0]["max_attempts"] == 2
    assert any(event == "node_transport_recovered" for event, _ in events)


@pytest.mark.asyncio
async def test_transport_backoff_emits_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="transport-heartbeat",
        project_path=str(tmp_path),
        status="running",
    )
    events: list[tuple[str, dict]] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(engine, "_emit", emit)

    await engine._sleep_with_transport_heartbeat(
        run=run,
        node_id="paper",
        operation_name="paper/method",
        stage_id="method",
        delay_seconds=61,
        attempt=4,
        max_attempts=8,
    )

    heartbeats = [payload for event, payload in events if event == "node_transport_heartbeat"]
    assert len(heartbeats) == 2
    assert all(item["stage_id"] == "method" for item in heartbeats)
