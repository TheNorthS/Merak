"""Execution completion and full acceptance remain independent state transitions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.workflows.acceptance_pipeline import _execution_owner_issues
from server.workflows.figure_execution_verification import revalidate_figure_after_runtime
from server.workflows.revision_gate_phases import record_runtime_gate


def test_contract_identity_and_asset_failures_cannot_be_filtered_out() -> None:
    issues = ["execution trace project identity differs", "figure producer contract conflict",
              "figure has stale source hash"]
    assert _execution_owner_issues({"execution_kind": "runtime_owned", "issues": issues}) == issues


def test_only_hybrid_runtime_completion_is_deferred_to_its_fresh_gate() -> None:
    missing = "missing verified current-run runtime execution for figure_renderers+figure_quality_gate"
    model = "missing verified current-run model execution for /model-svg-figure"
    assert _execution_owner_issues({"execution_kind": "hybrid", "issues": [missing, model]}) == [model]
    assert _execution_owner_issues({"execution_kind": "runtime_owned", "issues": [missing]}) == [missing]


def test_runtime_completion_requires_rechecking_the_actual_full_gate() -> None:
    calls = []
    rejected = {"accepted": False, "reason": "explicitly rejected scientific artifact"}
    host = SimpleNamespace(_acceptance_gate=lambda *args, **kwargs: calls.append((args, kwargs)) or rejected)
    ctx = SimpleNamespace(node=SimpleNamespace(id="figure"), preparation_error="",
                          execution_gate_applied=True, gate_runtime_service="figure_renderers+figure_quality_gate",
                          consumer_refresh_upstream_gate=None,
                          gate={"accepted": False, "reason": "declared node execution was not verified"},
                          host=host, run=object(), assurance="draft", result="Rendered", require_fresh=False)
    revalidate_figure_after_runtime(ctx)
    assert len(calls) == 1 and ctx.gate is rejected and not ctx.gate["accepted"]


@pytest.mark.asyncio
async def test_failed_preparation_is_not_recorded_as_completed_runtime(monkeypatch) -> None:
    calls = []
    from server.workflows import revision_gate_phases as phases

    monkeypatch.setattr(phases.skill_orchestrator, "mark_runtime_execution", lambda *a, **k: calls.append((a, k)))
    events = []

    async def emit(_run, name, data):
        events.append(name)

    ctx = SimpleNamespace(node=SimpleNamespace(id="figure"),
                          run=SimpleNamespace(project_path="fixture", id="test"),
                          host=SimpleNamespace(_emit=emit), preparation_error="invalid producer inputs",
                          gate_runtime_service="figure_renderers+figure_quality_gate",
                          gate={"accepted": False}, round_number=0, cycle=1)
    await record_runtime_gate(ctx)
    assert calls[0][0][-1] == "failed"
    assert calls[0][1]["error"] == "invalid producer inputs"
    assert events == ["runtime_execution_failed"]
