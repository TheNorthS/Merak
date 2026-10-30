from __future__ import annotations

from server.tests._workflow_checkpoints_support import (
    AUTONOMOUS_REVISION_ROUNDS as AUTONOMOUS_REVISION_ROUNDS,
    HTTPException as HTTPException,
    NodeStatus as NodeStatus,
    Path as Path,
    READINESS_SCHEMA_VERSION as READINESS_SCHEMA_VERSION,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowResumeRequest as WorkflowResumeRequest,
    WorkflowRun as WorkflowRun,
    WorkflowRunRequest as WorkflowRunRequest,
    asyncio as asyncio,
    normalize_revision_rounds as normalize_revision_rounds,
    normalize_workflow_illustration_mode as normalize_workflow_illustration_mode,
    pytest as pytest,
    resume_run as resume_run,
    run_workflow as run_workflow,
)


def test_checkpoint_defaults_leave_time_for_research_feedback() -> None:
    request = WorkflowRunRequest(node_ids=["paper"], project_path=".")
    assert request.checkpoint_timeout_seconds == 300
    assert request.max_revision_rounds == AUTONOMOUS_REVISION_ROUNDS
    assert request.human_checkpoint_nodes == ["exp-design", "exp-run", "paper"]
    assert request.non_experiment_evidence_mode == "design_only"
    assert request.illustration_mode == "auto"


def test_revision_budget_is_user_configurable_within_server_bounds() -> None:
    request = WorkflowRunRequest(
        node_ids=["paper"],
        project_path=".",
        max_revision_rounds=1,
    )

    assert request.max_revision_rounds == 1


def test_revision_budget_clamps_legacy_or_internal_values() -> None:
    assert normalize_revision_rounds(-5) == 1
    assert normalize_revision_rounds(8) == 8
    assert normalize_revision_rounds(99) == 12


def test_failed_phase_is_revalidated_before_replaying_primary_model() -> None:
    phase = {
        "status": "failed",
        "error": "ScannerError: malformed generated YAML",
        "details": {"summary": "primary model already wrote artifacts"},
    }

    assert WorkflowEngine._phase_requires_revalidation(phase) is True


def test_cancelled_attempt_normalized_to_pending_is_revalidated_first() -> None:
    phase = {
        "status": "pending",
        "error": "cancelled by operator",
        "details": {
            "execution_attempts": [
                {
                    "status": "failed",
                    "error": "ScannerError after primary artifacts were written",
                }
            ]
        },
    }

    assert WorkflowEngine._phase_requires_revalidation(phase) is True


def test_workflow_illustration_mode_accepts_only_current_selector() -> None:
    assert normalize_workflow_illustration_mode("auto") == "auto"
    for removed in ("codex-image2", "CODEX_IMAGE2", "gemini", "false"):
        with pytest.raises(ValueError, match="unsupported illustration_mode"):
            normalize_workflow_illustration_mode(removed)


@pytest.mark.asyncio
async def test_run_api_forwards_user_revision_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return "revision-budget-run"

    monkeypatch.setattr("server.api.workflow.workflow_engine.execute", fake_execute)
    response = await run_workflow(
        WorkflowRunRequest(
            node_ids=["lit"],
            project_path=str(tmp_path),
            max_revision_rounds=9,
        )
    )

    assert response["run_id"] == "revision-budget-run"
    assert captured["pipeline_options"]["max_revision_rounds"] == 9


@pytest.mark.asyncio
async def test_run_api_rejects_removed_image2_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    verified_integrations: list[str] = []

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return "illustration-mode-run"

    monkeypatch.setattr("server.api.workflow.workflow_engine.execute", fake_execute)
    monkeypatch.setattr(
        "server.api.settings.is_integration_verified",
        lambda name: verified_integrations.append(name) or False,
    )
    with pytest.raises(ValueError):
        WorkflowRunRequest(
            node_ids=["figure"],
            project_path=str(tmp_path),
            run_experiment=False,
            illustration_mode="codex-image2",
        )
    assert captured == {}
    assert verified_integrations == []


@pytest.mark.asyncio
async def test_run_api_rejects_removed_gemini_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def should_execute(**kwargs) -> str:
        captured.update(kwargs)
        return "automatic-figure-run"

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.execute",
        should_execute,
    )
    monkeypatch.setattr(
        "server.api.settings.is_integration_verified",
        lambda _name: False,
    )

    with pytest.raises(ValueError):
        WorkflowRunRequest(
            node_ids=["figure"], project_path=str(tmp_path),
            run_experiment=False, illustration_mode="gemini", enable_gemini=True,
        )
    assert captured == {}


