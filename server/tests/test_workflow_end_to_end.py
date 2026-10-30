from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from typing import Any

import pytest

from server.services.execution_provenance import execution_provenance_service
from server.services.paper_compiler import paper_compiler
from server.workflows.engine import NodeStatus, WorkflowEngine, WorkflowRun
from server.workflows.review_audit import (
    AUDIT_LAYER_SKILLS,
    AuditChain,
    AuditResult,
    Verdict,
    review_source_bundle,
)
from server.workflows.run_state import RunState


def _build_run(
    engine: WorkflowEngine,
    project: Path,
    run_id: str,
    options: dict[str, Any],
) -> tuple[WorkflowRun, RunState]:
    nodes = engine._get_default_nodes()
    run = WorkflowRun(
        id=run_id,
        project_path=str(project),
        nodes=nodes,
        status="running",
        options=dict(options),
    )
    state = RunState(str(project), run_id)
    state.start(
        [
            {
                "id": node.id,
                "name": node.name,
                "skill": node.skill,
                "execution_kind": node.execution_kind,
                "runtime_service": node.runtime_service,
                "policy_required": node.policy_required,
            }
            for node in nodes
        ],
        {
            "direction": "integration research",
            "effort": "balanced",
            "assurance": "submission",
            "options": dict(options),
        },
    )
    return run, state


def _install_pipeline_fakes(
    engine: WorkflowEngine,
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[tuple[str, dict[str, Any]]],
    executions: list[str],
    classification: str,
    submission_ready: bool,
    mock_readiness: bool = True,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    async def emit(_run, event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    async def no_context(*_args, **_kwargs) -> str:
        return ""

    async def no_specialists(**_kwargs) -> dict[str, Any]:
        return {"accepted": True, "subnodes": []}

    async def no_templates(*_args, **_kwargs) -> dict[str, Any]:
        return {"generated": True}

    async def fake_experiment(_run, _opts) -> str:
        executions.append("runtime:exp-run")
        return "runtime experiment completed with provenance"

    async def fake_paper(*_args, **_kwargs) -> str:
        executions.append("runtime:paper")
        return "paper authored"

    async def fake_review(*_args, **_kwargs) -> str:
        executions.append("runtime:review")
        return "structured review completed"

    async def fake_audit(*_args, **_kwargs) -> str:
        executions.append("runtime:audit")
        return "five-layer audit completed"

    async def notification(**_kwargs) -> dict[str, Any]:
        return {"delivered": False, "reason": "test"}

    def readiness(_project_path, state, *args, **kwargs) -> dict[str, Any]:
        phases = state.get("phases", {})
        assert phases
        assert all(phase.get("status") == "accepted" for phase in phases.values())
        return {
            "execution_completed": True,
            "submission_ready": submission_ready,
            "completion_class": classification,
            "evidence_mode": (
                "executed" if submission_ready else "synthetic_preview"
            ),
        }

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(engine, "_ensure_knowledge_source_context", no_context)
    monkeypatch.setattr(engine, "_execute_profile_specialists", no_specialists)
    monkeypatch.setattr(engine, "_ensure_planned_result_templates", no_templates)
    monkeypatch.setattr(engine, "_execute_managed_experiment", fake_experiment)
    monkeypatch.setattr(engine, "_execute_staged_paper", fake_paper)
    monkeypatch.setattr(engine, "_execute_review_node", fake_review)
    monkeypatch.setattr(engine, "_execute_audit_node", fake_audit)
    monkeypatch.setattr(
        engine,
        "_sleep_with_transport_heartbeat",
        no_context,
    )
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
            "nodes": {},
        },
    )
    monkeypatch.setattr(
        "server.services.research_workflow_contract.research_workflow_contract_service.prepare",
        lambda *_args, **_kwargs: {},
    )
    if mock_readiness:
        monkeypatch.setattr(
            "server.services.workflow_readiness.workflow_readiness_service.assess",
            readiness,
        )
    monkeypatch.setattr(
        "server.services.notification.notification_service.workflow_completed",
        notification,
    )
    monkeypatch.setattr(
        "server.services.notification.notification_service.workflow_failed",
        notification,
    )


