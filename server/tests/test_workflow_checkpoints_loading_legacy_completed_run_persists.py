from __future__ import annotations

from server.tests._workflow_checkpoints_support import (
    Path as Path,
    RunState as RunState,
    SIMULATION_MANIFEST_SCHEMA as SIMULATION_MANIFEST_SCHEMA,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    asyncio as asyncio,
    experiment_placeholder_service as experiment_placeholder_service,
    json as json,
    pytest as pytest,
    resume_run as resume_run,
    snapshot_paths as snapshot_paths,
    workflow_input_service as workflow_input_service,
)


def _seed_public_benchmark_contract(root: Path) -> None:
    """Current authored science for local simulation-sidecar fixture generation."""
    ideas = root / "ideas"
    ideas.mkdir(parents=True, exist_ok=True)
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "status": "accepted", "title": "Bounded representation comparison",
        "hypothesis": "Registered representation effects differ under matched conditions.",
        "claims": [{"id": "C1", "statement": "The registered effect is bounded to the comparison.",
                    "publication_statement": "The registered effect is bounded to the comparison."}],
        "mechanisms": [{"id": "M1", "name": "Registered representation", "publication_name": "Registered representation",
                        "publication_description": "Encodes the declared observation structure.",
                        "publication_evaluation": "Compare matched controls under the registered split."}],
        "publication": {"language": "en", "title": "Bounded Representation Comparison", "method_name": "Registered representation",
                        "contribution_type": "objective_mechanism", "comparator_names": ["Registered reference", "Matched control"]},
    }), encoding="utf-8")


def test_loading_legacy_completed_run_preserves_original_delivery_record(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    run_id = "legacy-completed-delivery"
    _seed_public_benchmark_contract(tmp_path)
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "test",
            evidence_mode="synthetic_preview",
        )
    )
    definitions = engine._get_default_nodes()
    run_state = RunState(str(tmp_path), run_id)
    run_state.start(
        [
            {"id": node.id, "name": node.name, "skill": node.skill}
            for node in definitions
        ],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": {
                "run_experiment": False,
                "non_experiment_evidence_mode": "synthetic_preview",
            },
        },
    )
    for node in definitions:
        run_state.set_status(node.id, "done")
        run_state.accept(node.id, f"legacy-{node.id}", "deterministic:test")
    assert run_state.complete() is True
    legacy = run_state.load()
    assert legacy is not None
    assert "completion" not in legacy
    historical_finished_at = legacy["finished_at"]

    migrated = engine.get_persisted_run_state(str(tmp_path), run_id)

    assert migrated is not None
    assert migrated == legacy
    assert migrated["finished_at"] == historical_finished_at
    assert not (tmp_path / ".merak" / "DELIVERY_STATUS.json").exists()


def test_platform_checkpoint_reopens_when_runtime_implementation_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "platform-runtime-upgrade"
    run_state = RunState(str(tmp_path), run_id)
    options = {"max_revision_rounds": 3, "run_experiment": False}
    run_state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "submission",
            "options": options,
        },
    )
    run_state.set_revision_waiting(
        "results",
        round_number=3,
        cycle=1,
        gate={
            "reason": "deterministic platform repair required",
            "issues": ["canonical artifact repair did not run"],
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
        artifact_signature=engine._revision_artifact_signature(
            str(tmp_path),
            "results",
            options,
        ),
        runtime_signature="runtime:before-upgrade",
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(
        engine,
        "_revision_runtime_signature",
        lambda *_args, **_kwargs: "runtime:after-upgrade",
    )
    monkeypatch.setattr(engine, "execute", fake_execute)

    resumed = asyncio.run(
        engine.resume_persisted_run(run_id, str(tmp_path))
    )

    revision = RunState(str(tmp_path), run_id).revision_state("results")
    assert resumed == run_id
    assert captured["node_ids"] == ["results"]
    assert revision["round"] == 0
    assert revision["waiting"] is False
    assert revision["runtime_signature"] == "runtime:after-upgrade"
    assert "last_gate" not in revision
    assert "revision_progress" not in revision
    assert "stopped_for_no_progress" not in revision
    assert revision["runtime_resets"][-1]["reason"] == (
        "workflow runtime capability contract changed"
    )


def test_changing_bounded_revision_budget_reopens_waiting_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "revision-budget-change"
    original_options = {"max_revision_rounds": 3}
    run_state = RunState(str(tmp_path), run_id)
    run_state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "draft",
            "options": original_options,
        },
    )
    run_state.set_revision_waiting(
        "paper",
        round_number=3,
        cycle=1,
        gate={"reason": "quality gap", "issues": ["missing evidence"]},
        artifact_signature=engine._revision_artifact_signature(
            str(tmp_path),
            "paper",
        ),
        runtime_signature=engine._revision_runtime_signature(
            str(tmp_path),
            "paper",
            original_options,
        ),
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)

    resumed = asyncio.run(
        engine.resume_persisted_run(
            run_id=run_id,
            project_path=str(tmp_path),
            pipeline_options={"max_revision_rounds": 6},
        )
    )

    assert resumed == run_id
    assert captured["pipeline_options"]["max_revision_rounds"] == 6
    revision = RunState(str(tmp_path), run_id).revision_state("paper")
    assert revision["round"] == 0
    assert revision["waiting"] is False
    assert revision["runtime_resets"][-1]["reason"] == (
        "workflow runtime capability contract changed"
    )


