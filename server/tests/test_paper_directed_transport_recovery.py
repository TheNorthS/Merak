"""An interrupted directed author cannot satisfy fresh scientific feedback with old prose."""

import json

import pytest

from server.services.paper_drafting import PaperDraftingError
from server.tests.test_paper_stage_validator_cache import _completed_intro, _coordinator


SCIENTIFIC_FEEDBACK = "Introduction: replace the scientific explanation with an explicit rival causal interpretation."


def _directed(root, service, paths):
    coordinator = _coordinator(root, service, paths)
    coordinator.revision_issues = [SCIENTIFIC_FEEDBACK]
    coordinator._configure_targeted_repairs()
    return coordinator


@pytest.mark.parametrize("error_type", [TimeoutError, RuntimeError])
@pytest.mark.asyncio
async def test_ordinary_transport_error_without_semantic_write_cannot_recover_a_directed_stage(tmp_path, error_type):
    service, paths, introduction = _completed_intro(tmp_path)
    coordinator = _directed(tmp_path, service, paths)
    before = introduction.read_bytes()
    calls = []

    async def author(stage, _prompt, _contract):
        calls.append(stage)
        raise error_type("fixture transport stopped before writing")

    coordinator.invoke_stage = author
    with pytest.raises(error_type, match="before writing"):
        await coordinator._run_stage("introduction")
    state = json.loads(paths["state"].read_text())
    assert calls == ["introduction"] and introduction.read_bytes() == before
    assert state["stages"]["introduction"]["status"] == "pending"
    assert not state["stages"]["introduction"].get("review_passed")


@pytest.mark.asyncio
async def test_actual_semantic_write_followed_by_transport_error_and_fresh_pass_recovers(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path)
    coordinator = _directed(tmp_path, service, paths)
    before = introduction.read_bytes()

    async def author(_stage, _prompt, _contract):
        introduction.write_text(introduction.read_text() + "\nA rival explanation is causal measurement opportunity; the matched comparison holds it fixed.\n")
        raise TimeoutError("fixture response lost after source write")

    coordinator.invoke_stage = author
    with pytest.raises(TimeoutError, match="after source write"):
        await coordinator._run_stage("introduction")
    state = json.loads(paths["state"].read_text())
    assert introduction.read_bytes() != before
    assert state["stages"]["introduction"]["status"] == "pending"
    assert not state["stages"]["introduction"].get("review_passed")


@pytest.mark.asyncio
async def test_comment_only_write_cannot_satisfy_directed_scientific_feedback(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path)
    coordinator = _directed(tmp_path, service, paths)

    async def author(_stage, _prompt, _contract):
        introduction.write_text(introduction.read_text() + "\n% Only a non-scientific attempt timestamp changed.\n")
        raise TimeoutError("no semantic progress")

    coordinator.invoke_stage = author
    with pytest.raises(TimeoutError, match="no semantic progress"):
        await coordinator._run_stage("introduction")
    state = json.loads(paths["state"].read_text())
    assert state["stages"]["introduction"]["status"] == "pending"


@pytest.mark.asyncio
async def test_changed_but_invalid_authorship_is_never_recovered(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path)
    coordinator = _directed(tmp_path, service, paths)

    async def author(_stage, _prompt, _contract):
        introduction.write_text("\\section{Introduction}\nUnsupported brief replacement.\n")
        raise TimeoutError("invalid output remains incomplete")

    coordinator.invoke_stage = author
    with pytest.raises(TimeoutError, match="invalid output"):
        await coordinator._run_stage("introduction")
    assert json.loads(paths["state"].read_text())["stages"]["introduction"]["status"] == "pending"


@pytest.mark.asyncio
async def test_nondirected_completed_source_before_transport_end_keeps_existing_recovery_behavior(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    state = json.loads(paths["state"].read_text())
    record = state["stages"]["introduction"]
    record.update({"status": "pending", "attempts": 0, "review_passed": False})
    paths["state"].write_text(json.dumps(state))

    async def author(_stage, _prompt, _contract):
        raise TimeoutError("fixture terminal response lost")

    coordinator.invoke_stage = author
    with pytest.raises(TimeoutError, match="terminal response lost"):
        await coordinator._run_stage("introduction")
    current = json.loads(paths["state"].read_text())
    assert current["stages"]["introduction"]["status"] == "pending"
    assert not current["stages"]["introduction"].get("review_passed")