@pytest.mark.asyncio
async def test_synthetic_pipeline_executes_all_nodes_but_never_claims_submission_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    options = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
        "human_checkpoint": False,
        "code_review": False,
        "research_quality_mode": "off",
    }
    run, state = _build_run(engine, tmp_path, "e2e-synthetic", options)
    events: list[tuple[str, dict[str, Any]]] = []
    executions: list[str] = []
    accepted_order: list[str] = []
    _install_pipeline_fakes(
        engine,
        monkeypatch,
        events=events,
        executions=executions,
        classification="synthetic_preview_ready",
        submission_ready=False,
    )

    async def fake_node(node, *_args, **_kwargs) -> str:
        executions.append(f"model:{node.id}")
        return f"{node.id} completed"

    def planned_results(_run, _direction, result="") -> str:
        executions.append("runtime:results-planned")
        return result or "planned analysis completed"

    async def accept_node(**kwargs):
        node = kwargs["node"]
        accepted_order.append(node.id)
        state.set_status(node.id, "done")
        return ({
            "accepted": True,
            "verdict_id": f"accepted:{node.id}",
            "reviewer": "deterministic:integration",
            "summary": f"{node.id} accepted",
            "details": {},
        }, kwargs["initial_result"])

    monkeypatch.setattr(engine, "_execute_node", fake_node)
    monkeypatch.setattr(engine, "_ensure_planned_results_analysis", planned_results)
    monkeypatch.setattr(engine, "_run_node_revision_loop", accept_node)

    await engine._execute_run(
        run,
        "integration research",
        "balanced",
        "submission",
        options,
    )

    persisted = state.load()
    expected_order = [node.id for node in engine._get_default_nodes()]
    assert persisted is not None
    assert accepted_order == expected_order
    assert run.status == "completed"
    assert run.completion["execution_completed"] is True
    assert run.completion["submission_ready"] is False
    assert run.completion["completion_class"] == "synthetic_preview_ready"
    assert all(node.status == NodeStatus.COMPLETED for node in run.nodes)
    assert any(event == "workflow_completed" for event, _ in events)


@pytest.mark.asyncio
async def test_executed_pipeline_recovers_transport_and_rebuilds_after_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    options = {
        "run_experiment": True,
        "human_checkpoint": False,
        "code_review": False,
        "research_quality_mode": "off",
        "model_transport_max_attempts": 3,
        "model_transport_retry_window_seconds": 60,
        "max_research_loop_cycles": 3,
    }
    run, state = _build_run(engine, tmp_path, "e2e-executed", options)
    events: list[tuple[str, dict[str, Any]]] = []
    executions: list[str] = []
    accepted_order: list[str] = []
    node_attempts: dict[str, int] = {}
    review_gates = 0
    _install_pipeline_fakes(
        engine,
        monkeypatch,
        events=events,
        executions=executions,
        classification="executed_submission_ready",
        submission_ready=True,
    )

    async def fake_node(node, *_args, **_kwargs) -> str:
        node_attempts[node.id] = node_attempts.get(node.id, 0) + 1
        executions.append(f"model:{node.id}:{node_attempts[node.id]}")
        if node.id == "idea" and node_attempts[node.id] == 1:
            raise RuntimeError("OpenAI API error 502: temporary upstream failure")
        return f"{node.id} completed"

    async def gate_with_one_research_loop(**kwargs):
        nonlocal review_gates
        node = kwargs["node"]
        accepted_order.append(node.id)
        state.set_status(node.id, "done")
        if node.id == "review" and review_gates == 0:
            review_gates += 1
            restart_from = await engine._prepare_research_loop_restart(
                run=run,
                run_state=state,
                owner_id="exp-design",
                reason="review found an invalid matched baseline",
                opts=options,
            )
            return ({
                "accepted": False,
                "restart_required": True,
                "restart_from_node": restart_from,
                "revision_owner_id": "exp-design",
            }, kwargs["initial_result"])
        return ({
            "accepted": True,
            "verdict_id": f"accepted:{node.id}:{accepted_order.count(node.id)}",
            "reviewer": "deterministic:integration",
            "summary": f"{node.id} accepted",
            "details": {},
        }, kwargs["initial_result"])

    monkeypatch.setattr(engine, "_execute_node", fake_node)
    monkeypatch.setattr(engine, "_run_node_revision_loop", gate_with_one_research_loop)

    await engine._execute_run(
        run,
        "integration research",
        "balanced",
        "submission",
        options,
    )

    first_stop = state.load()
    assert node_attempts["idea"] == 1 and run.status == "incomplete"
    assert first_stop["interruption"]["manual_resume_required"]
    assert first_stop["phases"]["lit"]["status"] == "accepted"
    assert "runtime:exp-run" not in executions
    from server.workflows.interruption_checkpoint import acknowledge_manual_resume
    acknowledge_manual_resume(state)
    engine._mark_run_running(run)
    await engine._execute_run(run, "integration research", "balanced", "submission", options)
    persisted = state.load()
    assert persisted is not None
    assert node_attempts["idea"] == 2
    assert executions.count("runtime:exp-run") == 2
    assert accepted_order.count("exp-run") == 2
    assert accepted_order.count("results") == 2
    assert accepted_order.count("paper") == 2
    assert accepted_order.count("review") == 2
    assert run.status == "completed"
    assert run.completion["submission_ready"] is True
    assert run.completion["completion_class"] == "executed_submission_ready"
    assert all(
        phase.get("status") == "accepted"
        for phase in persisted["phases"].values()
    )
    assert not any(event == "node_transport_retry" for event, _ in events)
    assert any(event == "node_transport_exhausted" for event, _ in events)
    assert any(event == "research_loop_restarted" for event, _ in events)
    assert any(event == "workflow_completed" for event, _ in events)


