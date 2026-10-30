"""Source deltas guide bounded repairs but never grant fresh acceptance."""

import hashlib
import json

import pytest

from server.services.paper_plan import paper_plan_service as service
from server.services.paper_plan_changes import plan_change_instruction
from server.services.paper_plan_delivery import plan_delivery


def _project(root):
    (root / "paper").mkdir()
    (root / "literature").mkdir()
    (root / "paper/PAPER_PLAN.md").write_text(
        "One-sentence contribution\nClaims-evidence\nSection plan\nFigure plan\nEvidence gap\n"
        + "Preserved scientific reasoning. " * 40, encoding="utf-8",
    )
    bib = root / "literature/references.bib"
    bib.write_bytes(b'@article{key,\r\n title={Nested {EEG} title},\r\n author={Wang},\r\n note={Original},\r\n doi={10.1/example}\r\n}\r\n')
    return bib


@pytest.mark.parametrize("field,old,new", [
    ("note", "Original", "Verified publisher spelling"),
    ("note", "Original", "Retracted due to invalid data"),
    ("author", "Wang", "Wang and Chen"),
    ("title", "Nested {EEG} title", "Changed {EEG} claim"),
    ("doi", "10.1/example", "10.2/corrected"),
])
def test_bibliography_delta_is_exact_and_never_rebinds_plan(tmp_path, monkeypatch, field, old, new):
    monkeypatch.setattr("server.services.paper_plan_evidence.verified_simulation_plan_evidence", lambda *_: False)
    bib = _project(tmp_path)
    build = service.record_existing(tmp_path)
    original = (tmp_path / service.build_relative_path).read_bytes()
    assert service.is_current(tmp_path)
    bib.write_bytes(bib.read_bytes().replace(old.encode(), new.encode()))
    instruction, tools = plan_delivery(tmp_path, True)
    assert "changed: literature/references.bib" in instruction
    assert f"{field}={{{new}}}" in instruction
    assert "Nested {EEG}" in build["bibliography_snapshot"]
    assert "new findings still require repair" in instruction
    assert "Write" not in tools
    assert not service.is_current(tmp_path)
    assert (tmp_path / service.build_relative_path).read_bytes() == original


def test_sources_added_removed_and_timestamp_only_updates(tmp_path):
    bib = _project(tmp_path)
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    selected.parent.mkdir()
    selected.write_text(json.dumps({"claim": "bounded", "generated_at": 1}))
    service.record_existing(tmp_path)
    selected.write_text(json.dumps({"claim": "bounded", "generated_at": 2}))
    assert "No tracked source changes" in plan_change_instruction(tmp_path)
    bib.unlink()
    (tmp_path / "NARRATIVE_REPORT.md").write_text("New scientific narrative")
    instruction = plan_change_instruction(tmp_path)
    assert "removed: literature/references.bib" in instruction
    assert "added: NARRATIVE_REPORT.md" in instruction
    assert "changed: ideas" not in instruction


@pytest.mark.parametrize("damage", ["legacy", "hash", "type", "non_ascii", "root"])
def test_unknown_or_corrupt_inventory_cannot_claim_unchanged_sources(tmp_path, damage):
    _project(tmp_path)
    build = service.record_existing(tmp_path)
    if damage == "legacy":
        del build["source_fingerprints"]
    elif damage == "hash":
        build["source_fingerprints"]["literature/references.bib"] = "0" * 64
    elif damage == "type":
        build["source_fingerprints"]["literature/references.bib"] = None
    elif damage == "non_ascii":
        build["source_fingerprints"]["literature/references.bib"] = "中" * 64
    else:
        build = []
    (tmp_path / service.build_relative_path).write_text(json.dumps(build))
    assert "change scope is unknown" in plan_change_instruction(tmp_path)


def test_changed_source_during_authoring_preserves_old_binding(tmp_path):
    bib = _project(tmp_path)
    build = service.record_existing(tmp_path)
    record = tmp_path / service.build_relative_path
    original = record.read_bytes()
    bib.write_text("@article{key, title={A different study}}")
    with pytest.raises(RuntimeError, match="sources changed during authoring"):
        service.record_existing(tmp_path, expected_source_hash=build["source_bundle_sha256"])
    assert record.read_bytes() == original


def test_existing_ordered_bundle_digest_is_unchanged(tmp_path):
    bib = _project(tmp_path)
    (tmp_path / "NARRATIVE_REPORT.md").write_text("Accepted narrative")
    digest = hashlib.sha256()
    for name in ("NARRATIVE_REPORT.md", "literature/references.bib"):
        digest.update(name.encode() + b"::")
        digest.update(hashlib.sha256((tmp_path / name).read_bytes()).hexdigest().encode() + b"\n")
    build = service.record_existing(tmp_path)
    assert build["source_bundle_sha256"] == digest.hexdigest()
    assert build["bibliography_snapshot"].encode() == bib.read_bytes()


@pytest.mark.asyncio
async def test_delegate_cannot_accept_concurrently_changed_sources(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from server.workflows.engine import WorkflowEngine
    from server.workflows.models import WorkflowNode, WorkflowRun

    bib = _project(tmp_path)
    service.record_existing(tmp_path)
    record = tmp_path / service.build_relative_path
    original = record.read_bytes()
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", AsyncMock())
    monkeypatch.setattr(service, "is_current", lambda *_: False)

    async def invoke(*args, **kwargs):
        bib.write_text("@article{key, title={Concurrent replacement}}")
        return "Model declares plan complete"

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    node = WorkflowNode(id="narrative", name="Narrative", skill="research-refine")
    run = WorkflowRun(id="source-conflict", project_path=str(tmp_path), nodes=[node])
    with pytest.raises(RuntimeError, match="sources changed during authoring"):
        await engine._execute_stage_delegates(
            node=node, run=run, direction="General study", effort="balanced", assurance="draft", opts={},
        )
    assert record.read_bytes() == original
    assert any(call.args[1] == "skill_invocation_failed" for call in engine._emit.call_args_list)
