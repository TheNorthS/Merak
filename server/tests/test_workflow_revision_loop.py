from __future__ import annotations

from server.tests._workflow_revision_loop_support import (
    NodeStatus as NodeStatus,
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
    os as os,
    pytest as pytest,
    time as time,
)


def test_staged_implementation_report_is_consumed_by_one_gate_pass(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="exp-design",
        name="Experiment design",
        skill="/experiment-plan",
    )
    run = WorkflowRun(
        id="one-shot-staged-report",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={
            "_staged_implementation_report": {
                "status": "blocked",
                "blocking": True,
                "issues": ["integration is incomplete"],
            }
        },
    )

    first = engine._acceptance_gate(
        node,
        run,
        "draft",
        "staged implementation build: blocked",
        require_fresh=False,
    )

    assert first["accepted"] is False
    assert "_staged_implementation_report" not in run.options

    second = engine._acceptance_gate(
        node,
        run,
        "draft",
        "revalidation after an external repair",
        require_fresh=False,
    )

    assert "integration is incomplete" not in json.dumps(second)


def test_revision_signature_detects_nested_artifact_edit(tmp_path: Path) -> None:
    source_dir = tmp_path / "experiments" / "src"
    config_dir = tmp_path / "experiments" / "configs"
    source_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    source = source_dir / "train.py"
    source.write_text("VARIANT_REGISTRY = {}\n", encoding="utf-8")
    (config_dir / "main.yaml").write_text("seed: 1\n", encoding="utf-8")
    (tmp_path / "experiments" / "METHOD_CONTRACT.json").write_text(
        "{}",
        encoding="utf-8",
    )

    engine = WorkflowEngine()
    before = engine._revision_artifact_signature(str(tmp_path), "exp-design")
    directory_times = source_dir.stat()
    source.write_text("VARIANT_REGISTRY = {'full': object()}\n", encoding="utf-8")
    os.utime(
        source,
        ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 1_000_000_000),
    )
    os.utime(
        source_dir,
        ns=(directory_times.st_atime_ns, directory_times.st_mtime_ns),
    )
    after = engine._revision_artifact_signature(str(tmp_path), "exp-design")

    assert before != after


def test_revision_scope_ignores_absolute_quality_report_timestamp_churn(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "experiments" / "results" / "analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("stable scientific result\n", encoding="utf-8")
    report = tmp_path / ".merak" / "quality" / "results.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps({"score": 0.75, "evaluated_at": 1.0}),
        encoding="utf-8",
    )
    diagnostics = {
        "repair_scope": {
            "target_files": [
                str(report.resolve()),
                "experiments/results/analysis.md",
            ],
            "asset_ids": [],
        },
    }
    engine = WorkflowEngine()

    before = engine._revision_scope_signature(
        str(tmp_path),
        "results",
        diagnostics,
    )
    report.write_text(
        json.dumps({"score": 0.75, "evaluated_at": 2.0}),
        encoding="utf-8",
    )
    after_report_refresh = engine._revision_scope_signature(
        str(tmp_path),
        "results",
        diagnostics,
    )
    analysis.write_text("changed scientific result\n", encoding="utf-8")
    after_artifact_edit = engine._revision_scope_signature(
        str(tmp_path),
        "results",
        diagnostics,
    )

    assert after_report_refresh == before
    assert after_artifact_edit != before


def test_cancelled_revision_is_revalidated_before_another_model_call() -> None:
    assert WorkflowEngine._phase_requires_revalidation({
        "status": "running",
        "details": {},
    }) is True
    assert WorkflowEngine._phase_requires_revalidation({
        "status": "pending",
        "details": {
            "revision": {
                "round": 3,
                "history": [{"accepted": False}],
                "last_gate": {"reason": "validator mismatch"},
            },
        },
    }) is True
    assert WorkflowEngine._phase_requires_revalidation({
        "status": "pending",
        "details": {"revision": {"round": 0, "history": []}},
    }) is False


def test_quality_diagnostics_target_artifacts_instead_of_report(
    tmp_path: Path,
) -> None:
    report = (tmp_path / ".merak" / "quality" / "results.json").resolve()
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "reason": "research depth contract failed",
        "details": {
            "research_quality": {
                "score": 0.75,
                "threshold": 0.78,
                "issues": [
                    "missing quality dimension provenance: "
                    "metric provenance and run identity"
                ],
                "artifacts": ["experiments/results/analysis.md"],
                "report_path": str(report),
            },
            # Even a legacy payload that repeats the report as a target must
            # not turn validator output into a repair artifact.
            "target_files": [str(report)],
        },
    })

    assert diagnostics["report_path"] == str(report)
    assert diagnostics["repair_scope"]["target_files"] == [
        "experiments/results/analysis.md"
    ]


