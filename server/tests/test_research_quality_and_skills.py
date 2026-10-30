from __future__ import annotations

from server.tests._research_quality_and_skills_support import (
    Path as Path,
    ToolCall as ToolCall,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _load_canonical_skills as _load_canonical_skills,
    _python_symbols as _python_symbols,
    _write_selected_idea_contract as _write_selected_idea_contract,
    agent_engine as agent_engine,
    asyncio as asyncio,
    get_skill_input_schema as get_skill_input_schema,
    hashlib as hashlib,
    invoke_skill as invoke_skill,
    json as json,
    method_contract_service as method_contract_service,
    pytest as pytest,
    register_all_tools as register_all_tools,
    research_quality_service as research_quality_service,
    skill_orchestrator as skill_orchestrator,
    skill_registry as skill_registry,
)


def test_finalize_integration_contract_owns_status_and_frozen_idea_hash(
    tmp_path: Path,
) -> None:
    _write_selected_idea_contract(
        tmp_path,
        "Auditable mechanism",
        [{"id": "M1", "name": "Mechanism"}],
    )
    experiments = tmp_path / "experiments"
    experiments.mkdir(exist_ok=True)
    contract = experiments / "METHOD_CONTRACT.json"
    contract.write_text(
        json.dumps({
            "schema": 2,
            "status": "implementation_in_progress",
            "idea_contract_sha256": "stale",
            "scientific_scene": {
                "schema": 1,
                "objects": [{
                    "id": "method", "kind": "operation",
                    "label": "Auditable mechanism",
                    "source_path": "ideas/SELECTED_IDEA.json",
                }],
                "relations": [],
            },
            "implementation_checks": [{
                "id": "I1",
                "description": "Bound integration route",
                "evidence": [{
                    "path": "experiments/src/train.py",
                    "symbols": ["main"],
                }],
            }],
        }),
        encoding="utf-8",
    )

    assert method_contract_service.finalize_integration_contract(
        tmp_path, {"passed": True, "output_sha256": "b" * 64},
    )
    finalized = json.loads(contract.read_text(encoding="utf-8"))
    expected = hashlib.sha256(
        (tmp_path / "ideas" / "SELECTED_IDEA.json").read_bytes()
    ).hexdigest()
    assert finalized["schema"] == 2
    assert finalized["status"] == "implemented"
    assert finalized["idea_contract_sha256"] == expected


def test_finalize_integration_contract_rejects_old_schema_without_rewriting(
    tmp_path: Path,
) -> None:
    _write_selected_idea_contract(
        tmp_path,
        "Auditable mechanism",
        [{"id": "M1", "name": "Mechanism"}],
    )
    experiments = tmp_path / "experiments"
    experiments.mkdir(exist_ok=True)
    contract = experiments / "METHOD_CONTRACT.json"
    original = {
        "schema": 1,
        "status": "implementation_in_progress",
        "idea_contract_sha256": "stale",
    }
    contract.write_text(json.dumps(original), encoding="utf-8")

    assert method_contract_service.finalize_integration_contract(
        tmp_path, {"passed": True, "output_sha256": "c" * 64},
    ) is False
    assert json.loads(contract.read_text(encoding="utf-8")) == original


def test_python_symbol_evidence_includes_module_level_registries(tmp_path: Path) -> None:
    source = tmp_path / "train.py"
    source.write_text(
        "VARIANT_REGISTRY = {'full': object()}\n"
        "ANNOTATED_REGISTRY: dict[str, object] = {}\n"
        "def build_variant():\n"
        "    LOCAL_ONLY = {}\n"
        "    return VARIANT_REGISTRY\n",
        encoding="utf-8",
    )

    symbols, error = _python_symbols(source)

    assert error == ""
    assert {"VARIANT_REGISTRY", "ANNOTATED_REGISTRY", "build_variant"} <= symbols
    assert "LOCAL_ONLY" not in symbols


def test_python_symbol_evidence_accepts_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "train.py"
    source.write_text(
        "VARIANT_REGISTRY = {'full': object()}\n",
        encoding="utf-8-sig",
    )

    symbols, error = _python_symbols(source)

    assert error == ""
    assert "VARIANT_REGISTRY" in symbols


