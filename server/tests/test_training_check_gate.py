import json
from pathlib import Path

import pytest

from server.services.node_risk_audit import node_risk_audit_service
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows.run_state import RunState
from server.workflows.training_check_result import (
    MAX_TRAINING_CHECK_FINDINGS,
    protocol_failure_result,
)


def test_training_check_parser_preserves_actionable_failures() -> None:
    result = json.dumps({
        "verdict": "FAIL",
        "summary": "The pseudo-group control is not independent.",
        "findings": [{
            "id": "CONTROL-001",
            "severity": "blocker",
            "category": "implementation",
            "message": "pseudo_group reuses the true class mask",
            "target_files": ["experiments/src/train.py"],
            "evidence": ["experiments/src/train.py:build_control"],
            "remediation": "Implement an independent pseudo-group assignment.",
        }],
    })

    assessment = WorkflowEngine._parse_training_check_result(
        result,
        assurance="submission",
    )

    assert assessment["verdict"] == "FAIL"
    assert assessment["blocking"] is True
    assert assessment["findings"][0]["owner_node"] == "exp-design"
    assert assessment["findings"][0]["target_files"] == [
        "experiments/src/train.py"
    ]


def test_training_check_warning_only_is_advisory_at_submission() -> None:
    result = json.dumps({
        "verdict": "WARN",
        "summary": "Add package versions to provenance.",
        "findings": [{
            "severity": "warning",
            "message": "Add package versions to provenance.",
        }],
    })

    submission = WorkflowEngine._parse_training_check_result(
        result,
        assurance="submission",
    )
    draft = WorkflowEngine._parse_training_check_result(
        result,
        assurance="draft",
    )

    assert submission["blocking"] is False
    assert draft["blocking"] is False


def test_training_check_does_not_infer_verdict_from_prose() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        WorkflowEngine._parse_training_check_result(
            "WARN\n- Add package versions to provenance.", assurance="submission",
        )


def test_training_check_warn_with_blocker_blocks_submission() -> None:
    result = json.dumps({
        "verdict": "WARN",
        "summary": "One execution-critical issue remains.",
        "findings": [{
            "severity": "blocker",
            "message": "The configured training entrypoint does not exist.",
            "target_files": ["experiments/RUN_SPEC.json"],
        }],
    })

    assessment = WorkflowEngine._parse_training_check_result(
        result,
        assurance="submission",
    )

    assert assessment["blocking"] is True


def test_training_check_parser_bounds_findings_and_long_fields() -> None:
    result = json.dumps({
        "verdict": "FAIL",
        "summary": "bounded",
        "findings": [{
            "id": f"F{index}",
            "severity": "blocker",
            "message": f"m{index}" + "m" * 1999,
            "evidence": ["e" * 1000 for _ in range(10)],
            "remediation": "r" * 2000,
        } for index in range(MAX_TRAINING_CHECK_FINDINGS + 3)],
    })

    assessment = WorkflowEngine._parse_training_check_result(
        result, assurance="draft",
    )

    assert len(assessment["findings"]) == MAX_TRAINING_CHECK_FINDINGS
    assert all(len(item["message"]) <= 900 for item in assessment["findings"])
    assert all(len(item["evidence"]) <= 4 for item in assessment["findings"])
    assert all(len(value) <= 240 for item in assessment["findings"] for value in item["evidence"])
    assert all(len(item["remediation"]) <= 600 for item in assessment["findings"])


def test_training_check_protocol_failure_cannot_manufacture_an_advisory() -> None:
    with pytest.raises(RuntimeError, match="TRAINING_CHECK_PROTOCOL_ERROR.*resume required"):
        protocol_failure_result("unterminated JSON", "length")


def test_failed_training_check_is_owned_by_exp_design(tmp_path: Path) -> None:
    options = {
        "run_experiment": True,
        "gpu_target": "local",
        "_training_check": {
            "blocking": True,
            "verdict": "FAIL",
            "summary": "Implementation mismatch.",
            "findings": [{
                "id": "TRAINING-CHECK-TEST",
                "message": "Declared control is not implemented.",
                "target_files": ["experiments/src/train.py"],
                "remediation": "Implement the declared control.",
            }],
        },
    }

    findings = node_risk_audit_service._audit_exp_run(tmp_path, options)

    assert len(findings) == 1
    assert findings[0]["id"] == "TRAINING-CHECK-TEST"
    assert findings[0]["severity"] == "blocker"
    assert findings[0]["upstream_node"] == "exp-design"


@pytest.mark.asyncio
async def test_failed_training_check_prevents_experiment_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(
        id="exp-run",
        name="Experiment",
        skill="/experiment-bridge",
        depends_on=[],
    )
    options = {
        "run_experiment": True,
        "gpu_target": "local",
        "code_review": True,
        "auto_proceed": False,
        "human_checkpoint": False,
        "research_quality_mode": "off",
    }
    run = WorkflowRun(
        id="training-check-block",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options=dict(options),
    )
    state = RunState(str(tmp_path), run.id)
    state.start(
        [{
            "id": node.id,
            "name": node.name,
            "skill": node.skill,
            "execution_kind": node.execution_kind,
            "runtime_service": node.runtime_service,
            "policy_required": node.policy_required,
        }],
        {
            "direction": "test research",
            "effort": "lite",
            "assurance": "submission",
            "options": dict(options),
        },
    )
    launched = False

    async def no_sleep(_seconds: float) -> None:
        return None

    async def no_emit(*_args, **_kwargs) -> None:
        return None

    async def failed_review(*_args, **_kwargs) -> str:
        return json.dumps({
            "verdict": "FAIL",
            "summary": "Training implementation is incomplete.",
            "findings": [{
                "id": "IMPLEMENTATION-001",
                "message": "The declared baseline is missing.",
                "target_files": ["experiments/src/train.py"],
                "remediation": "Implement the baseline before training.",
            }],
        })

    async def managed_experiment(*_args, **_kwargs) -> str:
        nonlocal launched
        launched = True
        return "should not run"

    async def waiting_revision(**kwargs):
        assessment = kwargs["opts"]["_training_check"]
        assert assessment["blocking"] is True
        assert assessment["findings"][0]["owner_node"] == "exp-design"
        return {"accepted": False, "waiting": True}, kwargs["initial_result"]

    async def no_notification(**_kwargs):
        return {"delivered": False, "reason": "test"}

    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", no_sleep)
    monkeypatch.setattr(engine, "_emit", no_emit)
    monkeypatch.setattr(engine, "_run_code_review", failed_review)
    monkeypatch.setattr(engine, "_execute_managed_experiment", managed_experiment)
    monkeypatch.setattr(engine, "_run_node_revision_loop", waiting_revision)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.notification.notification_service.workflow_failed",
        no_notification,
    )
    monkeypatch.setattr(
        "server.services.notification.notification_service.workflow_completed",
        no_notification,
    )

    await engine._execute_run(
        run,
        "test research",
        "lite",
        "submission",
        options,
    )

    assert launched is False
    report = json.loads(
        (tmp_path / ".merak" / "quality" / "training_check.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["verdict"] == "FAIL"
    assert report["blocking"] is True
