"""Verification-copy envelope relocation never fabricates upstream executions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.snapshot_execution_trace import archived_execution_source_unchanged, clone_execution_envelope
from server.services.skill_execution_trace import SkillExecutionTrace


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    original, copied = tmp_path / "source", tmp_path / "copy"
    payload = {"schema": 2, "run_id": "fixture-current", "project_path": str(original.resolve()),
               "stages": {"results": {"node_id": "results", "execution_kind": "runtime_owned",
                                      "policy_required": False, "runtime_service": "planned_results_analysis",
                                      "runtime_invocations": [{"runtime_service": "planned_results_analysis",
                                                               "status": "completed", "operation_id": "actual-fixture-op",
                                                               "run_id": "fixture-current"}], "invocations": []}}}
    relative = ".merak/runs/fixture-current.skills.json"
    for root in (original, copied):
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf8")
    return original, copied, original / relative, payload


def _trace() -> SkillExecutionTrace:
    return SkillExecutionTrace(SimpleNamespace(total_skills=0, get_skill=lambda _skill: None))


def test_explicit_copy_relocation_keeps_current_run_and_upstream_invocations_exact(tmp_path):
    original, copied, source, payload = _fixture(tmp_path)
    before = source.read_bytes()
    assert not _trace().execution_gate(str(copied), "fixture-current", "results")["accepted"]
    relocation = clone_execution_envelope(copied, original, "fixture-current")
    clone = json.loads((copied / ".merak/runs/fixture-current.skills.json").read_text())
    assert clone["project_path"] == str(copied.resolve())
    assert clone["run_id"] == payload["run_id"] and clone["stages"] == payload["stages"]
    assert not clone["snapshot_provenance"]["upstream_invocations_rewritten"]
    assert not clone["snapshot_provenance"]["new_upstream_execution_claimed"]
    assert _trace().execution_gate(str(copied), "fixture-current", "results")["accepted"]
    assert source.read_bytes() == before and archived_execution_source_unchanged(copied, relocation)
    foreign = copied / ".merak/runs/foreign-run.skills.json"
    foreign.write_text(json.dumps(clone))
    assert not _trace().execution_gate(str(copied), "foreign-run", "results")["accepted"]


@pytest.mark.parametrize("invalid", ["run", "project", "schema", "modified_copy"])
def test_wrong_source_identity_or_changed_copy_is_rejected_without_mutation(tmp_path, invalid):
    original, copied, source, payload = _fixture(tmp_path)
    if invalid == "modified_copy":
        (copied / ".merak/runs/fixture-current.skills.json").write_text("modified")
    else:
        payload[{"run": "run_id", "project": "project_path", "schema": "schema"}[invalid]] = {
            "run": "another-run", "project": str(tmp_path / "foreign-project"), "schema": 99,
        }[invalid]
        source.write_text(json.dumps(payload))
        (copied / ".merak/runs/fixture-current.skills.json").write_bytes(source.read_bytes())
    before = source.read_bytes()
    with pytest.raises(ValueError):
        clone_execution_envelope(copied, original, "fixture-current")
    assert source.read_bytes() == before
    assert not (copied / ".merak/snapshot-source-traces").exists()


def test_source_archive_tamper_is_detected(tmp_path):
    original, copied, source, _payload = _fixture(tmp_path)
    relocation = clone_execution_envelope(copied, original, "fixture-current")
    archive = copied / relocation["source_trace_archive"]
    archive.write_bytes(archive.read_bytes() + b"tampered")
    assert not archived_execution_source_unchanged(copied, relocation)
    assert source.read_bytes() != archive.read_bytes()