def test_python_symbol_evidence_includes_class_and_instance_fields(tmp_path: Path) -> None:
    source = tmp_path / "models.py"
    source.write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class VariantSpec:\n"
        "    parameter_match_width_multiplier: float = 1.0\n"
        "    family = 'factorized'\n"
        "\n"
        "class FactorizedEEGTokenizer:\n"
        "    default_fusion = 'gated'\n"
        "\n"
        "    def __init__(self):\n"
        "        self.fusion = object()\n"
        "        local_only = object()\n"
        "\n"
        "    def update(self):\n"
        "        self.revision_count += 1\n",
        encoding="utf-8",
    )

    symbols, error = _python_symbols(source)

    assert error == ""
    assert {
        "VariantSpec.parameter_match_width_multiplier",
        "VariantSpec.family",
        "FactorizedEEGTokenizer.default_fusion",
        "FactorizedEEGTokenizer.fusion",
        "FactorizedEEGTokenizer.revision_count",
    } <= symbols
    assert "local_only" not in symbols
    assert "FactorizedEEGTokenizer.local_only" not in symbols
    assert "FactorizedEEGTokenizer.nonexistent" not in symbols


def test_research_quality_is_reported_when_an_independent_gate_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_quality_service, "evaluate", lambda *_args, **_kwargs: {
        "applicable": True,
        "passed": True,
        "score": 1.0,
        "threshold": 0.58,
        "issues": [],
        "report_path": str(tmp_path / "quality.json"),
    })
    gate = {
        "accepted": False,
        "reason": "implementation contract failed",
        "details": {
            "implementation_contract": {
                "applicable": True,
                "passed": False,
            },
        },
    }

    result = research_quality_service.apply_gate(
        gate,
        str(tmp_path),
        "exp-design",
        "submission",
        "rigorous",
    )

    assert result["accepted"] is False
    assert result["reason"] == "implementation contract failed"
    assert result["details"]["research_quality"]["passed"] is True
    assert result["details"]["implementation_contract"]["passed"] is False


def test_stage_skill_plan_loads_only_the_owner_and_tracks_real_execution(tmp_path: Path) -> None:
    total = _load_canonical_skills()
    assert total >= 70

    plan = skill_orchestrator.select(
        "figure",
        "/paper-figure",
        str(tmp_path),
        {"run_experiment": False, "research_quality_mode": "rigorous"},
    )
    assert plan.primary == "rich-svg-figure"
    assert "excalidraw-skill" in plan.specialists
    assert "mermaid-diagram" in plan.specialists
    assert "paper-figure" not in plan.selected
    assert len(plan.selected) < total

    context = skill_orchestrator.render_context(plan)
    owner = skill_orchestrator.render_owner(plan)
    assert "Skill Invocation Routing" in context
    assert "Available on-demand delegates" in context
    assert "Specialist policy:" not in context
    assert "Loaded MERAK Skill Invocation" in owner
    assert "Rich SVG Figure" in owner
    assert "skip /paper-figure Phase 2a" in " ".join(plan.reasons)
    assert len(context) < 3000

    trace = skill_orchestrator.record(str(tmp_path), "skill-run", plan)
    payload = json.loads(trace.read_text(encoding="utf-8"))
    assert payload["registry_total"] == total
    assert payload["stages"]["figure"]["primary_status"] == "selected"
    assert payload["stages"]["figure"]["specialist_status"] == "available-on-demand"
    assert payload["coverage_ratio"] < 1.0

    skill_orchestrator.mark_execution(
        str(tmp_path),
        "skill-run",
        "figure",
        "rich-svg-figure",
        "completed",
        session_id="session-1",
        output="figure manifest written",
    )
    payload = json.loads(trace.read_text(encoding="utf-8"))
    stage = payload["stages"]["figure"]
    assert stage["primary_status"] == "completed"
    assert stage["primary_session_id"] == "session-1"
    invocation = stage["invocations"][-1]
    assert invocation["output_sha256"]
    assert Path(invocation["skill_source"]).name == "SKILL.md"
    assert len(invocation["skill_sha256"]) == 64
    assert invocation["skill_bytes"] > 0
    assert payload["unique_skills_selected"] == ["rich-svg-figure"]
    assert "rich-svg-figure" in payload["unique_skills_candidates"]


