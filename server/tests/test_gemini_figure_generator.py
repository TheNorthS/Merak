from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw

from server.services.figure_artifacts import figure_artifact_registry
from server.services.figure_engine import FigureEngine, FigureType
from server.services.api_visual_reviewer import (
    API_IMAGE_ATTACHMENT_MODE,
    API_VISUAL_REVIEW_TRANSPORT,
    FIGURE_REVIEW_SCHEMA,
    TRACE_SCHEMA_VERSION,
    ApiVisualReview,
    api_visual_reviewer,
)
from server.services.gemini_figure_generator import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_REASONING_MODEL,
    GeminiFigureConfig,
    GeminiPaperbananaGenerator,
    REVIEW_CHECKS,
    image_review_progress_signature,
    resolve_gemini_figure_config,
)


def _text_response(text: str) -> dict[str, Any]:
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": text}],
            }
        }]
    }


def _diagram_b64(accent: str = "#2563eb") -> str:
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (55, 90, 355, 510),
        radius=28,
        fill="#d1fae5",
        outline="#047857",
        width=8,
    )
    draw.rounded_rectangle(
        (450, 90, 750, 510),
        radius=28,
        fill=accent,
        outline="#1e3a8a",
        width=8,
    )
    draw.rounded_rectangle(
        (845, 90, 1145, 510),
        radius=28,
        fill="#ffedd5",
        outline="#c2410c",
        width=8,
    )
    draw.line((355, 300, 450, 300), fill="#111827", width=12)
    draw.polygon([(450, 300), (422, 282), (422, 318)], fill="#111827")
    draw.line((750, 300, 845, 300), fill="#111827", width=12)
    draw.polygon([(845, 300), (817, 282), (817, 318)], fill="#111827")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _image_response(encoded: str) -> dict[str, Any]:
    return {
        "candidates": [{
            "content": {
                "parts": [
                    {"text": "Rendered one academic diagram."},
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": encoded,
                        }
                    },
                ],
            }
        }]
    }


def _review_payload(
    score: float,
    *,
    failed_check: str = "",
    issues: list[str] | None = None,
    improvement: str = "",
) -> dict[str, Any]:
    checklist = {name: True for name in REVIEW_CHECKS}
    if failed_check:
        checklist[failed_check] = False
    return {
        "score": score,
        "verdict": "accept" if score >= 9 and not failed_check else "refine",
        "issues": issues or [],
        "strengths": ["The three-stage hierarchy is visually clear."],
        "improvement_prompt": improvement,
        "checklist": checklist,
    }


def _review_response(
    score: float,
    *,
    failed_check: str = "",
    issues: list[str] | None = None,
    improvement: str = "",
) -> dict[str, Any]:
    return _text_response(json.dumps(_review_payload(
        score,
        failed_check=failed_check,
        issues=issues,
        improvement=improvement,
    )))


class _ScriptedGemini:
    def __init__(self, responses: list[dict[str, Any] | httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append({
            "url": str(request.url),
            "headers": dict(request.headers),
            "json": json.loads(request.content.decode("utf-8")),
        })
        assert self.responses, "unexpected live/protocol request"
        response = self.responses.pop(0)
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)


class _ScriptedIndependentReviewer:
    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        available: bool = True,
    ) -> None:
        self.responses = list(responses or [_review_payload(9)])
        self.is_available = available
        self.calls: list[dict[str, Any]] = []

    def available(self) -> bool:
        return self.is_available

    async def review(self, **kwargs) -> ApiVisualReview:
        assert self.responses, "unexpected independent-review call"
        review = self.responses.pop(0)
        image_path = Path(kwargs["image_path"])
        project_root = Path(kwargs["project_root"])
        call_number = len(self.calls) + 1
        invocation_raw = f"visual-{call_number}"
        identity = "openai/vision-independent"
        invocation_id = f"model-api:{invocation_raw}"
        trace = project_root / ".merak" / "model-api-reviewer" / invocation_raw
        trace.mkdir(parents=True, exist_ok=False)
        relative_image = image_path.relative_to(project_root).as_posix()
        image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
        (trace / "prompt.txt").write_text(kwargs["prompt"], encoding="utf-8")
        (trace / "response.txt").write_text(json.dumps(review), encoding="utf-8")
        (trace / "meta.json").write_text(json.dumps({
            "schema_version": TRACE_SCHEMA_VERSION,
            "invocation_id": invocation_id,
            "transport": API_VISUAL_REVIEW_TRANSPORT,
            "model_identity": identity,
            "provider": "reviewer-api",
            "image_attachment_mode": API_IMAGE_ATTACHMENT_MODE,
            "image_paths": [relative_image],
            "image_sha256": {relative_image: image_sha256},
            "success": True,
            "failure_kind": "",
            "tool_policy": "model-output-only",
        }), encoding="utf-8")
        self.calls.append({
            **kwargs,
            "image_sha256": image_sha256,
            "trace_path": str(trace),
        })
        return ApiVisualReview(
            text=json.dumps(review),
            invocation_id=invocation_id,
            model_identity=identity,
            provider_name="reviewer-api",
            trace_path=str(trace),
        )


