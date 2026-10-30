from __future__ import annotations

from server.tests._workflow_revision_loop_support import (
    CompileError as CompileError,
    CompileResult as CompileResult,
    Path as Path,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    _rebind_review_layout_state as _rebind_review_layout_state,
    _start_run_state as _start_run_state,
    _write_review_layout_routing_fixture as _write_review_layout_routing_fixture,
    asyncio as asyncio,
    json as json,
    pytest as pytest,
)


@pytest.mark.parametrize(
    ("kind", "expected_owner", "expected_target"),
    [
        (
            "figure",
            "figure",
            "figures/method_architecture.figurespec.json",
        ),
        ("table", "paper", "paper/tables/results.tex"),
    ],
)
def test_pdf_layout_findings_bind_to_editable_float_sources(
    tmp_path: Path,
    kind: str,
    expected_owner: str,
    expected_target: str,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind=kind)

    findings = WorkflowEngine._review_layout_revision_findings(
        str(tmp_path),
        state,
    )

    assert len(findings) == 1
    assert findings[0]["owner_node"] == expected_owner
    assert expected_target in findings[0]["target_files"]
    assert findings[0]["asset_ids"] == [
        "method_architecture" if kind == "figure" else "main_results"
    ]
    assert all(
        not target.startswith("review-stage/")
        for target in findings[0]["target_files"]
    )


def test_pdf_layout_findings_split_mixed_figure_table_page(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="figure")
    paper = tmp_path / "paper"
    tables = paper / "tables"
    table_label = "tab:study-design"
    tables.joinpath("results.tex").write_text(
        "\\begin{table}\n"
        "\\caption{Study design.}\n"
        f"\\label{{{table_label}}}\n"
        "\\begin{tabular}{ll} A & B \\\\ \\end{tabular}\n"
        "\\end{table}\n",
        encoding="utf-8",
    )
    tables.joinpath("TABLE_MANIFEST.json").write_text(
        json.dumps({
            "schema": 3,
            "tables": [{
                "id": "study_design",
                "label": table_label,
                "latex_path": "paper/tables/results.tex",
            }],
        }),
        encoding="utf-8",
    )
    paper.joinpath("main.aux").write_text(
        "\\newlabel{fig:method-architecture}"
        "{{1}{5}{Figure}{float.1}{}}\n"
        f"\\newlabel{{{table_label}}}{{{{1}}{{5}}{{Table}}{{float.2}}{{}}}}\n",
        encoding="utf-8",
    )
    _rebind_review_layout_state(tmp_path, state)

    findings = WorkflowEngine._review_layout_revision_findings(
        str(tmp_path),
        state,
    )

    assert len(findings) == 2
    by_owner = {finding["owner_node"]: finding for finding in findings}
    assert set(by_owner) == {"figure", "paper"}
    assert by_owner["figure"]["label"] == "fig:method-architecture"
    assert "FIGURE-FIG-METHOD-ARCHITECTURE" in by_owner["figure"]["id"]
    assert by_owner["figure"]["asset_ids"] == ["method_architecture"]
    assert "paper/sections/03_method.tex" in by_owner["figure"]["target_files"]
    assert by_owner["paper"]["label"] == table_label
    assert "PAPER-TAB-STUDY-DESIGN" in by_owner["paper"]["id"]
    assert by_owner["paper"]["asset_ids"] == ["study_design"]
    assert by_owner["paper"]["target_files"] == ["paper/tables/results.tex"]


