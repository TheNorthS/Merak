from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from server.agent import ModelRole, ModelRouter
from server.agent.engine import agent_engine
from server.services.api_visual_reviewer import (
    API_IMAGE_ATTACHMENT_MODE,
    API_VISUAL_REVIEW_TRANSPORT,
    ApiVisualReview,
    api_visual_reviewer,
)
from server.services.paper_compiler import CompileError, CompileResult, paper_compiler
from server.services.skill_orchestrator import skill_orchestrator
from server.workflows.engine import WorkflowEngine
from server.workflows.review_audit import (
    AuditChain,
    REVIEW_NATIVE_IMAGE_LIMIT,
    ReviewState,
    cross_model_reviewer,
    model_router,
    review_source_bundle,
)


def test_saving_pdf_bookkeeping_does_not_rebind_stale_review_state(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("old manuscript\n", encoding="utf-8")
    reviewed_hash, _ = review_source_bundle(tmp_path)
    state = ReviewState(
        run_id="review-source-binding",
        source_bundle_sha256=reviewed_hash,
    )

    paper.write_text("revised manuscript\n", encoding="utf-8")
    revised_hash, _ = review_source_bundle(tmp_path)
    assert revised_hash != reviewed_hash

    cross_model_reviewer._save_state(state, str(tmp_path))
    payload = json.loads(
        (tmp_path / "review-stage" / "REVIEW_STATE.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["source_bundle_sha256"] == reviewed_hash
    assert state.source_bundle_sha256 == reviewed_hash


def _visual_review(pdf_path: str = "paper/main.pdf") -> dict[str, str]:
    return {
        "pdf_path": pdf_path,
        "figure_quality": "Figures are legible at the rendered page scale.",
        "caption_alignment": "Captions align with their referenced figures.",
        "page_layout": "No clipping, overlap, or orphan heading was observed.",
        "table_formatting": "Table columns and emphasis are consistent.",
        "visual_consistency": "Typography and visual encoding are consistent.",
    }


class _ScriptedApiProvider:
    def __init__(self, *responses: Any, model: str = "vision-reviewer") -> None:
        self.name = "openai"
        self.model = model
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def chat(self, messages, **kwargs):
        self.requests.append({"messages": messages, **kwargs})
        if not self._responses:
            raise AssertionError("unexpected independent reviewer API call")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        content = json.dumps(response) if isinstance(response, dict) else str(response)
        return SimpleNamespace(content=content, model=self.model)


def _patch_independent_api_route(
    monkeypatch: pytest.MonkeyPatch,
    reviewer: _ScriptedApiProvider,
    *,
    executor_identity: str = "anthropic/writer",
    reviewer_identity: str = "openai/vision-reviewer",
) -> None:
    executor = SimpleNamespace(name="anthropic", model="writer")
    monkeypatch.setattr(
        model_router,
        "get_provider_route",
        lambda _role: ("executor-api", executor, executor_identity),
    )
    monkeypatch.setattr(
        model_router,
        "get_isolated_provider_route",
        lambda role: (
            "reviewer-api",
            reviewer,
            reviewer_identity,
        ),
    )


def _request_text(request: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in request.get("messages") or []:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return "\n".join(parts)


def test_same_provider_with_different_models_is_independent() -> None:
    router = ModelRouter()
    writer = SimpleNamespace(name="openai", model="gpt-writer")
    reviewer = SimpleNamespace(name="openai", model="gpt-reviewer")
    router._providers = {"writer": writer, "reviewer": reviewer}
    router._strategy = {
        ModelRole.EXECUTOR: "writer",
        ModelRole.REVIEWER: "reviewer",
    }

    provider_name, provider, identity = router.get_isolated_provider_route(
        ModelRole.REVIEWER,
    )

    assert provider_name == "reviewer"
    assert provider is reviewer
    assert identity == "openai/gpt-reviewer"
    assert identity != router.get_provider_route(ModelRole.EXECUTOR)[2]


def test_identical_models_are_allowed_for_isolated_review_sessions() -> None:
    router = ModelRouter()
    writer = SimpleNamespace(name="openai", model="gpt-shared")
    reviewer_alias = SimpleNamespace(name="openai", model="gpt-shared")
    router._providers = {"writer": writer, "reviewer": reviewer_alias}
    router._strategy = {
        ModelRole.EXECUTOR: "writer",
        ModelRole.REVIEWER: "reviewer",
    }

    _, _, executor_identity = router.get_provider_route(ModelRole.EXECUTOR)
    provider_name, provider, reviewer_identity = (
        router.get_isolated_provider_route(
            ModelRole.REVIEWER,
        )
    )

    assert provider_name == "reviewer"
    assert provider is reviewer_alias
    assert reviewer_identity == executor_identity == "openai/gpt-shared"


def test_selected_reviewer_route_is_not_silently_replaced() -> None:
    router = ModelRouter()
    writer = SimpleNamespace(name="openai", model="gpt-shared")
    reviewer_alias = SimpleNamespace(name="openai", model="gpt-shared")
    independent = SimpleNamespace(name="glm", model="glm-reviewer")
    router._providers = {
        "writer": writer,
        "reviewer": reviewer_alias,
        "glm": independent,
    }
    router._strategy = {
        ModelRole.EXECUTOR: "writer",
        ModelRole.REVIEWER: "reviewer",
    }

    provider_name, provider, identity = router.get_isolated_provider_route(
        ModelRole.REVIEWER,
    )

    assert provider_name == "reviewer"
    assert provider is reviewer_alias
    assert identity == "openai/gpt-shared"


@pytest.mark.asyncio
async def test_review_rounds_use_fresh_independent_api_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\n\\begin{document}\nInitial draft.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    reviewer = _ScriptedApiProvider(
        {
            "score": 5,
            "verdict": "needs_work",
            "strengths": ["Clear question"],
            "weaknesses": ["The limitation is not explicit."],
            "action_items": [
                "[owner=paper] [target=paper/main.tex] Add the limitation."
            ],
            "visual_review": _visual_review(),
        },
        {
            "score": 8,
            "verdict": "ready",
            "strengths": ["The limitation is now explicit."],
            "weaknesses": [],
            "action_items": [],
            "visual_review": _visual_review(),
        },
    )
    _patch_independent_api_route(monkeypatch, reviewer)

    async def fake_run(session_id: str, *_args, **_kwargs) -> str:
        session = agent_engine.get_session(session_id)
        assert session is not None
        assert session.model_role == ModelRole.EXECUTOR
        paper.write_text(
            paper.read_text(encoding="utf-8").replace(
                "Initial draft.",
                "Initial draft. This study is limited by the declared evidence scope.",
            ),
            encoding="utf-8",
        )
        return "Targeted limitation edit completed."

    monkeypatch.setattr(agent_engine, "run", fake_run)

    state = await cross_model_reviewer.run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=2,
        difficulty="hard",
        run_id="continuous-review",
        evidence_mode="executed",
    )

    assert state.publication_ready is True
    assert len(state.rounds) == 2
    assert len(state.reviewer_session_ids) == 2
    assert len(set(state.reviewer_session_ids)) == 2
    assert all(
        session_id.startswith("model-api:")
        for session_id in state.reviewer_session_ids
    )
    assert len(reviewer.requests) == 2
    assert len(review_pdf_compiler) == 3
    original = tmp_path / "paper" / "main_round0_original.pdf"
    round_one = tmp_path / "paper" / "main_round1.pdf"
    round_two = tmp_path / "paper" / "main_round2.pdf"
    assert original.is_file()
    assert round_one.is_file()
    assert round_two.is_file()
    assert original.read_bytes() != round_one.read_bytes()
    assert round_one.read_bytes() == round_two.read_bytes()
    reviewer_inputs = [
        request["messages"][-1].content[0]["text"]
        for request in reviewer.requests
    ]
    assert "paper/main_round0_original.pdf" in reviewer_inputs[0]
    assert "paper/main_round1.pdf" in reviewer_inputs[1]
    assert "Mandatory Current-PDF Visual Review" in reviewer_inputs[0]
    assert "figure_quality" in reviewer_inputs[0]
    assert all(
        any(block.get("type") == "image_url" for block in request["messages"][-1].content)
        for request in reviewer.requests
    )
    persisted = json.loads(
        (tmp_path / "review-stage" / "REVIEW_STATE.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["reviewer_session_ids"] == state.reviewer_session_ids
    assert [item["round"] for item in persisted["pdf_snapshots"]] == [0, 1, 2]
    assert persisted["rounds"][-1]["visual_review"]["page_layout"]


def test_ready_verdict_requires_complete_compiled_pdf_visual_review() -> None:
    from server.workflows.review_audit import ReviewRound, ReviewState

    review_round = ReviewRound(
        round_number=1,
        score=8,
        verdict="ready",
    )
    state = ReviewState(rounds=[review_round])
    assert state.should_stop() is False

    review_round.visual_review = _visual_review("paper/main_round0_original.pdf")
    review_round.visual_review.update({
        "_coordinator_verified": "true",
        "_source_bundle_sha256": "source-hash",
        "_visual_bundle_sha256": "visual-hash",
        "_visual_content_sha256": "visual-content-hash",
        "_review_image_paths": '["paper/page.png"]',
        "_review_image_bundle_sha256": "review-image-hash",
        "_review_response_sha256": "review-response-hash",
        "_review_transport": API_VISUAL_REVIEW_TRANSPORT,
        "_review_trace_path": ".merak/model-api-reviewer/review-round-1",
        "_review_invocation_id": "model-api:review-1",
        "_review_model_identity": "openai/reviewer",
    })
    assert state.should_stop()


@pytest.mark.asyncio
async def test_review_refuses_to_score_tex_when_fresh_pdf_compile_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Draft\\end{document}",
        encoding="utf-8",
    )
    writer = SimpleNamespace(name="writer", model="writer-model")
    reviewer = SimpleNamespace(name="reviewer", model="reviewer-model")
    monkeypatch.setattr(
        model_router,
        "get_provider_route",
        lambda _role: ("writer", writer, "writer/writer-model"),
    )
    monkeypatch.setattr(
        model_router,
        "get_isolated_provider_route",
        lambda role: (
            "reviewer",
            reviewer,
            "reviewer/reviewer-model",
        ),
    )

    async def failed_compile(*_args, **_kwargs) -> CompileResult:
        return CompileResult(
            success=False,
            errors=[CompileError(
                file="main.tex",
                line=7,
                message="Undefined control sequence.",
                severity="error",
            )],
        )

    async def must_not_review(*_args, **_kwargs) -> str:
        raise AssertionError("reviewer must not score a TeX-only manuscript")

    monkeypatch.setattr(paper_compiler, "compile", failed_compile)
    monkeypatch.setattr(agent_engine, "run", must_not_review)

    with pytest.raises(RuntimeError, match="requires a fresh compiled PDF"):
        await cross_model_reviewer.run_review_loop(
            paper_path=str(paper),
            project_path=str(tmp_path),
            max_rounds=1,
            run_id="compile-failure-review",
            evidence_mode="executed",
        )


@pytest.mark.asyncio
async def test_review_accepts_same_model_through_fresh_reviewer_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\n\\begin{document}\nA complete draft.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    reviewer = _ScriptedApiProvider(
        {
            "score": 8,
            "verdict": "ready",
            "strengths": ["The complete rendered study is coherent."],
            "weaknesses": [],
            "action_items": [],
            "visual_review": _visual_review(
                "paper/main_round0_original.pdf"
            ),
        },
        model="gpt-shared",
    )
    _patch_independent_api_route(
        monkeypatch,
        reviewer,
        executor_identity="openai/gpt-shared",
        reviewer_identity="openai/gpt-shared",
    )
    state = await cross_model_reviewer.run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=1,
        difficulty="hard",
        run_id="shared-model-review",
        evidence_mode="executed",
    )

    assert state.publication_ready is True
    assert state.executor_model == state.reviewer_model == "openai/gpt-shared"
    assert len(state.reviewer_session_ids) == 1
    assert state.reviewer_session_ids[0].startswith("model-api:")
    assert len(reviewer.requests) == 1
    trace_meta = json.loads(
        (
            Path(state.rounds[-1].visual_review["_review_trace_path"])
            / "meta.json"
        ).read_text(encoding="utf-8")
    )
    assert trace_meta["same_model"] is True
    assert trace_meta["session_isolation"] == "fresh_context"


@pytest.mark.asyncio
async def test_independent_api_reviews_native_pdf_images_and_trace_is_tamper_evident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\n\\begin{document}\nVisual draft.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    response_payload = {
        "score": 8,
        "verdict": "ready",
        "strengths": ["The compiled layout is readable."],
        "weaknesses": [],
        "action_items": [],
        "visual_review": _visual_review(
            "paper/main_round0_original.pdf"
        ),
    }
    reviewer = _ScriptedApiProvider(response_payload)
    _patch_independent_api_route(monkeypatch, reviewer)

    state = await cross_model_reviewer.run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=1,
        run_id="native-api-visual-review",
        evidence_mode="executed",
    )

    assert state.reviewer_provider == "reviewer-api"
    assert state.reviewer_model == "openai/vision-reviewer"
    assert state.publication_ready is True
    assert len(reviewer.requests) == 1
    assert reviewer.requests[0]["tools"] is None
    user_content = reviewer.requests[0]["messages"][-1].content
    captured_prompt = user_content[0]["text"]
    assert "contact_sheets" in captured_prompt
    assert "native_image_attachments" in captured_prompt
    assert "top_text" not in captured_prompt
    assert "bottom_text" not in captured_prompt
    image_blocks = [block for block in user_content if block["type"] == "image_url"]
    assert image_blocks
    assert all(block["image_url"]["detail"] == "high" for block in image_blocks)

    gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))
    assert gate["accepted"] is True
    assert gate["details"]["visual_evidence"]["verified"] is True

    trace_meta_path = (
        Path(state.rounds[-1].visual_review["_review_trace_path"])
        / "meta.json"
    )
    successful_trace_meta = json.loads(
        trace_meta_path.read_text(encoding="utf-8")
    )
    assert successful_trace_meta["transport"] == API_VISUAL_REVIEW_TRANSPORT
    assert successful_trace_meta["image_attachment_mode"] == API_IMAGE_ATTACHMENT_MODE
    assert successful_trace_meta["tool_policy"] == "model-output-only"
    failed_trace_meta = {
        **successful_trace_meta,
        "success": False,
        "failure_kind": "timeout",
    }
    trace_meta_path.write_text(
        json.dumps(failed_trace_meta),
        encoding="utf-8",
    )
    failed_trace_gate = WorkflowEngine()._review_acceptance_gate(
        str(tmp_path),
    )
    assert failed_trace_gate["accepted"] is False
    assert any(
        "execution policy" in issue
        for issue in failed_trace_gate["details"]["visual_evidence"]["issues"]
    )
    strict_trace_mutations = [
        ("schema_version", 2, False),
        ("schema_version", "1", False),
        ("success", None, True),
        ("success", "true", False),
        ("failure_kind", "timeout", False),
        ("transport", "text-only-api", False),
        ("image_attachment_mode", "none", False),
        ("tool_policy", "agent-tools", False),
    ]
    for field, value, remove_field in strict_trace_mutations:
        invalid_meta = dict(successful_trace_meta)
        if remove_field:
            invalid_meta.pop(field, None)
        else:
            invalid_meta[field] = value
        trace_meta_path.write_text(json.dumps(invalid_meta), encoding="utf-8")
        invalid_gate = WorkflowEngine()._review_acceptance_gate(
            str(tmp_path),
        )
        assert invalid_gate["accepted"] is False, field
        assert any(
            "execution policy" in issue
            for issue in invalid_gate["details"]["visual_evidence"]["issues"]
        ), field
    trace_meta_path.write_text(
        json.dumps(successful_trace_meta),
        encoding="utf-8",
    )

    packet_path = trace_meta_path.parent / "evidence-packet.txt"
    successful_packet = packet_path.read_bytes()
    packet_path.write_bytes(successful_packet + b"\nforged evidence")
    forged_packet_gate = WorkflowEngine()._review_acceptance_gate(
        str(tmp_path),
    )
    assert forged_packet_gate["accepted"] is False
    assert any(
        "frozen evidence packet" in issue
        for issue in forged_packet_gate["details"]["visual_evidence"]["issues"]
    )
    packet_path.write_bytes(successful_packet)

    nonisolated_route_meta = json.loads(json.dumps(successful_trace_meta))
    nonisolated_route_meta["reviewer_route"]["session_isolation"] = "shared_context"
    nonisolated_route_meta["reviewer_route_sha256"] = hashlib.sha256(
        json.dumps(
            nonisolated_route_meta["reviewer_route"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    nonisolated_route_meta["request_sha256"] = hashlib.sha256(
        "\0".join((
            nonisolated_route_meta["invocation_id"],
            nonisolated_route_meta["purpose"],
            nonisolated_route_meta["prompt_sha256"],
            nonisolated_route_meta["schema_sha256"],
            nonisolated_route_meta["reviewer_route_sha256"],
            *[
                f"{path}:{nonisolated_route_meta['image_sha256'][path]}"
                for path in nonisolated_route_meta["image_paths"]
            ],
        )).encode("utf-8")
    ).hexdigest()
    trace_meta_path.write_text(
        json.dumps(nonisolated_route_meta),
        encoding="utf-8",
    )
    nonisolated_route_gate = WorkflowEngine()._review_acceptance_gate(
        str(tmp_path),
    )
    assert nonisolated_route_gate["accepted"] is False
    assert any(
        "API route is not session-isolated" in issue
        for issue in nonisolated_route_gate["details"]["visual_evidence"]["issues"]
    )
    trace_meta_path.write_text(
        json.dumps(successful_trace_meta),
        encoding="utf-8",
    )

    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    successful_state = json.loads(state_path.read_text(encoding="utf-8"))
    forged_state = json.loads(json.dumps(successful_state))
    forged_state["rounds"][-1]["score"] = 9.5
    forged_state["rounds"][-1]["visual_review"]["page_layout"] = (
        "Forged layout verdict."
    )
    state_path.write_text(json.dumps(forged_state), encoding="utf-8")
    forged_sidecar_gate = WorkflowEngine()._review_acceptance_gate(
        str(tmp_path),
    )
    assert forged_sidecar_gate["accepted"] is False
    assert any(
        "trace response does not match" in issue
        for issue in forged_sidecar_gate["details"]["visual_evidence"]["issues"]
    )
    state_path.write_text(json.dumps(successful_state), encoding="utf-8")

    final_preview = tmp_path / state.pdf_snapshots[-1]["page_preview_paths"][0]
    final_preview.write_bytes(final_preview.read_bytes() + b"tampered-after-review")
    stale_gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))
    assert stale_gate["accepted"] is False
    assert stale_gate["reason"] == (
        "managed review lacks current native PDF visual evidence"
    )
    assert any(
        "final visual" in issue or "page pixels changed" in issue
        for issue in stale_gate["details"]["visual_evidence"]["issues"]
    )


@pytest.mark.asyncio
async def test_native_review_timeout_persists_honest_state_and_resumes_same_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\n\\begin{document}\nComplete study.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    reviewer = _ScriptedApiProvider(
        asyncio.TimeoutError("model API reviewer timed out"),
        {
            "score": 8,
            "verdict": "ready",
            "strengths": ["The complete rendered study is coherent."],
            "weaknesses": [],
            "action_items": [],
            "visual_review": _visual_review(
                "paper/main_round0_original.pdf"
            ),
        },
    )
    _patch_independent_api_route(monkeypatch, reviewer)

    with pytest.raises(TimeoutError, match="model API visual review timed out"):
        await cross_model_reviewer.run_review_loop(
            paper_path=str(paper),
            project_path=str(tmp_path),
            max_rounds=1,
            run_id="timeout-resume-review",
            evidence_mode="synthetic_preview",
        )

    state_path = tmp_path / "review-stage" / "REVIEW_STATE.json"
    interrupted = json.loads(state_path.read_text(encoding="utf-8"))
    assert interrupted["phase"] == "review_transport_failed"
    assert interrupted["rounds"] == []
    assert interrupted["is_complete"] is False
    assert interrupted["bounded_complete"] is False
    assert interrupted["threshold_met"] is False
    assert interrupted["reviewer_model"] == "openai/vision-reviewer"
    assert interrupted["transport_failure"]["round"] == 1
    assert interrupted["transport_failure"]["review_image_paths"]
    assert interrupted["transport_failure"]["review_image_bundle_sha256"]
    assert [item["round"] for item in interrupted["pdf_snapshots"]] == [0]
    assert (tmp_path / "paper" / "main_round0_original.pdf").is_file()
    assert not (tmp_path / "paper" / "main_round1.pdf").exists()

    resumed = await cross_model_reviewer.run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=1,
        run_id="timeout-resume-review",
        evidence_mode="synthetic_preview",
    )

    assert len(reviewer.requests) == 2
    assert len(resumed.rounds) == 1
    assert resumed.rounds[0].score == 8
    assert resumed.phase == "completed"
    assert resumed.transport_failure == {}
    assert [item["round"] for item in resumed.pdf_snapshots] == [0, 1]
    persisted_text = state_path.read_text(encoding="utf-8")
    assert "deterministic:bounded-timeout" not in persisted_text
    assert "DETERMINISTIC BOUNDED FALLBACK" not in persisted_text

    reused = await cross_model_reviewer.run_review_loop(
        paper_path=str(paper),
        project_path=str(tmp_path),
        max_rounds=1,
        run_id="timeout-resume-review",
        evidence_mode="synthetic_preview",
    )
    assert reused.current_round == resumed.current_round
    assert len(reused.rounds) == 1
    assert len(reviewer.requests) == 2

    gate = WorkflowEngine()._review_acceptance_gate(str(tmp_path))
    assert gate["accepted"] is True
    assert gate["details"]["visual_evidence"]["verified"] is True


