"""A rejected deterministic template is reused only with intact visual evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from server.services.deterministic_figure_builder import (
    DeterministicFigureProducerError, UnchangedDeterministicFigureDefect,
    _failure_path, ensure_evaluation_design,
)
from server.services.figure_engine import FigureType, figure_engine
from server.services.figure_models import FigureResult
from server.services.rich_svg_visual_review import (
    PROTOCOL, REVIEW_POLICY_VERSION, _brief_sha256,
)


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _spec() -> dict[str, Any]:
    return {
        "id": "evaluation_design", "producer_kind": "deterministic",
        "production_strategy": "deterministic_template",
        "recommended_backend": "rich_svg",
        "scientific_question": "Which conditions are compared?",
    }


class _Host:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def _emit(self, _run: Any, _event: str, payload: dict[str, Any]) -> None:
        self.events.append(payload)


class _Registry:
    @staticmethod
    def load(_figures: Path) -> dict[str, Any]:
        return {"figures": []}


def _write_evidence(
    root: Path, code: str, metadata: dict[str, Any], *, alignment: bool,
    reviewer_verdict: str | None = None,
) -> FigureResult:
    asset = "evaluation_design"
    png = b"\x89PNG\r\n\x1a\nreviewed-pixels"
    image_hash = _hash(png)
    source_hash = _hash(code.encode("utf-8"))
    trace = root / ".merak" / "model-api-reviewer" / "rich-svg-review-test"
    candidate = root / ".merak" / "figure-candidates" / asset / "candidate-test"
    trace.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    files = {
        "prompt.txt": b"current-review-prompt",
        "output.schema.json": b"{}",
        "response.txt": b'{"verdict":"refine"}',
    }
    for name, content in files.items():
        (trace / name).write_bytes(content)
    (trace / "meta.json").write_text(json.dumps({
        "success": True, "invocation_id": "model-api:test",
        "model_identity": "test-review-model",
        "image_attachment_mode": "api-native-image-content",
        "image_sha256": {f"figures/diagrams/{asset}.png": image_hash},
        "prompt_sha256": _hash(files["prompt.txt"]),
        "schema_sha256": _hash(files["output.schema.json"]),
        "response_sha256": _hash(files["response.txt"]),
    }), encoding="utf-8")
    (candidate / f"{asset}.svg").write_text(code, encoding="utf-8")
    (candidate / f"{asset}.png").write_bytes(png)
    (candidate / f"{asset}.pdf").write_bytes(b"%PDF-1.4\nreviewed-pdf")
    issue = "The control relation is scientifically ambiguous"
    findings = [] if alignment else [{
        "target_layer": "runtime", "target_ids": ["comparison"],
        "severity": "blocker", "message": issue,
        "repair_action": "Clarify the comparison arrow",
    }]
    review = {
        "protocol": PROTOCOL,
        "review_backend": "independent-model-api-native-vision-v1",
        "review_policy_version": REVIEW_POLICY_VERSION,
        "review_model_identity": "test-review-model",
        "review_invocation_id": "model-api:test",
        "review_trace_path": str(trace), "candidate_path": str(candidate),
        "source_sha256": source_hash, "image_sha256": image_hash,
        "brief_sha256": _brief_sha256(metadata),
        "verdict": reviewer_verdict or ("accept" if alignment else "refine"),
        "score": 7.8,
        "issues": [] if alignment else [issue], "findings": findings,
        "checklist": {
            key: True for key in (
                "five_second_comprehension", "scientific_mechanism_clarity",
                "causal_flow", "paper_scale_readability", "no_visual_artifacts",
            )
        },
    }
    (candidate / "review.json").write_text(json.dumps({
        "protocol": PROTOCOL, "artifact_id": asset,
        "source_sha256": source_hash, "trace_path": str(trace),
        "review": review,
    }), encoding="utf-8")
    local = {
        "status": "passed" if alignment else "failed",
        "content_sha256": source_hash, "render_sha256": image_hash,
        "issues": [] if alignment else [
            "native-image figure review did not accept the candidate", issue,
        ],
    }
    review_path = root / ".merak" / "figure-reviews" / f"{asset}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps([local]), encoding="utf-8")
    error = (
        "Candidate scientific alignment failed: public label is inconsistent"
        if alignment else
        "Rich SVG native-image review failed; revise the same artifact_name: "
        + "; ".join(local["issues"]) + f"; candidate: {candidate}"
    )
    return FigureResult(
        False, FigureType.RICH_SVG, code=code, error=error,
        metadata={
            **metadata, "visual_review_rounds": [local],
            "independent_visual_review": review,
        },
    )


@pytest.mark.parametrize("alignment", [False, True])
@pytest.mark.asyncio
async def test_intact_rejection_is_not_reviewed_eight_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alignment: bool,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    host = _Host()
    calls = 0
    code_version = {"sha": "loaded-code-a"}

    async def generate(**kwargs: Any) -> FigureResult:
        nonlocal calls
        calls += 1
        return _write_evidence(
            tmp_path, str(kwargs["code"]), dict(kwargs["metadata"]),
            alignment=alignment,
        )

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    monkeypatch.setattr(
        "server.services.deterministic_figure_builder._template_code_sha256",
        lambda: code_version["sha"],
    )

    async def attempt(spec: dict[str, Any]) -> DeterministicFigureProducerError:
        with pytest.raises(DeterministicFigureProducerError) as caught:
            await ensure_evaluation_design(
                host, object(), figures, [spec], {}, set(), _Registry(),
            )
        return caught.value

    first = await attempt(_spec())
    assert not isinstance(first, UnchangedDeterministicFigureDefect)
    assert json.loads(_failure_path(figures, "evaluation_design").read_text())["schema"] == 2
    second = await attempt(_spec())
    assert isinstance(second, UnchangedDeterministicFigureDefect)
    assert calls == 1
    assert host.events[-1]["cached_failure"] is True
    assert host.events[-1]["success"] is False

    candidate = tmp_path / ".merak" / "figure-candidates" / "evaluation_design" / "candidate-test"
    (candidate / "evaluation_design.png").write_bytes(b"changed-pixels")
    await attempt(_spec())
    assert calls == 2

    trace = tmp_path / ".merak" / "model-api-reviewer" / "rich-svg-review-test"
    details = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    details["success"] = False
    (trace / "meta.json").write_text(json.dumps(details), encoding="utf-8")
    await attempt(_spec())
    assert calls == 3

    await attempt({**_spec(), "method_brief": {"condition": "new"}})
    assert calls == 4
    code_version["sha"] = "loaded-code-b"
    await attempt({**_spec(), "method_brief": {"condition": "new"}})
    assert calls == 5


@pytest.mark.asyncio
async def test_alignment_rejection_reopens_when_selected_idea_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    calls = 0

    async def generate(**kwargs: Any) -> FigureResult:
        nonlocal calls
        calls += 1
        return _write_evidence(
            tmp_path, str(kwargs["code"]), dict(kwargs["metadata"]),
            alignment=True,
        )

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    for _ in range(2):
        with pytest.raises(DeterministicFigureProducerError):
            await ensure_evaluation_design(
                _Host(), object(), figures, [_spec()], {}, set(), _Registry(),
            )
    assert calls == 1
    idea = tmp_path / "ideas" / "SELECTED_IDEA.json"
    idea.parent.mkdir()
    idea.write_text("{}", encoding="utf-8")
    with pytest.raises(DeterministicFigureProducerError):
        await ensure_evaluation_design(
            _Host(), object(), figures, [_spec()], {}, set(), _Registry(),
        )
    assert calls == 2


def test_rich_svg_failure_keeps_rejected_review_provenance() -> None:
    from server.services.rich_svg_backend import _failure

    review = {"protocol": PROTOCOL, "verdict": "refine"}
    failure = _failure("native review rejected", independent_review=review)
    assert failure.success is False
    assert failure.metadata == {"independent_visual_review": review}


@pytest.mark.asyncio
async def test_accept_verdict_with_explicit_scientific_blocker_is_cacheable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    calls = 0

    async def generate(**kwargs: Any) -> FigureResult:
        nonlocal calls
        calls += 1
        return _write_evidence(
            tmp_path, str(kwargs["code"]), dict(kwargs["metadata"]),
            alignment=False, reviewer_verdict="accept",
        )

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    for _ in range(2):
        with pytest.raises(DeterministicFigureProducerError):
            await ensure_evaluation_design(
                _Host(), object(), figures, [_spec()], {}, set(), _Registry(),
            )
    assert calls == 1


@pytest.mark.asyncio
async def test_missing_trace_and_transient_native_failure_are_never_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    calls = 0

    async def generate(**kwargs: Any) -> FigureResult:
        nonlocal calls
        calls += 1
        result = _write_evidence(
            tmp_path, str(kwargs["code"]), dict(kwargs["metadata"]),
            alignment=False,
        )
        review = result.metadata["independent_visual_review"]
        review["review_trace_path"] = ""
        result.error = "Rich SVG native-image review failed; TimeoutError: API 502"
        return result

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    for _ in range(2):
        with pytest.raises(DeterministicFigureProducerError):
            await ensure_evaluation_design(
                _Host(), object(), figures, [_spec()], {}, set(), _Registry(),
            )
    assert calls == 2
    assert not _failure_path(figures, "evaluation_design").exists()
