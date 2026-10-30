from __future__ import annotations

from server.tests._workflow_checkpoints_support import (
    NodeStatus as NodeStatus,
    Path as Path,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    asyncio as asyncio,
    json as json,
    pytest as pytest,
)


def test_revalidation_refreshes_runtime_sources_before_quality_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        engine = WorkflowEngine()
        node = WorkflowNode(id="novelty", name="Novelty", skill="/novelty-check")
        run = WorkflowRun(
            id="source-refresh-before-gate",
            project_path=str(tmp_path),
            nodes=[node],
            status="running",
        )
        state = RunState(str(tmp_path), run.id)
        options = {
            "research_strategy": {
                "literature_sources": ["arxiv", "semantic_scholar"],
            },
            "research_quality_mode": "off",
            "code_review": False,
        }
        state.start(
            [{"id": node.id, "name": node.name, "skill": node.skill}],
            {"direction": "test", "options": options},
        )
        state.set_status(node.id, "done", details={"summary": "existing report"})
        state.set_revision_waiting(
            node.id,
            round_number=3,
            cycle=1,
            gate={"reason": "source unavailable"},
            artifact_signature=engine._revision_artifact_signature(
                str(tmp_path),
                node.id,
            ),
        )
        order: list[str] = []
        events: list[str] = []

        async def no_sleep(_seconds: float) -> None:
            return None

        async def refresh(*_args, **_kwargs) -> str:
            order.append("refresh")
            return "arxiv retry result"

        async def revision_loop(*, initial_result, **_kwargs):
            order.append("gate")
            state.set_status(node.id, "done")
            return {
                "accepted": True,
                "verdict_id": "novelty:accepted",
                "reviewer": "deterministic:test",
                "details": {},
            }, initial_result

        async def emit(_run, event: str, _payload: dict) -> None:
            events.append(event)

        monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
        monkeypatch.setattr(engine, "_ensure_stage_search_evidence", refresh)
        monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
        monkeypatch.setattr(engine, "_emit", emit)
        monkeypatch.setattr(
            "server.services.node_risk_audit.node_risk_audit_service.audit_workflow",
            lambda *_args, **_kwargs: {"status": "clear", "counts": {}, "findings": []},
        )

        await engine._execute_run(
            run,
            "test",
            "balanced",
            "draft",
            options,
        )

        assert order == ["refresh", "gate"]
        assert "node_revalidation_inputs_refreshed" in events
        assert node.status == NodeStatus.COMPLETED

    asyncio.run(scenario())


def test_transport_revision_checkpoint_can_resume_without_an_artifact_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "transport-revision-resume"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "exp-design", "name": "Experiment design", "skill": "/experiment-plan"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "draft",
            "options": {},
        },
    )
    signature = engine._revision_artifact_signature(str(tmp_path), "exp-design")
    state.set_revision_waiting(
        "exp-design",
        round_number=0,
        cycle=1,
        gate={
            "reason": "revision execution interrupted",
            "summary": "TimeoutError: provider timed out",
            "issues": ["TimeoutError: provider timed out"],
            "error_type": "TimeoutError",
            "error_category": "transport",
            "retryable": True,
            "transport_exhausted": True,
            "intervention_kind": "platform_repair",
        },
        artifact_signature=signature,
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(
        engine.resume_persisted_run(run_id, str(tmp_path))
    )

    assert resumed == run_id
    assert captured["node_ids"] == ["exp-design"]


def test_platform_repair_checkpoint_can_resume_without_an_artifact_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "platform-repair-resume"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": {"run_experiment": False},
        },
    )
    signature = engine._revision_artifact_signature(str(tmp_path), "results")
    state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=1,
        gate={
            "reason": "required artifact missing, empty, or stale",
            "summary": "content is valid but deterministic output was unchanged",
            "issues": ["no canonical output changed by content"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature=signature,
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(engine.resume_persisted_run(run_id, str(tmp_path)))

    assert resumed == run_id
    assert captured["node_ids"] == ["results"]


def test_watchdog_resume_uses_bounded_auto_recovery_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "watchdog-platform-recovery"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": {
                "run_experiment": False,
                "max_research_loop_cycles": 3,
            },
        },
    )
    signature = engine._revision_artifact_signature(
        str(tmp_path),
        "results",
        {
            "run_experiment": False,
            "max_research_loop_cycles": 3,
        },
    )
    state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=1,
        gate={
            "reason": "required artifact remains stale",
            "summary": "deterministic platform reconciliation is required",
            "issues": ["no canonical output changed by content"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature=signature,
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(
        engine.resume_persisted_run(
            run_id,
            str(tmp_path),
            resume_source="watchdog",
        )
    )

    assert resumed == run_id
    assert captured["node_ids"] == ["results"]
    reopened = RunState(str(tmp_path), run_id).load()["phases"]["results"]
    revision = reopened["details"]["revision"]
    assert revision["platform_auto_recovery_count"] == 1
    assert len(revision["platform_auto_recoveries"]) == 1
    assert "platform_checkpoint_resumes" not in revision


def test_watchdog_resume_rejects_unchanged_terminal_platform_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "watchdog-terminal-unchanged"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": {"run_experiment": False},
        },
    )
    signature = engine._revision_artifact_signature(
        str(tmp_path),
        "results",
        {"run_experiment": False},
    )
    state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=4,
        gate={
            "reason": "unchanged targeted repair",
            "summary": "no progress after bounded repairs",
            "issues": ["no canonical output changed by content"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "stopped_for_no_progress": True,
        },
        artifact_signature=signature,
    )

    async def fake_execute(**_kwargs) -> str:
        pytest.fail("terminal watchdog resume must not execute the workflow")

    monkeypatch.setattr(engine, "execute", fake_execute)

    with pytest.raises(ValueError, match="terminal"):
        asyncio.run(
            engine.resume_persisted_run(
                run_id,
                str(tmp_path),
                resume_source="watchdog",
            )
        )

    revision = RunState(str(tmp_path), run_id).load()["phases"]["results"][
        "details"
    ]["revision"]
    assert "platform_checkpoint_resumes" not in revision
    assert "platform_auto_recoveries" not in revision


