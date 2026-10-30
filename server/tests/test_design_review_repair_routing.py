"""Independent review findings survive exception conversion and route to code owners."""

from types import SimpleNamespace
import pytest

from server.workflows.design_review import ImplementationReviewBlocked
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.revision_execution import _implementation_only, revise_node_from_gate


def review_diagnostics():
    error = ImplementationReviewBlocked({
        "summary": "The implementation has incomplete aggregation and resource guards.",
        "blocking": True, "verdict": "FAIL", "findings": [
            {"id": "aggregate-entrypoint", "severity": "blocker", "scope": "implementation_correctness",
             "message": "The registered aggregate entrypoint is missing.",
             "target_files": ["experiments/src/train.py", "experiments/src/metrics.py"]},
            {"id": "resource-enforcement", "severity": "blocker", "scope": "implementation_correctness",
             "message": "The declared GPU memory ceiling is not enforced.",
             "target_files": ["experiments/src/train.py"]},
        ],
    }, {"run_experiment": False})
    return WorkflowEngine()._gate_revision_diagnostics({"accepted": False,
        "reason": "artifact preparation or verification failed", "summary": str(error), "details": error.details()})


def test_report_summary_does_not_become_an_unowned_quality_finding():
    diagnostics = review_diagnostics()
    assert {item["id"] for item in diagnostics["findings"]} == {"aggregate-entrypoint", "resource-enforcement"}
    assert all(item["category"] == "implementation_review" for item in diagnostics["findings"])
    assert _implementation_only(WorkflowNode("exp-design", "Design", "/experiment-plan"), diagnostics["findings"])
    assert "experiments/EXPERIMENT_PLAN.md" not in diagnostics["repair_scope"]["target_files"]


@pytest.mark.asyncio
async def test_review_error_uses_real_revision_dispatch_without_design_model():
    diagnostics = review_diagnostics()
    events = []

    async def forbidden(*args, **kwargs):
        pytest.fail("Code review repair must not invoke design-document rewriting or unrelated specialists")

    async def emit(run, kind, payload):
        events.append((kind, payload))

    host = SimpleNamespace(_build_gate_revision_instruction=lambda *_args: "Repair the two named code defects",
                           _emit=emit, _execute_node=forbidden, _execute_profile_specialists=forbidden)
    node = WorkflowNode("exp-design", "Design", "/experiment-plan")
    result = await revise_node_from_gate(host, node, WorkflowRun(id="review-route", nodes=[node]),
        diagnostics, 1, 1, "", "Fixture research", "balanced", "draft", {"run_experiment": False})
    assert "staged owner" in result
    assert [kind for kind, _payload in events] == ["implementation_repair_routed"]


def test_empty_review_does_not_silently_clear_the_error():
    error = ImplementationReviewBlocked({"summary": "Malformed missing review findings", "findings": []}, {})
    assert error.details()["issues"] == ["Malformed missing review findings"]