@pytest.mark.asyncio
async def test_invalid_reviewer_output_does_not_create_a_scored_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_pdf_compiler,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\\begin{document}Draft\\end{document}",
        encoding="utf-8",
    )
    reviewer = _ScriptedApiProvider()
    _patch_independent_api_route(monkeypatch, reviewer)

    async def malformed_review(**_kwargs) -> ApiVisualReview:
        return ApiVisualReview(
            text="This is prose, not the required review object.",
            invocation_id="model-api:invalid-review",
            model_identity="openai/vision-reviewer",
            provider_name="reviewer-api",
            trace_path=str(tmp_path / ".merak" / "model-api-reviewer" / "invalid"),
        )

    monkeypatch.setattr(api_visual_reviewer, "review_manuscript", malformed_review)

    with pytest.raises(
        ValueError,
        match="no schema-conforming review JSON",
    ):
        await cross_model_reviewer.run_review_loop(
            paper_path=str(paper),
            project_path=str(tmp_path),
            max_rounds=1,
            run_id="invalid-review-output",
            evidence_mode="executed",
        )

    persisted = json.loads(
        (tmp_path / "review-stage" / "REVIEW_STATE.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["phase"] == "review_output_invalid"
    assert persisted["rounds"] == []
    assert persisted["is_complete"] is False
    assert persisted["bounded_complete"] is False
    assert persisted["final_score"] == 0
    assert not (tmp_path / "paper" / "main_round1.pdf").exists()


def test_native_review_packet_is_bounded_and_prioritizes_visual_risk(
    tmp_path: Path,
) -> None:
    preview_root = tmp_path / "paper" / "review-previews" / "round_0"
    preview_root.mkdir(parents=True)
    previews: list[str] = []
    for page_number in range(1, 19):
        path = preview_root / f"page_{page_number:03d}.png"
        path.write_bytes(f"page-{page_number}".encode())
        previews.append(path.relative_to(tmp_path).as_posix())
    contact = preview_root / "contact_sheet_001.png"
    contact.write_bytes(b"all-pages-contact-sheet")
    layout = {
        "renderer": "test",
        "page_count": 18,
        "document_findings": [],
        "pages": [
            {
                "page": page_number,
                "image_instances": 1 if page_number == 7 else 0,
                "possible_layout_findings": (
                    ["possible overlap"] if page_number == 12 else []
                ),
                "top_text": f"private top text {page_number}",
                "bottom_text": f"private bottom text {page_number}",
            }
            for page_number in range(1, 19)
        ],
    }
    layout_path = preview_root / "layout.json"
    layout_path.write_text(json.dumps(layout), encoding="utf-8")
    snapshot = {
        "snapshot_path": "paper/main_round0_original.pdf",
        "current_pdf_path": "paper/main.pdf",
        "pdf_sha256": "pdf-hash",
        "pages": 18,
        "page_preview_paths": previews,
        "contact_sheet_paths": [contact.relative_to(tmp_path).as_posix()],
        "layout_report_path": layout_path.relative_to(tmp_path).as_posix(),
    }

    selected = cross_model_reviewer._native_review_image_paths(
        tmp_path,
        snapshot,
    )
    assert len(selected) <= REVIEW_NATIVE_IMAGE_LIMIT
    assert selected[0] == contact.relative_to(tmp_path).as_posix()
    assert previews[11] in selected
    assert previews[6] in selected

    context = cross_model_reviewer._pdf_review_context(
        str(tmp_path),
        snapshot,
        review_images=selected,
    )
    assert "top_text" not in context
    assert "bottom_text" not in context
    assert previews[9] not in context
    assert "native_image_attachments" in context


def test_cross_section_reconciliation_does_not_stale_review_source_bundle(
    tmp_path: Path,
) -> None:
    paper_root = tmp_path / "paper"
    paper_root.mkdir(parents=True)
    (paper_root / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}Stable\\end{document}",
        encoding="utf-8",
    )
    reconciliation = paper_root / "CROSS_SECTION_REVIEW.md"
    reconciliation.write_text("first coordinator pass", encoding="utf-8")
    before, before_paths = review_source_bundle(tmp_path)

    reconciliation.write_text("second coordinator pass", encoding="utf-8")
    after, after_paths = review_source_bundle(tmp_path)

    assert before == after
    assert before_paths == after_paths
    assert reconciliation.resolve() not in before_paths


@pytest.mark.asyncio
async def test_independent_model_api_supplies_audit_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewer = _ScriptedApiProvider({
        "verdict": "PASS",
        "summary": "Execution artifacts are internally consistent.",
        "evidence": ["experiments/RUN_SPEC.json"],
    })
    _patch_independent_api_route(monkeypatch, reviewer)
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "RUN_SPEC.json").write_text("{}\n", encoding="utf-8")

    result = await AuditChain()._audit_experiment(
        str(paper),
        str(experiments),
        str(tmp_path),
        "executed",
    )

    assert result.verdict.value == "PASS"
    assert result.method == "model"
    assert result.session_id.startswith("model-api:")
    assert result.model_name == "openai/vision-reviewer"
    assert len(reviewer.requests) == 1
    assert "experiment-audit" in _request_text(reviewer.requests[0])
    assert reviewer.requests[0].get("tools") is None