def test_revision_diagnostics_separate_quality_from_implementation_contract() -> None:
    diagnostics = WorkflowEngine._gate_revision_diagnostics({
        "accepted": False,
        "reason": "node-specific research risk audit failed",
        "summary": "implementation contract mismatch",
        "details": {
            "research_quality": {
                "applicable": True,
                "passed": True,
                "score": 1.0,
                "threshold": 0.58,
                "issues": [],
            },
            "implementation_contract": {
                "applicable": True,
                "passed": False,
                "summary": "implementation mismatch",
                "issues": ["missing declared symbol"],
            },
        },
    })

    assert diagnostics["component_statuses"]["content_quality"] == {
        "label": "内容质量",
        "applicable": True,
        "passed": True,
        "score": 1.0,
        "threshold": 0.58,
        "issues": [],
    }
    assert diagnostics["component_statuses"]["implementation_contract"]["passed"] is False
    assert WorkflowEngine._revision_intervention_kind(
        WorkflowNode(id="exp-design", name="Experiment", skill="/experiment-plan"),
        {**diagnostics, "issues": ["missing declared symbol in experiments/src/models.py"]},
    ) == "platform_repair"


def test_revision_intervention_requires_an_explicit_researcher_choice() -> None:
    node = WorkflowNode(id="novelty", name="Novelty", skill="/novelty-check")

    assert WorkflowEngine._revision_intervention_kind(node, {
        "reason": "researcher decision required",
        "summary": "Change the hypothesis or select a different idea.",
        "issues": [],
    }) == "researcher_decision"
    assert WorkflowEngine._revision_intervention_kind(node, {
        "reason": "artifact parser failed",
        "summary": "missing declared symbol",
        "issues": [],
    }) == "platform_repair"
    assert WorkflowEngine._revision_intervention_kind(node, {
        "reason": "需要研究者决定",
        "summary": "需要修改研究假设或更换研究方向。",
        "issues": [],
    }) == "researcher_decision"


@pytest.mark.asyncio
async def test_gate_failure_revises_and_revalidates_until_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="idea",
        name="Idea",
        skill="/idea-discovery",
        status=NodeStatus.RUNNING,
        session_id="previous-session",
        error="previous-attempt-error",
        started_at=time.time(),
        finished_at=time.time(),
    )
    run = WorkflowRun(id="revision-pass", project_path=str(tmp_path), nodes=[node], status="running")
    engine._runs[run.id] = run
    state = _start_run_state(tmp_path, run.id, [node])
    target = tmp_path / "ideas" / "ideas.md"
    rejected = _rejected()
    rejected["details"]["research_quality"]["artifacts"] = [
        "ideas/ideas.md",
    ]
    gates = iter([rejected, _accepted()])
    revisions: list[dict] = []
    events: list[tuple[str, dict]] = []
    revision_lifecycles: list[dict] = []

    async def prepare(*_args, **_kwargs) -> str:
        return _args[2]

    async def canonicalize(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        revisions.append(kwargs)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("revised scientific idea", encoding="utf-8")
        return "revised artifact"

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))
        if event_type == "node_revision_started":
            snapshot = engine.get_run(run.id)["nodes"][0]
            revision_lifecycles.append({
                **snapshot,
                "session_id": node.session_id,
                "output": node.output,
            })

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: next(gates))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, result = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="initial artifact",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=2,
    )

    assert gate["accepted"] is True
    assert gate["revision_round"] == 1
    assert result == "revised artifact"
    assert len(revisions) == 1
    revision = state.revision_state(node.id)
    assert revision["round"] == 1
    assert [item["accepted"] for item in revision["history"]] == [False, True]
    assert state.load()["phases"][node.id]["status"] == "done"
    assert any(event_type == "node_revision_started" for event_type, _ in events)
    assert len(revision_lifecycles) == 1
    revision_lifecycle = revision_lifecycles[0]
    assert revision_lifecycle["status"] == "running"
    assert revision_lifecycle["started_at"] is not None
    assert revision_lifecycle["finished_at"] is None
    assert revision_lifecycle["error"] is None
    assert revision_lifecycle["session_id"] is None
    assert revision_lifecycle["output"] is None
    completed = next(
        payload
        for event_type, payload in events
        if event_type == "node_revision_completed"
    )
    assert completed["target_artifact_changed"] is True
    assert completed["target_signature_before"] != (
        completed["target_signature_after"]
    )
    assert not any(
        event_type == "node_revision_no_progress"
        for event_type, _ in events
    )


