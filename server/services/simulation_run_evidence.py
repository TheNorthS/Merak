"""Construct run-level observations and provenance for simulation inputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .simulation_evidence_helpers import (
    provenance_fields as _provenance_fields,
    seed_values as _seed_values,
)

Row = dict[str, str]


@dataclass(frozen=True)
class SimulationRunEvidence:
    rows: list[Row]
    ledger: list[Row]
    frozen_manifest: Path
    manifest_sha256: str
    calibrator_id: str
    software_image: str
    hardware_contract_id: str
    provenance: Callable[..., Row]


def materialize_run_evidence(
    root: Path,
    evidence_sources: dict[str, list[Row]],
    simulation_id: str,
    source_run_id: str,
    seed_ids: tuple[int, ...],
    primary_metric: str,
    metric_direction: str,
    configured_contract: dict[str, Any],
    configured_method: dict[str, Any],
    simulated: Callable[[dict[str, Any]], Row],
    write_csv: Callable[[Path, list[Row]], None],
) -> SimulationRunEvidence:
    data_contract = (
        configured_contract.get("data")
        if isinstance(configured_contract.get("data"), dict)
        else {}
    )
    calibration_contract = (
        configured_method.get("calibration")
        if isinstance(configured_method.get("calibration"), dict)
        else {}
    )
    efficiency_contract = (
        configured_method.get("efficiency_measurement")
        if isinstance(configured_method.get("efficiency_measurement"), dict)
        else {}
    )
    data_version = str(data_contract.get("version") or "simulation-dataset-v1")
    data_manifest_path = "experiments/results/simulated/data_manifest.csv"
    frozen_data_manifest = root / data_manifest_path
    data_manifest_sha256 = _write_manifest(
        frozen_data_manifest,
        evidence_sources,
        simulation_id,
        seed_ids,
        primary_metric,
        write_csv,
    )
    build_provenance, calibrator_id, software_image, hardware_contract_id = (
        _provenance_factory(
            configured_method,
            calibration_contract,
            efficiency_contract,
            simulation_id,
            data_version,
            data_manifest_path,
            data_manifest_sha256,
        )
    )
    run_level_rows, run_ledger_rows = _run_rows(
        evidence_sources,
        seed_ids,
        source_run_id,
        primary_metric,
        metric_direction,
        simulated,
        build_provenance,
    )
    return SimulationRunEvidence(
        run_level_rows,
        run_ledger_rows,
        frozen_data_manifest,
        data_manifest_sha256,
        calibrator_id,
        software_image,
        hardware_contract_id,
        build_provenance,
    )


def _write_manifest(
    frozen_data_manifest: Path,
    evidence_sources: dict[str, list[Row]],
    simulation_id: str,
    seed_ids: tuple[int, ...],
    primary_metric: str,
    write_csv: Callable[[Path, list[Row]], None],
) -> str:
    data_manifest_rows: list[dict[str, str]] = []
    for role, rows in evidence_sources.items():
        for row in rows:
            row_id = str(row.get("row_id") or "registered-row")
            for seed_id in seed_ids:
                identity = f"{simulation_id}|{role}|{row_id}|seed-{seed_id}"
                data_manifest_rows.append(
                    {
                        "row_id": f"simulation-unit-{len(data_manifest_rows) + 1}",
                        "sample_id": f"simulation-unit-{len(data_manifest_rows) + 1}",
                        "simulation_id": simulation_id,
                        "artifact_role": role,
                        "aggregate_row_id": row_id,
                        "seed": str(seed_id),
                        "partition": str(
                            row.get("dataset") or row.get("split") or role
                        ),
                        "analysis_unit": "random_seed",
                        "metric": str(row.get("metric") or primary_metric),
                        "content_sha256": hashlib.sha256(
                            identity.encode("utf-8")
                        ).hexdigest(),
                    }
                )
    write_csv(frozen_data_manifest, data_manifest_rows)
    return _sha256_file(frozen_data_manifest)


def _provenance_factory(
    configured_method: dict[str, Any],
    calibration_contract: dict[str, Any],
    efficiency_contract: dict[str, Any],
    simulation_id: str,
    data_version: str,
    data_manifest_path: str,
    data_manifest_sha256: str,
) -> tuple[Callable[..., Row], str, str, str]:
    calibrator_id = str(calibration_contract.get("method") or "identity")
    software_image = "merak-deterministic-simulation-v3"
    hardware_contract_id = "simulation-fixed-device-v1"
    matched_fields = "|".join(
        str(value)
        for value in (
            (configured_method.get("ablations") or {}).get("matched_fields", [])
            if isinstance(configured_method.get("ablations"), dict)
            else []
        )
        if str(value).strip()
    )

    build_provenance = partial(
        _provenance_fields,
        simulation_id=simulation_id,
        data_version=data_version,
        data_manifest_path=data_manifest_path,
        data_manifest_sha256=data_manifest_sha256,
        calibrator_id=calibrator_id,
        software_image=software_image,
        hardware_contract_id=hardware_contract_id,
        efficiency_contract=efficiency_contract,
        matched_fields=matched_fields,
    )
    return build_provenance, calibrator_id, software_image, hardware_contract_id


def _run_rows(
    evidence_sources: dict[str, list[Row]],
    seed_ids: tuple[int, ...],
    source_run_id: str,
    primary_metric: str,
    metric_direction: str,
    simulated: Callable[[dict[str, Any]], Row],
    build_provenance: Callable[..., Row],
) -> tuple[list[Row], list[Row]]:
    run_level_rows: list[Row] = []
    run_ledger_rows: list[Row] = []
    for role, rows in evidence_sources.items():
        for row in rows:
            values = _seed_values(row)
            row_id = str(row.get("row_id") or "")
            method = str(
                row.get("method") or row.get("component_setting") or "registered-system"
            )
            model_id = str(row.get("model_id") or method)
            for position, seed_id in enumerate(seed_ids):
                value = (
                    values[position] if position < len(values) else float(row["value"])
                )
                run_identity = f"{source_run_id}:{role}:{row_id}:seed-{seed_id}"
                provenance = build_provenance(
                    role=role,
                    method=method,
                    model_id=model_id,
                    seed_id=seed_id,
                    split_identity=str(row.get("dataset") or row.get("split") or role),
                )
                run_level_rows.append(
                    simulated(
                        {
                            "row_id": f"run-level-{role}-{row_id}-{seed_id}",
                            "run_id": run_identity,
                            "artifact_role": role,
                            "aggregate_row_id": row_id,
                            "method": method,
                            "model_id": model_id,
                            "dataset": str(row.get("dataset") or "registered-scenario"),
                            "condition": str(
                                row.get("component_setting")
                                or row.get("shift_condition")
                                or row.get("coverage")
                                or row.get("epoch")
                                or "registered"
                            ),
                            "seed": str(seed_id),
                            "metric": str(row.get("metric") or primary_metric),
                            "metric_direction": str(
                                row.get("metric_direction") or metric_direction
                            ),
                            "value": f"{value:.6f}",
                            "completion_status": "completed",
                            **provenance,
                        }
                    )
                )
                run_ledger_rows.append(_ledger_row(
                    role, row_id, method, model_id, seed_id, run_identity,
                    provenance, simulated,
                ))
    return run_level_rows, run_ledger_rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ledger_row(
    role: str, row_id: str, method: str, model_id: str, seed_id: int,
    run_identity: str, provenance: Row,
    simulated: Callable[[dict[str, Any]], Row],
) -> Row:
    return simulated({
        "row_id": f"ledger-{role}-{row_id}-{seed_id}",
        "run_id": run_identity, "artifact_role": role,
        "aggregate_row_id": row_id, "method": method, "model_id": model_id,
        "seed": str(seed_id), "completion_status": "completed",
        "failure_reason": "", **provenance,
        "run_level_table": "experiments/results/simulated/run_level_results.csv",
        "latency_table": (
            "experiments/results/simulated/latency_samples.csv"
            if role == "efficiency_tradeoff" else "not_applicable"
        ),
    })
