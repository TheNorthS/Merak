from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.services.workflow_inputs import snapshot_paths
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows.run_state import RunState


def _write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _manifest(csv_path: str, csv_hash: str) -> dict:
    return {
        "schema": 5,
        "generated_at": 1.0,
        "simulation_id": "sim-v1",
        "simulation_seed": "1729",
        "primary_metric": "score",
        "metric_direction": "maximize",
        "evidence_status": "synthetic_preview",
        "submission_eligible": False,
        "data_files": [{"path": csv_path, "sha256": csv_hash}],
        "figure_files": [{
            "id": "main",
            "source_sha256": "a" * 64,
            "output_sha256": {"pdf": "b" * 64},
        }],
        "visual_quality": {"png_dpi": 450},
        "paper_table_sha256": "c" * 64,
    }


def test_renderer_only_manifest_drift_does_not_change_semantic_snapshot(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    csv_path = _write(
        tmp_path / "experiments" / "results" / "simulated" / "main.csv",
        "method,value\nfull,0.8\n",
    )
    manifest_path = _write(
        tmp_path / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json",
        json.dumps(
            _manifest(
                "experiments/results/simulated/main.csv",
                hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            ),
            indent=2,
        ),
    )
    expected = engine._semantic_manifest_snapshot_state(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["generated_at"] = 99.0
    payload["figure_files"][0]["output_sha256"]["pdf"] = "d" * 64
    payload["paper_table_sha256"] = "e" * 64
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert engine._artifact_snapshot_issues(
        str(tmp_path),
        {"experiments/results/simulated/SIMULATION_MANIFEST.json": expected},
    ) == []

    payload["simulation_seed"] = "1730"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert any(
        "accepted semantic artifact changed" in issue
        for issue in engine._artifact_snapshot_issues(
            str(tmp_path),
            {"experiments/results/simulated/SIMULATION_MANIFEST.json": expected},
        )
    )


def test_synthetic_results_snapshot_excludes_renderer_directory(
    tmp_path: Path,
) -> None:
    csv_path = _write(
        tmp_path / "experiments" / "results" / "simulated" / "main.csv",
        "method,value\nfull,0.8\n",
    )
    manifest_path = _write(
        tmp_path / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json",
        json.dumps(
            _manifest(
                "experiments/results/simulated/main.csv",
                hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            )
        ),
    )
    _write(tmp_path / "experiments" / "results" / "analysis.md", "analysis\n")
    _write(tmp_path / "experiments" / "RUN_SPEC.json", "{}\n")
    _write(tmp_path / "ideas" / "SELECTED_IDEA.json", "{}\n")
    engine = WorkflowEngine()
    run = WorkflowRun(
        id="synthetic-snapshot",
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    paths = engine._accepted_snapshot_paths(
        run,
        "results",
        {"details": {}},
        [tmp_path / "experiments" / "results"],
    )
    relatives = {path.relative_to(tmp_path).as_posix() for path in paths}
    assert "experiments/results" not in relatives
    assert "experiments/results/simulated/SIMULATION_MANIFEST.json" in relatives
    assert csv_path.relative_to(tmp_path).as_posix() in relatives

    gate = {"details": {}}
    engine._bind_gate_artifact_snapshot(
        WorkflowNode(id="results", name="Results", skill="/analyze-results"),
        run,
        gate,
    )
    snapshot = gate["details"]["artifact_snapshot"]
    assert snapshot[manifest_path.relative_to(tmp_path).as_posix()]["kind"] == (
        "semantic_manifest"
    )
    assert gate["details"]["artifact_snapshot_mode"] == "semantic-results-v1"


def test_synthetic_revision_signature_ignores_renderer_manifest_churn(
    tmp_path: Path,
) -> None:
    csv_path = _write(
        tmp_path / "experiments" / "results" / "simulated" / "main.csv",
        "method,value\nfull,0.8\n",
    )
    payload = _manifest(
        "experiments/results/simulated/main.csv",
        hashlib.sha256(csv_path.read_bytes()).hexdigest(),
    )
    manifest_path = _write(
        tmp_path / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json",
        json.dumps(payload, indent=2),
    )
    _write(tmp_path / "experiments" / "results" / "analysis.md", "analysis\n")
    _write(tmp_path / "experiments" / "RUN_SPEC.json", "{}\n")
    _write(tmp_path / "ideas" / "SELECTED_IDEA.json", "{}\n")
    options = {
        "run_experiment": False,
        "non_experiment_evidence_mode": "synthetic_preview",
    }
    engine = WorkflowEngine()
    before = engine._revision_artifact_signature(str(tmp_path), "results", options)

    payload["generated_at"] = 88.0
    payload["figure_files"][0]["output_sha256"]["pdf"] = "f" * 64
    payload["paper_table_sha256"] = "9" * 64
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert (
        engine._revision_artifact_signature(str(tmp_path), "results", options)
        == before
    )

    csv_path.write_text("method,value\nfull,0.9\n", encoding="utf-8")
    assert (
        engine._revision_artifact_signature(str(tmp_path), "results", options)
        != before
    )


def test_accepted_phase_invalidation_is_journaled_with_snapshot_keys(
    tmp_path: Path,
) -> None:
    artifact = _write(tmp_path / "ideas" / "ideas.md", "frozen idea\n")
    run_id = "invalidation-journal"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "idea", "name": "Idea", "skill": "/idea-discovery"}],
        {"options": {}},
    )
    state.set_status("idea", "done")
    state.accept(
        "idea",
        "artifact:idea",
        "deterministic:test",
        {"artifact_snapshot": snapshot_paths(tmp_path, [artifact])},
    )
    artifact.write_text("changed idea\n", encoding="utf-8")
    engine = WorkflowEngine()
    run = WorkflowRun(id=run_id, project_path=str(tmp_path))
    assert engine._validated_accepted_phase_ids(run, state) == []

    events_path = tmp_path / ".merak" / "runs" / f"{run_id}.events.jsonl"
    records = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event = next(item for item in records if item.get("event") == "accepted_phase_invalidated")
    data = event["data"]
    assert data["phase_id"] == "idea"
    assert "ideas/ideas.md" in data["changed_snapshot_keys"]
    assert data["owner"] == "idea"
    assert isinstance(data["dependency"], list)