def test_figure_skill_owner_uses_current_system_routing(tmp_path: Path) -> None:
    _load_canonical_skills()
    figures = tmp_path / "figures"
    figures.mkdir()
    spec = {"id": "method_architecture", "kind": "figure", "generation_policy": "generate",
            "producer_kind": "deterministic", "production_strategy": "deterministic_architecture",
            "figure_nature": "conceptual", "composition_owner": "runtime", "full_svg_authority": False,
            "recommended_backend": "figurespec", "recommended_skill": "figure-spec"}
    spec_path = figures / "FIGURE_SPECS.json"
    spec_path.write_text(json.dumps({"schema": 4, "publication_label_schema": 1, "production_policy_schema": 1,
                                    "figures": [spec]}), encoding="utf-8")

    with_results = skill_orchestrator.select(
        "figure",
        "/paper-figure",
        str(tmp_path),
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "existing_results",
            "illustration_mode": "auto",
        },
    )
    assert with_results.primary == "paper-figure"
    assert with_results.execution_kind == "runtime_owned"
    spec.update({"producer_kind": "model", "production_strategy": "model_composed_full_svg", "composition_owner": "model",
                 "full_svg_authority": True, "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure"})
    spec_path.write_text(json.dumps({"schema": 4, "publication_label_schema": 1, "production_policy_schema": 1,
                                    "figures": [spec]}), encoding="utf-8")
    current_phase_2b = skill_orchestrator.select(
        "figure",
        "/paper-figure",
        str(tmp_path),
        {
            "run_experiment": False,
            "non_experiment_evidence_mode": "design_only",
            "illustration_mode": "auto",
        },
    )

    assert current_phase_2b.primary == "model-svg-figure"
    assert current_phase_2b.execution_kind == "hybrid"
    assert "paper-figure" not in current_phase_2b.selected
    assert skill_registry.get_skill("paper-illustration-image2") is None
    with pytest.raises(ValueError, match="unsupported illustration mode"):
        skill_orchestrator.select("figure", "/paper-figure", str(tmp_path), {"illustration_mode": "figurespec"})
    with pytest.raises(ValueError, match="unsupported illustration mode"):
        skill_orchestrator.select(
            "figure", "/paper-figure", str(tmp_path),
            {"run_experiment": False, "illustration_mode": "codex-image2"},
        )


def test_excalidraw_skill_has_a_first_class_input_schema() -> None:
    schema = get_skill_input_schema("excalidraw-skill")
    fields = {item["name"]: item for item in schema["fields"]}

    assert schema["requires"] == ["description", "artifact_name"]
    assert fields["scientific_role"]["default"] == "method"
    assert fields["output_dir"]["default"] == "./figures/diagrams"

    paper_figure = get_skill_input_schema("paper-figure")
    figure_type = next(
        item for item in paper_figure["fields"] if item["name"] == "figure_type"
    )
    assert "excalidraw" in figure_type["options"]


def test_skill_policy_resolves_installed_shared_reference_paths() -> None:
    _load_canonical_skills()
    metadata = skill_registry.get_skill("paper-write")
    assert metadata is not None and metadata.file_path

    source_path = Path(metadata.file_path).resolve()
    writing_principles = (
        source_path.parent / "../shared-references/writing-principles.md"
    ).resolve()
    policy = skill_orchestrator.full_policy("paper-write")

    assert writing_principles.is_file()
    assert str(writing_principles) in policy
    assert "../shared-references/writing-principles.md" not in policy


def test_skill_registry_parses_declared_tools_for_runtime_enforcement() -> None:
    _load_canonical_skills()

    pipeline = skill_registry.get_skill("paper-writing")
    planner = skill_registry.get_skill("paper-plan")

    assert pipeline is not None and {"Read", "Write", "Skill"} <= set(pipeline.allowed_tools)
    assert planner is not None and {"Read", "Write", "reviewer_api"} <= set(
        planner.allowed_tools
    )
    assert "mcp__codex__codex" not in planner.allowed_tools
    assert skill_registry.resolve_allowed_tools(
        "research-lit",
        ["Read", "mcp__zotero__search", "mcp__obsidian-vault__read", "Skill"],
    ) == ["Read", "mcp__zotero__search", "mcp__obsidian-vault__read"]

    novelty = skill_registry.get_skill("novelty-check")
    assert novelty is not None
    assert {"Write", "Edit"} <= set(novelty.allowed_tools)


