from server.workflows.resume_policy import (
    phase_is_durably_terminal,
    tool_artifact_path,
    training_check_blocks_current_mode,
)


def test_completed_phase_requires_acceptance_identity() -> None:
    assert phase_is_durably_terminal({"status": "completed"}) is False
    assert phase_is_durably_terminal({
        "status": "completed", "verdict_id": "paper:accepted:v1",
    }) is False
    assert phase_is_durably_terminal({"status": "accepted"}) is True


def test_missing_run_authorization_is_fail_closed() -> None:
    assessment = {"blocking": True}

    assert training_check_blocks_current_mode(assessment, {}) is False
    assert training_check_blocks_current_mode(
        assessment, {"run_experiment": True}
    ) is True


def test_tool_artifact_path_supports_only_structured_events() -> None:
    assert tool_artifact_path({"args": {"path": "paper/main.tex"}}) == "paper/main.tex"
    assert tool_artifact_path({
        "output": "Written 42 bytes to experiments/results/metrics.json"
    }) == ""
