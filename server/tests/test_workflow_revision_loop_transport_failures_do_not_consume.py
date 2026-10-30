from __future__ import annotations

from server.tests._workflow_revision_loop_support import (
    AgentEngine as AgentEngine,
    NodeStatus as NodeStatus,
    Path as Path,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _accepted as _accepted,
    _rejected as _rejected,
    _start_run_state as _start_run_state,
    agent_engine as agent_engine,
    asyncio as asyncio,
    json as json,
    os as os,
    pytest as pytest,
    time as time,
)


@pytest.mark.asyncio
async def test_transport_failures_do_not_consume_scientific_revision_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="exp-design", name="Experiment", skill="/experiment-plan", started_at=time.time())
    run = WorkflowRun(id="revision-transport", project_path=str(tmp_path), nodes=[node], status="running")
    _start_run_state(tmp_path, run.id, [node])
    calls = 0

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**_kwargs) -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: _rejected("missing contract"))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", noop)

    operation = engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={"max_retries": 2},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    with pytest.raises(TimeoutError, match="provider timed out"):
        await operation
    assert calls == 1
    revision = RunState(str(tmp_path), run.id).revision_state(node.id)
    assert not revision.get("transport_exhausted")


def test_revision_error_classification_keeps_node_failures_out_of_transport() -> None:
    engine = WorkflowEngine()

    assert agent_engine._is_transient_model_error(
        RuntimeError("OpenAI API error 502")
    )
    assert engine._is_transport_research_error(TimeoutError("provider timed out"))
    assert engine._is_transport_research_error(
        RuntimeError("Model stream stalled after 45s without chunks")
    )
    assert engine._is_transport_research_error(
        RuntimeError("OpenAI API error 502")
    )
    assert not engine._is_transport_research_error(
        RuntimeError("Deterministic ppt compile failed: missing image")
    )
    assert not engine._is_transport_research_error(RuntimeError())
    assert engine._exception_summary(RuntimeError()) == (
        "RuntimeError: (no exception message was provided)"
    )