def test_novelty_workflow_merges_canonical_authoring_tools(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _load_canonical_skills()
    register_all_tools()
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="novelty",
        name="Novelty",
        skill="/novelty-check",
    )
    run = WorkflowRun(
        id="novelty-tools",
        project_path=str(tmp_path),
        nodes=[node],
        options={"run_experiment": False},
    )
    observed: dict = {}

    async def fake_run(session_id: str, user_message: str, **kwargs) -> str:
        observed["tools"] = list(kwargs.get("tools") or [])
        observed["policy"] = agent_engine.get_session(session_id).tool_policy
        return "novelty artifacts written"

    async def fake_emit(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(agent_engine, "run", fake_run)
    monkeypatch.setattr(engine, "_emit", fake_emit)
    monkeypatch.setattr(engine, "_build_node_input", lambda *_args: "check novelty")
    from unittest.mock import AsyncMock
    from server.workflows import node_execution_coordinator
    # This unit checks tool wiring only; retrieval and output acceptance have
    # dedicated contract tests and must not perform live network calls here.
    monkeypatch.setattr(engine, "_ensure_stage_search_evidence", AsyncMock(return_value=""))
    monkeypatch.setattr(node_execution_coordinator, "ensure_primary_output_delivery", AsyncMock())

    asyncio.run(
        engine._execute_node(
            node,
            run,
            "test direction",
            "balanced",
            "draft",
            opts={"run_experiment": False},
        )
    )

    assert {"Read", "Write", "Edit", "Glob", "Grep"} <= set(observed["tools"])
    assert observed["policy"] == "workflow_artifacts"


def test_invoke_skill_uses_isolated_full_policy_and_project_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    register_all_tools()
    _load_canonical_skills()
    observed: dict = {}

    async def fake_run(session_id: str, user_message: str, **kwargs) -> str:
        session = agent_engine.get_session(session_id)
        assert session is not None
        observed.update({
            "project_path": session.project_path,
            "readonly_roots": list(session.readonly_roots),
            "context_key": session.context_key,
            "system": session.messages[0].content,
            "user": user_message,
            "tools": kwargs.get("tools", []),
        })
        return "Paper plan completed."

    monkeypatch.setattr(agent_engine, "run", fake_run)

    result = asyncio.run(
        invoke_skill(
            "paper-plan",
            "Write the canonical paper plan.",
            project_path=str(tmp_path),
            parent_context="skill-chain:research-refine",
        )
    )

    assert result == "Paper plan completed."
    assert observed["project_path"] == str(tmp_path.resolve())
    assert observed["context_key"] == "skill-chain:research-refine>paper-plan"
    assert "# Paper Plan:" in observed["system"]
    planner = skill_registry.get_skill("paper-plan")
    assert planner is not None and planner.file_path
    writing_principles = (
        Path(planner.file_path).resolve().parent
        / "../shared-references/writing-principles.md"
    ).resolve()
    assert str(writing_principles) in observed["system"]
    assert "../shared-references/writing-principles.md" not in observed["system"]
    assert str(writing_principles.parent) in observed["readonly_roots"]
    assert "Write the canonical paper plan." in observed["user"]
    assert "reviewer_api" in observed["tools"]
    assert "mcp__codex__codex" not in observed["tools"]
    assert "mcp__codex__codex" not in observed["system"]
    assert "Codex MCP" not in observed["system"]
    assert "Skill" not in observed["tools"]
    assert "Agent" not in observed["tools"]
    traces = list((tmp_path / ".merak" / "skill-invocations").glob("*_paper-plan.json"))
    assert len(traces) == 1
    trace = json.loads(traces[0].read_text(encoding="utf-8"))
    assert trace["status"] == "completed"
    assert Path(trace["skill_source"]).name == "SKILL.md"
    assert len(trace["skill_sha256"]) == 64
    assert trace["skill_bytes"] > 0


def test_workflow_tool_policy_binds_relative_paths_and_skill_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    register_all_tools()
    observed: dict = {}

    async def fake_skill_handler(**kwargs) -> str:
        observed.update(kwargs)
        return "delegate completed"

    monkeypatch.setitem(agent_engine._tools, "Skill", fake_skill_handler)
    session = agent_engine.create_session()
    session.project_path = str(tmp_path)
    session.context_key = "skill-chain:paper-write"
    session.workflow_node_id = "paper"
    session.tool_policy = "workflow_artifacts"

    write_result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="write-relative",
                name="Write",
                arguments={"path": "paper/section.tex", "content": "Grounded text."},
            ),
        )
    )
    skill_result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="delegate",
                name="Skill",
                arguments={"skill_name": "/citation-audit", "arguments": "paper/"},
            ),
        )
    )

    assert write_result.success
    assert (tmp_path / "paper" / "section.tex").read_text(encoding="utf-8") == "Grounded text."
    assert skill_result.success
    assert observed["project_path"] == str(tmp_path)
    assert observed["parent_context"] == "skill-chain:paper-write"
    assert observed["workflow_node_id"] == "paper"


