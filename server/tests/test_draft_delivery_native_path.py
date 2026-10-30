"""Use the real coordinator, schema, traces and gates with an offline scripted provider."""

import json

import pytest

from server.tests.test_review_session_continuity import (
    _ScriptedApiProvider, _patch_independent_api_route, _visual_review,
)
from server.workflows.draft_delivery import DRAFT
from server.workflows.engine import WorkflowEngine
from server.workflows.review_audit import AuditChain, cross_model_reviewer
from server.workflows.run_state import RunState


def _project(root, run_id):
    paper = root / "paper/main.tex"
    paper.parent.mkdir()
    paper.write_text(r"\documentclass{article}\begin{document}An honestly scoped simulation draft.\end{document}")
    (root / "experiments").mkdir()
    durable = RunState(str(root), run_id)
    durable.start([{"id": "review"}, {"id": "audit"}], {"options": {"delivery_goal": DRAFT}})
    return paper


@pytest.mark.asyncio
async def test_low_score_draft_uses_native_trace_and_gate_without_rewriting_verdict(tmp_path, monkeypatch, review_pdf_compiler):
    paper = _project(tmp_path, "draft-native")
    provider = _ScriptedApiProvider({"score": 4, "verdict": "major_revision", "strengths": ["Honest scope"],
        "weaknesses": ["Real experiment missing"], "action_items": ["[owner=exp-run] Execute before publication"],
        "visual_review": _visual_review(), "draft_blockers": []})
    _patch_independent_api_route(monkeypatch, provider)
    state = await cross_model_reviewer.run_review_loop(str(paper), str(tmp_path), run_id="draft-native", evidence_mode="synthetic_preview")
    assert state.is_complete and not state.publication_ready and state.final_score == 4
    path = tmp_path / "review-stage/REVIEW_STATE.json"
    saved = json.loads(path.read_text())
    saved["paper_reconciliation"] = {"passed": True}
    path.write_text(json.dumps(saved))
    engine = WorkflowEngine()
    gate = engine._review_acceptance_gate(str(tmp_path), delivery_goal=DRAFT)
    assert gate["accepted"], gate
    assert gate["details"]["score"] == 4 and gate["details"]["publication_ready"] is False
    assert gate["details"]["unresolved_scientific_findings"]["weaknesses"] == ["Real experiment missing"]
    assert not engine._review_acceptance_gate(str(tmp_path))["accepted"]
    from server.services.draft_readiness import draft_review_issues
    saved = json.loads(path.read_text())
    assert not draft_review_issues(tmp_path, saved, run_id="draft-native", mode="synthetic_preview")
    paper.write_text(paper.read_text() + "\nUnreviewed changed claim.")
    assert draft_review_issues(tmp_path, saved, run_id="draft-native", mode="synthetic_preview")


@pytest.mark.asyncio
async def test_five_real_schema_audits_keep_scientific_fail_and_allow_honest_draft(tmp_path, monkeypatch):
    paper = _project(tmp_path, "draft-audit-native")
    provider = _ScriptedApiProvider(*[{"verdict": "FAIL", "summary": "External evidence missing",
        "evidence": ["paper/main.tex"], "draft_blockers": []} for _ in range(5)])
    _patch_independent_api_route(monkeypatch, provider)
    results = await AuditChain().run_full_audit(str(paper), str(tmp_path / "experiments"), str(tmp_path),
        run_id="draft-audit-native", evidence_mode="synthetic_preview")
    assert len(results) == 6 and all(item.verdict.value == "FAIL" for item in results[:5])
    engine = WorkflowEngine()
    gate = engine._audit_acceptance_gate(str(tmp_path), "draft", "", evidence_mode="synthetic_preview",
        run_id="draft-audit-native", delivery_goal=DRAFT)
    assert gate["accepted"], gate
    assert gate["details"]["publication_ready"] is False
    assert not engine._audit_acceptance_gate(str(tmp_path), "submission", "", evidence_mode="synthetic_preview",
        run_id="draft-audit-native")["accepted"]
    from server.workflows.audit_coordinator import _start_contract
    from server.workflows.audit_layer_checkpoint import load_layer_checkpoints
    from server.workflows.draft_delivery import AUDIT_DELIVERY
    from types import SimpleNamespace
    token = AUDIT_DELIVERY.set(DRAFT)
    try:
        contract = _start_contract(str(tmp_path))
    finally:
        AUDIT_DELIVERY.reset(token)
    checkpoints = load_layer_checkpoints(SimpleNamespace(project_path=str(tmp_path), run_id="draft-audit-native",
        evidence_mode="synthetic_preview"), contract)
    assert set(checkpoints) == {1, 2, 3, 4, 5}