def test_resumed_subset_uses_accepted_persisted_dependencies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        engine = WorkflowEngine()
        run_id = "resume-with-persisted-dependency"
        run_state = RunState(str(tmp_path), run_id)
        run_state.start(
            [
                {"id": "lit", "name": "Literature", "skill": "/research-lit"},
                {"id": "idea", "name": "Idea", "skill": "/idea-discovery"},
            ],
            {"direction": "test", "options": {}},
        )
        run_state.set_status("lit", "done")
        run_state.accept("lit", "lit-ok", "deterministic:test")

        resumed_node = WorkflowNode(
            id="idea",
            name="Idea",
            skill="/idea-discovery",
            depends_on=["lit"],
        )
        run = WorkflowRun(
            id=run_id,
            project_path=str(tmp_path),
            nodes=[resumed_node],
            status="running",
        )
        engine._runs[run_id] = run
        executed: list[str] = []

        async def immediate_sleep(_seconds: float) -> None:
            return None

        async def fake_execute_node(node: WorkflowNode, *_args, **_kwargs) -> str:
            executed.append(node.id)
            return "generated"

        async def fake_revision_loop(**kwargs):
            RunState(str(tmp_path), run_id).set_status("idea", "done")
            return {
                "accepted": True,
                "verdict_id": "idea-ok",
                "reviewer": "deterministic:test",
                "summary": "accepted",
            }, kwargs["initial_result"]

        monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
        monkeypatch.setattr(
            "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
            lambda *_args, **_kwargs: [],
        )
        monkeypatch.setattr(engine, "_execute_node", fake_execute_node)
        monkeypatch.setattr(engine, "_run_node_revision_loop", fake_revision_loop)

        await engine._execute_run(
            run,
            "test",
            opts={
                "human_checkpoint": False,
                "code_review": False,
                "research_quality_mode": "off",
            },
        )

        assert executed == ["idea"]
        state = RunState(str(tmp_path), run_id).load()
        assert state is not None
        assert state["phases"]["idea"]["status"] == "accepted"

    asyncio.run(scenario())


def test_upstream_artifact_owner_survives_reload_and_controls_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "upstream-owner-reload"
    run_state = RunState(str(tmp_path), run_id)
    run_state.start(
        [
            {"id": "exp-design", "name": "Experiment design", "skill": "/experiment-plan"},
            {"id": "figure", "name": "Figure", "skill": "/paper-figure"},
        ],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "draft",
            "options": {},
        },
    )
    source = tmp_path / "experiments" / "src" / "train.py"
    source.parent.mkdir(parents=True)
    source.write_text("def train():\n    return 1\n", encoding="utf-8")
    run_state.set_status("exp-design", "done")
    run_state.accept("exp-design", "design-ok", "deterministic:test")
    signature = engine._revision_artifact_signature(str(tmp_path), "exp-design")
    run_state.set_revision_waiting(
        "figure",
        round_number=3,
        cycle=1,
        gate={"reason": "upstream design invalid"},
        artifact_signature=signature,
        artifact_owner_id="exp-design",
    )

    reloaded = RunState(str(tmp_path), run_id).revision_state("figure")
    assert reloaded["artifact_owner_id"] == "exp-design"

    # Changing only the blocked downstream artifact must not reopen the loop.
    figure_manifest = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    figure_manifest.parent.mkdir(parents=True)
    figure_manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(engine.resume_persisted_run(run_id, str(tmp_path)))

    source.write_text("def train():\n    return 2\n", encoding="utf-8")
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["pipeline_options"]["resume_run_id"]

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(engine.resume_persisted_run(run_id, str(tmp_path)))

    assert resumed == run_id
    assert captured["node_ids"] == ["figure"]
    revision = RunState(str(tmp_path), run_id).revision_state("figure")
    assert revision["round"] == 0
    assert revision["waiting"] is False
    assert revision["runtime_resets"][-1]["reason"] == (
        "research artifact or validator signature changed before manual recovery"
    )




