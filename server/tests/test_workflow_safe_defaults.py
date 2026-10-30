"""Safety defaults that must not require an experiment execution environment."""

import re
from pathlib import Path

from server.api.workflow import WorkflowRunRequest
from server.workflows.engine import WorkflowEngine


def test_workflow_request_requires_explicit_scientific_execution_opt_in() -> None:
    request = WorkflowRunRequest(node_ids=["exp-run"], project_path=".")

    assert request.run_experiment is False


def test_missing_runtime_flag_never_authorizes_scientific_execution() -> None:
    assessment = {"blocking": True, "verdict": "FAIL"}

    assert WorkflowEngine._training_check_blocks_current_mode(assessment, {}) is False


def test_production_code_has_no_opt_out_experiment_defaults() -> None:
    root = Path(__file__).resolve().parents[2]
    unsafe_get = re.compile(r"get\(\s*['\"]run_experiment['\"]\s*,\s*True\s*\)")
    unsafe_default = re.compile(r"run_experiment\s*:\s*bool\s*=\s*True")
    findings: list[str] = []
    for source in sorted((root / "server").rglob("*.py")):
        if "tests" in source.parts:
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        if unsafe_get.search(text) or unsafe_default.search(text):
            findings.append(source.relative_to(root).as_posix())
    assert findings == []