def test_mixed_layout_repairs_rotate_owners_and_scope_diagnostics(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="figure")
    paper = tmp_path / "paper"
    tables = paper / "tables"
    table_label = "tab:study-design"
    tables.joinpath("results.tex").write_text(
        "\\begin{table}\\caption{Study design.}"
        f"\\label{{{table_label}}}"
        "\\begin{tabular}{ll} A & B \\\\ \\end{tabular}\\end{table}\n",
        encoding="utf-8",
    )
    tables.joinpath("TABLE_MANIFEST.json").write_text(
        json.dumps({
            "schema": 3,
            "tables": [{
                "id": "study_design",
                "label": table_label,
                "latex_path": "paper/tables/results.tex",
            }],
        }),
        encoding="utf-8",
    )
    paper.joinpath("main.aux").write_text(
        "\\newlabel{fig:method-architecture}"
        "{{1}{5}{Figure}{float.1}{}}\n"
        f"\\newlabel{{{table_label}}}{{{{1}}{{5}}{{Table}}{{float.2}}{{}}}}\n",
        encoding="utf-8",
    )
    _rebind_review_layout_state(tmp_path, state)
    findings = WorkflowEngine._review_layout_revision_findings(
        str(tmp_path),
        state,
    )
    gate = {
        "accepted": False,
        "details": {"review_findings": findings},
    }
    figure = WorkflowNode(id="figure", name="Figure", skill="/figure")
    paper_node = WorkflowNode(id="paper", name="Paper", skill="/paper")
    review = WorkflowNode(id="review", name="Review", skill="/review")
    run = WorkflowRun(
        id="mixed-owner-routing",
        project_path=str(tmp_path),
        nodes=[figure, paper_node, review],
    )
    engine = WorkflowEngine()

    first_owner = engine._revision_owner_for_gate(
        review,
        run,
        gate,
        {"figure": 0, "paper": 0},
    )
    second_owner = engine._revision_owner_for_gate(
        review,
        run,
        gate,
        {"figure": 1, "paper": 0},
    )
    assert first_owner.id == "figure"
    assert second_owner.id == "paper"

    diagnostics = engine._gate_revision_diagnostics(gate)
    figure_scope = engine._revision_diagnostics_for_owner(
        diagnostics,
        "figure",
    )
    paper_scope = engine._revision_diagnostics_for_owner(
        diagnostics,
        "paper",
    )
    assert {item["owner_node"] for item in figure_scope["findings"]} == {
        "figure"
    }
    assert figure_scope["repair_scope"]["asset_ids"] == [
        "method_architecture"
    ]
    assert "paper/tables/results.tex" not in (
        figure_scope["repair_scope"]["target_files"]
    )
    assert {item["owner_node"] for item in paper_scope["findings"]} == {
        "paper"
    }
    assert paper_scope["repair_scope"]["asset_ids"] == ["study_design"]
    assert all(
        not target.startswith("figures/")
        for target in paper_scope["repair_scope"]["target_files"]
    )


def test_pdf_layout_findings_ignore_unreachable_duplicate_label_tex(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="figure")
    paper = tmp_path / "paper"
    figures = tmp_path / "figures"
    paper.joinpath("generated_figures.tex").write_text(
        "\\begin{figure}\n"
        "\\includegraphics{../figures/obsolete.pdf}\n"
        "\\caption{Obsolete duplicate.}\n"
        "\\label{fig:method-architecture}\n"
        "\\end{figure}\n",
        encoding="utf-8",
    )
    figures.joinpath("obsolete.pdf").write_bytes(b"obsolete")
    figures.joinpath("obsolete.py").write_text("print('obsolete')\n", encoding="utf-8")
    manifest_path = figures / "FIGURE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["figures"].append({
        "id": "obsolete_duplicate",
        "output_path": "figures/obsolete.pdf",
        "source_path": "figures/obsolete.py",
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _rebind_review_layout_state(tmp_path, state)

    findings = WorkflowEngine._review_layout_revision_findings(
        str(tmp_path),
        state,
    )

    assert len(findings) == 1
    targets = findings[0]["target_files"]
    assert "paper/generated_figures.tex" not in targets
    assert "figures/obsolete.py" not in targets
    assert findings[0]["asset_ids"] == ["method_architecture"]


