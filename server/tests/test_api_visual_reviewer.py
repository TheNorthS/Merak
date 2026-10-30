from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from server.agent import LLMResponse, ModelRole, model_router
from server.services.api_visual_reviewer import (
    API_IMAGE_ATTACHMENT_MODE,
    API_VISUAL_REVIEW_TRANSPORT,
    ApiVisualReviewer,
)


def _review_payload() -> dict[str, Any]:
    return {
        "score": 8,
        "verdict": "almost",
        "strengths": ["Clear contribution."],
        "weaknesses": ["Tighten one caption."],
        "action_items": [
            "[owner=paper] [target=paper/main.tex] Tighten the caption."
        ],
        "visual_review": {
            "pdf_path": "paper/main.pdf",
            "figure_quality": "Figures are readable.",
            "caption_alignment": "Captions align with the shown panels.",
            "page_layout": "No clipping or overlap is visible.",
            "table_formatting": "Tables use consistent rules and spacing.",
            "visual_consistency": "Typography and colors are consistent.",
        },
    }


class _Provider:
    name = "review-api/reviewer-vision"
    model = "reviewer-vision"

    def __init__(self, *, mutate: Path | None = None, payload: Any = None) -> None:
        self.mutate = mutate
        self.payload = _review_payload() if payload is None else payload
        self.messages: list[Any] = []

    async def chat(self, messages, **_kwargs) -> LLMResponse:
        self.messages = messages
        if self.mutate is not None:
            self.mutate.write_text("changed during review", encoding="utf-8")
        return LLMResponse(
            content=json.dumps(self.payload),
            model=self.model,
        )


def _routes(
    monkeypatch: pytest.MonkeyPatch,
    provider: _Provider,
    *,
    same_model: bool = False,
) -> None:
    executor = SimpleNamespace(name="writer-api/writer", model="writer")
    monkeypatch.setattr(
        model_router,
        "get_provider_route",
        lambda role: (
            ("writer-api", executor, "writer-api/writer")
            if role == ModelRole.EXECUTOR
            else ("review-api", provider, "review-api/reviewer-vision")
        ),
    )
    monkeypatch.setattr(
        model_router,
        "get_isolated_provider_route",
        lambda role: (
            "writer-api",
            provider,
            "writer-api/writer",
        )
        if same_model
        else ("review-api", provider, "review-api/reviewer-vision"),
    )


def _bundle_hash(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"::")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


@pytest.mark.asyncio
async def test_api_visual_reviewer_binds_images_evidence_route_and_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "paper" / "main.tex"
    source.parent.mkdir(parents=True)
    source.write_text("\\documentclass{article}", encoding="utf-8")
    image = tmp_path / "review-stage" / "page-1.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\nnative-review-pixels")
    provider = _Provider()
    _routes(monkeypatch, provider)

    result = await ApiVisualReviewer().review_manuscript(
        project_path=tmp_path,
        prompt="Inspect the frozen paper and attached page.",
        round_number=1,
        timeout_seconds=30,
        image_paths=[image],
        evidence_paths=[source],
        evidence_bundle_sha256=_bundle_hash(tmp_path, [source]),
    )

    assert result.invocation_id.startswith("model-api:")
    assert result.model_identity == "review-api/reviewer-vision"
    user_content = provider.messages[-1].content
    assert user_content[0]["type"] == "text"
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    trace = Path(result.trace_path)
    meta = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    assert meta["success"] is True
    assert meta["transport"] == API_VISUAL_REVIEW_TRANSPORT
    assert meta["image_attachment_mode"] == API_IMAGE_ATTACHMENT_MODE
    assert meta["model_identity"] != meta["executor_model_identity"]
    assert meta["image_sha256"] == {
        image.relative_to(tmp_path).as_posix(): hashlib.sha256(
            image.read_bytes()
        ).hexdigest()
    }
    assert meta["evidence_packet"]["source_bundle_sha256"] == _bundle_hash(
        tmp_path, [source]
    )
    response = (trace / "response.txt").read_text(encoding="utf-8")
    assert meta["response_sha256"] == hashlib.sha256(
        response.encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_api_visual_reviewer_accepts_executor_model_in_fresh_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Provider()
    _routes(monkeypatch, provider, same_model=True)

    result = await ApiVisualReviewer().invoke(
        project_path=tmp_path,
        prompt="review",
        purpose="identity-test",
        schema={"type": "object"},
    )

    assert result.model_identity == "writer-api/writer"
    assert provider.messages
    trace = Path(result.trace_path)
    meta = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    assert meta["success"] is True
    assert meta["same_model_allowed"] is True
    assert meta["same_model"] is True
    assert meta["session_isolation"] == "fresh_context"
    assert meta["invocation_id"] == result.invocation_id


@pytest.mark.asyncio
async def test_api_visual_reviewer_discards_response_when_evidence_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "paper.tex"
    source.write_text("before", encoding="utf-8")
    provider = _Provider(mutate=source)
    _routes(monkeypatch, provider)

    with pytest.raises(RuntimeError, match="changed during the API request"):
        await ApiVisualReviewer().review_manuscript(
            project_path=tmp_path,
            prompt="review",
            round_number=1,
            timeout_seconds=30,
            image_paths=[],
            evidence_paths=[source],
            evidence_bundle_sha256=_bundle_hash(tmp_path, [source]),
        )
    trace = next((tmp_path / ".merak" / "model-api-reviewer").iterdir())
    meta = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    assert meta["success"] is False
    assert meta["failure_kind"] == "invalid_or_failed_response"
    assert not (trace / "response.txt").exists()
