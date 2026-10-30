"""Paper stages retain real activity but waiting pulses never defeat their budget."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.paper_stage_invocation import invoke_paper_stage


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["progress", "waiting", "hard_limit"])
async def test_paper_stage_uses_activity_and_joins_cancelled_delegate(tmp_path, monkeypatch, mode):
    host = WorkflowEngine()
    monkeypatch.setattr(host, "_emit", AsyncMock())
    monkeypatch.setattr(host, "_agent_node_timeout_seconds", lambda *args, **kwargs: 0.08)
    monkeypatch.setattr(host, "_agent_node_hard_timeout_seconds", lambda *args, **kwargs: 0.12 if mode == "hard_limit" else 1.0)
    node = WorkflowNode("paper", "Paper", "/domain-paper-write")
    run = WorkflowRun(id="paper-activity", project_path=str(tmp_path), nodes=[node])
    closed = asyncio.Event()

    async def invoke(*args, **kwargs):
        assert kwargs["workflow_node_id"] == "paper"
        try:
            for _ in range(6 if mode == "progress" else 100):
                event = SimpleNamespace(type="status", data={"status": "waiting_model"}) if mode == "waiting" else SimpleNamespace(type="tool_result", data={"success": True})
                await kwargs["on_event"](event)
                await asyncio.sleep(0.03)
            return "authored"
        finally:
            closed.set()

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    operation = invoke_paper_stage(host, node, run, "domain-paper-write", "stage", "contract", AsyncMock())
    if mode == "progress":
        assert await operation == "authored"
    else:
        with pytest.raises(TimeoutError):
            await operation
    assert closed.is_set()


def test_interrupted_consistency_identity_changes_with_authored_input_but_not_its_report(tmp_path):
    from server.workflows.paper_stage_invocation import _resume_inputs
    from server.agent.skill_resume import delegate_identity
    paper = tmp_path / "paper"
    sections = paper / "sections"
    sections.mkdir(parents=True)
    (paper / "main.tex").write_text(r"\input{sections/04_experiments}")
    source = sections / "04_experiments.tex"
    source.write_text("Old unqualified statement.")
    loaded = SimpleNamespace(name="paper-write")
    before = _resume_inputs(str(tmp_path), "consistency")
    original = delegate_identity(loaded, "paper", "consistency", None, input_fingerprint=before)
    (paper / "CROSS_SECTION_REVIEW.md").write_text("Partial review output.")
    assert _resume_inputs(str(tmp_path), "consistency") == before
    source.write_text("Current qualified statement; planned experiment only.")
    after = _resume_inputs(str(tmp_path), "consistency")
    assert after != before
    assert delegate_identity(loaded, "paper", "consistency", None, input_fingerprint=after) != original


def test_author_resume_preserves_own_partial_write_but_restarts_for_upstream_change(tmp_path):
    from server.workflows.paper_stage_invocation import _resume_inputs
    sections = tmp_path / "paper/sections"
    sections.mkdir(parents=True)
    own = sections / "04_experiments.tex"
    upstream = sections / "03_method.tex"
    upstream.write_text("Registered method.")
    before = _resume_inputs(str(tmp_path), "experiments")
    own.write_text("Saved partial author work.")
    assert _resume_inputs(str(tmp_path), "experiments") == before
    upstream.write_text("Corrected registered method.")
    assert _resume_inputs(str(tmp_path), "experiments") != before


def test_consistency_input_tracks_reachable_tables_and_never_its_own_report(tmp_path):
    from server.services.paper_drafting import paper_drafting_service
    paper = tmp_path/'paper';(paper/'tables').mkdir(parents=True)
    (paper/'main.tex').write_text(r'\input{tables/method_components}')
    table=paper/'tables/method_components.tex';table.write_text('Old comparison')
    paths=paper_drafting_service.paths(tmp_path)
    before=paper_drafting_service.stage_input_signature(paths,'consistency')
    (paper/'CROSS_SECTION_REVIEW.md').write_text('FAIL old comparison')
    assert paper_drafting_service.stage_input_signature(paths,'consistency')==before
    table.write_text('Current four-condition mechanism comparison')
    assert paper_drafting_service.stage_input_signature(paths,'consistency')!=before


def test_stale_failed_review_routes_to_reviewer_before_any_author(tmp_path):
    import json
    from server.services.paper_drafting import paper_drafting_service, SECTION_BY_ID
    from server.services.paper_model_consistency_findings import model_consistency_findings
    paper=tmp_path/'paper';(paper/'tables').mkdir(parents=True)
    (paper/'main.tex').write_text(r'\input{tables/method_components}')
    table=paper/'tables/method_components.tex';table.write_text('Old table')
    paths=paper_drafting_service.paths(tmp_path)
    signature=paper_drafting_service.stage_input_signature(paths,'consistency')
    paths['state'].write_text(json.dumps({'stages':{'consistency':{'reviewed_input_signature':signature}}}))
    paths['cross_review'].write_text('# Final Consistency Verdict\nFAIL\n\n1. Contradiction\nResponsible authored section: `paper/sections/03_method.tex`\nRequired scientific repair: correct old table\n')
    table.write_text('Corrected table')
    findings=model_consistency_findings(paths,SECTION_BY_ID.values())
    assert len(findings)==1 and findings[0]['stage_id']=='consistency'