@pytest.mark.asyncio
async def test_agent_timeout_is_retried_on_the_same_route_without_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = AgentEngine(type("Router", (), {})())
    session = engine.create_session("test")
    provider = type("Provider", (), {"name": "fake", "model": "fake-model"})()
    calls = 0

    monkeypatch.setattr(
        engine,
        "_candidate_providers",
        lambda _session: ([("fake", provider)], False),
    )

    async def timeout(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("Model request timeout after 90s")

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(engine, "_chat_with_progress", timeout)
    monkeypatch.setattr("server.agent.engine.asyncio.sleep", no_sleep)

    with pytest.raises(TimeoutError, match="fake"):
        await engine.run(session.id, "run", tools=[])

    assert calls == 2


def test_review_reconciliation_failure_is_owned_by_paper() -> None:
    engine = WorkflowEngine()
    review_node = WorkflowNode(
        id="review",
        name="review",
        skill="/auto-review-loop",
    )
    run = WorkflowRun(id="review-owner", nodes=[review_node])

    owner = engine._revision_owner_for_gate(
        review_node,
        run,
        {
            "reason": "reviewed paper failed deterministic reconciliation",
            "details": {
                "managed_review": True,
                "paper_reconciliation": {
                    "passed": False,
                    "issues": [
                        "experiments: section unfocused (1670; preferred maximum 1150)"
                    ],
                },
            },
        },
    )

    assert owner.id == "paper"


def test_compile_source_failure_is_owned_by_paper_but_platform_failure_is_not() -> None:
    engine = WorkflowEngine()
    compile_node = WorkflowNode(id="compile", name="compile", skill="/paper-compile")
    run = WorkflowRun(id="compile-owner", nodes=[compile_node])

    source_owner = engine._revision_owner_for_gate(
        compile_node,
        run,
        {"reason": "Undefined control sequence in paper/main.tex"},
    )
    platform_owner = engine._revision_owner_for_gate(
        compile_node,
        run,
        {"reason": "latexmk not found. Install TeX Live."},
    )
    bibliography_owner = engine._revision_owner_for_gate(
        compile_node,
        run,
        {"reason": "./main.bbl:13: Missing $ inserted."},
    )

    assert source_owner.id == "paper"
    assert platform_owner.id == "compile"
    assert bibliography_owner.id == "lit"


@pytest.mark.parametrize(
    ("current_node_id", "message", "target_file", "expected_owner"),
    [
        (
            "compile",
            "The paper plan is stale.",
            "paper/PAPER_PLAN.md",
            "narrative",
        ),
        (
            "compile",
            "The narrative report no longer matches the evidence.",
            "NARRATIVE_REPORT.md",
            "narrative",
        ),
        (
            "compile",
            "The five-layer audit result is stale.",
            "audit-results/AUDIT_RESULTS.json",
            "audit",
        ),
        (
            "ppt",
            "The proof audit build sidecar is missing or stale.",
            "paper/PROOF_AUDIT.json",
            "audit",
        ),
        (
            "audit",
            "The managed review state is stale.",
            "review-stage/REVIEW_STATE.json",
            "review",
        ),
        (
            "review",
            "The frozen selection record must be refreshed.",
            "ideas/SELECTED_IDEA.json",
            "novelty",
        ),
        (
            "review",
            "The idea catalogue is incomplete.",
            "ideas/ideas.md",
            "idea",
        ),
        (
            "audit",
            "A counterexample shows that the theorem has an invalid proof.",
            "paper/PROOF_AUDIT.json",
            "paper",
        ),
    ],
)
def test_downstream_gate_targets_route_to_the_artifact_owner(
    current_node_id: str,
    message: str,
    target_file: str,
    expected_owner: str,
) -> None:
    engine = WorkflowEngine()
    current = WorkflowNode(
        id=current_node_id,
        name=current_node_id,
        skill=f"/{current_node_id}",
    )
    run = WorkflowRun(id="target-owner", nodes=[current])
    gate = {
        "accepted": False,
        "details": {
            "issues": [{
                "id": "TARGET-OWNER-001",
                "message": message,
                "target_files": [target_file],
            }],
        },
    }

    owner = engine._revision_owner_for_gate(current, run, gate)

    assert owner.id == expected_owner


def test_compile_build_finding_stays_with_compile_despite_tex_target_owner() -> None:
    engine = WorkflowEngine()
    compile_node = WorkflowNode(
        id="compile",
        name="compile",
        skill="/paper-compile",
    )
    run = WorkflowRun(id="compile-build-owner", nodes=[compile_node])
    gate = {
        "accepted": False,
        "details": {
            "issues": [{
                "id": "COMPILE-HASH-001",
                "message": "PAPER_BUILD source hash does not match.",
                "owner_node": "paper",
                "target_files": [
                    "paper/main.tex",
                    "paper/PAPER_BUILD.json",
                ],
            }],
        },
    }

    owner = engine._revision_owner_for_gate(compile_node, run, gate)

    assert owner.id == "compile"


def test_agent_node_idle_and_hard_limits_are_bounded_by_internal_policy() -> None:
    from server.agent.engine import MODEL_TOOL_RESPONSE_TIMEOUT

    engine = WorkflowEngine()

    assert engine._agent_node_timeout_seconds("paper", is_revision=False) == 360.0
    assert engine._agent_node_timeout_seconds("lit", is_revision=False) == 600.0
    assert engine._agent_node_timeout_seconds("figure", is_revision=False) == 720.0
    assert engine._agent_node_timeout_seconds("figure", is_revision=True) == 720.0
    assert engine._agent_node_timeout_seconds("paper", is_revision=True) == 360.0
    assert engine._agent_node_timeout_seconds("results", is_revision=False) == 360.0
    assert engine._agent_node_timeout_seconds("narrative", is_revision=False) == 360.0
    assert engine._agent_node_timeout_seconds("unknown", is_revision=False) == 360.0
    assert engine._agent_node_hard_timeout_seconds("idea", is_revision=False) == 1800.0
    assert engine._agent_node_hard_timeout_seconds("figure", is_revision=False) == 3600.0
    assert engine._agent_node_hard_timeout_seconds("results", is_revision=False) == 1200.0
    assert engine._agent_node_hard_timeout_seconds("results", is_revision=True) == 1800.0
    for node_id in (
        "idea",
        "exp-design",
        "results",
        "narrative",
        "figure",
        "paper",
        "ppt",
        "unknown",
    ):
        assert (
            engine._agent_node_timeout_seconds(node_id, is_revision=False)
            > MODEL_TOOL_RESPONSE_TIMEOUT
        )
        assert (
            engine._agent_node_timeout_seconds(node_id, is_revision=True)
            > MODEL_TOOL_RESPONSE_TIMEOUT
        )


def test_workflow_risk_delta_reports_warnings_once_and_keeps_blockers_active() -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(id="risk-delta")
    snapshot = {
        "nodes": {
            "lit": {
                "findings": [{
                    "id": "LIT-WARN",
                    "severity": "warning",
                    "plain_message": "检索覆盖不足。",
                    "remediation": "补充检索。",
                    "owner_node": "lit",
                }],
            },
            "exp-design": {
                "findings": [{
                    "id": "DESIGN-BLOCK",
                    "severity": "blocker",
                    "plain_message": "实验契约与冻结 Idea 不一致。",
                    "remediation": "修复方法契约。",
                    "owner_node": "exp-design",
                }],
            },
        },
    }

    first = engine._new_workflow_risk_findings(run, snapshot, "paper")
    second = engine._new_workflow_risk_findings(run, snapshot, "paper")

    assert [item["severity"] for item in first["new_findings"]] == [
        "warning",
        "blocker",
    ]
    assert first["latent_blockers"][0]["owner_node"] == "exp-design"
    assert second["new_findings"] == []
    assert len(second["latent_blockers"]) == 1


@pytest.mark.asyncio
async def test_empty_node_revision_exception_remains_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="exp-design",
        name="Experiment",
        skill="/experiment-plan",
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="revision-node-error",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [node])
    events: list[tuple[str, dict]] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**_kwargs) -> str:
        raise RuntimeError()

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: _rejected("missing contract"),
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    operation = engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={"max_retries": 2},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=1,
    )

    with pytest.raises(RuntimeError) as raised:
        await operation
    assert engine._exception_summary(raised.value) == "RuntimeError: (no exception message was provided)"
    assert not any(event == "node_revision_completed" for event, _ in events)