def test_resume_selection_expands_nonterminal_dependency_closure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "resume-dependency-closure"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [
            {"id": "audit", "name": "Audit", "skill": "/experiment-audit"},
            {"id": "compile", "name": "Compile", "skill": "/paper-compile"},
            {"id": "ppt", "name": "Slides", "skill": "/paper-talk"},
        ],
        {"direction": "test", "options": {}},
    )
    state.set_status("audit", "done")
    state.set_status("compile", "skipped", error="dependency not accepted")
    state.set_status("ppt", "skipped", error="dependency not accepted")
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(
        engine.resume_persisted_run(
            run_id,
            str(tmp_path),
            node_ids=["compile", "ppt"],
        )
    )

    assert resumed == run_id
    assert captured["node_ids"] == ["audit", "compile", "ppt"]


def test_resume_invalidates_accepted_descendants_of_nonterminal_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "resume-invalid-accepted-descendants"
    state = RunState(str(tmp_path), run_id)
    phase_ids = [
        "results",
        "narrative",
        "figure",
        "paper",
        "review",
        "audit",
        "compile",
        "ppt",
    ]
    state.start(
        [
            {"id": phase_id, "name": phase_id, "skill": f"/{phase_id}"}
            for phase_id in phase_ids
        ],
        {"direction": "test", "options": {}},
    )
    state.set_status("results", "done")
    for phase_id in ("narrative", "figure", "paper"):
        state.set_status(phase_id, "done")
        state.accept(phase_id, f"{phase_id}-accepted", "deterministic:test")
    state.set_status("review", "done")
    for phase_id in ("audit", "compile", "ppt"):
        state.set_status(phase_id, "done")
        state.accept(phase_id, f"{phase_id}-accepted", "deterministic:test")

    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(
        engine.resume_persisted_run(
            run_id,
            str(tmp_path),
            node_ids=["review", "audit", "compile", "ppt"],
        )
    )

    assert resumed == run_id
    assert captured["node_ids"] == phase_ids
    phases = state.load()["phases"]
    assert phases["results"]["status"] == "done"
    assert phases["review"]["status"] == "done"
    expected_upstream = {
        "narrative": "results",
        "figure": "narrative",
        "paper": "figure",
        "audit": "review",
        "compile": "audit",
        "ppt": "compile",
    }
    for phase_id in ("narrative", "figure", "paper", "audit", "compile", "ppt"):
        assert phases[phase_id]["status"] == "done"
        invalidations = phases[phase_id]["details"]["acceptance_invalidations"]
        assert invalidations
        assert expected_upstream[phase_id] in invalidations[-1]["reason"]


