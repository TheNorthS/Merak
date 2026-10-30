"""Local regressions for source-bound deterministic figure failure reuse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.deterministic_figure_builder import (
    DeterministicFigureProducerError,
    _failure_path,
    ensure_evaluation_design,
)
from server.services.figure_engine import FigureType, figure_engine
from server.services.figure_models import FigureResult


class _Registry:
    @staticmethod
    def load(_figures_root: Path) -> dict:
        return {"figures": []}


class _Host:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def _emit(self, _run: object, _event: str, payload: dict) -> None:
        self.events.append(payload)


def _spec() -> dict:
    return {
        "id": "evaluation_design", "producer_kind": "deterministic",
        "production_strategy": "deterministic_template",
        "recommended_backend": "rich_svg",
        "scientific_question": "How are conditions compared?",
        "publication_labels": [],
    }


def test_template_code_fingerprint_tracks_loaded_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import evaluation_design_svg
    from server.services.deterministic_figure_builder import _module_code_digest

    def changed_text(*_args: object, **_kwargs: object) -> str:
        return "<text/>"

    before = _module_code_digest("evaluation_design_svg")
    monkeypatch.setattr(evaluation_design_svg, "_text", changed_text)
    after = _module_code_digest("evaluation_design_svg")
    assert before != after


def test_template_fingerprint_tracks_explicit_plan_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import deterministic_figure_builder as builder
    from server.services import evaluation_plan_projection as projection

    before = builder._template_code_sha256()

    def changed_binding(*_args: object, **_kwargs: object) -> None:
        raise ValueError("changed explicit-source projection")

    monkeypatch.setattr(projection, "bind_plan_split", changed_binding)
    assert builder._template_code_sha256() != before


@pytest.mark.asyncio
async def test_targeted_repair_does_not_render_unrelated_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    calls: list[str] = []

    async def generate(**kwargs: object) -> FigureResult:
        calls.append(str(kwargs["artifact_name"]))
        return FigureResult(True, FigureType.RICH_SVG, output_path="figure.pdf")

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    await ensure_evaluation_design(
        _Host(), object(), figures,
        [_spec(), {**_spec(), "id": "other_protocol"}], {},
        {"evaluation_design"}, _Registry(),
    )
    assert calls == ["evaluation_design"]


@pytest.mark.parametrize("failure_phase", ["source", "render"])
@pytest.mark.asyncio
async def test_same_template_defect_fails_without_rendering_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_phase: str,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    host = _Host()
    calls: list[str] = []
    code = {"sha": "template-code-a"}
    outcome = {"success": False}
    finding = (
        "diagram content touches or is likely cropped at the right canvas edge"
        if failure_phase == "render" else "placed SVG text falls below 8.0 pt"
    )
    error = f"Rich SVG {failure_phase} review failed; revise the same artifact_name and retry: {finding}"
    review = {
        "status": "failed", "issues": [finding],
        "content_sha256": "rendered-svg-sha",
        "render_sha256": "rendered-png-sha" if failure_phase == "render" else "",
    }

    async def generate(**kwargs: object) -> FigureResult:
        calls.append(str(kwargs["code"]))
        reviews = tmp_path / ".merak" / "figure-reviews"
        reviews.mkdir(parents=True, exist_ok=True)
        (reviews / "evaluation_design.json").write_text(
            json.dumps([review]), encoding="utf-8",
        )
        return FigureResult(
            outcome["success"], FigureType.RICH_SVG,
            output_path="evaluation_design.pdf" if outcome["success"] else None,
            error=None if outcome["success"] else error,
            metadata={"visual_review_rounds": [review]},
        )

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    monkeypatch.setattr(
        "server.services.deterministic_figure_builder._template_code_sha256",
        lambda: code["sha"],
    )

    async def attempt(spec: dict) -> None:
        with pytest.raises(DeterministicFigureProducerError):
            await ensure_evaluation_design(
                host, object(), figures, [spec], {}, set(), _Registry(),
            )

    spec = _spec()
    await attempt(spec)
    record_path = _failure_path(figures, "evaluation_design")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["error"] == error
    assert record["error_signature"]
    assert len(calls) == 1
    assert host.events[-1]["success"] is False
    assert host.events[-1]["cached_failure"] is False

    await attempt(spec)
    assert len(calls) == 1
    assert host.events[-1]["cached_failure"] is True
    assert host.events[-1]["error"] == error

    review["render_sha256"] = "changed-png-sha"
    (tmp_path / ".merak" / "figure-reviews" / "evaluation_design.json").write_text(
        json.dumps([review]), encoding="utf-8",
    )
    await attempt(spec)
    assert len(calls) == 2

    await attempt({**spec, "method_brief": {"endpoint": "changed"}})
    assert len(calls) == 3
    code["sha"] = "template-code-b"
    await attempt({**spec, "method_brief": {"endpoint": "changed"}})
    assert len(calls) == 4

    outcome["success"] = True
    code["sha"] = "template-code-c"
    await ensure_evaluation_design(
        host, object(), figures, [spec], {}, set(), _Registry(),
    )
    assert len(calls) == 5
    assert host.events[-1]["success"] is True
    assert not record_path.exists()


@pytest.mark.asyncio
async def test_transient_review_failure_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    calls = 0

    async def generate(**_kwargs: object) -> FigureResult:
        nonlocal calls
        calls += 1
        return FigureResult(
            False, FigureType.RICH_SVG,
            error="Rich SVG native-image review failed: TimeoutError: reviewer unavailable",
        )

    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr(
        "server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg viewBox='0 0 10 10'/>", []),
    )
    host = _Host()
    for _ in range(2):
        with pytest.raises(DeterministicFigureProducerError):
            await ensure_evaluation_design(
                host, object(), figures, [_spec()], {}, set(), _Registry(),
            )
    assert calls == 2
    assert all(event["cached_failure"] is False for event in host.events)
    assert not _failure_path(figures, "evaluation_design").exists()