def test_figure_workflow_cannot_edit_frozen_upstream_contracts(
    tmp_path: Path,
) -> None:
    register_all_tools()
    idea = tmp_path / "ideas" / "SELECTED_IDEA.json"
    idea.parent.mkdir(parents=True)
    idea.write_text('{"status":"accepted"}\n', encoding="utf-8")

    session = agent_engine.create_session()
    session.project_path = str(tmp_path)
    session.context_key = "skill-chain:paper-figure"
    session.workflow_node_id = "figure"
    session.tool_policy = "workflow_artifacts"

    blocked = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="figure-edit-frozen-idea",
                name="Edit",
                arguments={
                    "path": str(idea),
                    "old_text": '"accepted"',
                    "new_text": '"changed-by-figure"',
                },
            ),
        )
    )
    blocked_spec = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="figure-write-owned-spec",
                name="Write",
                arguments={
                    "path": "figures/FIGURE_SPECS.json",
                        "content": '{"schema":4,"publication_label_schema":1,"figures":[]}\n',
                },
            ),
        )
    )

    assert blocked.success is False
    assert "cannot write outside its owned artifacts" in (blocked.error or "")
    assert idea.read_text(encoding="utf-8") == '{"status":"accepted"}\n'
    assert blocked_spec.success is False
    assert "runtime-owned" in (blocked_spec.error or "")
    assert not (tmp_path / "figures" / "FIGURE_SPECS.json").exists()


def test_cancelling_parent_tool_cancels_nested_skill(tmp_path: Path, monkeypatch) -> None:
    register_all_tools()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hanging_skill_handler(**_kwargs) -> str:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setitem(agent_engine._tools, "Skill", hanging_skill_handler)
    session = agent_engine.create_session()
    session.project_path = str(tmp_path)
    session.context_key = "skill-chain:paper-figure"
    session.tool_policy = "workflow_artifacts"

    async def exercise() -> None:
        task = asyncio.create_task(
            agent_engine._execute_tool(
                session,
                ToolCall(
                    id="nested-figure-skill",
                    name="Skill",
                    arguments={"skill_name": "/excalidraw-skill"},
                ),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), timeout=1.0)

    asyncio.run(exercise())


def test_nested_skill_has_bounded_wall_clock_timeout(tmp_path: Path, monkeypatch) -> None:
    register_all_tools()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hanging_skill_handler(**_kwargs) -> str:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setitem(agent_engine._tools, "Skill", hanging_skill_handler)
    monkeypatch.setattr("server.agent.engine.NESTED_SKILL_WALL_TIMEOUT", 0.01)
    monkeypatch.setattr("server.agent.engine.NESTED_SKILL_HEARTBEAT_INTERVAL", 0.005)
    monkeypatch.setattr("server.agent.engine.NESTED_SKILL_CANCEL_GRACE", 0.1)
    session = agent_engine.create_session()
    session.project_path = str(tmp_path)
    session.context_key = "skill-chain:paper-figure"
    session.tool_policy = "workflow_artifacts"

    async def exercise() -> None:
        result = await agent_engine._execute_tool(
            session,
            ToolCall(
                id="timed-nested-figure-skill",
                name="Skill",
                arguments={"skill_name": "/excalidraw-skill"},
            ),
        )
        assert started.is_set()
        await asyncio.wait_for(cancelled.wait(), timeout=1.0)
        assert result.success is False
        assert "wall-clock deadline exceeded" in (result.error or "")
        assert "/excalidraw-skill" in (result.error or "")

    asyncio.run(exercise())


