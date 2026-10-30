"""Runtime-owned cell receipts let all restart/repair consumers use exact output paths."""
import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json
from .execution_matrix import compile_execution_cells, cell_output_spec


def _digest(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def expected_jobs(spec: dict, execution_id: str) -> dict[str, dict]:
    return {f"{execution_id[:56]}-seed-{cell['seed']}-{index}": cell
            for index, cell in enumerate(compile_execution_cells(spec, execution_id=execution_id))}


def persist_cell_receipts(experiment, jobs: list) -> None:
    if not experiment.execution_cells:
        return
    root = Path(experiment.project_path).resolve()
    spec = json.loads((root / "experiments/RUN_SPEC.json").read_text(encoding="utf-8-sig"))
    expected = expected_jobs(spec, experiment.id)
    if {job.id: job.cell for job in jobs} != expected:
        raise ValueError("Scheduler cells differ from the frozen run contract")
    for job in jobs:
        atomic_write_json(root / ".merak/experiments" / job.id / "CELL_BINDING.json", {
            "schema": 1, "experiment_id": experiment.id, "job_id": job.id,
            "run_spec_sha256": _digest(spec), "cell": job.cell,
        })


def resolve_cell_spec(root: Path, spec: dict, job) -> dict:
    if not spec.get("scheduled_runs"):
        return spec
    path = Path(str(job if isinstance(job, (str, Path)) else job.manifest_path)).resolve()
    runtime_root = (root / ".merak/experiments").resolve()
    if path.parent.parent != runtime_root:
        raise ValueError("Matrix manifest is outside its runtime-owned directory")
    receipt = json.loads(path.with_name("CELL_BINDING.json").read_text(encoding="utf-8-sig"))
    if (receipt.get("schema") != 1 or receipt.get("job_id") != path.parent.name
            or receipt.get("run_spec_sha256") != _digest(spec)):
        raise ValueError("Matrix cell receipt does not bind the current run specification")
    expected = expected_jobs(spec, str(receipt.get("experiment_id") or ""))
    if receipt.get("cell") != expected.get(path.parent.name):
        raise ValueError("Matrix cell receipt has incorrect scientific coordinates")
    return cell_output_spec(spec, receipt["cell"])


def persisted_matrix_issues(spec: dict, experiment_id: str, refs: list) -> list[str]:
    if not spec.get("scheduled_runs"):
        return []
    expected = expected_jobs(spec, experiment_id)
    actual = [Path(str(ref if isinstance(ref, (str, Path)) else ref.manifest_path)).parent.name for ref in refs]
    if set(actual) != set(expected) or len(actual) != len(expected):
        return ["Persisted managed manifests do not exactly cover the registered execution matrix"]
    return []