@pytest.mark.asyncio
async def test_run_api_enables_verified_gemini_under_system_owned_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return "gemini-api-review-run"

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.execute",
        fake_execute,
    )
    monkeypatch.setattr(
        "server.api.settings.is_integration_verified",
        lambda name: name == "gemini",
    )
    response = await run_workflow(WorkflowRunRequest(
        node_ids=["figure"],
        project_path=str(tmp_path),
        run_experiment=False,
        illustration_mode="auto",
        enable_gemini=True,
    ))

    assert response["run_id"] == "gemini-api-review-run"
    assert captured["pipeline_options"]["illustration_mode"] == "auto"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "assurance",
    ["draft", "polished", "conference-ready", "submission"],
)
async def test_run_api_allows_synthetic_preview_in_every_assurance_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assurance: str,
) -> None:
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return f"{assurance}-synthetic-preview-run"

    monkeypatch.setattr("server.api.workflow.workflow_engine.execute", fake_execute)

    response = await run_workflow(
        WorkflowRunRequest(
            node_ids=["lit", "exp-run", "results", "paper"],
            project_path=str(tmp_path),
            assurance=assurance,
            run_experiment=False,
            non_experiment_evidence_mode="synthetic_preview",
        )
    )

    assert response["run_id"] == f"{assurance}-synthetic-preview-run"
    assert captured["assurance"] == assurance
    assert captured["pipeline_options"]["run_experiment"] is False
    assert (
        captured["pipeline_options"]["non_experiment_evidence_mode"]
        == "synthetic_preview"
    )


@pytest.mark.asyncio
async def test_submission_run_still_rejects_design_only_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def should_not_execute(**_kwargs) -> str:
        raise AssertionError("design-only cannot satisfy a complete manuscript track")

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.execute",
        should_not_execute,
    )

    with pytest.raises(HTTPException) as exc_info:
        await run_workflow(WorkflowRunRequest(
            node_ids=["lit", "exp-run", "results", "paper"],
            project_path=str(tmp_path),
            assurance="submission",
            run_experiment=False,
            non_experiment_evidence_mode="design_only",
        ))

    assert exc_info.value.status_code == 422
    assert "design_only" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_submission_run_allows_explicit_hash_verifiable_evidence_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metric = tmp_path / "experiments" / "results" / "imported.csv"
    metric.parent.mkdir(parents=True)
    metric.write_text(
        "status,method,metric,value\ncompleted,Imported,accuracy,0.8\n",
        encoding="utf-8",
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return "submission-import-run"

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.execute",
        fake_execute,
    )

    response = await run_workflow(
        WorkflowRunRequest(
            node_ids=["lit", "results", "paper"],
            project_path=str(tmp_path),
            assurance="submission",
            run_experiment=False,
            non_experiment_evidence_mode="existing_results",
            input_files=["experiments/results/imported.csv"],
        )
    )

    assert response["run_id"] == "submission-import-run"
    assert captured["pipeline_options"]["run_experiment"] is False
    assert (
        captured["pipeline_options"]["non_experiment_evidence_mode"]
        == "existing_results"
    )


@pytest.mark.asyncio
async def test_resume_api_forwards_updated_revision_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    monkeypatch.setattr("server.api.workflow.workflow_engine.get_run", lambda _run_id: None)

    async def fake_resume_persisted_run(**kwargs) -> str:
        captured.update(kwargs)
        return str(kwargs["run_id"])

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.resume_persisted_run",
        fake_resume_persisted_run,
    )
    response = await resume_run(
        "persisted-budget-run",
        WorkflowResumeRequest(
            project_path=str(tmp_path),
            max_revision_rounds=10,
        ),
    )

    assert response["status"] == "running"
    assert captured["pipeline_options"]["max_revision_rounds"] == 10


@pytest.mark.asyncio
async def test_resume_api_preserves_saved_revision_budget_when_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    monkeypatch.setattr("server.api.workflow.workflow_engine.get_run", lambda _run_id: None)

    async def fake_resume_persisted_run(**kwargs) -> str:
        captured.update(kwargs)
        return str(kwargs["run_id"])

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.resume_persisted_run",
        fake_resume_persisted_run,
    )
    await resume_run(
        "persisted-budget-run",
        WorkflowResumeRequest(project_path=str(tmp_path)),
    )

    assert "max_revision_rounds" not in captured["pipeline_options"]


