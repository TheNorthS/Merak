"""Compile the exact declared experiment matrix; no silent first-seed reduction."""
import hashlib
import itertools
import json
import re
from pathlib import PurePosixPath
from string import Formatter

from ..contracts.preparation import PreparationContractError
from .run_spec import execution_seeds, run_spec_scientific_command


def _names(value, field: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", v) for v in value):
        raise PreparationContractError(f"scheduled_runs.{field} requires nonempty shell-safe stable IDs")
    if len(value) != len(set(value)):
        raise PreparationContractError(f"scheduled_runs.{field} contains duplicates")
    return value


def compile_execution_cells(spec: dict, command: str | None = None, *, execution_id: str = "") -> list[dict]:
    """A multi-axis declaration requires scheduler ownership and explicit bindings."""
    command = command if command is not None else run_spec_scientific_command(spec)
    seeds = execution_seeds(spec) or [0]
    matrix = spec.get("scheduled_runs")
    if matrix is not None and not isinstance(matrix, dict):
        raise PreparationContractError("scheduled_runs must be a version-1 matrix object")
    fields = {field for _, field, _, _ in Formatter().parse(command) if field}
    if not matrix:
        if len(seeds) > 1 and "seed" not in fields:
            raise PreparationContractError("Multiple registered seeds require an explicit {seed} command binding; implicit entrypoint traversal is unverified")
        return []
    if matrix.get("schema") != 1 or matrix.get("owner") != "scheduler":
        raise PreparationContractError("scheduled_runs requires schema=1 and owner=scheduler; implicit matrix execution cannot be accepted")
    conditions, axes = _names(matrix.get("conditions"), "conditions"), _names(matrix.get("holdout_axes"), "holdout_axes")
    if not {"seed", "condition", "axis", "output_dir"} <= fields:
        raise PreparationContractError("Matrix command must bind {seed}, {condition}, {axis}, and {output_dir}")
    if len(seeds) * len(conditions) * len(axes) > 10000:
        raise PreparationContractError("Execution matrix exceeds the 10000-cell bound")
    outputs = (spec.get("outputs") or {}).get("per_run_files")
    if not isinstance(outputs, list) or not outputs or any(not isinstance(p, str) or not p.startswith("{output_dir}/") for p in outputs):
        raise PreparationContractError("Matrix outputs.per_run_files must live below {output_dir}/ for every cell")
    base = str(matrix.get("output_root") or "experiments/results/cells")
    if PurePosixPath(base).is_absolute() or ".." in PurePosixPath(base).parts or not re.fullmatch(r"[A-Za-z0-9_./-]+", base):
        raise PreparationContractError("Matrix output_root must be a safe project-relative directory")
    if execution_id:
        base += "/" + hashlib.sha256(execution_id.encode()).hexdigest()[:16]
    cells = []
    for condition, axis, seed in itertools.product(conditions, axes, seeds):
        identity = hashlib.sha256(json.dumps([condition, axis, seed]).encode()).hexdigest()[:16]
        cells.append({"cell_id": identity, "condition": condition, "axis": axis, "seed": seed,
                      "output_dir": f"{base}/{identity}"})
    for cell in cells:
        cell_output_spec(spec, cell)
    return cells


def cell_output_spec(spec: dict, cell: dict) -> dict:
    if not cell:
        return spec
    outputs = dict(spec.get("outputs") or {})
    try:
        paths = [path.format(**cell) for path in outputs["per_run_files"]]
    except (KeyError, ValueError, IndexError) as error:
        raise PreparationContractError("Invalid matrix output path binding") from error
    prefix = PurePosixPath(cell["output_dir"])
    if any(".." in PurePosixPath(p).parts or not PurePosixPath(p).is_relative_to(prefix) for p in paths):
        raise PreparationContractError("Cell output leaves its immutable namespace")
    return {**spec, "outputs": {**outputs, "per_run_files": paths}}


def matrix_coverage_issues(spec: dict, jobs: list, *, execution_id: str = "") -> list[str]:
    cells = compile_execution_cells(spec, execution_id=execution_id)
    if not cells:
        return []
    expected = {cell["cell_id"] for cell in cells}
    actual = [job.cell.get("cell_id") for job in jobs if getattr(job.status, "value", job.status) == "completed"]
    if set(actual) != expected or len(actual) != len(expected):
        return ["Completed job identities do not exactly cover the registered condition/axis/seed matrix"]
    by_id = {cell["cell_id"]: cell for cell in cells}
    if any(job.cell != by_id.get(job.cell.get("cell_id")) for job in jobs):
        return ["Completed job cell binding differs from its registered scientific coordinates"]
    return []