def test_workflow_skill_shared_references_are_read_only(
    tmp_path: Path,
) -> None:
    register_all_tools()
    project = tmp_path / "project"
    project.mkdir()
    shared = tmp_path / "installed-skills" / "shared-references"
    shared.mkdir(parents=True)
    reference = shared / "writing-principles.md"
    reference.write_text("# Grounded writing policy", encoding="utf-8")

    session = agent_engine.create_session()
    session.project_path = str(project)
    session.readonly_roots = [str(shared)]
    session.tool_policy = "workflow_artifacts"

    read_result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="read-skill-reference",
                name="Read",
                arguments={"path": str(reference)},
            ),
        )
    )
    write_result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="write-skill-reference",
                name="Write",
                arguments={"path": str(reference), "content": "modified"},
            ),
        )
    )
    other = tmp_path / "private.txt"
    other.write_text("private", encoding="utf-8")
    unrelated_result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="read-unrelated-external-file",
                name="Read",
                arguments={"path": str(other)},
            ),
        )
    )

    assert read_result.success is True
    assert "Grounded writing policy" in read_result.output
    assert write_result.success is False
    assert unrelated_result.success is False
    assert reference.read_text(encoding="utf-8") == "# Grounded writing policy"


def test_workflow_read_recovers_a_shortened_shared_reference_install_path(
    tmp_path: Path,
) -> None:
    """A guessed install prefix must resolve only into the verified root."""
    register_all_tools()
    project = tmp_path / "project"
    project.mkdir()
    shared = tmp_path / "actual-install" / "merak-skills" / "shared-references"
    shared.mkdir(parents=True)
    reference = shared / "writing-principles.md"
    reference.write_text("# Verified shared policy", encoding="utf-8")

    session = agent_engine.create_session()
    session.project_path = str(project)
    session.readonly_roots = [str(shared)]
    session.tool_policy = "workflow_artifacts"
    guessed = tmp_path / "wrong-install" / "merak-skills" / "shared-references" / reference.name

    result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="read-guessed-shared-reference",
                name="Read",
                arguments={"path": str(guessed)},
            ),
        )
    )

    assert result.success is True
    assert "Verified shared policy" in result.output


def test_workflow_tool_policy_blocks_model_authored_runtime_provenance(
    tmp_path: Path,
) -> None:
    register_all_tools()
    session = agent_engine.create_session()
    session.project_path = str(tmp_path)
    session.tool_policy = "workflow_artifacts"
    evidence_path = tmp_path / "literature" / "SEARCH_EVIDENCE.json"

    result = asyncio.run(
        agent_engine._execute_tool(
            session,
            ToolCall(
                id="write-runtime-evidence",
                name="Write",
                arguments={
                    "path": str(evidence_path),
                    "content": '{"model_claim": "searched"}',
                },
            ),
        )
    )

    assert result.success is False
    assert "runtime-owned" in (result.error or "")
    assert not evidence_path.exists()


def test_chat_and_workflow_discovery_policies_are_isolated(tmp_path: Path) -> None:
    register_all_tools()
    literature = tmp_path / "literature"
    literature.mkdir()
    (literature / "survey.md").write_text("# Survey", encoding="utf-8")
    runtime_dir = tmp_path / ".merak"
    runtime_dir.mkdir()
    (runtime_dir / "run.json").write_text('{"status":"running"}', encoding="utf-8")

    workflow = agent_engine.create_session()
    workflow.project_path = str(tmp_path)
    workflow.tool_policy = "workflow_artifacts"

    workflow_literature = asyncio.run(
        agent_engine._execute_tool(
            workflow,
            ToolCall(
                id="workflow-root-literature",
                name="Glob",
                arguments={"directory": str(tmp_path), "pattern": "literature/*"},
            ),
        )
    )
    workflow_runtime = asyncio.run(
        agent_engine._execute_tool(
            workflow,
            ToolCall(
                id="workflow-root-runtime",
                name="Glob",
                arguments={"directory": str(tmp_path), "pattern": ".merak/*"},
            ),
        )
    )
    workflow_outside = asyncio.run(
        agent_engine._execute_tool(
            workflow,
            ToolCall(
                id="workflow-outside",
                name="Glob",
                arguments={"directory": str(tmp_path.parent), "pattern": "*"},
            ),
        )
    )
    workflow_pattern_escape = asyncio.run(
        agent_engine._execute_tool(
            workflow,
            ToolCall(
                id="workflow-pattern-escape",
                name="Glob",
                arguments={"directory": str(tmp_path), "pattern": "../*"},
            ),
        )
    )

    assert workflow_literature.success
    assert "survey.md" in workflow_literature.output
    assert workflow_runtime.success
    assert "run.json" in workflow_runtime.output
    assert not workflow_outside.success
    assert "科研工作流" in (workflow_outside.error or "")
    assert "Chat 面板" not in (workflow_outside.error or "")
    assert not workflow_pattern_escape.success
    assert "科研工作流" in (workflow_pattern_escape.error or "")

    chat = agent_engine.create_session()
    chat.project_path = str(tmp_path)
    chat.tool_policy = "research_artifacts"
    chat_root = asyncio.run(
        agent_engine._execute_tool(
            chat,
            ToolCall(
                id="chat-root",
                name="Glob",
                arguments={"directory": str(tmp_path), "pattern": "literature/*"},
            ),
        )
    )
    chat_literature = asyncio.run(
        agent_engine._execute_tool(
            chat,
            ToolCall(
                id="chat-literature",
                name="Glob",
                arguments={"directory": str(literature), "pattern": "*"},
            ),
        )
    )
    chat_runtime = asyncio.run(
        agent_engine._execute_tool(
            chat,
            ToolCall(
                id="chat-runtime",
                name="Read",
                arguments={"path": str(runtime_dir / "run.json")},
            ),
        )
    )

    assert not chat_root.success
    assert "Chat 面板" in (chat_root.error or "")
    assert chat_literature.success
    assert "survey.md" in chat_literature.output
    assert not chat_runtime.success
    assert "Chat 面板" in (chat_runtime.error or "")