@pytest.mark.asyncio
async def test_node_revision_exception_propagates_without_automatic_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="exp-design",
        name="Experiment",
        skill="/experiment-plan",
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="revision-repeated-node-error",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
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
        raise RuntimeError("unchanged repair failure")

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: _rejected("missing contract"),
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    operation = engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=6,
    )

    with pytest.raises(RuntimeError, match="unchanged repair failure"):
        await operation
    assert revision_calls == 1
    assert not any(event in {"node_revision_completed", "node_revision_no_progress"} for event, _ in events)
    persisted = RunState(str(tmp_path), run.id).revision_state(node.id)
    assert not persisted.get("stopped_for_no_progress")


def test_artifact_freshness_requires_one_update_not_every_file(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("valid A", encoding="utf-8")
    second.write_text("valid B", encoding="utf-8")
    old = time.time() - 30
    os.utime(first, (old, old))
    os.utime(second, (old, old))
    since = time.time() - 2

    unchanged, issues = engine._artifact_check([first, second], since=since)
    assert unchanged is False
    assert "no canonical artifact changed" in issues[0]

    first.write_text("updated A", encoding="utf-8")
    accepted, issues = engine._artifact_check([first, second], since=since)
    assert accepted is True
    assert issues == []


@pytest.mark.asyncio
async def test_figure_stage_executes_the_model_owned_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="figure",
        name="Figure",
        skill="/paper-figure",
    )
    run = WorkflowRun(
        id="figure-model-owner",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [node])
    executed: list[tuple[str, str]] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def execute_node(active_node, *_args, **kwargs) -> str:
        executed.append((active_node.id, str(kwargs.get("revision_context") or "")))
        return "model-authored scene persisted"

    async def revision_loop(**kwargs):
        RunState(str(tmp_path), run.id).set_status("figure", "done")
        return _accepted(), kwargs["initial_result"]

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(engine, "_execute_node", execute_node)
    monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
    monkeypatch.setattr(engine, "_emit", noop)

    await engine._execute_run(
        run,
        "test direction",
        "balanced",
        "draft",
        {
            "run_experiment": True,
            "human_checkpoint": False,
            "code_review": False,
            "research_quality_mode": "off",
        },
    )

    assert executed == [("figure", "")]
    assert node.status == NodeStatus.COMPLETED