def test_legacy_nested_checkpoint_without_explicit_classification_cannot_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "legacy-platform-repair-resume"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": {"run_experiment": False},
        },
    )
    signature = engine._revision_artifact_signature(
        str(tmp_path),
        "results",
        {"run_experiment": False},
    )
    state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=1,
        gate={
            "reason": "required artifact missing, empty, or stale",
            "summary": "planned analysis needs deterministic reconciliation",
            "issues": ["no canonical output changed by content"],
        },
        artifact_signature=signature,
    )
    state_path = tmp_path / ".merak" / "runs" / f"{run_id}.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    revision = payload["phases"]["results"]["details"]["revision"]
    revision.pop("intervention_kind", None)
    revision.pop("requires_human_decision", None)
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    before_phase = RunState(str(tmp_path), run_id).load()["phases"]["results"]
    with pytest.raises(ValueError, match="没有变化"):
        asyncio.run(engine.resume_persisted_run(run_id, str(tmp_path)))
    assert captured == {}
    assert RunState(str(tmp_path), run_id).load()["phases"]["results"] == before_phase


def test_platform_resume_reopens_after_automatic_recovery_budget_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "exhausted-platform-repair-resume"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": {
                "run_experiment": False,
                "max_research_loop_cycles": 3,
            },
        },
    )
    signature = engine._revision_artifact_signature(str(tmp_path), "results")
    state.set_revision_waiting(
        "results",
        round_number=6,
        cycle=4,
        gate={
            "reason": "node-specific research risk audit failed",
            "summary": "planned analysis needs platform-owned reconciliation",
            "issues": [
                "Planned analysis uses empirical support language without "
                "executed evidence."
            ],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature=signature,
    )
    state_path = tmp_path / ".merak" / "runs" / f"{run_id}.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    revision = payload["phases"]["results"]["details"]["revision"]
    revision["platform_auto_recovery_count"] = 3
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(engine.resume_persisted_run(run_id, str(tmp_path)))

    assert resumed == run_id
    assert captured["node_ids"] == ["results"]
    reopened = RunState(str(tmp_path), run_id).load()["phases"]["results"]
    revision = reopened["details"]["revision"]
    assert reopened["status"] == "done"
    assert revision["round"] == 0
    assert revision["cycle"] == 5
    assert revision["platform_auto_recovery_count"] == 3


def test_explicit_platform_resume_clears_previous_terminal_stop_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "managed-review-platform-resume"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "review", "name": "Review", "skill": "/auto-review-loop"}],
        {"options": {"max_revision_rounds": 6}},
    )
    signature = engine._revision_artifact_signature(str(tmp_path), "review")
    state.set_revision_waiting(
        "review",
        round_number=1,
        cycle=3,
        gate={
            "reason": "cross-model review loop exhausted its bounded rounds",
            "issues": ["REVIEW_STATE source bundle is stale for the current paper"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "stopped_for_managed_stage": True,
        },
        artifact_signature=signature,
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(
        engine.resume_persisted_run(
            run_id,
            str(tmp_path),
            node_ids=["review"],
        )
    )

    assert resumed == run_id
    assert captured["node_ids"] == ["review"]
    reopened = RunState(str(tmp_path), run_id).load()["phases"]["review"]
    revision = reopened["details"]["revision"]
    assert reopened["status"] == "done"
    assert revision["round"] == 0
    assert revision["stopped_for_managed_stage"] is False
    assert revision["last_gate"]["stopped_for_managed_stage"] is False
    assert revision["consumer_refresh_required"] is True
    assert revision["consumer_refresh_owner_id"] == "review"


def test_legacy_nested_default_does_not_bypass_researcher_decision_guard(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    revision = {
        "last_gate": {
            "reason": "researcher decision required",
            "summary": "Change the hypothesis or select a different idea.",
            "issues": ["hypothesis scope choice"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
    }

    assert engine._is_platform_repair_revision_checkpoint(revision) is False


def test_platform_auto_recovery_uses_structured_checkpoint_classification() -> None:
    engine = WorkflowEngine()
    revision = {
        "intervention_kind": "platform_repair",
        "requires_human_decision": False,
        "last_gate": {
            "reason": "node-specific research risk audit failed",
            "summary": "Content quality passed but artifact repair did not close.",
            "issues": [
                "Planned analysis uses empirical support language without "
                "executed evidence."
            ],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
    }

    assert engine._platform_checkpoint_is_auto_recoverable(revision) is True


@pytest.mark.parametrize(
    "stop_flag",
    [
        "hard_limit",
        "stopped_for_no_progress",
        "stopped_for_deterministic_stage",
        "stopped_for_managed_stage",
    ],
)
def test_terminal_revision_stop_is_persisted_and_not_auto_recovered(
    tmp_path: Path,
    stop_flag: str,
) -> None:
    run_id = f"terminal-stop-{stop_flag}"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {"options": {"run_experiment": False}},
    )
    state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=1,
        gate={
            "reason": "bounded revision stopped",
            "issues": ["the same quality finding remains unresolved"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            stop_flag: True,
        },
    )

    revision = state.revision_state("results")
    assert revision[stop_flag] is True
    assert revision["last_gate"][stop_flag] is True
    assert WorkflowEngine._is_platform_repair_revision_checkpoint(revision) is True
    assert (
        WorkflowEngine._platform_checkpoint_is_auto_recoverable(revision)
        is False
    )


@pytest.mark.parametrize(
    "revision",
    [
        {
            "intervention_kind": "researcher_decision",
            "requires_human_decision": True,
            "last_gate": {
                "intervention_kind": "researcher_decision",
                "requires_human_decision": True,
            },
        },
        {
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "transport_exhausted": True,
            "error_category": "transport",
            "last_gate": {
                "intervention_kind": "platform_repair",
                "requires_human_decision": False,
                "error_category": "transport",
            },
        },
    ],
)
def test_platform_auto_recovery_excludes_decisions_and_transport(
    revision: dict,
) -> None:
    assert (
        WorkflowEngine._platform_checkpoint_is_auto_recoverable(revision)
        is False
    )


def test_platform_recovery_count_survives_backend_reload(tmp_path: Path) -> None:
    run_id = "durable-platform-recovery"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {"options": {"run_experiment": False}},
    )
    state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=1,
        gate={
            "reason": "artifact reconciliation incomplete",
            "issues": ["canonical artifact still needs platform repair"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature="artifact-before-recovery",
    )

    first = state.start_platform_recovery_cycle(
        "results",
        runtime_signature="runtime:first",
        reason="first platform recovery",
    )
    reloaded = RunState(str(tmp_path), run_id)
    reloaded.set_revision_waiting(
        "results",
        round_number=3,
        cycle=2,
        gate={
            "reason": "artifact reconciliation incomplete",
            "issues": ["canonical artifact still needs platform repair"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature="artifact-after-first-recovery",
    )
    second = reloaded.start_platform_recovery_cycle(
        "results",
        runtime_signature="runtime:second",
        reason="second platform recovery",
    )

    phase = RunState(str(tmp_path), run_id).load()["phases"]["results"]
    revision = phase["details"]["revision"]
    assert (first, second) == (1, 2)
    assert phase["status"] == "done"
    assert revision["platform_auto_recovery_count"] == 2
    assert [item["count"] for item in revision["platform_auto_recoveries"]] == [
        1,
        2,
    ]


@pytest.mark.asyncio
async def test_platform_checkpoint_auto_recovers_without_workflow_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-generation")
    run = WorkflowRun(
        id="platform-auto-recovery-success",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    engine._runs[run.id] = run
    state = RunState(str(tmp_path), run.id)
    options = {
        "auto_proceed": True,
        "platform_auto_recovery": True,
        "max_research_loop_cycles": 2,
        "code_review": False,
        "research_quality_mode": "off",
    }
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"direction": "test", "options": options},
    )
    gate_attempts = 0
    events: list[str] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def execute_node(*_args, **_kwargs) -> str:
        return "generated idea"

    async def specialists(**_kwargs) -> dict:
        return {"accepted": True, "applicable": False, "issues": []}

    async def revision_loop(**kwargs):
        nonlocal gate_attempts
        gate_attempts += 1
        if gate_attempts == 1:
            state.set_revision_waiting(
                node.id,
                round_number=3,
                cycle=1,
                gate={
                    "reason": "node-specific research risk audit failed",
                    "summary": "Platform-owned artifact reconciliation is pending.",
                    "issues": ["validator wording changed"],
                    "intervention_kind": "platform_repair",
                    "requires_human_decision": False,
                },
                artifact_signature="unchanged-artifact",
            )
            return {"accepted": False, "waiting": True}, kwargs["initial_result"]
        state.set_status(node.id, "done")
        return {
            "accepted": True,
            "verdict_id": "idea:accepted-after-platform-recovery",
            "reviewer": "deterministic:test",
            "summary": "accepted",
            "details": {},
        }, kwargs["initial_result"]

    async def emit(_run, event: str, _payload: dict) -> None:
        events.append(event)

    async def notification(**_kwargs) -> dict:
        return {"sent": False, "channels": []}

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(engine, "_execute_node", execute_node)
    monkeypatch.setattr(engine, "_execute_profile_specialists", specialists)
    monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.audit_workflow",
        lambda *_args, **_kwargs: {
            "status": "clear",
            "counts": {},
            "findings": [],
        },
    )
    monkeypatch.setattr(
        "server.services.workflow_readiness.workflow_readiness_service.assess",
        lambda *_args, **_kwargs: {
            "completion_class": "design_package_ready",
            "submission_ready": False,
        },
    )
    monkeypatch.setattr(
        "server.services.notification.notification_service.workflow_completed",
        notification,
    )

    await engine._execute_run(
        run,
        "test",
        "balanced",
        "draft",
        options,
    )

    persisted = state.load()
    revision = persisted["phases"][node.id]["details"]["revision"]
    assert gate_attempts == 2
    assert run.status == "completed"
    assert persisted["phases"][node.id]["status"] == "accepted"
    assert revision["platform_auto_recovery_count"] == 1
    assert events.count("node_platform_auto_recovery_started") == 1
    assert "workflow_incomplete" not in events


@pytest.mark.asyncio
async def test_platform_auto_recovery_stops_once_at_persisted_cycle_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-generation")
    run = WorkflowRun(
        id="platform-auto-recovery-bounded",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    engine._runs[run.id] = run
    state = RunState(str(tmp_path), run.id)
    options = {
        "auto_proceed": True,
        "platform_auto_recovery": True,
        "max_research_loop_cycles": 2,
        "code_review": False,
        "research_quality_mode": "off",
    }
    state.start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"direction": "test", "options": options},
    )
    gate_attempts = 0
    events: list[str] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def execute_node(*_args, **_kwargs) -> str:
        return "generated idea"

    async def specialists(**_kwargs) -> dict:
        return {"accepted": True, "applicable": False, "issues": []}

    async def revision_loop(**kwargs):
        nonlocal gate_attempts
        gate_attempts += 1
        revision = state.revision_state(node.id)
        cycle = max(1, int(revision.get("cycle") or 1))
        state.set_revision_waiting(
            node.id,
            round_number=3,
            cycle=cycle,
            gate={
                "reason": "artifact reconciliation incomplete",
                "summary": "The platform repair still has not closed.",
                "issues": ["canonical output remains invalid"],
                "intervention_kind": "platform_repair",
                "requires_human_decision": False,
            },
            artifact_signature=f"artifact-cycle-{cycle}",
        )
        return {"accepted": False, "waiting": True}, kwargs["initial_result"]

    async def emit(_run, event: str, _payload: dict) -> None:
        events.append(event)

    async def notification(**_kwargs) -> dict:
        return {"sent": False, "channels": []}

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(engine, "_execute_node", execute_node)
    monkeypatch.setattr(engine, "_execute_profile_specialists", specialists)
    monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.notification.notification_service.workflow_failed",
        notification,
    )

    await engine._execute_run(
        run,
        "test",
        "balanced",
        "draft",
        options,
    )

    persisted = state.load()
    revision = persisted["phases"][node.id]["details"]["revision"]
    assert gate_attempts == 3
    assert run.status == "incomplete"
    assert revision["platform_auto_recovery_count"] == 2
    assert events.count("node_platform_auto_recovery_started") == 2
    assert events.count("workflow_incomplete") == 1
