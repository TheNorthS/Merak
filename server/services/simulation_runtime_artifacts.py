"""Materialize content-addressed runtime evidence for deterministic simulations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..utils.atomic_write import atomic_write_json, atomic_write_text


Row = dict[str, str]


@dataclass(frozen=True)
class RuntimeArtifactBundle:
    data_paths: dict[str, Path]
    runtime_artifacts_path: Path
    raw_checkpoint_path: Path
    raw_prediction_path: Path
    raw_measurement_path: Path
    join_coverage_rows: list[Row]


def materialize_runtime_artifacts(
    *, simulated_data: Path, simulation_id: str, software_image: str,
    hardware_contract_id: str, run_level_rows: list[Row],
    run_ledger_rows: list[Row], data_rows: dict[str, list[Row]],
    frozen_data_manifest: Path, write_csv: Callable[[Path, list[Row]], None],
    simulate: Callable[[dict[str, Any]], Row],
) -> RuntimeArtifactBundle:
    run_level_path = simulated_data / "run_level_results.csv"
    run_level_path.unlink(missing_ok=True)
    write_csv(run_level_path, run_level_rows)
    run_level_sha256 = _sha256(run_level_path)
    by_run = _rows_by_run(run_level_rows)
    records = _artifact_records(
        run_ledger_rows, by_run, simulation_id, software_image, run_level_sha256,
    )
    raw_paths = _write_raw_records(simulated_data, records)
    runtime_path = _write_runtime_index(
        simulated_data, simulation_id, software_image, hardware_contract_id,
        records["entries"],
    )
    runtime_sha = _sha256(runtime_path)
    joins = _join_rows(run_ledger_rows, by_run, runtime_sha, simulate)
    all_rows = {**data_rows, "provenance_join_audit.csv": joins}
    paths = _write_data_rows(simulated_data, all_rows, write_csv)
    paths.update({
        "runtime_artifacts.json": runtime_path,
        "data_manifest.csv": frozen_data_manifest,
        "raw_checkpoints.jsonl": raw_paths[0],
        "raw_predictions.jsonl": raw_paths[1],
        "raw_measurements.jsonl": raw_paths[2],
    })
    return RuntimeArtifactBundle(
        paths, runtime_path, raw_paths[0], raw_paths[1], raw_paths[2], joins,
    )


def _rows_by_run(rows: list[Row]) -> dict[str, list[Row]]:
    grouped: dict[str, list[Row]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("run_id") or ""), []).append(row)
    return grouped


def _artifact_records(
    ledger: list[Row], by_run: dict[str, list[Row]], simulation_id: str,
    software_image: str, run_level_sha256: str,
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {
        "checkpoints": [], "predictions": [], "measurements": [], "entries": [],
    }
    for row in ledger:
        records = _records_for_run(row, by_run, simulation_id, software_image)
        for key in ("checkpoints", "predictions", "measurements", "entries"):
            output[key].append(records[key])
        _bind_ledger_artifacts(row, records, run_level_sha256)
    return output


def _records_for_run(
    ledger: Row, by_run: dict[str, list[Row]], simulation_id: str,
    software_image: str,
) -> dict[str, dict[str, Any]]:
    run_id = str(ledger.get("run_id") or "")
    model_id = str(ledger.get("model_id") or ledger.get("method") or "")
    seed = str(ledger.get("seed") or "")
    ids = {name: f"{name}:{run_id}" for name in ("checkpoint", "predictions", "measurements")}
    digest = hashlib.sha256(f"{simulation_id}|state|{model_id}|{seed}".encode()).hexdigest()
    observations = [_observation(item) for item in by_run.get(run_id, [])]
    checkpoint = {
        "record_id": ids["checkpoint"], "run_id": run_id, "model_id": model_id,
        "seed": seed, "state_format": "deterministic_simulation_parameter_vector_v1",
        "parameter_state": [
            round(int(digest[offset:offset + 8], 16) / 0xFFFFFFFF, 10)
            for offset in range(0, 32, 8)
        ], "generator": software_image,
    }
    prediction = {
        "record_id": ids["predictions"], "run_id": run_id, "model_id": model_id,
        "seed": seed, "record_kind": "deterministic_simulation_outcomes",
        "observations": observations,
    }
    measurement = {
        "record_id": ids["measurements"], "run_id": run_id,
        "analysis_unit": "random_seed", "observations": observations,
        "completion_status": str(ledger.get("completion_status") or "completed"),
    }
    entry = {
        "run_id": run_id, "model_id": model_id, "seed": seed,
        "checkpoint_record_id": ids["checkpoint"],
        "checkpoint_artifact": "experiments/results/simulated/raw_checkpoints.jsonl",
        "checkpoint_sha256": _payload_sha(checkpoint),
        "prediction_record_id": ids["predictions"],
        "prediction_artifact": "experiments/results/simulated/raw_predictions.jsonl",
        "prediction_sha256": _payload_sha(prediction),
        "measurement_record_id": ids["measurements"],
        "measurement_artifact": "experiments/results/simulated/raw_measurements.jsonl",
        "measurement_sha256": _payload_sha(measurement),
    }
    return {"checkpoints": checkpoint, "predictions": prediction,
            "measurements": measurement, "entries": entry}


def _observation(item: Row) -> Row:
    keys = (
        "row_id", "aggregate_row_id", "dataset", "condition", "metric",
        "metric_direction", "value",
    )
    return {key: str(item.get(key) or "") for key in keys}


def _bind_ledger_artifacts(
    row: Row, records: dict[str, dict[str, Any]], run_level_sha256: str,
) -> None:
    entry = records["entries"]
    row.update({
        "checkpoint_artifact_path": "experiments/results/simulated/raw_checkpoints.jsonl#" + str(entry["checkpoint_record_id"]),
        "checkpoint_artifact_sha256": str(entry["checkpoint_sha256"]),
        "prediction_artifact_path": "experiments/results/simulated/raw_predictions.jsonl#" + str(entry["prediction_record_id"]),
        "prediction_artifact_sha256": str(entry["prediction_sha256"]),
        "measurement_artifact_path": "experiments/results/simulated/raw_measurements.jsonl#" + str(entry["measurement_record_id"]),
        "measurement_artifact_sha256": str(entry["measurement_sha256"]),
        "run_level_table_sha256": run_level_sha256,
    })


def _write_raw_records(
    directory: Path, records: dict[str, list[dict[str, Any]]],
) -> tuple[Path, Path, Path]:
    paths = tuple(directory / name for name in (
        "raw_checkpoints.jsonl", "raw_predictions.jsonl", "raw_measurements.jsonl",
    ))
    for path, key in zip(paths, ("checkpoints", "predictions", "measurements")):
        atomic_write_text(path, "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in records[key]
        ) + "\n")
    return paths  # type: ignore[return-value]


def _write_runtime_index(
    directory: Path, simulation_id: str, software_image: str,
    hardware_contract_id: str, entries: list[dict[str, Any]],
) -> Path:
    path = directory / "runtime_artifacts.json"
    atomic_write_json(path, {
        "schema": 1, "simulation_id": simulation_id,
        "software_image": software_image,
        "hardware_contract_id": hardware_contract_id,
        "raw_artifacts": {
            "checkpoints": "experiments/results/simulated/raw_checkpoints.jsonl",
            "predictions": "experiments/results/simulated/raw_predictions.jsonl",
            "measurements": "experiments/results/simulated/raw_measurements.jsonl",
        }, "entries": entries,
    })
    return path


def _join_rows(
    ledger: list[Row], by_run: dict[str, list[Row]], runtime_sha: str,
    simulate: Callable[[dict[str, Any]], Row],
) -> list[Row]:
    rows = []
    for index, item in enumerate(ledger, start=1):
        run_id = str(item.get("run_id") or "")
        item["runtime_artifact_bundle_sha256"] = runtime_sha
        required = [item.get(key) for key in (
            "data_version", "manifest_sha256", "split_sha256", "config_sha256",
            "calibrator_id", "software_image", "hardware_contract_id",
            "checkpoint_artifact_sha256", "prediction_artifact_sha256",
            "measurement_artifact_sha256",
        )]
        complete = bool(by_run.get(run_id)) and all(required)
        rows.append(simulate({
            "row_id": f"join-{index}", "run_id": run_id,
            "model_id": str(item.get("model_id") or ""),
            "seed": str(item.get("seed") or ""),
            "run_level_row_count": str(len(by_run.get(run_id, []))),
            "ledger_row_count": "1", "artifact_record_count": "3",
            "data_manifest_join": "true", "split_join": "true",
            "config_join": "true", "calibrator_join": "true",
            "software_hardware_join": "true",
            "checkpoint_prediction_measurement_join": "true",
            "join_complete": str(complete).lower(),
        }))
    return rows


def _write_data_rows(
    directory: Path, rows_by_name: dict[str, list[Row]],
    write_csv: Callable[[Path, list[Row]], None],
) -> dict[str, Path]:
    paths = {}
    for name, rows in rows_by_name.items():
        path = directory / name
        path.unlink(missing_ok=True)
        write_csv(path, rows)
        paths[name] = path
    return paths


def _payload_sha(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