def _config(max_iterations: int = 5) -> GeminiFigureConfig:
    return GeminiFigureConfig(
        api_key="unit-test-key",
        base_url="https://gemini.invalid/v1beta",
        reasoning_model=DEFAULT_REASONING_MODEL,
        image_model=DEFAULT_IMAGE_MODEL,
        max_iterations=max_iterations,
        timeout_seconds=30,
    )


async def _run_generator(
    tmp_path: Path,
    scripted: _ScriptedGemini,
    *,
    max_iterations: int = 5,
    reviewer: _ScriptedIndependentReviewer | None = None,
):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(scripted),
        timeout=30,
    ) as client:
        generator = GeminiPaperbananaGenerator(
            _config(max_iterations),
            client=client,
            independent_reviewer=reviewer or _ScriptedIndependentReviewer(),
        )
        return await generator.generate(
            description=(
                "Show the verified sensor encoder feeding a fusion module and "
                "then the calibrated decision output."
            ),
            output_dir=tmp_path / "figures",
            artifact_stem="method_overview",
            metadata={
                "scientific_role": "method",
                "scientific_question": "How does sensor evidence reach the decision?",
                "intended_comparison": "Input, fusion, and output stages",
                "visual_encoding": "Left-to-right labeled architecture",
                "publication_labels": [
                    {"schema": 1, "id": "method.sensor", "kind": "concept", "display_text": "Sensor encoder"},
                    {"schema": 1, "id": "method.fusion", "kind": "concept", "display_text": "Fusion module"},
                    {"schema": 1, "id": "method.output", "kind": "concept", "display_text": "Decision output"},
                ],
            },
        )


def _success_responses() -> list[dict[str, Any]]:
    return [
        _text_response("Layout: encoder left, fusion center, output right."),
        _text_response("Style: exact labels, thick arrows, white background."),
        _image_response(_diagram_b64()),
    ]


def test_gemini_config_uses_verified_saved_pair_before_environment(
    monkeypatch,
) -> None:
    import server.services.gemini_figure_generator as gemini_module

    monkeypatch.setattr(
        gemini_module,
        "_configured_gemini_values",
        lambda: ("saved-key", "https://saved.invalid/v1beta/openai"),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "different-env-key")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://env.invalid/v1beta")

    config = resolve_gemini_figure_config()

    assert config.api_key == "saved-key"
    assert config.base_url == "https://saved.invalid/v1beta"