def test_paper_only_resume_rejects_legacy_simulation_without_rewriting_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "resume-legacy-simulation-paper-only"
    options = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    }
    _seed_public_benchmark_contract(tmp_path)
    asyncio.run(
        experiment_placeholder_service.ensure(
            tmp_path,
            "deterministic simulation migration",
            evidence_mode="synthetic_preview",
        )
    )
    manifest_path = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_manifest["schema"] = 4
    manifest_path.write_text(
        json.dumps(legacy_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    baseline = workflow_input_service.capture(tmp_path, [], run_id=run_id)
    state = RunState(str(tmp_path), run_id)
    phase_ids = [
        "exp-design",
        "exp-run",
        "results",
        "narrative",
        "figure",
        "paper",
    ]
    state.start(
        [
            {"id": phase_id, "name": phase_id, "skill": f"/{phase_id}"}
            for phase_id in phase_ids
        ],
        {
            "direction": "deterministic simulation migration",
            "effort": "balanced",
            "assurance": "draft",
            "options": options,
        },
        input_baseline=baseline,
    )
    for phase_id in phase_ids[:-1]:
        state.set_status(phase_id, "done")
        acceptance_details = {}
        if phase_id in {"results", "figure"}:
            acceptance_details = {
                "artifact_snapshot": snapshot_paths(
                    tmp_path,
                    [manifest_path],
                ),
                "input_baseline_snapshot_id": baseline["snapshot_id"],
            }
        state.accept(
            phase_id,
            f"{phase_id}-schema4",
            "deterministic:test",
            details=acceptance_details,
        )

    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)
    protected = {path.relative_to(tmp_path).as_posix(): path.read_bytes()
                 for directory in (tmp_path / "ideas", tmp_path / "experiments", tmp_path / "figures")
                 for path in directory.rglob("*") if path.is_file()}
    before_phases = state.load()["phases"]
    with pytest.raises(ValueError, match="Unsupported simulation schema"):
        asyncio.run(engine.resume_persisted_run(run_id, str(tmp_path), node_ids=["paper"]))
    assert captured == {}
    assert protected == {relative: (tmp_path / relative).read_bytes() for relative in protected}
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["schema"] == 4
    assert state.load()["phases"] == before_phases


def test_validator_upgrade_allows_one_revalidation_of_an_old_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = WorkflowEngine()
    run_id = "legacy-revision-signature"
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
    legacy_signature = engine._verdict_id(
        "revision-waiting:paper",
        engine._required_artifacts_for_node(str(tmp_path), "paper"),
    )
    run_state.set_revision_waiting(
        "paper",
        round_number=3,
        cycle=1,
        gate={"reason": "legacy validator finding"},
        artifact_signature=legacy_signature,
    )
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["pipeline_options"]["resume_run_id"]

    monkeypatch.setattr(engine, "execute", fake_execute)
    resumed = asyncio.run(
        engine.resume_persisted_run(
            run_id=run_id,
            project_path=str(tmp_path),
            checkpoint_feedback="",
        )
    )

    assert resumed == run_id
    assert captured["node_ids"] == ["paper"]


def test_checkpoint_accepts_feedback_and_can_be_extended(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = WorkflowEngine()
        node = WorkflowNode(id="paper", name="Paper", skill="/paper")
        run = WorkflowRun(id="checkpoint-test", project_path=str(tmp_path), nodes=[node])
        engine._runs[run.id] = run
        RunState(str(tmp_path), run.id).start(
            [{"id": "paper", "name": "Paper", "skill": "/paper"}],
            {"options": {"human_checkpoint": True}},
        )
        events: list[tuple[str, dict]] = []

        async def on_event(event_type: str, payload: dict) -> None:
            events.append((event_type, payload))

        run.on_event = on_event
        waiter = asyncio.create_task(engine._wait_for_human_checkpoint(run, node, 30))
        await asyncio.sleep(0)
        original_deadline = run.checkpoint_deadline
        extended = await engine.extend_checkpoint(run.id, 300)
        assert run.checkpoint_deadline > original_deadline
        assert extended["remaining_seconds"] >= 329
        assert await engine.resume_run(run.id, "Keep the core hypothesis unchanged") is True
        assert RunState(str(tmp_path), run.id).human_checkpoint_consumed("paper") is True
        assert await waiter == "Keep the core hypothesis unchanged"
        from server.workflows.operator_feedback import current_operator_feedback
        restarted = WorkflowRun(id=run.id, project_path=str(tmp_path))
        assert current_operator_feedback(restarted, "paper") == "Keep the core hypothesis unchanged"
        assert run.status == "running"
        assert run.checkpoint_deadline == 0
        assert any(event_type == "checkpoint_extended" for event_type, _ in events)

    asyncio.run(scenario())


def test_late_checkpoint_resume_is_a_noop(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(id="already-running", project_path=str(tmp_path), status="running")
    engine._runs[run.id] = run
    assert asyncio.run(engine.resume_run(run.id, "late feedback")) is False


def test_results_prompt_uses_discovered_template_paths(tmp_path: Path) -> None:
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / "ideas.md").write_text("# Idea\nA robust method.", encoding="utf-8")
    _seed_public_benchmark_contract(tmp_path)
    asyncio.run(experiment_placeholder_service.ensure(tmp_path, "robust learning"))

    engine = WorkflowEngine()
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": False})
    prompt = engine._input_results("robust learning", {}, run)

    canonical = tmp_path / "experiments" / "results" / "templates"
    assert str(canonical / "PLANNED_RESULT_MANIFEST.json") in prompt
    assert str(canonical / "main_comparison.csv") in prompt
    assert str(tmp_path / "paper" / "tables" / "planned_result_templates.tex") in prompt
    assert "禁止猜测并探测这些错误别名" in prompt
    assert "demo_value" not in prompt
    assert "测量字段必须保持空白" in prompt


def test_result_prompt_treats_selected_fixed_benchmark_as_complete_results(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    prompt = engine._input_results("robust learning", {}, run)

    expected_manifest = (
        tmp_path
        / "experiments"
        / "results"
        / "simulated"
        / "SIMULATION_MANIFEST.json"
    )
    assert "完整固定基准结果包" in prompt
    assert str(expected_manifest) in prompt
    assert "完整分析主比较、消融、训练动态、鲁棒性、错误分析、校准和效率结果" in prompt
    assert "测量字段必须保持空白" not in prompt
    assert "没有真实指标时生成 planned-result analysis" not in prompt


def test_review_gate_rejects_prose_score_without_structured_rounds(tmp_path: Path) -> None:
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"final_score": 4.0, "final_verdict": "major_revision"}),
        encoding="utf-8",
    )
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\\begin{document}Paper\\end{document}", encoding="utf-8")

    result = """
Earlier draft score: 4/10, verdict major_revision.
### Final Score: 6.5/10
### Final Verdict: almost
"""
    gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert "structured review" in gate["reason"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["final_score"] == 4.0
    assert persisted["final_verdict"] == "major_revision"


def test_review_gate_uses_structured_review_state(tmp_path: Path) -> None:
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({
            "final_score": 6.5,
            "final_verdict": "almost",
            "reviewer_model": "independent-reviewer",
            "rounds": [{
                "round": 1,
                "score": 6.5,
                "verdict": "almost",
                "weaknesses": ["One bounded residual risk."],
                "action_items": ["Keep the limitation visible."],
            }],
        }),
        encoding="utf-8",
    )
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\\begin{document}Paper\\end{document}", encoding="utf-8")

    gate = WorkflowEngine()._review_acceptance_gate(
        str(tmp_path),
    )

    assert gate["accepted"] is True
    assert gate["details"]["score"] == 6.5
    assert gate["details"]["verdict"] == "almost"
    assert gate["details"]["source"] == "review-state"

    stale_gate = WorkflowEngine()._review_acceptance_gate(
        str(tmp_path),
        review_started_at=state_path.stat().st_mtime + 30,
    )
    assert stale_gate["accepted"] is False
    assert stale_gate["reason"] == "structured review state is stale"


