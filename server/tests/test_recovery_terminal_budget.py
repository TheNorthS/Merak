"""Changing signatures cannot silently reopen an exhausted quality transaction."""

from types import SimpleNamespace
import pytest

from server.services.workflow_recovery_policy import due_phase


@pytest.mark.parametrize("flag", ["hard_limit", "stopped_for_no_progress", "stopped_for_deterministic_stage", "stopped_for_managed_stage"])
@pytest.mark.parametrize("where", ["revision", "last_gate"])
def test_changed_artifacts_do_not_automatically_reset_terminal_budget(flag, where):
    revision = {"artifact_signature": "previous", "runtime_signature": "previous", "last_gate": {}}
    (revision if where == "revision" else revision["last_gate"])[flag] = True
    state = {"status": "incomplete", "config": {"options": {"auto_proceed": True}},
             "phases": {"exp-design": {"status": "awaiting_revision", "details": {"revision": revision}}}}

    def forbidden(*args):
        pytest.fail("An exhausted transaction must not probe changes to reauthorize itself")

    engine = SimpleNamespace(_is_platform_repair_revision_checkpoint=lambda r: True,
        _is_transport_revision_checkpoint=lambda r: False,
        _revision_artifact_signature=forbidden, _revision_runtime_signature=forbidden)
    assert due_phase(engine=engine, project_path="fixture", state=state, now=100) == ""


def test_nonterminal_platform_checkpoint_retains_existing_bounded_recovery():
    revision = {"artifact_signature": "previous", "runtime_signature": "previous"}
    state = {"status": "incomplete", "config": {"options": {"auto_proceed": True}},
             "phases": {"figure": {"status": "awaiting_revision", "details": {"revision": revision}}}}
    engine = SimpleNamespace(_is_platform_repair_revision_checkpoint=lambda r: True,
        _is_transport_revision_checkpoint=lambda r: False,
        _revision_artifact_signature=lambda *args: "changed", _revision_runtime_signature=lambda *args: "previous")
    assert due_phase(engine=engine, project_path="fixture", state=state, now=100) == "figure"


def test_explicit_resume_can_reopen_the_same_terminal_checkpoint(tmp_path):
    from server.workflows.resume_execution import _unchanged_checkpoint_action
    from server.workflows.run_state import RunState
    state = RunState(str(tmp_path), "manual-after-stop")
    state.start([{"id": "exp-design", "name": "Design", "skill": "experiment-plan"}], {"options": {}})
    state.set_revision_waiting("exp-design", round_number=2, cycle=1,
        gate={"intervention_kind": "platform_repair", "stopped_for_no_progress": True,
              "summary": "No new progress", "issues": ["one source defect"]},
        artifact_signature="same", runtime_signature="same")
    engine = SimpleNamespace(_revision_artifact_signature=lambda *args: "same",
        _revision_runtime_signature=lambda *args: "same",
        _is_transport_revision_checkpoint=lambda r: False,
        _is_platform_repair_revision_checkpoint=lambda r: True)
    phase = state.load()["phases"]["exp-design"]
    _unchanged_checkpoint_action(engine, state, "exp-design", phase, {}, watchdog=False)
    revision = state.revision_state("exp-design")
    assert revision.get("stopped_for_no_progress") is not True
    assert revision.get("waiting") is False
