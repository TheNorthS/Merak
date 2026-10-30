"""Frozen CSFS-v1 probe evaluation and source-bound prediction identities.

This module performs no fitting, checkpoint selection or persistence. It is
called only by the explicitly authorized study runner, never to convert a code
readiness check into scientific execution. Primary probabilities are uncalibrated.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import re
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from .metrics import SegmentPrediction, UnitPrediction, aggregate_predictions, classification_metrics
from .protocol import METHOD_IDS, PROTOCOL_ID, SEEDS, VIEW_KEYS
from .statistics import HASH_BINDINGS, ScoreRecord


@dataclass(frozen=True)
class EvaluationBindings:
    """Caller binds real frozen runtime assets before any target scoring.

    target_id is the outer fold target even for source-validation selection.
    fit_role is source_training for LDO or target_local_training for in-domain;
    evaluation_role is target_test/source_validation/target_local_test/target_local_validation.
    """
    method_id: str
    target_id: str
    seed: int
    source_training_dataset_ids: tuple[str, ...]
    source_validation_dataset_id: str
    evaluation_dataset_id: str
    fit_role: str
    evaluation_role: str
    checkpoint_sha256: str
    probe_sha256: str
    config_sha256: str
    source_sha256: str
    manifest_sha256: str
    split_sha256: str
    normalization_sha256: str
    label_vocabulary_sha256: str
    protocol_id: str = PROTOCOL_ID


def label_vocabulary_hash(vocabulary: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(vocabulary), separators=(",", ":")).encode()).hexdigest()


def _validate_bindings(bindings: EvaluationBindings, vocabulary: Sequence[str]) -> None:
    if (bindings.protocol_id != PROTOCOL_ID or bindings.method_id not in METHOD_IDS or bindings.seed not in SEEDS
            or any(not re.fullmatch(r"[a-f0-9]{64}", getattr(bindings, key)) for key in HASH_BINDINGS)
            or bindings.label_vocabulary_sha256 != label_vocabulary_hash(vocabulary)):
        raise ValueError("Evaluation lacks registered method, seed or immutable current runtime bindings")
    if bindings.fit_role == "source_training":
        if (not bindings.source_training_dataset_ids
                or len(set(bindings.source_training_dataset_ids)) != len(bindings.source_training_dataset_ids)
                or bindings.target_id in bindings.source_training_dataset_ids
                or bindings.source_validation_dataset_id in bindings.source_training_dataset_ids
                or bindings.source_validation_dataset_id == bindings.target_id):
            raise ValueError("LDO evaluation detected target/source-validation exposure in fitting")
        expected = {"target_test": bindings.target_id, "source_validation": bindings.source_validation_dataset_id}
    elif bindings.fit_role == "target_local_training":
        if bindings.source_training_dataset_ids != (bindings.target_id,):
            raise ValueError("In-domain evaluation must retain its isolated target-local training corpus")
        expected = {"target_local_test": bindings.target_id, "target_local_validation": bindings.target_id}
    else:
        raise ValueError("Evaluation cannot substitute an undeclared adaptation/fitting regime")
    if expected.get(bindings.evaluation_role) != bindings.evaluation_dataset_id:
        raise ValueError("Evaluation dataset differs from its frozen fold role")


def _frozen_probe(probe: Any, bindings: EvaluationBindings) -> None:
    encoder = getattr(probe, "encoder", None)
    head = getattr(probe, "head", None)
    if (encoder is None or head is None or getattr(encoder, "method_id", None) != bindings.method_id
            or getattr(probe, "training", True) or getattr(encoder, "training", True)
            or any(parameter.requires_grad for parameter in probe.parameters())):
        raise ValueError("Primary evaluation requires the frozen registered encoder and frozen affine probe")
    if not hasattr(head, "weight") or not hasattr(head, "bias"):
        raise ValueError("Primary evaluation requires a single affine classifier head")


def _softmax(logits: Any, classes: int) -> np.ndarray:
    values = logits.detach().cpu().numpy() if hasattr(logits, "detach") else np.asarray(logits)
    if values.ndim != 2 or values.shape[1] != classes or not np.isfinite(values).all():
        raise ValueError("Frozen probe emitted malformed or nonfinite canonical class logits")
    shifted = values.astype(np.float64) - values.max(axis=1, keepdims=True)
    probabilities = np.exp(shifted)
    return probabilities / probabilities.sum(axis=1, keepdims=True)


def _metadata_value(value: Any, key: str) -> Any:
    try:
        return value[key] if isinstance(value, dict) else getattr(value, key)
    except (KeyError, AttributeError) as error:
        raise ValueError("Prediction lacks its registered unit/parent metadata: " + key) from error


def evaluate_frozen_probe(
    probe: Any, batches: Iterable[dict[str, Any]], *, bindings: EvaluationBindings,
    label_vocabulary: Sequence[str], expected_segment_ids: Sequence[str],
    recording_fallback_datasets: Sequence[str] = (),
    on_batch: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Score only complete expected segments; never fit, calibrate or drop a row.

    batches contain the four VIEW_KEYS, canonical channel masks and a metadata
    list of dataset/subject/recording/segment IDs with canonical integer labels.
    FrozenLinearProbe owns the registered four-view representation and affine head.
    """
    _validate_bindings(bindings, label_vocabulary)
    _frozen_probe(probe, bindings)
    expected = tuple(expected_segment_ids)
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("Evaluation requires the unique predeclared complete segment inventory")
    records = []
    for batch in batches:
        if on_batch is not None:
            on_batch()
        if any(key not in batch for key in (*VIEW_KEYS, "a_mask", "b_mask", "metadata")):
            raise ValueError("Primary inference requires all four crossed views with masks and parent identity")
        metadata = batch["metadata"]
        probabilities = _softmax(probe(batch), len(label_vocabulary))
        if on_batch is not None:
            on_batch()
        if len(metadata) != len(probabilities):
            raise ValueError("Probe batch outcomes do not cover every metadata/parent identity")
        for item, values in zip(metadata, probabilities):
            dataset = _metadata_value(item, "dataset_id")
            if dataset != bindings.evaluation_dataset_id:
                raise ValueError("Prediction batch exposes an undeclared evaluation dataset")
            records.append(SegmentPrediction(dataset, _metadata_value(item, "subject_id"),
                                              _metadata_value(item, "recording_id"), _metadata_value(item, "segment_id"),
                                              _metadata_value(item, "label"), tuple(map(float, values))))
    if len(records) != len(expected) or {row.segment_id for row in records} != set(expected):
        raise ValueError("Evaluation is incomplete or includes foreign/duplicate segments; no intersection dropping is allowed")
    units = aggregate_predictions(records, label_vocabulary, recording_fallback_datasets=recording_fallback_datasets)
    metrics = classification_metrics(units, label_vocabulary)
    score_bindings = {key: value for key, value in asdict(bindings).items()
                      if key in {*HASH_BINDINGS, "protocol_id", "evaluation_role", "evaluation_dataset_id", "fit_role"}}
    score = ScoreRecord(bindings.target_id, bindings.method_id, bindings.seed, metrics["macro_f1"],
                        tuple(row.unit_id for row in units), tuple(sorted(expected)), score_bindings)
    return {"bindings": asdict(bindings), "metrics": metrics, "score_record": score,
            "segment_predictions": tuple(records), "unit_predictions": units,
            "calibration_applied": False, "fitting_performed": False}