def test_gemini_protocol_runs_layout_style_image_review_and_persists_audit(
    tmp_path: Path,
) -> None:
    scripted = _ScriptedGemini(_success_responses())
    reviewer = _ScriptedIndependentReviewer()

    outcome = asyncio.run(_run_generator(tmp_path, scripted, reviewer=reviewer))

    assert outcome.success is True
    assert outcome.error is None
    output = Path(outcome.output_path or "")
    source = Path(outcome.source_path or "")
    assert output.is_file()
    assert source.is_file()
    assert len(scripted.calls) == 3
    assert [call["url"].split("/models/")[1].split(":")[0] for call in scripted.calls] == [
        DEFAULT_REASONING_MODEL,
        DEFAULT_REASONING_MODEL,
        DEFAULT_IMAGE_MODEL,
    ]
    assert all(
        call["headers"]["x-goog-api-key"] == "unit-test-key"
        for call in scripted.calls
    )
    assert scripted.calls[2]["json"]["generationConfig"]["responseModalities"] == [
        "TEXT",
        "IMAGE",
    ]
    assert len(reviewer.calls) == 1
    assert reviewer.calls[0]["image_path"].suffix == ".png"
    assert "native model-API image content" in reviewer.calls[0]["prompt"]

    manifest = json.loads(source.read_text(encoding="utf-8"))
    assert manifest["status"] == "accepted"
    assert manifest["accepted_round"] == 1
    assert manifest["reasoning_model"] == DEFAULT_REASONING_MODEL
    assert manifest["image_model"] == DEFAULT_IMAGE_MODEL
    assert "api_key" not in json.dumps(manifest).casefold()
    run_dir = source.parent
    expected = {
        "initial_prompt.txt",
        "latex_include.tex",
        "review_log.json",
        "round_01/layout_prompt.txt",
        "round_01/layout_response.json",
        "round_01/style_prompt.txt",
        "round_01/style_response.json",
        "round_01/render_prompt.txt",
        "round_01/render_response.json",
        "round_01/review_prompt.txt",
        "round_01/review_response.json",
        "round_01/review.json",
    }
    persisted = {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert expected <= persisted
    last_review = outcome.metadata["visual_review_rounds"][-1]
    assert last_review["status"] == "passed"
    assert last_review["review_backend"] == API_VISUAL_REVIEW_TRANSPORT
    assert last_review["review_model_identity"] == "openai/vision-independent"
    assert last_review["review_invocation_id"].startswith("model-api:")
    assert last_review["review_coordinator_verified"] is True
    assert (tmp_path / last_review["review_trace_path"]).is_dir()
    assert last_review["render_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    for key, relative in outcome.metadata["protocol_artifacts"].items():
        artifact = tmp_path / relative
        assert artifact.is_file(), key
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == (
            outcome.metadata["protocol_artifact_sha256"][key]
        )


def test_gemini_protocol_retries_with_exact_visual_feedback_then_accepts(
    tmp_path: Path,
) -> None:
    issue = "Encoder to Fusion arrow points left; reverse it to point right."
    scripted = _ScriptedGemini([
        _text_response("Round one layout."),
        _text_response("Round one style."),
        _image_response(_diagram_b64("#60a5fa")),
        _text_response("Round two corrected layout."),
        _text_response("Round two corrected style."),
        _image_response(_diagram_b64("#2563eb")),
    ])
    reviewer = _ScriptedIndependentReviewer([
        _review_payload(
            7,
            failed_check="arrow_correctness",
            issues=[issue],
            improvement="Reverse the Encoder to Fusion arrow and retain all labels.",
        ),
        _review_payload(9),
    ])

    outcome = asyncio.run(_run_generator(
        tmp_path, scripted, max_iterations=2, reviewer=reviewer
    ))

    assert outcome.success is True
    assert outcome.metadata["accepted_round"] == 2
    assert [item["status"] for item in outcome.metadata["visual_review_rounds"]] == [
        "failed",
        "passed",
    ]
    second_layout_prompt = scripted.calls[3]["json"]["contents"][0]["parts"][0]["text"]
    assert issue in second_layout_prompt
    assert "Reverse the Encoder to Fusion arrow" in second_layout_prompt
    source = Path(outcome.source_path or "")
    assert len(list(source.parent.glob("round_*/*_round_*.png"))) == 2


def test_gemini_progress_signature_ignores_operational_review_churn() -> None:
    review = {
        "issues": ["  Arrow label is unclear  "],
        "improvement_prompt": "Increase contrast.",
        "model_verdict": "refine",
        "checklist": {name: False for name in REVIEW_CHECKS},
        "score": 6,
        "reviewed_at": 1,
    }
    noisy = {**review, "score": 7, "reviewed_at": 2}
    assert image_review_progress_signature("ABC", review) == (
        image_review_progress_signature("abc", noisy)
    )
    changed_finding = {**review, "issues": ["Arrow direction is reversed"]}
    assert image_review_progress_signature("abc", review) != (
        image_review_progress_signature("abc", changed_finding)
    )
    assert image_review_progress_signature("abc", review) != (
        image_review_progress_signature("def", review)
    )


def test_gemini_stops_after_two_identical_image_and_finding_rounds(
    tmp_path: Path,
) -> None:
    repeated_review = _review_payload(
        7,
        failed_check="arrow_correctness",
        issues=["Encoder arrow direction is unclear."],
        improvement="Make the encoder arrow direction explicit.",
    )
    scripted = _ScriptedGemini([
        _text_response("Round one layout."),
        _text_response("Round one style."),
        _image_response(_diagram_b64()),
        _text_response("Round two layout."),
        _text_response("Round two style."),
        _image_response(_diagram_b64()),
    ])
    reviewer = _ScriptedIndependentReviewer([
        dict(repeated_review),
        dict(repeated_review),
    ])

    outcome = asyncio.run(_run_generator(
        tmp_path,
        scripted,
        max_iterations=5,
        reviewer=reviewer,
    ))

    assert outcome.success is False
    assert len(scripted.calls) == 6
    assert len(reviewer.calls) == 2
    assert "same image SHA256" in (outcome.error or "")
    assert outcome.metadata["stop_reason"] == (
        "no_progress_same_image_and_review_findings"
    )
    assert outcome.metadata["terminal"] is True
    rounds = outcome.metadata["visual_review_rounds"]
    assert len(rounds) == 2
    assert rounds[-1]["stopped_for_no_progress"] is True
    source = Path(outcome.source_path or "")
    manifest = json.loads(source.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["terminal"] is True
    assert manifest["stop_reason"] == "no_progress_same_image_and_review_findings"


def test_gemini_protocol_exhaustion_is_a_strict_failure_and_keeps_rounds(
    tmp_path: Path,
) -> None:
    responses: list[dict[str, Any]] = []
    review_responses: list[dict[str, Any]] = []
    for round_number in (1, 2):
        responses.extend([
            _text_response(f"Layout {round_number}."),
            _text_response(f"Style {round_number}."),
            _image_response(_diagram_b64()),
        ])
        review_responses.append(_review_payload(
            8,
            failed_check="text_readability",
            issues=[f"Round {round_number}: output label is too small."],
            improvement="Increase the output label to at least 14 pt.",
        ))
    scripted = _ScriptedGemini(responses)
    reviewer = _ScriptedIndependentReviewer(review_responses)

    outcome = asyncio.run(_run_generator(
        tmp_path, scripted, max_iterations=2, reviewer=reviewer
    ))

    assert outcome.success is False
    assert outcome.output_path is None
    assert "budget exhausted" in (outcome.error or "")
    source = Path(outcome.source_path or "")
    manifest = json.loads(source.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["accepted_round"] is None
    assert len(manifest["rounds"]) == 2
    assert len(list(source.parent.glob("round_*/*_round_*.png"))) == 2
    assert not list(source.parent.glob("method_overview.png"))


def test_gemini_protocol_persists_api_error_and_fails_without_fabrication(
    tmp_path: Path,
) -> None:
    scripted = _ScriptedGemini([
        httpx.Response(
            429,
            json={"error": {"code": 429, "message": "quota exhausted"}},
        )
    ])

    outcome = asyncio.run(_run_generator(tmp_path, scripted, max_iterations=1))

    assert outcome.success is False
    assert outcome.output_path is None
    assert "HTTP 429" in (outcome.error or "")
    source = Path(outcome.source_path or "")
    response = json.loads(
        (source.parent / "round_01" / "layout_response.json").read_text(
            encoding="utf-8"
        )
    )
    assert response["status_code"] == 429
    assert response["response"]["error"]["message"] == "quota exhausted"


def test_gemini_protocol_fails_closed_before_generation_without_independent_reviewer(
    tmp_path: Path,
) -> None:
    scripted = _ScriptedGemini(_success_responses())
    reviewer = _ScriptedIndependentReviewer(available=False)

    outcome = asyncio.run(_run_generator(
        tmp_path,
        scripted,
        max_iterations=1,
        reviewer=reviewer,
    ))

    assert outcome.success is False
    assert outcome.output_path is None
    assert "cannot self-approve" in (outcome.error or "")
    assert scripted.calls == []
    assert reviewer.calls == []


def test_gemini_protocol_rejects_missing_or_invalid_inline_image(
    tmp_path: Path,
) -> None:
    invalid_render_responses = [
        _text_response("No image was produced."),
        _image_response("this-is-not-base64"),
    ]
    for index, render_response in enumerate(invalid_render_responses, start=1):
        case_dir = tmp_path / f"case_{index}"
        scripted = _ScriptedGemini([
            _text_response("Layout."),
            _text_response("Style."),
            render_response,
        ])

        outcome = asyncio.run(_run_generator(case_dir, scripted, max_iterations=1))

        assert outcome.success is False
        assert outcome.output_path is None
        assert (
            "exactly one inline image" in (outcome.error or "")
            or "invalid base64" in (outcome.error or "")
        )
        assert not list(case_dir.rglob("method_overview.png"))


def test_figure_engine_records_gemini_protocol_hashes_and_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import server.services.gemini_figure_generator as gemini_module

    source_data = tmp_path / "method_contract.md"
    source_data.write_text("sensor encoder -> fusion module -> decision output", encoding="utf-8")
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "title": "Sensor-to-decision fusion", "problem_statement": "Sensor evidence must reach the decision.",
        "hypothesis": "Sensor encoder and fusion module enable the declared decision output.",
        "claims": [{"id": "C1", "publication_statement": "Sensor evidence reaches the decision through the declared fusion module."}],
        "mechanisms": [{"id": "M1", "publication_name": "Sensor encoder", "publication_description": "Encodes sensor evidence."},
                       {"id": "M2", "publication_name": "Fusion module", "publication_description": "Fuses the declared sensor evidence."}],
        "publication": {"language": "en", "title": "Sensor-to-decision fusion", "method_name": "Sensor fusion",
                        "contribution_type": "system_architecture", "comparator_names": ["Sensor fusion", "Unfused sensor reference"]},
    }), encoding="utf-8")
    scripted = _ScriptedGemini(_success_responses())
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(scripted),
        timeout=30,
    )
    real_generator = gemini_module.GeminiPaperbananaGenerator
    reviewer = _ScriptedIndependentReviewer()
    monkeypatch.setattr(
        gemini_module,
        "resolve_gemini_figure_config",
        lambda: _config(max_iterations=1),
    )
    monkeypatch.setattr(
        gemini_module,
        "GeminiPaperbananaGenerator",
        lambda config: real_generator(
            config,
            client=client,
            independent_reviewer=reviewer,
        ),
    )
    metadata = {
        "scientific_role": "qualitative",
        "scientific_question": "How does sensor evidence reach the decision?",
        "intended_comparison": "Input, fusion, and output stages",
        "visual_encoding": "Left-to-right labeled architecture",
        "source_data": [source_data.relative_to(tmp_path).as_posix()],
        "evidence_status": "artifact",
        "publication_labels": [
            {"schema": 1, "id": "method.sensor", "kind": "concept", "display_text": "Sensor encoder"},
            {"schema": 1, "id": "method.fusion", "kind": "concept", "display_text": "Fusion module"},
            {"schema": 1, "id": "method.output", "kind": "concept", "display_text": "Decision output"},
        ],
        "caption": "Verified sensor-to-decision architecture and information flow.",
        "generator_skill": "paper-illustration",
        "skill": "paper-illustration",
        "skill_invocation_verified": True,
        "skill_invocation_verified_by": "agent-runtime",
    }

    try:
        result = asyncio.run(FigureEngine().generate(
            (
                "Show the verified sensor encoder feeding a fusion module and "
                "then the calibrated decision output."
            ),
            figure_type=FigureType.NANO_BANANA,
            output_dir=str(tmp_path / "figures"),
            metadata=metadata,
            artifact_name="method_overview",
        ))
    finally:
        asyncio.run(client.aclose())

    assert result.success is True, result.error
    assert result.manifest_path
    valid, issues, payload = figure_artifact_registry.validate(tmp_path / "figures")
    assert valid is True, issues
    entry = next(item for item in payload["figures"] if item["id"] == "method_overview")
    entry_metadata = entry["metadata"]
    assert entry["type"] == "nano_banana"
    assert entry_metadata["generator"] == "gemini-paperbanana"
    assert entry_metadata["generator_skill"] == "paper-illustration"
    assert entry_metadata["skill"] == "paper-illustration"
    assert entry_metadata["skill_invocation_verified"] is True
    assert entry_metadata["skill_invocation_verified_by"] == "agent-runtime"
    assert entry_metadata["renderer"] == DEFAULT_IMAGE_MODEL
    assert entry_metadata["review_backend"] == API_VISUAL_REVIEW_TRANSPORT
    assert entry_metadata["review_model"] == "openai/vision-independent"
    assert entry_metadata["accepted_round"] == 1
    assert entry_metadata["accepted_score"] == 9
    assert entry_metadata["output_sha256"] == entry["output_sha256"]
    assert entry_metadata["final_output_sha256"] == entry["output_sha256"]
    assert entry_metadata["final_source_sha256"] == entry["source_sha256"]
    assert entry_metadata["visual_review_rounds"][-1]["render_sha256"] == (
        entry["output_sha256"]
    )
    assert set(entry_metadata["rendered_variants"]) == {
        "png",
        "round_01_png",
    }
    assert figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    ) == []

    review_prompt_rel = entry_metadata["protocol_artifacts"][
        "round_01/review_prompt.txt"
    ]
    review_prompt = tmp_path / review_prompt_rel
    review_prompt.write_text(
        review_prompt.read_text(encoding="utf-8") + "\ntampered",
        encoding="utf-8",
    )
    valid, validation_issues, _ = figure_artifact_registry.validate(
        tmp_path / "figures"
    )
    assert valid is False
    assert any(
        "hash mismatch for protocol artifact round_01/review_prompt.txt" in issue
        for issue in validation_issues
    )
    quality_issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )
    assert any("review prompt hash is stale" in issue for issue in quality_issues)

    trace = tmp_path / entry_metadata["visual_review_rounds"][-1][
        "review_trace_path"
    ]
    (trace / "extra.txt").write_text("tampered trace", encoding="utf-8")
    quality_issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )
    assert any("trace hash is stale" in issue for issue in quality_issues)

    manifest_path = Path(result.manifest_path or "")
    tampered_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered_entry = next(
        item for item in tampered_manifest["figures"]
        if item["id"] == "method_overview"
    )
    tampered_entry["metadata"]["visual_review_rounds"][-1]["score"] = 8
    manifest_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")
    quality_issues = figure_artifact_registry.scientific_quality_issues(
        tmp_path / "figures"
    )
    assert any(
        "accepted visual-review score is below threshold" in issue
        for issue in quality_issues
    )


