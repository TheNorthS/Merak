"""Local regressions for bounded model-figure redraws across outer revisions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import figure_delegate_budget as budget
from server.services.figure_delegate_budget import (
    FigureRetryDeferred,
    begin_delegate_attempt,
    figure_resume_input_sha256,
    record_delegate_failure,
)
from server.workflows.figure_asset_delegates import (
    _reserve_asset_attempt,
    run_figure_asset_delegates,
)
from server.workflows.figure_feedback_scope import scoped_figure_feedback
from server.workflows.revision_execution import _figure_repair


def _asset() -> dict:
    return {
        "id": "method_architecture", "source_artifacts": ["method.txt"],
        "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure",
        "production_strategy": "model_composed_full_svg", "full_svg_authority": True,
    }


def test_unchanged_failed_asset_needs_changed_input_code_or_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "method.txt").write_text("first", encoding="utf-8")
    asset = _asset()
    first = begin_delegate_attempt(tmp_path, "run100", asset)
    assert first.allowed
    record_delegate_failure(
        tmp_path, "run100", asset["id"], first.attempt_id,
        error="visual review rejected", guidance="Fix the M1 merge arrow",
    )
    blocked = begin_delegate_attempt(tmp_path, "run100", asset)
    assert not blocked.allowed
    assert blocked.last_error == "visual review rejected"
    assert "M1 merge" in blocked.last_guidance

    feedback = begin_delegate_attempt(
        tmp_path, "run100", asset, user_feedback="Rework the merge path",
    )
    assert feedback.allowed
    assert not begin_delegate_attempt(tmp_path, "run100", asset).allowed
    assert not begin_delegate_attempt(
        tmp_path, "run100", asset, user_feedback="Rework the merge path",
    ).allowed
    changed_feedback = begin_delegate_attempt(
        tmp_path, "run100", asset, user_feedback="Show both loss inputs",
    )
    assert changed_feedback.allowed
    assert not begin_delegate_attempt(
        tmp_path, "run100", asset, user_feedback="Rework the merge path",
    ).allowed

    sibling = {**asset, "id": "core_mechanism"}
    assert begin_delegate_attempt(tmp_path, "run100", sibling).allowed
    changed_semantics = {**asset, "scientific_question": "How do both losses merge?"}
    assert begin_delegate_attempt(tmp_path, "run100", changed_semantics).allowed

    (tmp_path / "method.txt").write_text("second", encoding="utf-8")
    assert begin_delegate_attempt(tmp_path, "run100", changed_semantics).allowed
    monkeypatch.setattr(
        "server.services.figure_delegate_budget._code_sha256", lambda: "new-code",
    )
    assert begin_delegate_attempt(tmp_path, "run100", changed_semantics).allowed


def test_new_resume_claims_do_not_reset_unchanged_asset_budget(tmp_path: Path) -> None:
    (tmp_path / "method.txt").write_text("first", encoding="utf-8")
    asset = _asset()
    assert begin_delegate_attempt(tmp_path, "run100", asset).allowed
    state_path = tmp_path / ".merak" / "runs" / "run100.json"
    state_path.write_text(json.dumps({
        "resume_claim": {"token": "watchdog-token", "source": "watchdog"},
    }), encoding="utf-8")
    assert not begin_delegate_attempt(
        tmp_path, "run100", asset,
    ).allowed
    state_path.write_text(json.dumps({
        "resume_claim": {"token": "explicit-token-1", "source": "explicit"},
    }), encoding="utf-8")
    assert not begin_delegate_attempt(
        tmp_path, "run100", asset,
    ).allowed
    assert not begin_delegate_attempt(
        tmp_path, "run100", asset,
    ).allowed
    state_path.write_text(json.dumps({
        "resume_claim": {"token": "explicit-token-2", "source": "explicit"},
    }), encoding="utf-8")
    assert not begin_delegate_attempt(tmp_path, "run100", asset).allowed


def test_feedback_only_reopens_its_target_asset() -> None:
    assets = ["method_architecture", "core_mechanism"]
    assert scoped_figure_feedback(assets, "Please try again") == {}
    assert scoped_figure_feedback(
        assets, "Fix the method_architecture merge arrow",
    ) == {"method_architecture": "Fix the method_architecture merge arrow"}
    assert scoped_figure_feedback(
        assets, "Fix both method_architecture and core_mechanism",
    ) == {}
    assert scoped_figure_feedback(
        ["method_architecture"], "Make both loss inputs explicit",
    ) == {"method_architecture": "Make both loss inputs explicit"}


@pytest.mark.asyncio
async def test_scoped_feedback_cannot_reopen_sibling_asset(tmp_path: Path) -> None:
    (tmp_path / "method.txt").write_text("first", encoding="utf-8")
    method = _asset()
    sibling = {**method, "id": "core_mechanism"}
    for asset in (method, sibling):
        attempt = begin_delegate_attempt(tmp_path, "run100", asset)
        record_delegate_failure(
            tmp_path, "run100", asset["id"], attempt.attempt_id,
            error="review rejected", guidance="Fix the arrow",
        )

    class Host:
        async def _emit(self, *_args) -> None:
            return None

    context = SimpleNamespace(
        run=SimpleNamespace(id="run100"), host=Host(),
        opts={"_figure_revision_scoped_feedback": {
            "method_architecture": "Fix the method_architecture arrow",
        }},
    )
    assert (await _reserve_asset_attempt(context, method, tmp_path)).allowed
    with pytest.raises(FigureRetryDeferred):
        await _reserve_asset_attempt(context, sibling, tmp_path)


def test_corrupt_budget_fails_closed_before_model_call(tmp_path: Path) -> None:
    (tmp_path / "method.txt").write_text("first", encoding="utf-8")
    path = tmp_path / ".merak" / "runs" / "run100.figure-delegate-budget.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="budget is unreadable"):
        begin_delegate_attempt(tmp_path, "run100", _asset())


def test_missing_declared_source_fails_before_model_call(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="declared sources are unavailable"):
        begin_delegate_attempt(tmp_path, "run100", _asset())


def test_changed_declared_source_changes_resume_signature(tmp_path: Path) -> None:
    specs = tmp_path / "figures" / "FIGURE_SPECS.json"
    specs.parent.mkdir()
    specs.write_text(json.dumps({"figures": [{
        **_asset(), "producer_kind": "model",
    }]}), encoding="utf-8")
    source = tmp_path / "method.txt"
    source.write_text("first", encoding="utf-8")
    before = figure_resume_input_sha256(tmp_path)
    source.write_text("second", encoding="utf-8")
    assert figure_resume_input_sha256(tmp_path) != before


@pytest.mark.parametrize("producer_name", ["figure_delegate_budget.py", "evaluation_plan_projection.py"])
def test_frozen_figure_code_hash_reads_exact_source_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, producer_name: str,
) -> None:
    expected = budget.figure_producer_code_sha256()
    source_root = Path(budget.__file__).resolve().parents[1]
    for relative in budget._CODE_SOURCES:
        source = source_root / relative
        bundled = tmp_path / (
            relative.removeprefix("../") if relative.startswith("../merak-skills/")
            else f"merak-source/server/{relative}"
        )
        bundled.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, bundled)
    monkeypatch.setattr(budget.sys, "frozen", True, raising=False)
    monkeypatch.setattr(budget.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert budget.figure_producer_code_sha256() == expected

    producer = tmp_path / "merak-source/server/services" / producer_name
    producer.write_bytes(producer.read_bytes() + b"\n# changed producer\n")
    assert budget.figure_producer_code_sha256() != expected
    producer.unlink()
    with pytest.raises(RuntimeError, match="source snapshot is unavailable"):
        budget.figure_producer_code_sha256()


@pytest.mark.asyncio
async def test_outer_revision_does_not_redraw_unchanged_failed_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "method.txt").write_text("first", encoding="utf-8")
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._model_assets",
        lambda _context: [_asset()],
    )
    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._accepted_entry",
        lambda *_args: None,
    )
    calls: list[str] = []

    async def fail_draw(*_args, **_kwargs):
        calls.append("draw")
        raise RuntimeError("review rejected unclear flow")

    monkeypatch.setattr(
        "server.workflows.figure_asset_delegates._draw_asset", fail_draw,
    )
    events: list[tuple[str, dict]] = []

    class Host:
        async def _emit(self, _run, event: str, payload: dict) -> None:
            events.append((event, payload))

    context = SimpleNamespace(
        node=SimpleNamespace(id="figure"), opts={}, project_path=str(tmp_path),
        direction="test", host=Host(), run=SimpleNamespace(id="run100"),
    )
    with pytest.raises(RuntimeError, match="review rejected unclear flow"):
        await run_figure_asset_delegates(context)
    with pytest.raises(FigureRetryDeferred, match="automatic model redraw deferred"):
        await run_figure_asset_delegates(context)
    assert calls == ["draw"]
    deferred = [payload for event, payload in events if event == "figure_asset_delegate_retry_deferred"]
    assert deferred[0]["asset_id"] == "method_architecture"
    assert "review rejected unclear flow" in deferred[0]["last_error"]


@pytest.mark.asyncio
async def test_revision_passes_only_explicit_feedback_to_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def route(_host, _run, _node_id, _direction, _round, _assets):
        return ["method_architecture"], []

    monkeypatch.setattr(
        "server.workflows.figure_repair_routing.rebuild_deterministic_assets", route,
    )
    received: list[dict] = []

    class Host:
        async def _execute_node(self, _node, _run, *_args, **kwargs):
            received.append(kwargs["opts"])
            return "unaccepted until gate"

    run = SimpleNamespace(project_path=str(tmp_path))
    node = SimpleNamespace(id="figure")
    await _figure_repair(
        Host(), node, run, {"repair_scope": {"asset_ids": ["method_architecture"]}},
        "revision instruction", "direction", "balanced", "draft", 2,
        {"run_experiment": False}, "  Researcher says: make arrows explicit  ",
    )
    assert received[0]["_figure_revision_scoped_feedback"] == {
        "method_architecture": "Researcher says: make arrows explicit",
    }