@pytest.mark.asyncio
async def test_resume_api_reconciles_a_stale_click_after_background_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "completed-before-resume-click"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {"direction": "test", "options": {"run_experiment": False}},
    )
    state.set_status("results", "done")
    state.accept("results", "results:accepted", "deterministic:test")
    completion = {
        "execution_completed": True,
        "submission_ready": False,
        "completion_class": "synthetic_preview_ready",
    }
    assert state.complete(completion) is True

    monkeypatch.setattr("server.api.workflow.workflow_engine.get_run", lambda _run_id: None)

    async def should_not_resume(**_kwargs) -> str:
        raise AssertionError("a completed durable run must not be launched again")

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.resume_persisted_run",
        should_not_resume,
    )

    response = await resume_run(
        run_id,
        WorkflowResumeRequest(project_path=str(tmp_path)),
    )

    assert response["status"] == "completed"
    assert response["already_completed"] is True
    assert response["nodes_status"] == {"results": "accepted"}
    assert response["completion"]["schema"] == READINESS_SCHEMA_VERSION
    assert response["completion"]["execution_completed"] is True
    assert response["completion"]["submission_ready"] is False
    assert response["completion"]["completion_class"] == "partial_workflow_complete"


def test_checkpoint_consumption_and_revision_acknowledgement_survive_reload(
    tmp_path: Path,
) -> None:
    run_state = RunState(str(tmp_path), "durable-checkpoint")
    run_state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper"}],
        {"options": {"human_checkpoint": True}},
    )
    run_state.consume_human_checkpoint(
        "paper",
        resolution="feedback",
        feedback_supplied=True,
    )

    reloaded = RunState(str(tmp_path), "durable-checkpoint")
    assert reloaded.human_checkpoint_consumed("paper") is True

    reloaded.set_revision_waiting(
        "paper",
        round_number=3,
        cycle=1,
        gate={"reason": "quality gap", "issues": ["missing evidence"]},
        artifact_signature="revision-signature",
    )
    reloaded.acknowledge_revision_checkpoint("paper")
    revision = RunState(str(tmp_path), "durable-checkpoint").revision_state("paper")
    assert revision["prompt_acknowledged"] is True
    assert revision["artifact_signature"] == "revision-signature"


def test_revision_scope_accepts_null_optional_lists(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "nullable-repair-scope")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper"}],
        {"options": {}},
    )
    gate = {
        "reason": "structured finding",
        "issues": ["missing analysis"],
        "repair_scope": {
            "finding_ids": None,
            "target_files": None,
            "asset_ids": None,
        },
    }

    state.record_revision_gate(
        "paper",
        round_number=1,
        cycle=1,
        gate=gate,
    )
    state.set_revision_waiting(
        "paper",
        round_number=1,
        cycle=1,
        gate=gate,
    )

    revision = RunState(str(tmp_path), "nullable-repair-scope").revision_state("paper")
    assert revision["history"][-1]["repair_scope"] == {
        "finding_ids": [],
        "target_files": [],
        "asset_ids": [],
    }
    assert revision["last_gate"]["repair_scope"] == {
        "finding_ids": [],
        "target_files": [],
        "asset_ids": [],
    }


def test_new_attempt_clears_stale_phase_error_and_timestamps(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "phase-retry-state")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper-writing"}],
        {"options": {}},
    )
    state.set_status("paper", "running")
    first_started = state.load()["phases"]["paper"]["started_at"]
    state.set_status("paper", "running")
    repeated_running = state.load()["phases"]["paper"]
    assert repeated_running["started_at"] == first_started
    assert repeated_running.get("details", {}).get("execution_attempts", []) == []

    def clear_legacy_started_at(current: dict) -> None:
        current["phases"]["paper"]["started_at"] = None

    state.update_state(clear_legacy_started_at)
    state.set_status("paper", "running")
    assert state.load()["phases"]["paper"]["started_at"] is not None
    state.set_status("paper", "failed", error="provider timeout")
    state.set_status("paper", "pending")
    pending = state.load()["phases"]["paper"]
    assert pending["error"] == ""
    assert pending["started_at"] is None
    assert pending["finished_at"] is None

    state.set_status("paper", "running")
    running = state.load()["phases"]["paper"]
    assert running["error"] == ""
    assert running["started_at"] >= first_started
    assert running["finished_at"] is None
    state.set_status("paper", "done")
    state.accept("paper", "paper-ok", "deterministic:test")
    accepted = state.load()["phases"]["paper"]
    assert accepted["status"] == "accepted"
    assert accepted["error"] == ""