def test_pdf_layout_findings_ignore_unreferenced_stale_aux(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="figure")
    paper = tmp_path / "paper"
    tables = paper / "tables"
    stale_label = "tab:stale-result"
    tables.joinpath("results.tex").write_text(
        "\\begin{table}\\caption{Stale result.}"
        f"\\label{{{stale_label}}}"
        "\\begin{tabular}{ll} A & B \\\\ \\end{tabular}\\end{table}\n",
        encoding="utf-8",
    )
    tables.joinpath("TABLE_MANIFEST.json").write_text(
        json.dumps({
            "schema": 3,
            "tables": [{
                "id": "stale_result",
                "label": stale_label,
                "latex_path": "paper/tables/results.tex",
            }],
        }),
        encoding="utf-8",
    )
    paper.joinpath("obsolete.aux").write_text(
        f"\\newlabel{{{stale_label}}}{{{{1}}{{5}}{{Stale}}{{float.9}}{{}}}}\n",
        encoding="utf-8",
    )
    _rebind_review_layout_state(tmp_path, state)

    findings = WorkflowEngine._review_layout_revision_findings(
        str(tmp_path),
        state,
    )

    assert len(findings) == 1
    assert findings[0]["owner_node"] == "figure"
    assert findings[0]["label"] == "fig:method-architecture"
    assert "stale_result" not in findings[0]["asset_ids"]


def test_review_timeout_layout_finding_routes_to_figure_source(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="figure")
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    engine = WorkflowEngine()

    gate = engine._review_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    finding = gate["details"]["review_findings"][0]
    assert finding["owner_node"] == "figure"
    assert finding["target_files"][0] == (
        "figures/method_architecture.figurespec.json"
    )
    review = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    owner = engine._revision_owner_for_gate(
        review,
        WorkflowRun(
            id="layout-timeout-owner",
            project_path=str(tmp_path),
            nodes=[review],
        ),
        gate,
    )
    assert owner.id == "figure"


def test_bounded_review_does_not_advisory_pass_unrepaired_pdf_layout(
    tmp_path: Path,
) -> None:
    state = _write_review_layout_routing_fixture(tmp_path, kind="figure")
    reviewed_snapshot = state["rounds"][-1]["pdf_snapshot"]
    source_hash = state["source_bundle_sha256"]
    state.update({
        "current_round": 1,
        "max_rounds": 1,
        "final_score": 5.0,
        "final_verdict": "needs_work",
        "is_complete": True,
        "bounded_complete": True,
        "evidence_mode": "synthetic_preview",
        "rounds": [{
            "round": 1,
            "score": 5.0,
            "verdict": "needs_work",
            "weaknesses": [
                "Independent semantic reviewer timed out before visual review."
            ],
            "action_items": [
                "Run an independent semantic review before submission."
            ],
            "pdf_snapshot": reviewed_snapshot,
            "visual_review": {"_source_bundle_sha256": source_hash},
        }],
    })
    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))

    assert gate["accepted"] is False
    assert gate["reason"] == (
        "deterministic PDF layout findings require source repair"
    )
    assert gate["details"]["active_layout_findings"][0]["owner_node"] == (
        "figure"
    )


