from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.execution_provenance import execution_provenance_service
from server.services.experiment_runtime_diagnostics import write_diagnosis
from server.services.experiment_runtime_finalization import finalize_runtime
from server.services.experiment_health import HealthFinding


class FakeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "run_manifest.json"
        self.attempt_updates: list[dict] = []
        self.manifest_updates: list[dict] = []
        self.events: list[tuple[str, dict]] = []

    def load(self) -> dict:
        return {"attempts": [{"attempt": 1, "started_at": "2026-01-01T00:00:00+00:00"}]}

    def update_attempt(self, attempt: int, **fields) -> None:
        self.attempt_updates.append({"attempt": attempt, **fields})

    def update(self, **fields) -> dict:
        self.manifest_updates.append(fields)
        return {"schema_version": 1, **fields}

    def append_event(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


class FakeHealth:
    latest_metrics = {"loss": 0.4}

    @staticmethod
    def snapshot() -> dict:
        return {"status": "failed"}


@pytest.mark.asyncio
async def test_finalize_runtime_binds_diagnosis_and_manifest_without_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    store = FakeStore(project / ".merak" / "runs" / "run-1")
    store.root.mkdir(parents=True)
    (store.root / "snapshot.json").write_text(
        json.dumps({"files": [{
            "path": "experiments/configs/main.yaml", "sha256": "cfg-hash",
        }]}),
        encoding="utf-8",
    )
    log_path = tmp_path / "attempt.log"
    log_path.write_text("loss=nan\n", encoding="utf-8")
    spec = SimpleNamespace(
        run_id="run-1",
        project_path=str(project),
        normalized_backend=lambda: "local",
    )
    finding = HealthFinding(
        kind="non_finite_loss",
        severity="critical",
        message="Loss became non-finite.",
        evidence={"step": 4},
    )
    monkeypatch.setattr(
        execution_provenance_service,
        "result_artifacts",
        lambda _project: {},
    )
    emitted: list[tuple[str, dict]] = []

    async def emit(_callback, event: str, payload: dict) -> None:
        emitted.append((event, payload))

    def diagnosis_writer(*args) -> Path:
        return write_diagnosis(*args, utc_now=lambda: "2026-01-01T00:01:00+00:00")

    result = await finalize_runtime(
        spec=spec,
        store=store,
        attempt_number=1,
        state="failed",
        exit_code=1,
        anomalies=[finding],
        health=FakeHealth(),
        log_path=log_path,
        result_path="",
        error="non-finite loss",
        on_event=None,
        transfers=None,
        diagnosis_writer=diagnosis_writer,
        emitter=emit,
        utc_now=lambda: "2026-01-01T00:01:00+00:00",
    )

    assert result["status"] == "failed"
    assert Path(result["diagnosis_path"]).is_file()
    assert store.attempt_updates[0]["config_hashes"] == {
        "experiments/configs/main.yaml": "cfg-hash"
    }
    assert store.manifest_updates[0]["evidence_eligible"] is False
    assert store.events[0][0] == "finished"
    assert emitted[0][0] == "experiment_finished"
    published = project / "experiments" / "results" / "remote" / "run-1" / "run_manifest.json"
    assert published.is_file()


def test_diagnosis_recommends_preflight_without_structured_anomaly(
    tmp_path: Path,
) -> None:
    store = FakeStore(tmp_path / "run")
    spec = SimpleNamespace(run_id="run", normalized_backend=lambda: "local")

    diagnosis = write_diagnosis(
        spec, store, 1, "failed", [], "exit 2", "attempt.log",
        utc_now=lambda: "2026-01-01T00:01:00+00:00",
    )

    payload = json.loads(diagnosis.read_text(encoding="utf-8"))
    assert payload["retry_contract"]["automatic_code_edits"] is False
    assert any("smallest deterministic preflight" in item for item in payload["recommendations"])