@pytest.mark.asyncio
async def test_revision_revalidation_does_not_require_a_gratuitous_file_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="results",
        name="Results",
        skill="/analyze-results",
        status=NodeStatus.RUNNING,
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="revision-valid-unchanged",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [node])
    gates = iter([_rejected("specialist subnode is pending"), _accepted()])
    freshness_checks: list[bool] = []
    events: list[str] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def revise(**_kwargs) -> str:
        return "same valid artifact"

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def emit(_run, event: str, _payload: dict) -> None:
        events.append(event)

    async def specialists(**_kwargs) -> dict:
        return {"accepted": True}

    def acceptance_gate(*_args, **kwargs):
        freshness_checks.append(bool(kwargs.get("require_fresh")))
        return next(gates)

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_execute_profile_specialists",
        specialists,
    )
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance_gate)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="same valid artifact",
        research_direction="test",
        effort="balanced",
        assurance="submission",
        opts={},
        require_fresh=True,
        checkpoint_timeout=30,
        max_revision_rounds=2,
    )

    assert gate["accepted"] is True
    assert freshness_checks == [True, False]
    assert "node_revision_revalidated" in events
    assert "node_revision_no_progress" not in events


@pytest.mark.asyncio
async def test_revision_budget_is_scoped_to_each_responsible_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    upstream = WorkflowNode(id="lit", name="Literature", skill="/research-lit")
    node = WorkflowNode(
        id="novelty",
        name="Novelty",
        skill="/novelty-check",
        status=NodeStatus.RUNNING,
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="owner-scoped-revisions",
        project_path=str(tmp_path),
        nodes=[upstream, node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [upstream, node])
    gates = iter([
        _rejected("upstream literature provenance missing"),
        _accepted(),  # upstream literature revalidation
        _rejected("novelty search provenance missing"),
        _rejected("upstream literature artifact needs refresh"),
        _accepted(),  # upstream literature revalidation
        _rejected("novelty artifact needs refresh"),
        _accepted(),
    ])
    owners = iter([upstream, node, upstream, node])
    revision_calls: list[tuple[str, int]] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        revision_calls.append((kwargs["node"].id, kwargs["round_number"]))
        return f"revised {kwargs['node'].id} round {kwargs['round_number']}"

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: next(gates))
    monkeypatch.setattr(engine, "_revision_owner_for_gate", lambda *_args, **_kwargs: next(owners))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
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

    assert gate["accepted"] is True
    assert revision_calls == [
        ("lit", 1),
        ("novelty", 1),
        ("lit", 2),
        ("novelty", 2),
    ]
    revision = RunState(str(tmp_path), run.id).revision_state(node.id)
    assert revision["owner_rounds"] == {"lit": 2, "novelty": 2}
    assert revision["active_owner_id"] == "novelty"


@pytest.mark.asyncio
async def test_multi_owner_no_progress_survives_owner_switches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    figure = WorkflowNode(id="figure", name="Figure", skill="/figure")
    paper = WorkflowNode(id="paper", name="Paper", skill="/paper")
    review = WorkflowNode(
        id="review",
        name="Review",
        skill="/review",
        status=NodeStatus.RUNNING,
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="multi-owner-no-progress",
        project_path=str(tmp_path),
        nodes=[figure, paper, review],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [figure, paper, review])
    gate_payload = {
        "accepted": False,
        "reason": "mixed PDF layout findings",
        "details": {
            "review_findings": [
                {
                    "id": "PDF-FIG",
                    "message": "Figure text is too small.",
                    "owner_node": "figure",
                    "target_files": ["figures/chart.py"],
                    "asset_ids": ["chart"],
                },
                {
                    "id": "PDF-TABLE",
                    "message": "Table text overlaps.",
                    "owner_node": "paper",
                    "target_files": ["paper/tables/results.tex"],
                    "asset_ids": ["results"],
                },
            ],
        },
    }
    revision_calls: list[str] = []
    events: list[tuple[str, dict]] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        revision_calls.append(kwargs["node"].id)
        return kwargs["node"].id

    def acceptance(active_node, *_args, **_kwargs):
        return _accepted() if active_node.id != "review" else gate_payload

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=review,
        run=run,
        initial_result="review",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={"revision_no_progress_limit": 2},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=6,
    )

    assert gate["waiting"] is True
    assert revision_calls == ["figure", "paper", "figure", "paper"]
    assert any(
        event == "node_revision_waiting"
        and payload["stopped_for_no_progress"] is True
        for event, payload in events
    )