@pytest.mark.asyncio
async def test_stale_managed_review_starts_one_fresh_review_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="managed-review-refresh",
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
        return "fresh managed review output"

    def acceptance(*_args, **_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 1:
            return {
                "accepted": False,
                "reason": "node-specific research risk audit failed",
                "summary": "Structured review source hash is stale.",
                "details": {
                    "managed_review": True,
                    "issues": ["Structured review source bundle hash is stale."],
                    "findings": [{
                        "id": "REVIEW-HASH-001",
                        "severity": "blocker",
                        "message": "Structured review source bundle hash is stale.",
                    }],
                },
            }
        return {
            "accepted": True,
            "verdict_id": "review:fresh",
            "reviewer": "cross-model:reviewer",
            "summary": "fresh review accepted",
            "details": {},
        }

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_emit", noop)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)

    gate, result = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="stale review output",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert gate["accepted"] is True
    assert result == "review output"
    assert revision_calls == 1


@pytest.mark.asyncio
async def test_resumed_hash_stale_review_refreshes_without_saved_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="review", name="Review", skill="/auto-review-loop")
    run = WorkflowRun(
        id="hash-stale-review-refresh",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={},
    )
    _start_run_state(tmp_path, run.id, [node])
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("current manuscript\n", encoding="utf-8")
    review_state = tmp_path / "review-stage" / "REVIEW_STATE.json"
    review_state.parent.mkdir(parents=True)
    review_state.write_text(
        json.dumps({"source_bundle_sha256": "stale-source-hash"}),
        encoding="utf-8",
    )
    review_calls = 0
    events: list[str] = []

    async def prepare(*_args, **_kwargs) -> str:
        return "stale persisted review"

    async def refresh_review(*_args, **_kwargs) -> str:
        nonlocal review_calls
        review_calls += 1
        return "fresh managed review"

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def emit(_run, event: str, _payload: dict) -> None:
        events.append(event)

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(engine, "_execute_review_node", refresh_review)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(
        engine,
        "_acceptance_gate",
        lambda *_args, **_kwargs: {
            "accepted": True,
            "verdict_id": "review:fresh",
            "reviewer": "cross-model:reviewer",
            "summary": "fresh review accepted",
            "details": {},
        },
    )

    gate, result = await engine._run_node_revision_loop(
        node=node,
        run=run,
        initial_result="stale review output",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts=run.options,
        require_fresh=False,
        checkpoint_timeout=30,
        max_revision_rounds=3,
    )

    assert gate["accepted"] is True
    assert result == "fresh managed review"
    assert review_calls == 1
    assert "consumer_snapshot_refresh_required" in events
    assert "consumer_snapshot_refresh_started" in events
    assert "consumer_snapshot_refreshed" in events


@pytest.mark.asyncio
async def test_review_reconciliation_failure_repairs_paper_before_stopping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    paper_dir.joinpath("main.tex").write_text(
        "\\documentclass{article}\\begin{document}Paper\\end{document}",
        encoding="utf-8",
    )
    paper_node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    review_node = WorkflowNode(
        id="review",
        name="Review",
        skill="/auto-review-loop",
    )
    run = WorkflowRun(
        id="review-reconciliation-repair",
        project_path=str(tmp_path),
        nodes=[paper_node, review_node],
        status="running",
    )
    _start_run_state(tmp_path, run.id, [paper_node, review_node])
    gate_calls = 0
    revised_nodes: list[str] = []

    async def prepare(*_args, **_kwargs) -> str:
        return "prepared output"

    async def noop(*_args, **_kwargs) -> None:
        return None

    async def revise(**kwargs) -> str:
        revised_nodes.append(kwargs["node"].id)
        return "paper repaired"

    async def refresh_review(*_args, **_kwargs) -> str:
        return "fresh review after canonical paper repair"

    def acceptance(*_args, **_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 1:
            return {
                "accepted": False,
                "reason": "reviewed paper failed deterministic reconciliation",
                "summary": "experiments: section unfocused",
                "details": {
                    "managed_review": True,
                    "paper_reconciliation": {
                        "passed": False,
                        "issues": ["experiments: section unfocused"],
                    },
                    "issues": ["experiments: section unfocused"],
                },
            }
        return {
            "accepted": True,
            "verdict_id": f"fresh:{gate_calls}",
            "reviewer": "deterministic:test",
            "summary": "accepted after paper repair",
            "details": {},
        }

    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_emit", noop)
    monkeypatch.setattr(engine, "_acceptance_gate", acceptance)
    monkeypatch.setattr(engine, "_revise_node_from_gate", revise)
    monkeypatch.setattr(engine, "_execute_review_node", refresh_review)

    gate, _ = await engine._run_node_revision_loop(
        node=review_node,
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

    assert gate["accepted"] is True
    assert revised_nodes == ["paper"]


@pytest.mark.asyncio
async def test_review_regression_gets_a_separate_bounded_paper_repair_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="review-regression-paper-repair",
        project_path=str(tmp_path),
    )
    captured: list[str] = []

    async def fake_staged_paper(**kwargs):
        captured.extend(kwargs["revision_issues"])
        return "repaired"

    monkeypatch.setattr(engine, "_execute_staged_paper", fake_staged_paper)

    result = await engine._revise_node_from_gate(
        node=WorkflowNode(id="paper", name="Paper", skill="/paper-write"),
        run=run,
        diagnostics={
            "reason": "reviewed paper failed deterministic reconciliation",
            "issues": [
                "experiments: section unfocused "
                "(1520; preferred maximum 1150)"
            ],
        },
        round_number=2,
        cycle=4,
        user_feedback="",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
    )

    assert result == "repaired"
    assert captured[0].startswith("Downstream review regression repair:")
    assert "experiments: section unfocused" in captured[1]


@pytest.mark.asyncio
async def test_paper_revision_preserves_structured_target_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="paper-structured-repair-scope",
        project_path=str(tmp_path),
    )
    captured: list[str] = []

    async def fake_staged_paper(**kwargs):
        captured.extend(kwargs["revision_issues"])
        return "repaired"

    monkeypatch.setattr(engine, "_execute_staged_paper", fake_staged_paper)

    result = await engine._revise_node_from_gate(
        node=WorkflowNode(id="paper", name="Paper", skill="/paper-write"),
        run=run,
        diagnostics={
            "reason": "reviewed paper failed deterministic reconciliation",
            "issues": ["Align the method and results with the evidence."],
            "repair_scope": {
                "target_files": [
                    "paper/sections/03_method.tex",
                    "paper/sections/05_results.tex",
                    "experiments/results/analysis.md",
                ],
            },
        },
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
    )

    assert result == "repaired"
    assert "Target artifact: paper/sections/03_method.tex" in captured
    assert "Target artifact: paper/sections/05_results.tex" in captured
    assert all("experiments/results/analysis.md" not in item for item in captured)