@pytest.mark.asyncio
async def test_simulation_adjudication_follows_loaded_audit_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewer = _ScriptedApiProvider({
        "verdict": "WARN",
        "summary": "The completed negative result is internally consistent.",
        "evidence": ["experiments/RUN_SPEC.json"],
    })
    _patch_independent_api_route(monkeypatch, reviewer)
    monkeypatch.setattr(
        skill_orchestrator,
        "full_policy",
        lambda _skill_name: "# Loaded empirical anti-fabrication policy",
    )
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("\\documentclass{article}\n", encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "RUN_SPEC.json").write_text("{}\n", encoding="utf-8")

    result = await AuditChain()._audit_experiment(
        str(paper),
        str(experiments),
        str(tmp_path),
        "synthetic_preview",
    )

    request_text = _request_text(reviewer.requests[0])
    assert result.verdict.value == "WARN"
    assert request_text.index("Loaded empirical anti-fabrication policy") < (
        request_text.index("Binding evidence-mode adjudication")
    )
    assert "completed negative or non-decisive" in request_text
    assert "do not FAIL merely because no physical training" in request_text


@pytest.mark.asyncio
async def test_all_five_plus_proof_audits_use_fresh_model_api_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text(
        "\\documentclass{article}\n"
        "\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\nAuditable paper.\n"
        "\\begin{theorem}For every x, x=x.\\end{theorem}\n"
        "\\begin{proof}By reflexivity.\\end{proof}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "RUN_SPEC.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        skill_orchestrator,
        "full_policy",
        lambda skill_name: f"# Loaded policy for {skill_name}",
    )
    expected_skills = [
        "experiment-audit",
        "result-to-claim",
        "paper-claim-audit",
        "citation-audit",
        "kill-argument",
        "proof-checker",
    ]
    responses = [
        {
                "verdict": "PASS",
                "summary": f"{skill_name} passed.",
                "evidence": ["paper/main.tex", "experiments/RUN_SPEC.json"],
        }
        for skill_name in expected_skills[:5]
    ]
    responses.append({
        "audit_skill": "proof-checker",
        "verdict": "PASS",
        "reason_code": "proofs_verified",
        "summary": "The theorem and proof are internally consistent.",
        "details": {"theorems_audited": 1, "issues": []},
        "evidence": ["paper/main.tex"],
    })
    reviewer = _ScriptedApiProvider(*responses)
    _patch_independent_api_route(monkeypatch, reviewer)

    results = await AuditChain().run_full_audit(
        paper_path=str(paper),
        experiment_dir=str(experiments),
        project_path=str(tmp_path),
        evidence_mode="executed",
        layer_timeout_seconds=5,
        run_id="all-api-audits",
    )

    assert len(results) == 6
    assert all(result.method == "model" for result in results)
    assert all(result.verdict.value == "PASS" for result in results)
    assert all(result.policy_loaded for result in results)
    assert [result.skill_name for result in results] == expected_skills
    assert len(reviewer.requests) == 6
    assert len({result.session_id for result in results}) == 6
    assert all(result.session_id.startswith("model-api:") for result in results)
    assert all(
        result.model_name == "openai/vision-reviewer"
        for result in results
    )
    request_texts = [_request_text(request) for request in reviewer.requests]
    assert all(
        skill_name in request_text
        for skill_name, request_text in zip(expected_skills, request_texts)
    )
    assert '"audit_skill"' in request_texts[-1]
    assert all(request.get("tools") is None for request in reviewer.requests)