def test_untrusted_review_annotations_do_not_grant_upstream_repair_authority(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({
            "final_score": 4.5,
            "final_verdict": "major_revision",
            "evidence_mode": "executed",
            "managed_by": "cross_model_review_loop",
            "bounded_complete": True,
            "rounds": [{
                "round": 1,
                "score": 4.5,
                "verdict": "major_revision",
                "weaknesses": [],
                "action_items": [
                    "[owner=results] [target=experiments/results/analysis.md] "
                    "Report per-seed confidence intervals and provenance."
                ],
            }],
        }),
        encoding="utf-8",
    )
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Paper\\end{document}",
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    gate = engine._review_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    finding = gate["details"]["review_findings"][0]
    assert finding["owner_node"] == "results"
    assert finding["target_files"] == ["experiments/results/analysis.md"]
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    owner = engine._revision_owner_for_gate(
        review,
        WorkflowRun(
            id="review-owner-target",
            nodes=[review],
            options={"run_experiment": True},
        ),
        gate,
    )
    # Parsed annotation is diagnostic text, not a verified review invocation.
    # The malformed review must be re-executed before it can direct an upstream edit.
    assert owner.id == "review"


def test_review_gate_rejects_failed_paper_reconciliation(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({
            "final_score": 7.0,
            "final_verdict": "almost",
            "rounds": [{
                "round": 1,
                "score": 7.0,
                "verdict": "almost",
                "weaknesses": [],
                "action_items": [],
            }],
            "paper_reconciliation": {
                "passed": False,
                "issues": ["experiments section violates its local contract"],
            },
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
    assert gate["reason"] == (
        "reviewed paper failed deterministic reconciliation"
    )
    assert "experiments section" in gate["summary"]
