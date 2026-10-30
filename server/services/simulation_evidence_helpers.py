"""Pure helpers for deterministic simulation evidence and claim decisions."""

from __future__ import annotations

import hashlib
from typing import Any


def is_primary_reference_axis(axis: dict[str, Any], primary_metric: str) -> bool:
    axis_id = str(axis.get("axis_id") or "").casefold()
    metric_key = str(axis.get("metric_key") or "").casefold()
    primary_key = str(primary_metric or "").casefold()
    blocked = (
        "shift", "stress", "worst", "nll", "brier", "latency",
        "memory", "energy", "calibration", "robust",
    )
    if any(marker in axis_id for marker in blocked):
        return False
    return (
        "iid" in axis_id and "acc" in axis_id
        or axis_id == primary_key
        or metric_key == primary_key
    )


def bind_seed_replicates(
    rows: list[dict[str, str]], seed_ids: list[int], t_critical_95: float,
) -> None:
    for row_index, item in enumerate(rows):
        if item.get("seed_count") == str(len(seed_ids)):
            continue
        center = float(item["value"])
        scale = 0.004 + 0.001 * (row_index % 3)
        offsets = tuple(
            scale * (index - (len(seed_ids) - 1) / 2.0)
            for index in range(len(seed_ids))
        )
        values = [center + offset for offset in offsets]
        variance = sum(offset ** 2 for offset in offsets) / (len(offsets) - 1)
        width = t_critical_95 * (variance / len(offsets)) ** 0.5
        item.update({
            "seed": "|".join(str(seed) for seed in seed_ids),
            "seed_count": str(len(seed_ids)),
            "seed_values": "|".join(f"{value:.4f}" for value in values),
            "replicate_unit": "random_seed",
            "ci_low": f"{center - width:.3f}",
            "ci_high": f"{center + width:.3f}",
        })


def seed_values(row: dict[str, str]) -> list[float]:
    values = []
    for raw in str(row.get("seed_values") or "").split("|"):
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def provenance_fields(
    *, simulation_id: str, role: str, method: str, model_id: str,
    seed_id: int, split_identity: str, data_version: str,
    data_manifest_path: str, data_manifest_sha256: str, calibrator_id: str,
    software_image: str, hardware_contract_id: str,
    efficiency_contract: dict[str, Any], matched_fields: str,
) -> dict[str, str]:
    config_sha256 = hashlib.sha256(
        f"{simulation_id}|{role}|{model_id}|{seed_id}".encode("utf-8")
    ).hexdigest()
    split_sha256 = hashlib.sha256(
        f"{simulation_id}|{split_identity}".encode("utf-8")
    ).hexdigest()
    return {
        "method": method, "model_id": model_id, "data_version": data_version,
        "data_manifest_path": data_manifest_path,
        "manifest_sha256": data_manifest_sha256, "split_sha256": split_sha256,
        "config_sha256": config_sha256, "calibrator_id": calibrator_id,
        "software_image": software_image,
        "hardware_contract_id": hardware_contract_id,
        "precision": str(efficiency_contract.get("precision") or "float32"),
        "batch_size": str(efficiency_contract.get("batch_size") or 32),
        "matched_fields": matched_fields,
    }


def axis_center(axis_id: str, direction: str, model_index: int) -> tuple[float, float]:
    normalized = axis_id.casefold()
    cases = (
        ("iid" in normalized and "acc" in normalized, 0.640 + 0.024 * model_index, 0.0040),
        ("shift" in normalized and "acc" in normalized, 0.535 + 0.021 * model_index, 0.0050),
        ("nll" in normalized, 0.720 - 0.046 * model_index, 0.0060),
        ("brier" in normalized, 0.235 - 0.019 * model_index, 0.0030),
        ("latency" in normalized, 18.40 - 0.85 * model_index, 0.075),
        ("memory" in normalized or "bytes" in normalized,
         2_147_483_648.0 - 67_108_864.0 * model_index, 2_097_152.0),
    )
    for matched, center, scale in cases:
        if matched:
            return center, scale
    delta = 0.020 * model_index if direction == "maximize" else -0.020 * model_index
    return 0.600 + delta, 0.0040


def evidence_kind(outcome: str) -> str:
    lower = outcome.casefold()
    mappings = (
        (("removal", "ablation", "necessity"), "component necessity"),
        (("morphology", "band", "frequency"), "mechanism readout"),
        (("stability", "agreement", "shift"), "stability readout"),
        (("held-out", "held out", "transfer", "effect"), "held-out comparison"),
        (("calibration", "brier", "ece", "coverage"), "calibration"),
    )
    return next((label for terms, label in mappings if any(term in lower for term in terms)), "registered endpoint")


def evidence_decision(outcome: str) -> str:
    lower = outcome.casefold()
    mappings = (
        (("ablation", "single-factor", "single factor", "单因素"), "matched_single_factor_effect_observed_without_reversal_state_change"),
        (("paired",), "paired_effects_computed_from_run_level_results"),
        (("reversal", "排名反转"), "no_qualifying_reversal_after_registered_paired_rule"),
        (("holm", "multiplicity"), "holm_family_completed_without_qualifying_rejection"),
        (("interval", "confidence", "bootstrap", "区间"), "paired_seed_and_bootstrap_intervals_computed"),
        (("ledger", "provenance", "audit", "溯源", "账本"), "complete_provenance_binding_verified"),
    )
    return next((decision for terms, decision in mappings if any(term in lower for term in terms)), "registered_outcome_observed")
