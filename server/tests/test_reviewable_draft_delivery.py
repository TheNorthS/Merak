"""Draft delivery is an explicit goal with fresh independent integrity verdicts."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.draft_delivery import DRAFT, draft_audit_gate, draft_schema, archive_previous_review
from server.workflows.draft_review_evidence import draft_response_matches
from server.workflows.review_models import ReviewRound, ReviewState
from server.workflows.review_loop import _accept_threshold


def _trace(root, item, *, review=False):
    directory = root / ".merak/model-api-reviewer" / f"call-{item.get('layer', 'review')}"
    directory.mkdir(parents=True)
    raw = json.dumps({key: item[key] for key in ("verdict", "draft_blockers", "score" if review else "summary")}).encode()
    (directory / "response.txt").write_bytes(raw)
    if not review:
        item.update(skill_name="fixture-audit", session_id=f"call-{item['layer']}", model_name="reviewer")
    (directory / "meta.json").write_text(json.dumps({"success": True, "response_sha256": hashlib.sha256(raw).hexdigest(),
        "purpose": f"audit-{item.get('skill_name')}", "invocation_id": item.get("session_id"), "model_identity": item.get("model_name")}))
    (directory / "output.schema.json").write_text(json.dumps({"required": ["draft_blockers"]}))
    if review:
        item["visual_review"] = {"_review_trace_path": str(directory)}
    else:
        item["trace_path"] = str(directory)
    return directory


@pytest.mark.asyncio
async def test_low_scientific_score_can_finish_draft_review_without_becoming_publication_ready(tmp_path, monkeypatch):
    import server.workflows.review_loop as loop
    compile_snapshot = AsyncMock()
    monkeypatch.setattr(loop, "_compile_output_snapshot", compile_snapshot)
    state = ReviewState(delivery_goal=DRAFT)
    review = ReviewRound(1, 4, "major_revision", weaknesses=["Real experiment missing"], draft_blockers=[])
    state.rounds.append(review)
    context = SimpleNamespace(delivery_goal=DRAFT, project_path=str(tmp_path), on_progress=None,
                              reviewer=SimpleNamespace(_save_state=lambda *_: None))
    assert await _accept_threshold(context, state, review, 1)
    assert state.final_score == 4 and state.final_verdict == "major_revision"
    assert state.is_complete and not state.publication_ready and not state.threshold_met
    assert not state.fallback_reason
    assert review.weaknesses == ["Real experiment missing"]
    compile_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_high_score_cannot_bypass_draft_integrity_blocker():
    state = ReviewState(delivery_goal=DRAFT)
    review = ReviewRound(1, 9, "ready", draft_blockers=["[owner=paper] Contradictory number"])
    assert not await _accept_threshold(SimpleNamespace(delivery_goal=DRAFT), state, review, 1)
    assert not state.is_complete


@pytest.mark.parametrize("tamper", [False, True])
def test_draft_fields_are_bound_to_actual_independent_response(tmp_path, tamper):
    item = {"score": 4, "verdict": "major_revision", "draft_blockers": ["Contradiction"]}
    _trace(tmp_path, item, review=True)
    if tamper:
        item["draft_blockers"] = []
    assert draft_response_matches(tmp_path, item, review=True) is not tamper


@pytest.mark.parametrize("defect", ["none", "missing_field", "contradiction", "model_error", "bad_proof", "forged"])
def test_draft_audit_preserves_scientific_failure_but_requires_fresh_integrity(tmp_path, defect):
    entries = [{"layer": i, "verdict": "FAIL", "summary": "Real EEG experiment missing",
        "method": "model", "delivery_goal": DRAFT, "draft_blockers": []} for i in range(1, 6)]
    for item in entries:
        _trace(tmp_path, item)
    bundle = {"entries": entries, "proof_payload": {"verdict": "NOT_APPLICABLE"}, "verdicts": ["FAIL"] * 5}
    if defect == "missing_field":
        entries[0].pop("draft_blockers")
    elif defect == "contradiction":
        entries[0]["draft_blockers"] = ["Numbers disagree"]
    elif defect == "model_error":
        entries[0]["verdict"] = "ERROR"
    elif defect == "bad_proof":
        bundle["proof_payload"]["verdict"] = "FAIL"
    elif defect == "forged":
        (Path(entries[0]["trace_path"]) / "response.txt").write_text("{}")
    host = SimpleNamespace(_verdict_id=lambda *_: "fresh")
    gate = draft_audit_gate(host, bundle, [tmp_path / "audit-results/AUDIT_RESULTS.json"])
    assert gate["accepted"] is (defect == "none")
    assert gate["details"]["publication_ready"] is False
    assert len(gate["details"]["unresolved_scientific_findings"]) == 5


def test_mode_switch_archives_prior_review_bytes(tmp_path):
    path = tmp_path / "review-stage/REVIEW_STATE.json"
    path.parent.mkdir()
    path.write_bytes(b'{"final_score":4,"final_verdict":"major_revision"}')
    archive_previous_review(str(tmp_path))
    assert next((path.parent / "history").glob("*.json")).read_bytes() == path.read_bytes()


def test_draft_schema_requires_independent_blocker_list_without_mutating_submission_schema():
    from server.services.api_visual_review_schemas import REVIEW_SCHEMA
    before = copy.deepcopy(REVIEW_SCHEMA)
    assert "draft_blockers" in draft_schema(REVIEW_SCHEMA)["required"]
    assert REVIEW_SCHEMA == before


def test_draft_completion_never_claims_submission_or_partial_pipeline_completion():
    from server.services.workflow_readiness_assessment import _classification
    context = {"execution_completed": True, "evidence_mode": "synthetic_preview", "options": {"delivery_goal": DRAFT},
        "missing_submission_phases": [], "selected_phase_ids": ["ppt"], "draft_integrity_valid": True}
    ready, kind, _ = _classification(context, ["Scientific evidence missing"], {"valid": True})
    assert ready is False and kind == "reviewable_draft_ready"
    context["draft_integrity_valid"] = False
    assert _classification(context, [], {})[1] == "evidence_blocked"
    context["draft_integrity_valid"] = True
    context["missing_submission_phases"] = ["paper"]
    assert _classification(context, [], {})[1] != "reviewable_draft_ready"


def test_api_and_resume_expose_explicit_delivery_choice_and_preserve_defaults():
    from server.api.workflow import WorkflowRunRequest, WorkflowResumeRequest
    assert WorkflowRunRequest(node_ids=["paper"], project_path="fixture").delivery_goal == "reviewable_draft"
    assert WorkflowRunRequest(node_ids=["paper"], project_path="fixture",
                              delivery_goal="submission_candidate").delivery_goal == "submission_candidate"
    assert WorkflowResumeRequest(delivery_goal=DRAFT).delivery_goal == DRAFT
    with pytest.raises(ValueError):
        WorkflowResumeRequest(delivery_goal="skip_all_checks")


def test_completed_phase_flags_cannot_certify_missing_draft_artifacts(tmp_path):
    from server.services.workflow_readiness import SUBMISSION_PHASES, workflow_readiness_service
    state = {"run_id": "missing-draft", "config": {"options": {"delivery_goal": DRAFT}},
        "phases": {name: {"status": "accepted"} for name in (*SUBMISSION_PHASES, "ppt")}}
    report = workflow_readiness_service.assess(tmp_path, state, persist=False)
    assert report["completion_class"] == "evidence_blocked"
    assert not report["submission_ready"] and not report["publication_ready"]
    assert not report["attestations"]["draft_integrity"]["valid"]


def test_draft_goal_propagates_without_authorizing_scientific_execution():
    from server.services.research_delivery_prompt import research_delivery_instruction
    instruction = research_delivery_instruction({"delivery_goal": DRAFT})
    assert "Do not pursue a publication score" in instruction
    assert "No new training" in instruction and "concrete contradictions" in instruction
    assert research_delivery_instruction({}) == ""