def test_reopened_phase_clears_previous_terminal_attestation(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "terminal-lifecycle")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper-writing"}],
        {"options": {}},
    )
    state.set_status("paper", "running")
    state.set_status(
        "paper",
        "done",
        details={"summary": "old completed manuscript"},
    )
    state.accept("paper", "paper-old", "deterministic:old")
    assert state.complete({
        "execution_completed": True,
        "submission_ready": True,
        "completion_class": "submission_ready",
    }) is True

    state.set_status("paper", "running")
    reopened = state.load()
    phase = reopened["phases"]["paper"]

    assert reopened["status"] == "running"
    for key in (
        "finished_at",
        "completion",
        "completion_class",
        "execution_completed",
        "submission_ready",
    ):
        assert key not in reopened
    assert phase["status"] == "running"
    assert phase["finished_at"] is None
    assert phase["error"] == ""
    assert phase["verdict_id"] == ""
    assert phase["reviewer"] == ""
    assert phase["accepted_at"] is None
    assert "summary" not in phase["details"]
    previous_attempt = phase["details"]["execution_attempts"][-1]
    assert previous_attempt["verdict_id"] == "paper-old"
    assert previous_attempt["reviewer"] == "deterministic:old"
    assert previous_attempt["summary"] == "old completed manuscript"


def test_runtime_node_retry_clears_previous_terminal_fields(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="paper",
        name="Paper",
        skill="/paper-writing",
        status=NodeStatus.COMPLETED,
        session_id="old-session",
        output="old completed output",
        error="old failure",
        started_at=10.0,
        finished_at=20.0,
    )
    run = WorkflowRun(
        id="runtime-lifecycle",
        project_path=str(tmp_path),
        nodes=[node],
        status="completed",
        finished_at=30.0,
        completion={"completion_class": "submission_ready"},
    )
    engine._runs[run.id] = run

    engine._mark_run_running(run)
    started_at = engine._start_node_attempt(node)
    snapshot = engine.get_run(run.id)

    assert snapshot["status"] == "running"
    assert snapshot["finished_at"] is None
    assert snapshot["completion"] == {}
    assert snapshot["nodes"][0]["status"] == "running"
    assert snapshot["nodes"][0]["started_at"] == started_at
    assert snapshot["nodes"][0]["finished_at"] is None
    assert snapshot["nodes"][0]["error"] is None
    assert node.session_id is None
    assert node.output is None


def test_acceptance_resolves_stale_revision_prompt_state(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "resolved-revision-state")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper-writing"}],
        {"options": {}},
    )
    state.set_revision_waiting(
        "paper",
        round_number=2,
        cycle=1,
        gate={
            "reason": "",
            "summary": "",
            "issues": [""],
            "transport_exhausted": True,
        },
        artifact_signature="before-repair",
    )
    waiting = state.revision_state("paper")
    assert waiting["last_gate"]["issues"][0].strip()

    state.set_status("paper", "done")
    state.accept("paper", "paper-repaired", "deterministic:test")

    revision = state.revision_state("paper")
    assert revision["waiting"] is False
    assert "waiting_since" not in revision
    assert revision["transport_exhausted"] is False
    assert revision["resolved_verdict_id"] == "paper-repaired"
    assert revision["resolved_reviewer"] == "deterministic:test"
    assert revision["prompt_acknowledged"] is True
    assert revision["last_gate"]["accepted"] is True
    assert revision["last_gate"]["issues"] == []
    assert revision["history"][-1]["accepted"] is True