@pytest.mark.asyncio
async def test_runtime_owned_paper_table_revision_never_calls_model_table_or_section_authors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="paper-table-repair-scope",
        project_path=str(tmp_path),
    )
    captured: dict[str, object] = {}

    async def fake_table_repair(**kwargs):
        captured.update(kwargs)
        return "tables repaired"

    async def fail_staged_paper(**_kwargs):
        raise AssertionError("table targets must not enter staged section repair")

    async def runtime_projection(*_args, **_kwargs):
        captured["runtime_refreshed"] = True
        return {"passed": True, "issues": []}

    monkeypatch.setattr(
        engine,
        "_execute_bounded_paper_table_repair",
        fake_table_repair,
    )
    monkeypatch.setattr(engine, "_execute_staged_paper", fail_staged_paper)
    monkeypatch.setattr("server.workflows.paper_repair_runtime.refresh_paper_runtime_inputs", runtime_projection)
    monkeypatch.setattr(engine, "_paper_acceptance_gate", lambda *_args, **_kwargs: {"accepted": True})
    table_targets = [
        "paper/tables/method_components.tex",
        "paper/tables/synthetic_preview_results.tex",
    ]
    findings = [
        {
            "id": "TABLE-METHOD",
            "owner_node": "paper",
            "message": "Method table exceeds the usable text width.",
            "target_files": [table_targets[0]],
        },
        {
            "id": "TABLE-RESULTS",
            "owner_node": "paper",
            "message": "Results table has crowded columns.",
            "target_files": [table_targets[1]],
        },
    ]

    result = await engine._revise_node_from_gate(
        node=WorkflowNode(id="paper", name="Paper", skill="/paper-write"),
        run=run,
        diagnostics={
            "reason": "deterministic PDF layout findings require source repair",
            "issues": [item["message"] for item in findings],
            "findings": findings,
            "repair_scope": {"target_files": table_targets},
        },
        round_number=1,
        cycle=1,
        user_feedback="",
        research_direction="test",
        effort="balanced",
        assurance="draft",
        opts={},
    )

    assert "Runtime-owned paper projections" in result
    assert captured == {"runtime_refreshed": True}