def test_narrative_stage_executes_paper_plan_delegate_before_figures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "paper").mkdir()
    (tmp_path / "NARRATIVE_REPORT.md").write_text(
        "# Narrative\nA domain contribution grounded in evidence.",
        encoding="utf-8",
    )
    templates = tmp_path / "experiments" / "results" / "templates"
    templates.mkdir(parents=True)
    (templates / "ablation.csv").write_text(
        "status,metric,value\nplanned,accuracy,\n",
        encoding="utf-8",
    )
    calls: list[dict] = []

    async def fake_invoke(
        skill_name: str,
        arguments: str = "",
        project_path: str = "",
        parent_context: str = "",
        on_event=None,
        workflow_node_id="",
        allowed_tools_override=None,
    ) -> str:
        assert workflow_node_id == "narrative"
        assert allowed_tools_override is None  # Initial authoring uses the owner's normal tool policy.
        calls.append({
            "skill": skill_name,
            "arguments": arguments,
            "project_path": project_path,
            "parent_context": parent_context,
        })
        body = (
            "# Paper Plan\n\n"
            "## One-sentence contribution\nA testable domain contribution.\n\n"
            "## Claims-Evidence Matrix\nClaim and evidence are mapped here.\n\n"
            "## Section Plan\nIntroduction, Method, Experiments, Results, Conclusion.\n\n"
            "## Figure Plan\nA method figure and a result figure.\n\n"
            + ("Grounded section detail. " * 40)
        )
        (tmp_path / "paper" / "PAPER_PLAN.md").write_text(body, encoding="utf-8")
        return "Canonical paper plan written."

    import server.agent.tools as agent_tools

    monkeypatch.setattr(agent_tools, "invoke_skill", fake_invoke)
    run = WorkflowRun(
        id="paper-plan-run",
        project_path=str(tmp_path),
        created_at=1.0,
        options={},
    )

    asyncio.run(
        WorkflowEngine()._execute_stage_delegates(
            node=WorkflowNode(
                id="narrative",
                name="Narrative",
                skill="/research-refine",
            ),
            run=run,
            direction="EEG foundation models",
            effort="balanced",
            assurance="draft",
            opts={"target_venue": "ICLR", "target_pages": 9},
        )
    )

    assert calls and calls[0]["skill"] == "paper-plan"
    assert calls[0]["project_path"] == str(tmp_path)
    assert str(tmp_path / "paper" / "PAPER_PLAN.md") in calls[0]["arguments"]
    assert "Authoritative existing input inventory" in calls[0]["arguments"]
    assert "- NARRATIVE_REPORT.md" in calls[0]["arguments"]
    assert "- experiments/results/templates/ablation.csv" in calls[0]["arguments"]
    assert "Do not probe guessed aliases" in calls[0]["arguments"]
    trace = json.loads(
        (tmp_path / ".merak" / "runs" / "paper-plan-run.skills.json").read_text(
            encoding="utf-8"
        )
    )
    delegate = trace["stages"]["narrative"]["invocations"][-1]
    assert delegate["skill"] == "paper-plan"
    assert delegate["status"] == "completed"