@pytest.mark.asyncio
async def test_figure_gate_revision_redraws_the_same_semantic_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="figure",
        name="Figure",
        skill="/paper-figure",
    )
    run = WorkflowRun(
        id="figure-targeted-revision",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    figures = tmp_path / "figures"
    figures.mkdir()
    figures.joinpath("FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "publication_label_schema": 1,
        "figures": [{"id": "method_architecture", "producer_kind": "model"}],
    }), encoding="utf-8")
    captured: dict[str, str] = {}

    async def execute_node(active_node, *_args, **kwargs) -> str:
        captured["node_id"] = active_node.id
        captured["revision_context"] = str(kwargs.get("revision_context") or "")
        return "revised model-authored scene"

    async def must_not_rebuild_locally(*_args, **_kwargs) -> None:
        raise AssertionError("figure revision must return to the model owner")

    monkeypatch.setattr(engine, "_execute_node", execute_node)
    monkeypatch.setattr(engine, "_ensure_figure_artifacts", must_not_rebuild_locally)

    result = await engine._revise_node_from_gate(
        node=node,
        run=run,
        diagnostics={
            "reason": "figure artifact contract failed",
            "issues": ["required scientific figure was not rendered: method_architecture"],
            "repair_scope": {"asset_ids": ["method_architecture"]},
        },
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="test direction",
        effort="balanced",
        assurance="draft",
        opts={"run_experiment": False},
    )

    assert result == "revised model-authored scene"
    assert captured["node_id"] == "figure"
    context = captured["revision_context"]
    assert "method_architecture" in context
    assert "existing FIGURE_SPECS id as" in context
    assert "Never add a suffix" in context


@pytest.mark.asyncio
async def test_figure_plan_linkage_revision_reuses_existing_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="figure", name="Figure", skill="/paper-figure")
    run = WorkflowRun(
        id="figure-plan-linkage-revision",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    figures = tmp_path / "figures"
    figures.mkdir()
    figures.joinpath("FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "publication_label_schema": 1,
        "figures": [{"id": "main_comparison_preview", "producer_kind": "model"}],
    }), encoding="utf-8")
    captured: dict[str, str] = {}

    async def execute_node(active_node, *_args, **kwargs) -> str:
        captured["node_id"] = active_node.id
        captured["revision_context"] = str(kwargs.get("revision_context") or "")
        return "relinked existing figure"

    monkeypatch.setattr(engine, "_execute_node", execute_node)

    result = await engine._revise_node_from_gate(
        node=node,
        run=run,
        diagnostics={
            "reason": "figure artifact contract failed",
            "issues": [
                "required figure is not referenced in paper/PAPER_PLAN.md: "
                "main_comparison_preview"
            ],
            "repair_scope": {"asset_ids": ["main_comparison_preview"]},
        },
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="test direction",
        effort="balanced",
        assurance="draft",
        opts={"run_experiment": False},
    )

    assert result == "relinked existing figure"
    context = captured["revision_context"]
    assert "manuscript-plan linkage repair" in context
    assert "Do not call\n  generate_figure" in context
    assert "edit only the canonical\n  paper/PAPER_PLAN.md" in context