@pytest.mark.asyncio
async def test_thirteen_node_empirical_run_reaches_real_submission_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    options = {
        "run_experiment": True,
        "human_checkpoint": False,
        "code_review": False,
        "research_quality_mode": "off",
    }
    run, state = _build_run(engine, tmp_path, "e2e-real-readiness", options)
    events: list[tuple[str, dict[str, Any]]] = []
    executions: list[str] = []
    _install_pipeline_fakes(
        engine,
        monkeypatch,
        events=events,
        executions=executions,
        classification="unused",
        submission_ready=False,
        mock_readiness=False,
    )

    def write_json(relative: str, payload: object) -> None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    config = tmp_path / "experiments" / "configs" / "main.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("experiment:\n  metric: accuracy\n", encoding="utf-8")
    metric = tmp_path / "experiments" / "results" / "main_metrics.csv"
    metric.parent.mkdir(parents=True, exist_ok=True)
    metric.write_text(
        "status,method,seed,split,metric,value,ci95_low,ci95_high\n"
        "completed,Proposed,42,test,accuracy,0.81,0.79,0.83\n",
        encoding="utf-8",
    )
    now = time.time()
    execution_provenance_service.record(
        tmp_path,
        session_id="e2e-runtime-session",
        tool="Bash",
        arguments={
            "command": (
                "python experiments/src/train.py "
                "--config experiments/configs/main.yaml"
            ),
            "cwd": str(tmp_path),
        },
        success=True,
        started_at=now - 1.0,
        finished_at=now,
        output="experiment completed",
    )

    write_json("figures/SCIENTIFIC_ASSET_PLAN.json", {
        "evidence_mode": "executed",
        "submission_eligible": True,
    })
    write_json("figures/FIGURE_MANIFEST.json", {
        "schema": 1,
        "figures": [],
    })
    paper = tmp_path / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Empirical submission candidate.\n\\end{document}\n",
        encoding="utf-8",
    )
    write_json("paper/PAPER_BUILD.json", {
        "evidence_mode": "executed",
        "submission_eligible": True,
    })
    pdf = paper / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsubmission candidate\n")
    assert paper_compiler.refresh_build_record(
        paper,
        "PAPER_BUILD.json",
        "main.pdf",
        pages=1,
    ) is True

    original_snapshot = paper / "main_round0_original.pdf"
    final_snapshot = paper / "main_round1.pdf"
    original_snapshot.write_bytes(pdf.read_bytes())
    final_snapshot.write_bytes(pdf.read_bytes())
    write_json("review-stage/pdf-layout/main_round1.json", {
        "schema": 1,
        "pdf_path": "paper/main_round1.pdf",
        "page_count": 1,
        "renderer": "integration-test-renderer",
        "pages": [{"page": 1, "possible_layout_findings": []}],
    })
    review_hash, review_sources = review_source_bundle(tmp_path)
    visual_review = {
        "pdf_path": "paper/main_round1.pdf",
        "figure_quality": "All figures are legible at paper scale.",
        "caption_alignment": "Captions align with their figures.",
        "page_layout": "No clipping, overlap, or broken page flow is visible.",
        "table_formatting": "Tables are aligned and readable.",
        "visual_consistency": "Typography and visual encodings are consistent.",
    }
    write_json("review-stage/REVIEW_STATE.json", {
        "managed_by": "cross_model_review_loop",
        "run_id": "e2e-real-readiness",
        "evidence_mode": "executed",
        "publication_ready": True,
        "policy_loaded": True,
        "source_bundle_sha256": review_hash,
        "sources": [path.relative_to(tmp_path).as_posix() for path in review_sources],
        "executor_model": "executor-model",
        "reviewer_model": "independent-reviewer-model",
        "reviewer_session_ids": ["review-session"],
        "executor_session_ids": ["executor-session"],
        "is_complete": True,
        "threshold_met": True,
        "bounded_complete": True,
        "current_round": 1,
        "max_rounds": 1,
        "fallback_reason": "",
        "final_score": 8.0,
        "final_verdict": "ready",
        "rounds": [{
            "round": 1,
            "score": 8.0,
            "verdict": "ready",
            "weaknesses": ["No unresolved visual blocker remained after inspection."],
            "action_items": ["Retain the inspected final layout."],
            "pdf_snapshot": "paper/main_round1.pdf",
            "visual_review": visual_review,
        }],
        "pdf_snapshots": [
            {
                "round": 0,
                "snapshot_path": "paper/main_round0_original.pdf",
                "pdf_sha256": hashlib.sha256(
                    original_snapshot.read_bytes()
                ).hexdigest(),
                "source_bundle_sha256": review_hash,
                "layout_report_path": "review-stage/pdf-layout/main_round1.json",
            },
            {
                "round": 1,
                "snapshot_path": "paper/main_round1.pdf",
                "pdf_sha256": hashlib.sha256(
                    final_snapshot.read_bytes()
                ).hexdigest(),
                "source_bundle_sha256": review_hash,
                "layout_report_path": "review-stage/pdf-layout/main_round1.json",
            },
        ],
    })
    audit_entries = [
        AuditResult(
            layer=layer,
            layer_name=f"Layer {layer}",
            verdict=Verdict.WARN,
            summary="audited",
            details="inspected evidence",
            evidence=["paper/main.tex"],
            method="model",
            policy_loaded=True,
            session_id=f"audit-session-{layer}",
            skill_name=AUDIT_LAYER_SKILLS[layer],
            model_name="independent-reviewer-model",
        )
        for layer in range(1, 6)
    ]
    AuditChain()._save_results(
        audit_entries,
        str(tmp_path),
        evidence_mode="executed",
        run_id="e2e-real-readiness",
    )

    async def fake_node(node, *_args, **_kwargs) -> str:
        executions.append(f"model:{node.id}")
        return f"{node.id} completed"

    async def accept_node(**kwargs):
        node = kwargs["node"]
        state.set_status(node.id, "done")
        return ({
            "accepted": True,
            "verdict_id": f"accepted:{node.id}",
            "reviewer": "deterministic:integration",
            "summary": f"{node.id} accepted",
            "details": {},
        }, kwargs["initial_result"])

    monkeypatch.setattr(engine, "_execute_node", fake_node)
    monkeypatch.setattr(engine, "_run_node_revision_loop", accept_node)

    await engine._execute_run(
        run,
        "integration research",
        "balanced",
        "submission",
        options,
    )

    persisted = state.load()
    assert persisted is not None
    assert run.status == "completed"
    assert run.completion["execution_completed"] is True
    assert run.completion["submission_ready"] is True
    assert run.completion["completion_class"] == "submission_ready"
    assert run.completion["submission_blockers"] == []
    assert run.completion["submission_advisories"]
    assert run.completion["evidence_details"]["proven_sources"] == [
        "experiments/results/main_metrics.csv"
    ]
    assert all(
        phase.get("status") == "accepted"
        for phase in persisted["phases"].values()
    )
    assert persisted["submission_ready"] is True
    assert any(event == "workflow_completed" for event, _ in events)
