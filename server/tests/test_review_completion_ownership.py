"""Review progress prose and missing coverage cannot erase or misroute findings."""

import json
from types import SimpleNamespace

import pytest

from server.services.implementation_review_completion import ImplementationReviewIncomplete
from server.workflows.engine import WorkflowEngine, WorkflowRun


def review(**updates):
    return {"verdict": "FAIL", "summary": "An endpoint calculation is incorrect.",
            "review_complete": True, "unreviewed_files": [], "findings": [{
                "id": "ENDPOINT-1", "severity": "blocker", "scope": "implementation_correctness",
                "category": "statistics", "message": "Nested intervals are counted twice.",
                "target_files": ["experiments/src/metrics.py"],
                "evidence": ["experiments/src/metrics.py:negative_exposure"],
                "remediation": "Correct the interval union.",
            }], **updates}


def test_single_final_json_after_streamed_progress_preserves_exact_defect():
    payload = review()
    raw = "已完成端点检查，下面提交结论。" + json.dumps(payload, ensure_ascii=False)
    result = WorkflowEngine._parse_training_check_result(raw, assurance="draft")
    assert result["blocking"] and result["verdict"] == "FAIL"
    assert result["findings"][0]["id"] == "ENDPOINT-1"
    assert result["findings"][0]["target_files"] == ["experiments/src/metrics.py"]


@pytest.mark.parametrize("raw", [
    json.dumps(review()) + json.dumps(review(verdict="PASS", findings=[])),
    json.dumps(review())[:-2],
    "arbitrary prose with no verdict",
])
def test_ambiguous_or_incomplete_json_remains_invalid(raw):
    with pytest.raises(ValueError):
        WorkflowEngine._parse_training_check_result(raw, assurance="draft")


@pytest.mark.parametrize("changes", [
    {"review_complete": False},
    {"unreviewed_files": ["experiments/src/metrics.py"]},
    {"findings": [{"category": "review_coverage", "severity": "blocker",
                   "message": "Not inspected", "target_files": ["experiments/src/train.py"]}]},
])
def test_incomplete_review_never_becomes_an_author_finding(changes):
    with pytest.raises(ImplementationReviewIncomplete):
        WorkflowEngine._parse_training_check_result(json.dumps(review(**changes)), assurance="draft")


def test_incomplete_review_trace_can_resume_without_a_scientific_acceptance(tmp_path):
    from server.services.implementation_review_completion import parse_review_checkpoint

    path = tmp_path / ".merak/skill-invocations/check_training-check.json"
    path.parent.mkdir(parents=True)
    saved = {"skill": "training-check", "session_id": "review-session", "status": "completed",
             "resume_key": "source-bound-key", "output_sha256": "original-report-hash"}
    path.write_text(json.dumps(saved))
    with pytest.raises(ImplementationReviewIncomplete):
        parse_review_checkpoint(WorkflowEngine._parse_training_check_result,
            json.dumps(review(review_complete=False)), assurance="draft", project_path=str(tmp_path),
            trace={**saved, "trace_path": str(path)})
    updated = json.loads(path.read_text())
    assert updated == {**saved, "status": "failed", "error_code": "IMPLEMENTATION_REVIEW_INCOMPLETE"}
    assert not (tmp_path / ".merak/quality/implementation_review.json").exists()


@pytest.mark.asyncio
async def test_old_coverage_report_forces_review_without_author_obligation(tmp_path):
    from server.services.implementation_review_receipt import stage_obligations, review_source_hash
    from server.workflows.design_review import ensure_design_review

    path = tmp_path / ".merak/quality/implementation_review.json"
    path.parent.mkdir(parents=True)
    old = {"schema": 1, "source_sha256": review_source_hash(tmp_path), "assessment": review()}
    path.write_text(json.dumps(old))
    before = path.read_bytes()
    assert stage_obligations(tmp_path, ["experiments/src/metrics.py"]) == []
    calls = []

    async def review_again(*args):
        calls.append(True)
        raise ImplementationReviewIncomplete("Still incomplete")

    async def emit(*args):
        pass

    host = SimpleNamespace(_emit=emit, _run_code_review=review_again)
    with pytest.raises(ImplementationReviewIncomplete):
        await ensure_design_review(host, SimpleNamespace(project_path=str(tmp_path)), "Fixture", {}, "draft")
    # One bounded read-only continuation is allowed; neither attempt edits the
    # author artifacts or replaces the previous review with invented success.
    assert calls == [True, True] and path.read_bytes() == before


@pytest.mark.asyncio
async def test_format_repair_retains_original_report_and_has_no_tools(tmp_path, monkeypatch):
    from server.agent import tools
    from server.services.skill_orchestrator import skill_orchestrator

    first = json.dumps(review())[:-1] + ",}"
    calls = []

    async def respond(skill, arguments, **kwargs):
        calls.append((arguments, kwargs))
        return first if len(calls) == 1 else json.dumps(review())

    monkeypatch.setattr(tools, "invoke_skill", respond)
    monkeypatch.setattr(skill_orchestrator, "select", lambda *a, **k: None)
    monkeypatch.setattr(skill_orchestrator, "record", lambda *a, **k: None)
    monkeypatch.setattr(skill_orchestrator, "mark_execution", lambda *a, **k: None)
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_skill_invocation_traces", lambda *a: [])
    result = await engine._run_code_review(
        WorkflowRun(id="format-fixture", project_path=str(tmp_path), nodes=[]), "Fixture", "balanced", "draft")
    assert len(calls) == 2 and first in calls[1][0]
    assert calls[1][1]["allowed_tools_override"] == []
    assert engine._parse_training_check_result(result, assurance="draft")["blocking"]


@pytest.mark.asyncio
async def test_incomplete_review_does_not_start_format_retry(tmp_path, monkeypatch):
    from server.agent import tools
    from server.services.skill_orchestrator import skill_orchestrator

    calls = []

    async def respond(*args, **kwargs):
        calls.append(kwargs)
        return json.dumps(review(review_complete=False))

    monkeypatch.setattr(tools, "invoke_skill", respond)
    monkeypatch.setattr(skill_orchestrator, "select", lambda *a, **k: None)
    monkeypatch.setattr(skill_orchestrator, "record", lambda *a, **k: None)
    monkeypatch.setattr(skill_orchestrator, "mark_execution", lambda *a, **k: None)
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_skill_invocation_traces", lambda *a: [])
    with pytest.raises(ImplementationReviewIncomplete):
        await engine._run_code_review(
            WorkflowRun(id="coverage-fixture", project_path=str(tmp_path), nodes=[]), "Fixture", "balanced", "draft")
    assert len(calls) == 1