@pytest.mark.asyncio
async def test_exp_run_revision_repairs_source_before_scheduler_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="exp-run", name="Experiment", skill="/experiment-bridge")
    run = WorkflowRun(
        id="exp-run-debug-order",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    calls: list[str] = []

    async def repair(**_kwargs) -> str:
        calls.append("repair")
        return "source repaired"

    async def execute(_run, _opts) -> str:
        calls.append("execute")
        return '{"status":"completed"}'

    async def runtime_started(*_args, **_kwargs):
        return "operation", "experiment_scheduler"

    async def runtime_finished(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_repair_failed_experiment_source", repair)
    monkeypatch.setattr(engine, "_execute_managed_experiment", execute)
    monkeypatch.setattr(engine, "_runtime_execution_started", runtime_started)
    monkeypatch.setattr(engine, "_runtime_execution_finished", runtime_finished)

    result = await engine._revise_node_from_gate(
        node=node,
        run=run,
        diagnostics={"reason": "process failed", "issues": ["traceback"]},
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={"run_experiment": True},
    )

    assert calls == ["repair", "execute"]
    assert result.startswith("source repaired")
    assert '"status":"completed"' in result


@pytest.mark.asyncio
async def test_downstream_node_waits_for_upstream_acceptance_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    lit = WorkflowNode(id="lit", name="Literature", skill="/research-lit")
    idea = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery", depends_on=["lit"])
    run = WorkflowRun(id="revision-dependency", project_path=str(tmp_path), nodes=[lit, idea], status="running")
    engine._runs[run.id] = run
    state = _start_run_state(tmp_path, run.id, [lit, idea])
    loop_entered = asyncio.Event()
    release_loop = asyncio.Event()
    executed: list[str] = []

    async def immediate_sleep(_seconds: float) -> None:
        return None

    async def execute_node(node, *_args, **_kwargs) -> str:
        executed.append(node.id)
        return node.id

    async def revision_loop(*, node, initial_result, **_kwargs):
        state.set_status(node.id, "done")
        if node.id == "lit":
            loop_entered.set()
            await release_loop.wait()
        return _accepted(), initial_result

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(engine, "_execute_node", execute_node)
    monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
    monkeypatch.setattr(engine, "_emit", noop)

    task = asyncio.create_task(
        engine._execute_run(
            run,
            "test",
            "balanced",
            "draft",
            {"code_review": False, "research_quality_mode": "off"},
        )
    )
    await loop_entered.wait()
    assert executed == ["lit"]
    assert idea.status == NodeStatus.IDLE
    release_loop.set()
    await task

    assert executed == ["lit", "idea"]
    assert lit.status == NodeStatus.COMPLETED
    assert idea.status == NodeStatus.COMPLETED
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_node_preflight_runs_before_agent_and_exp_run_code_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="exp-run", name="Experiment", skill="/experiment-bridge")
    run = WorkflowRun(
        id="preflight-before-agent",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={"run_experiment": True, "code_review": True},
    )
    _start_run_state(tmp_path, run.id, [node])
    captured: dict[str, str] = {}
    calls: list[str] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    async def must_not_execute(*_args, **_kwargs) -> str:
        calls.append("agent")
        raise AssertionError("node agent must not start while preflight is blocked")

    async def must_not_review(*_args, **_kwargs) -> str:
        calls.append("code-review")
        raise AssertionError("code review must wait for protected upstream repair")

    async def revision_loop(*, initial_result, **_kwargs):
        captured["result"] = initial_result
        return _accepted(), initial_result

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [{
            "severity": "blocker",
            "upstream_node": "exp-design",
            "plain_message": "实验设计尚未通过验收。",
        }],
    )
    monkeypatch.setattr(engine, "_execute_node", must_not_execute)
    monkeypatch.setattr(engine, "_run_code_review", must_not_review)
    monkeypatch.setattr(engine, "_run_node_revision_loop", revision_loop)
    monkeypatch.setattr(engine, "_emit", noop)

    await engine._execute_run(
        run,
        "test direction",
        "balanced",
        "draft",
        {"run_experiment": True, "code_review": True, "research_quality_mode": "off"},
    )

    assert calls == []
    assert "deferred" in captured["result"]