def evaluate_paired_condition(
    clean_results: dict[str, Any], perturbed_results: dict[str, Any], *,
    predeclared_pair_ids: Sequence[str], eligibility_sha256: str,
) -> dict[str, Any]:
    """C3 comparison preserves every declared clean/perturbed parent, not an overlap."""
    expected = tuple(sorted(predeclared_pair_ids))
    if (not expected or len(set(expected)) != len(expected)
            or not re.fullmatch(r"[a-f0-9]{64}", eligibility_sha256)):
        raise ValueError("C3 requires its source-bound predeclared evaluable pair inventory")
    for result in (clean_results, perturbed_results):
        record = result["score_record"]
        if tuple(sorted(record.segment_ids)) != expected:
            raise ValueError("C3 clean and perturbed scores do not cover the exact declared paired subset")
    clean, perturbed = clean_results["score_record"], perturbed_results["score_record"]
    if (_identity_for_pair(clean) != _identity_for_pair(perturbed)
            or tuple(sorted(clean.unit_ids)) != tuple(sorted(perturbed.unit_ids))):
        raise ValueError("C3 scoring changed method, seed, checkpoint, eligible units or fold identity")
    return {"clean": clean, "perturbed": perturbed, "pair_ids": expected,
            "eligibility_sha256": eligibility_sha256}


def _identity_for_pair(record: ScoreRecord) -> tuple:
    return record.target_id, record.method_id, record.seed, tuple(sorted(record.bindings.items()))


def temperature_sensitivity(
    units: Sequence[UnitPrediction], label_vocabulary: Sequence[str], *, temperature: float,
    fitted_dataset_id: str, source_validation_dataset_id: str, target_id: str,
    fit_unit_ids: Sequence[str], fitted_artifact_sha256: str,
) -> dict[str, Any]:
    """Optional secondary calibration only; primary probabilities remain untouched.

    Caller supplies a real temperature fitted exclusively on source validation,
    its unit inventory and immutable artifact identity. This function never fits.
    """
    if (isinstance(temperature, bool) or not np.isfinite(temperature) or temperature <= 0
            or fitted_dataset_id != source_validation_dataset_id or fitted_dataset_id == target_id
            or not fitted_dataset_id or not fit_unit_ids or len(set(fit_unit_ids)) != len(fit_unit_ids)
            or not re.fullmatch(r"[a-f0-9]{64}", fitted_artifact_sha256)
            or any(unit.dataset_id != target_id for unit in units)):
        raise ValueError("Secondary temperature scaling lacks source-validation-only fitted provenance")
    calibrated = []
    for unit in units:
        values = np.asarray(unit.probabilities, dtype=np.float64)
        powered = values ** (1.0 / temperature)
        if not np.isfinite(powered).all() or powered.sum() <= 0:
            raise ValueError("Secondary temperature transformation cannot impute invalid probabilities")
        calibrated.append(UnitPrediction(unit.dataset_id, unit.unit_id, unit.analysis_unit, unit.label,
                                         tuple(map(float, powered / powered.sum())), unit.recording_ids, unit.segment_ids))
    metrics = classification_metrics(calibrated, label_vocabulary)
    metrics["uncalibrated"] = False
    return {"scope": "secondary_source_validation_temperature_sensitivity", "temperature": temperature,
            "fit_dataset_id": fitted_dataset_id, "fit_unit_ids": list(fit_unit_ids),
            "fitted_artifact_sha256": fitted_artifact_sha256, "metrics": metrics,
            "primary_predictions_modified": False}