@pytest.mark.asyncio
async def test_deterministic_stage_gets_one_automatic_repair_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="compile",
        name="Compile",
        skill="/paper-compile",
        status=NodeStatus.RUNNING,
        started_at=time.time(),
    )
    run = WorkflowRun(
        id="deterministic-repair",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [node])
    gates = iter([_rejected("stale PDF hash"), _accepted()])
    revisions: list[dict] = []

    async def prepare(*_args, **_kwargs) -> str:
        return _args[2]

    async def canonicalize(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        revisions.append(kwargs)
        return "deterministically rebuilt"

    async def emit(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: next(gates),
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, result = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="stale build",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert gate["accepted"] is True
    assert result == "deterministically rebuilt"
    assert len(revisions) == 1


@pytest.mark.parametrize("node_id", ["compile", "ppt"])
@pytest.mark.asyncio
async def test_deterministic_stage_stops_after_one_unsuccessful_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node_id: str,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id=node_id,
        name=node_id.title(),
        skill="/paper-compile" if node_id == "compile" else "/paper-slides",
        status=NodeStatus.RUNNING,
        started_at=time.time(),
    )
    run = WorkflowRun(
        id=f"deterministic-stop-{node_id}",
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
        return "same unresolved deterministic build"

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: _rejected("stale build record"),
    )
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_emit", emit)

    gate, _ = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="stale deterministic build",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=6,
    )

    assert gate["waiting"] is True
    assert gate["revision_round"] == 1
    assert revision_calls == 1
    assert not any(
        event == "node_revision_completed"
        for event, _ in events
    )
    waiting = next(
        payload
        for event, payload in events
        if event == "node_revision_waiting"
    )
    assert waiting["stopped_for_deterministic_stage"] is True
    assert waiting["hard_limit"] is False
    persisted = RunState(str(tmp_path), run.id).revision_state(node.id)
    assert persisted["stopped_for_deterministic_stage"] is True
    assert (
        persisted["last_gate"]["stopped_for_deterministic_stage"]
        is True
    )
    assert persisted["hard_limit"] is False
    assert engine._platform_checkpoint_is_auto_recoverable(persisted) is False


@pytest.mark.asyncio
async def test_revision_history_persists_multiple_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="lit", name="Literature", skill="/research-lit", started_at=time.time())
    run = WorkflowRun(id="revision-history", project_path=str(tmp_path), nodes=[node], status="running")
    state = _start_run_state(tmp_path, run.id, [node])
    gates = iter([_rejected("gap A"), _rejected("gap B"), _accepted()])

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        return "revision " + str(kwargs["round_number"])

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: next(gates))
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
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
        max_revision_rounds=3,
    )

    history = state.revision_state(node.id)["history"]
    assert gate["revision_round"] == 2
    assert [item["round"] for item in history] == [0, 1, 2]
    assert [item["accepted"] for item in history] == [False, False, True]


@pytest.mark.asyncio
async def test_revision_hard_limit_stops_without_starting_another_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery", started_at=time.time())
    run = WorkflowRun(id="revision-wait", project_path=str(tmp_path), nodes=[node], status="running")
    state = _start_run_state(tmp_path, run.id, [node])
    gates = iter([_rejected("gap A"), _rejected("gap B")])
    feedback_seen: list[str] = []
    events: list[tuple[str, dict]] = []

    async def prepare(_node, _run, result, *_args, **_kwargs) -> str:
        return result

    async def canonicalize(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        feedback_seen.append(kwargs["user_feedback"])
        return "revised"

    async def emit(_run, event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *_args, **_kwargs: next(gates))
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
        max_revision_rounds=1,
    )

    assert gate["accepted"] is False
    assert gate["waiting"] is True
    assert gate["max_revision_rounds"] == 1
    assert feedback_seen == [""]
    waiting_payload = next(payload for event_type, payload in events if event_type == "node_revision_waiting")
    assert waiting_payload["decision_brief"]["headline"]
    assert waiting_payload["decision_brief"]["research_impact"]
    assert waiting_payload["decision_brief"]["recommended_actions"]
    persisted_phase = state.load()["phases"][node.id]
    assert persisted_phase["status"] == "awaiting_revision"
    revision = persisted_phase["details"]["revision"]
    assert revision["last_gate"]["decision_brief"]["protected_state"]
    assert revision["hard_limit"] is True
    assert revision["last_gate"]["hard_limit"] is True
    assert engine._platform_checkpoint_is_auto_recoverable(revision) is False


def test_revision_decision_brief_explains_contract_symbol_mismatch() -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="exp-design", name="实验设计", skill="/experiment-plan")
    issue = (
        "I4: missing declared symbol(s) in experiments/src/train.py: "
        "VARIANT_REGISTRY"
    )

    brief = engine._build_revision_decision_brief(
        node,
        {
            "issues": [issue],
            "reason": "accepted idea and implementation contract are misaligned",
        },
        round_number=4,
        max_revision_rounds=3,
    )

    assert "VARIANT_REGISTRY" in brief["plain_issues"][0]
    assert "方法契约" in brief["plain_issues"][0]
    assert "可靠归因" in brief["research_impact"]
    assert any("METHOD_CONTRACT.json" in item for item in brief["recommended_actions"])
    assert brief["technical_details"] == [issue]