def test_api_figure_reviewer_requests_native_image_attachment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "round.png"
    image_path.write_bytes(base64.b64decode(_diagram_b64()))
    captured: dict[str, Any] = {}

    async def fake_invoke(**kwargs) -> ApiVisualReview:
        captured.update(kwargs)
        return ApiVisualReview(
            text=json.dumps(_review_payload(9)),
            invocation_id="model-api:native-image",
            model_identity="openai/vision",
            provider_name="reviewer-api",
            trace_path=str(tmp_path / ".merak" / "model-api-reviewer"),
        )

    monkeypatch.setattr(api_visual_reviewer, "invoke", fake_invoke)

    result = asyncio.run(api_visual_reviewer.review_figure(
        project_path=tmp_path,
        prompt="Inspect the attached pixels.",
        image_path=image_path,
        artifact_name="method_overview",
        round_number=1,
        timeout_seconds=30,
    ))

    assert result.invocation_id == "model-api:native-image"
    assert captured["schema"] is FIGURE_REVIEW_SCHEMA
    assert captured["image_paths"] == [image_path]
    assert captured["purpose"] == "figure-method_overview-round-1"


def test_candidate_image_alignment_rejects_missing_frozen_idea_without_writing_contract(tmp_path: Path) -> None:
    from server.services.figure_scientific_alignment import candidate_scientific_alignment_issues
    source = tmp_path / "candidate.prompt.json"
    source.write_text(json.dumps({"prompt": "Sensor encoder -> fusion module -> decision output"}), encoding="utf-8")
    before = source.read_bytes()
    issues = candidate_scientific_alignment_issues(figure_artifact_registry, tmp_path, {
        "semantic_key": "method_overview", "scientific_role": "qualitative",
        "publication_labels": [{"schema": 1, "id": "sensor", "kind": "concept", "display_text": "Sensor encoder"}],
    }, source)
    assert issues == ["frozen selected-idea contract is missing or invalid"]
    assert source.read_bytes() == before and not (tmp_path / "ideas/SELECTED_IDEA.json").exists()
