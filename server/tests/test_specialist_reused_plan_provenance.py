"""Preparing a current reused specialist must preserve its source-call identity."""

import json
from pathlib import Path

import pytest

from server.services.research_specialists import ResearchSpecialistService


def test_repeated_current_plan_preparation_preserves_reused_source_fields_without_new_execution(tmp_path, monkeypatch):
    service = ResearchSpecialistService()
    options = {"research_family": "machine_learning", "study_archetype": "algorithm_benchmark",
               "target_venue": "ICLR", "run_experiment": False, "non_experiment_evidence_mode": "design_only"}
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    selected.parent.mkdir(parents=True)
    selected.write_text('{"idea":"stable source fixture"}', encoding="utf-8")
    run_id = "current-reuse-fixture"
    payload = service.prepare(tmp_path, run_id, "machine learning benchmark", options, ["results"])
    entry = next(item for item in payload["subnodes"] if item["id"] == "domain-validation")
    artifact = tmp_path / entry["artifact"]
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        "# Domain Validation Plan and Audit\n## Alternative Explanations\n"
        + "A matched source-backed control tests independent competing mechanisms. " * 8
        + "\n## Evidence Status\nThe declared sources bound this validation.\n",
        encoding="utf-8",
    )
    trace = tmp_path / ".merak/skill-invocations/source-verification.json"
    trace.parent.mkdir(parents=True)
    trace.write_text(json.dumps({"status": "completed", "session_id": "source-model-session",
                                "skill": "domain-validation", "run_id": "source-fixture-run"}), encoding="utf-8")
    reuse_fields = {"reused_from_run": "source-fixture-run", "reused_model_session_id": "source-model-session",
                   "reused_invocation_trace": str(trace)}
    entry.update({"status": "reused", "artifact_sha256": service._sha256(artifact), "session_id": "",
                  "completed_at": 1, **reuse_fields})
    service._atomic_write(service.plan_path(tmp_path, run_id), payload)
    before_artifact, before_trace = artifact.read_bytes(), trace.read_bytes()

    def forbidden_recovery(*_args, **_kwargs):
        pytest.fail("A verified current reused entry must not recover, rerun or invent new execution")

    for name in ("_recover_project_trace_entry", "_reusable_entry", "_completed_trace_fallback_entry"):
        monkeypatch.setattr(service, name, forbidden_recovery)
    for _repeat in range(2):
        current = service.prepare(tmp_path, run_id, "machine learning benchmark", options, ["results"])
        reused = next(item for item in current["subnodes"] if item["id"] == "domain-validation")
        assert reused["status"] == "reused" and reused["session_id"] == ""
        assert {key: reused[key] for key in reuse_fields} == reuse_fields
        assert reused["input_digest"] == entry["input_digest"]
        assert reused["artifact_sha256"] == entry["artifact_sha256"]
        assert reused["completed_at"] == 1
    assert artifact.read_bytes() == before_artifact and trace.read_bytes() == before_trace


def test_reused_provenance_preservation_does_not_make_changed_inputs_current(tmp_path):
    from server.services.specialist_plan import _restore_entry

    class StrictFixtureService:
        def _sha256(self, _path):
            return "same-artifact"

        def _artifact_valid(self, _root, _entry):
            return True, []

        def _recover_project_trace_entry(self, *_args):
            return None

        def _reusable_entry(self, *_args):
            return None

    old = {"status": "reused", "input_digest": "previous-science", "artifact_sha256": "same-artifact",
           "reused_from_run": "source-fixture-run", "reused_model_session_id": "source-session",
           "reused_invocation_trace": "source-trace.json"}
    entry = {"artifact": "experiments/specialists/DOMAIN_VALIDATION.md", "input_digest": "changed-science"}
    _restore_entry(StrictFixtureService(), tmp_path, tmp_path / "plan.json", entry, old)
    assert entry["status"] == "pending"
    assert "reused_from_run" not in entry and "reused_model_session_id" not in entry
