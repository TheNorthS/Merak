"""A dependency invalidated during launch cannot be skipped from the resumed queue."""

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.workflows.resume_node_closure import include_reopened_dependencies
from server.workflows.run_state import RunState


def test_launch_reopens_invalidated_paper_before_review_without_rerunning_accepted_science(tmp_path):
    host = WorkflowEngine()
    definitions = host._get_default_nodes()
    state = RunState(str(tmp_path), "resume-closure")
    state.start([{"id": node.id} for node in definitions], {})
    for node in definitions:
        if node.id not in {"review", "audit", "compile", "ppt"}:
            state.set_status(node.id, "done")
            state.accept(node.id, "fixture-verdict", "fixture-validator")
    run = WorkflowRun(id="resume-closure", project_path=str(tmp_path), options={"resume_run_id": "resume-closure"},
        nodes=[node for node in definitions if node.id in {"review", "audit", "compile", "ppt"}])
    state.invalidate_acceptance("paper", "renderer implementation changed after queue selection")
    include_reopened_dependencies(host, run, state)
    assert [node.id for node in run.nodes] == ["paper", "review", "audit", "compile", "ppt"]
    assert all(state.load()["phases"][node.id]["status"] == "accepted" for node in definitions[:8])


def test_explicit_partial_resume_only_adds_necessary_unaccepted_dependencies(tmp_path):
    host = WorkflowEngine()
    definitions = {node.id: node for node in host._get_default_nodes()}
    state = RunState(str(tmp_path), "partial")
    state.start([{"id": key} for key in definitions], {})
    for key in definitions:
        state.set_status(key, "done")
        state.accept(key, "fixture-verdict", "fixture-validator")
    state.invalidate_acceptance("paper", "changed")
    state.invalidate_acceptance("review", "paper changed")
    run = WorkflowRun(id="partial", project_path=str(tmp_path), options={"resume_run_id": "partial"},
        nodes=[definitions["review"]])
    include_reopened_dependencies(host, run, state)
    assert [node.id for node in run.nodes] == ["paper", "review"]
