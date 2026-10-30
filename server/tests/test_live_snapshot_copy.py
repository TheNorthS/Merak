"""Live verification copy preserves specialist identity and excludes local secrets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.live_snapshot_copy import additional_input_files, relocate_specialist_plan_same_run, safe_selected_input_files


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict]:
    original, root = tmp_path / "source", tmp_path / "copy"
    trace = original / ".merak/skill-invocations/real-session_domain-validation.json"
    trace.parent.mkdir(parents=True)
    trace.write_text(json.dumps({"status": "completed", "session_id": "real-source-session",
                                "skill": "domain-validation", "run_id": "current-source-run"}))
    plan = {"schema": 1, "run_id": "current-source-run", "subnodes": [{
        "id": "domain-validation", "node_id": "results", "status": "completed",
        "session_id": "real-source-session", "skill": "domain-validation",
        "artifact_sha256": "original-artifact-hash", "input_digest": "original-input-digest",
        "invocation_trace": str(trace),
    }]}
    source = original / ".merak/runs/current-source-run.specialists.json"
    source.parent.mkdir()
    source.write_text(json.dumps(plan))
    for path in (source, trace):
        target = root / path.relative_to(original)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return original, root, source, trace, plan


def test_same_run_plan_relocation_preserves_every_evidence_field_except_local_path(tmp_path):
    original, root, source, trace, plan = _fixture(tmp_path)
    before = {path: path.read_bytes() for path in (source, trace)}
    report = relocate_specialist_plan_same_run(root, original, "current-source-run")
    clone = json.loads((root / source.relative_to(original)).read_text())
    expected = dict(plan["subnodes"][0])
    expected["invocation_trace"] = str(root / trace.relative_to(original))
    assert clone["run_id"] == plan["run_id"] and clone["subnodes"] == [expected]
    assert report["source_archive_unchanged"] and report["source_original_plan_unchanged"]
    assert not report["new_model_session_claimed"] and not report["invocation_records_rewritten"]
    assert all(path.read_bytes() == value for path, value in before.items())
    assert (root / trace.relative_to(original)).read_bytes() == before[trace]


@pytest.mark.parametrize("defect", ["foreign_path", "missing_trace", "trace_bytes", "wrong_run", "schema"])
def test_bad_source_evidence_is_rejected_before_any_relocation_mutation(tmp_path, defect):
    original, root, source, trace, plan = _fixture(tmp_path)
    if defect in {"foreign_path", "missing_trace"}:
        plan["subnodes"][0]["invocation_trace"] = str(tmp_path / "foreign.json" if defect == "foreign_path" else trace.with_name("missing.json"))
    elif defect == "wrong_run":
        plan["run_id"] = "foreign-run"
    elif defect == "schema":
        plan["schema"] = 99
    else:
        (root / trace.relative_to(original)).write_bytes(b"changed copied invocation")
    source.write_text(json.dumps(plan))
    copied = root / source.relative_to(original)
    copied.write_bytes(source.read_bytes())
    before = copied.read_bytes()
    with pytest.raises(ValueError):
        relocate_specialist_plan_same_run(root, original, "current-source-run")
    assert copied.read_bytes() == before and source.read_bytes() == before
    assert not (root / ".merak/snapshot-source-traces").exists()


def test_input_selection_carries_evidence_but_never_lease_keys_database_or_agent_sessions(tmp_path):
    root = tmp_path / "source"
    relatives = (".env", "user_settings.json", "merak_ide.db", ".merak/active-workflow.json",
                 ".merak/recovery-leases/active.json", ".merak/agent-sessions/private.json",
                 "experiments/specialists/DOMAIN_VALIDATION.md", ".merak/skill-invocations/trace.json")
    paths = []
    for relative in relatives:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("local fixture")
        paths.append(path)
    selected = safe_selected_input_files(root, paths)
    assert {path.relative_to(root).as_posix() for path in selected} == {
        "experiments/specialists/DOMAIN_VALIDATION.md", ".merak/skill-invocations/trace.json",
    }
    assert {path.relative_to(root).as_posix() for path in additional_input_files(root, "source-run")} == {
        "experiments/specialists/DOMAIN_VALIDATION.md", ".merak/skill-invocations/trace.json",
    }