def test_only_selected_key_nodes_open_human_checkpoints(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario(run_experiment: bool) -> list[str]:
        engine = WorkflowEngine()
        nodes = [
            WorkflowNode(id="lit", name="Literature", skill="/lit"),
            WorkflowNode(id="idea", name="Idea", skill="/idea"),
            WorkflowNode(id="exp-design", name="Design", skill="/design"),
            WorkflowNode(id="exp-run", name="Experiment", skill="/run"),
            WorkflowNode(id="results", name="Results", skill="/results"),
            WorkflowNode(id="paper", name="Paper", skill="/paper"),
        ]
        run = WorkflowRun(
            id=f"checkpoint-policy-{int(run_experiment)}",
            project_path=str(tmp_path / str(int(run_experiment))),
            nodes=nodes,
            status="running",
        )
        engine._runs[run.id] = run
        opened: list[str] = []

        async def immediate_sleep(_seconds: float) -> None:
            return None

        async def fake_wait(
            active_run: WorkflowRun,
            node: WorkflowNode,
            _timeout: int,
        ) -> str:
            opened.append(node.id)
            active_run.checkpoint_resolution = "continued"
            return ""

        async def fake_execute_node(*_args, **_kwargs) -> str:
            return "generated"

        async def fake_managed_experiment(*_args, **_kwargs) -> str:
            return "experiment generated"

        async def fake_planned_templates(*_args, **_kwargs) -> None:
            return None

        async def fake_revision_loop(**kwargs):
            return {
                "accepted": True,
                "verdict_id": "test-verdict",
                "reviewer": "deterministic:test",
                "summary": "accepted",
            }, kwargs["initial_result"]

        monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
        monkeypatch.setattr(engine, "_wait_for_human_checkpoint", fake_wait)
        monkeypatch.setattr(engine, "_execute_node", fake_execute_node)
        monkeypatch.setattr(engine, "_execute_managed_experiment", fake_managed_experiment)
        monkeypatch.setattr(engine, "_ensure_planned_result_templates", fake_planned_templates)
        monkeypatch.setattr(engine, "_run_node_revision_loop", fake_revision_loop)
        await engine._execute_run(
            run,
            "test direction",
            "lite",
            "draft",
            {
                "human_checkpoint": True,
                "human_checkpoint_nodes": ["exp-design", "exp-run", "paper"],
                "run_experiment": run_experiment,
                "code_review": False,
                "research_quality_mode": "off",
            },
        )
        return opened

    assert asyncio.run(scenario(True)) == ["exp-design", "exp-run", "paper"]
    assert asyncio.run(scenario(False)) == ["exp-design", "paper"]


def test_consumed_checkpoint_is_not_reopened_on_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        run_id = "checkpoint-resume"
        run_state = RunState(str(tmp_path), run_id)
        run_state.start(
            [
                {"id": "lit", "name": "Literature", "skill": "/lit"},
                {"id": "paper", "name": "Paper", "skill": "/paper"},
            ],
            {"options": {"human_checkpoint": True}},
        )
        run_state.set_status("lit", "done")
        run_state.accept("lit", "lit-ok", "deterministic:test")
        run_state.consume_human_checkpoint(
            "paper",
            resolution="timeout",
            feedback_supplied=False,
        )

        engine = WorkflowEngine()
        run = WorkflowRun(
            id=run_id,
            project_path=str(tmp_path),
            nodes=[
                WorkflowNode(
                    id="lit",
                    name="Literature",
                    skill="/lit",
                    status=NodeStatus.COMPLETED,
                ),
                WorkflowNode(id="paper", name="Paper", skill="/paper"),
            ],
            status="running",
        )
        engine._runs[run.id] = run
        opened: list[str] = []

        async def immediate_sleep(_seconds: float) -> None:
            return None

        async def fake_wait(*_args, **_kwargs) -> str:
            opened.append("paper")
            return ""

        async def fake_execute_node(*_args, **_kwargs) -> str:
            return "generated"

        async def fake_revision_loop(**kwargs):
            run_state.set_status("paper", "done")
            return {
                "accepted": True,
                "verdict_id": "paper-ok",
                "reviewer": "deterministic:test",
                "summary": "accepted",
            }, kwargs["initial_result"]

        monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
        monkeypatch.setattr(engine, "_wait_for_human_checkpoint", fake_wait)
        monkeypatch.setattr(engine, "_execute_node", fake_execute_node)
        monkeypatch.setattr(engine, "_run_node_revision_loop", fake_revision_loop)
        await engine._execute_run(
            run,
            "test direction",
            opts={
                "human_checkpoint": True,
                "human_checkpoint_nodes": ["paper"],
                "code_review": False,
                "research_quality_mode": "off",
            },
        )
        assert opened == []

    asyncio.run(scenario())


def test_unchanged_revision_artifacts_do_not_start_the_same_loop_again(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    run_id = "unchanged-revision"
    run_state = RunState(str(tmp_path), run_id)
    run_state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "draft",
            "options": {},
        },
    )
    signature = engine._revision_artifact_signature(str(tmp_path), "paper")
    run_state.set_revision_waiting(
        "paper",
        round_number=3,
        cycle=1,
        gate={"reason": "quality gap", "issues": ["missing evidence"]},
        artifact_signature=signature,
    )

    with pytest.raises(ValueError, match="没有变化"):
        asyncio.run(
            engine.resume_persisted_run(
                run_id=run_id,
                project_path=str(tmp_path),
                checkpoint_feedback="",
            )
        )