@pytest.mark.asyncio
async def test_compile_revision_uses_deterministic_builder_not_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    engine = WorkflowEngine()
    run = WorkflowRun(id="deterministic-compile", project_path=str(tmp_path))
    calls: list[tuple[str, bool]] = []

    async def fake_compile(source_root: str, _main: str, *, clean: bool = False):
        calls.append((source_root, clean))
        return SimpleNamespace(
            success=True,
            pdf_path=str(Path(source_root) / "main.pdf"),
            pages=7,
            errors=[],
            log_output="",
        )

    async def must_not_execute(*_args, **_kwargs):
        raise AssertionError("compile revision must not invoke the model agent")

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("server.services.paper_compiler.paper_compiler.compile", fake_compile)
    monkeypatch.setattr(
        "server.services.paper_compiler.paper_compiler.repair_common_source_dependencies",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("compile stage must not mutate reviewed TeX sources")
        ),
    )
    monkeypatch.setattr(engine, "_execute_node", must_not_execute)
    monkeypatch.setattr(
        engine,
        "_refresh_compiled_artifact_record",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(engine, "_emit", noop)

    result = await engine._revise_node_from_gate(
        WorkflowNode(id="compile", name="Compile", skill="/paper-compile"),
        run,
        {"reason": "stale build", "issues": ["source hash mismatch"]},
        1,
        1,
        "",
        "test",
        "balanced",
        "draft",
        {},
    )

    assert calls == [(str(tmp_path / "paper"), True)]
    assert "no model-authored source change" in result


@pytest.mark.asyncio
async def test_ppt_build_only_revision_does_not_regenerate_slide_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    slide_source = tmp_path / "slides" / "main.tex"
    slide_source.parent.mkdir(parents=True)
    slide_source.write_text(
        "\\documentclass{beamer}\\begin{document}"
        "\\begin{frame}Stable source\\end{frame}\\end{document}\n",
        encoding="utf-8",
    )
    original = slide_source.read_bytes()
    engine = WorkflowEngine()
    run = WorkflowRun(id="deterministic-ppt", project_path=str(tmp_path))
    compile_calls: list[tuple[str, bool]] = []

    async def fake_compile(source_root: str, _main: str, *, clean: bool = False):
        compile_calls.append((source_root, clean))
        return SimpleNamespace(
            success=True,
            pdf_path=str(Path(source_root) / "main.pdf"),
            pages=8,
            errors=[],
            warnings=[],
            log_output="",
        )

    async def must_not_execute(*_args, **_kwargs):
        raise AssertionError("build-only PPT repair must not invoke a model")

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "server.services.paper_compiler.paper_compiler.compile",
        fake_compile,
    )
    monkeypatch.setattr(
        "server.services.paper_compiler.paper_compiler.repair_common_source_dependencies",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.scientific_slides.scientific_slide_service.ensure",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("build-only PPT repair must preserve slide source")
        ),
    )
    monkeypatch.setattr(
        "server.services.scientific_slides.scientific_slide_service.refresh_plan_binding",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(engine, "_execute_node", must_not_execute)
    monkeypatch.setattr(
        engine,
        "_refresh_compiled_artifact_record",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(engine, "_emit", noop)

    result = await engine._revise_node_from_gate(
        WorkflowNode(id="ppt", name="Slides", skill="/paper-talk"),
        run,
        {
            "reason": "slide build record is stale",
            "issues": ["SLIDE_BUILD.json is not hash-bound to the current PDF."],
            "repair_scope": {"finding_ids": ["PPT-BUILD-002"]},
        },
        1,
        1,
        "",
        "test",
        "balanced",
        "draft",
        {},
    )

    assert compile_calls == [(str(tmp_path / "slides"), True)]
    assert slide_source.read_bytes() == original
    assert "no model-authored source change" in result


def test_compile_failure_summary_preserves_file_and_line() -> None:
    result = CompileResult(
        success=False,
        errors=[CompileError(
            file="./sections/05_results.tex",
            line=2,
            message="Undefined control sequence.",
            severity="error",
        )],
    )

    summary = WorkflowEngine._compile_failure_summary(result)

    assert summary.startswith(
        "./sections/05_results.tex:2: Undefined control sequence."
    )
