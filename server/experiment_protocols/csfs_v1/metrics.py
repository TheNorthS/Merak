"""CSFS-v1 probability aggregation and registered classification metrics.

Segments are not independent observations: recording probabilities are averaged
first, then each subject gives every recording equal weight. No missing label,
unit or probability is imputed and no class disappears from macro-F1.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True)
class SegmentPrediction:
    dataset_id: str
    subject_id: str | None
    recording_id: str
    segment_id: str
    label: int
    probabilities: tuple[float, ...]


@dataclass(frozen=True)
class UnitPrediction:
    dataset_id: str
    unit_id: str
    analysis_unit: str
    label: int
    probabilities: tuple[float, ...]
    recording_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]


def _vocabulary(labels: Sequence[str]) -> tuple[str, ...]:
    result = tuple(labels)
    if (len(result) < 2 or len(set(result)) != len(result)
            or any(not isinstance(label, str) or not label.strip() for label in result)):
        raise ValueError("CSFS-v1 requires one stable, nonempty classification vocabulary")
    return result


def _probabilities(values: Sequence[float], classes: int) -> tuple[float, ...]:
    if len(values) != classes or any(isinstance(value, bool) for value in values):
        raise ValueError("Every prediction must retain the complete canonical label vocabulary")
    result = tuple(float(value) for value in values)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in result) or not math.isclose(sum(result), 1.0, abs_tol=1e-6):
        raise ValueError("CSFS-v1 refuses nonfinite, invalid or unnormalized probabilities")
    return result


def _mean_probability(rows: Sequence[SegmentPrediction | UnitPrediction], classes: int) -> tuple[float, ...]:
    return tuple(mean(row.probabilities[index] for row in rows) for index in range(classes))


def aggregate_predictions(
    records: Iterable[SegmentPrediction], label_vocabulary: Sequence[str], *,
    recording_fallback_datasets: Iterable[str] = (),
) -> tuple[UnitPrediction, ...]:
    """Use recording fallback only for a dataset's predeclared no-subject exception."""
    classes, fallback = len(_vocabulary(label_vocabulary)), set(recording_fallback_datasets)
    groups: dict[tuple[str, str], list[SegmentPrediction]] = {}
    observed = set()
    for row in records:
        if any(not isinstance(value, str) or not value.strip() for value in (row.dataset_id, row.recording_id, row.segment_id)):
            raise ValueError("CSFS-v1 requires stable dataset, recording and segment identities")
        key = (row.dataset_id, row.segment_id)
        if key in observed or isinstance(row.label, bool) or not isinstance(row.label, int) or not 0 <= row.label < classes:
            raise ValueError("CSFS-v1 refuses duplicate segments or noncanonical class labels")
        if row.dataset_id in fallback:
            if row.subject_id is not None:
                raise ValueError("A recording-only exception cannot silently discard known subject identities")
        elif not isinstance(row.subject_id, str) or not row.subject_id.strip():
            raise ValueError("Subject-level evaluation requires its registered subject identity")
        _probabilities(row.probabilities, classes)
        observed.add(key)
        groups.setdefault((row.dataset_id, row.recording_id), []).append(row)
    if not groups:
        raise ValueError("CSFS-v1 evaluation has no observed predictions")
    units: dict[tuple[str, str], list[UnitPrediction]] = {}
    for (dataset, recording), rows in groups.items():
        if len({(row.label, row.subject_id) for row in rows}) != 1:
            raise ValueError("Recording segments disagree on their subject or endpoint label")
        label, subject = rows[0].label, rows[0].subject_id
        identity = recording if dataset in fallback else str(subject)
        record = UnitPrediction(dataset, identity, "recording" if dataset in fallback else "subject", label,
                                _mean_probability(rows, classes), (recording,), tuple(sorted(row.segment_id for row in rows)))
        units.setdefault((dataset, identity), []).append(record)
    result = []
    for (dataset, identity), records in sorted(units.items()):
        if len({row.label for row in records}) != 1:
            raise ValueError("A subject's recordings disagree on the registered endpoint label")
        result.append(UnitPrediction(dataset, identity, records[0].analysis_unit, records[0].label,
                                     _mean_probability(records, classes), tuple(sorted(recording for row in records for recording in row.recording_ids)),
                                     tuple(sorted(segment for row in records for segment in row.segment_ids))))
    return tuple(result)


def classification_metrics(units: Sequence[UnitPrediction], label_vocabulary: Sequence[str]) -> dict:
    """Macro-F1, uncalibrated NLL/Brier and ten-bin ECE at the actual analysis unit."""
    labels = _vocabulary(label_vocabulary)
    classes = len(labels)
    if not units or len({row.dataset_id for row in units}) != 1 or len({row.unit_id for row in units}) != len(units):
        raise ValueError("Classification metrics require unique units from exactly one target dataset")
    predictions, probabilities = [], []
    for row in units:
        if isinstance(row.label, bool) or not isinstance(row.label, int) or not 0 <= row.label < classes:
            raise ValueError("Classification unit has a noncanonical label")
        values = _probabilities(row.probabilities, classes)
        probabilities.append(values)
        predictions.append(max(range(classes), key=lambda index: values[index]))
    scores = []
    for label in range(classes):
        tp = sum(row.label == label and predicted == label for row, predicted in zip(units, predictions))
        fp = sum(row.label != label and predicted == label for row, predicted in zip(units, predictions))
        fn = sum(row.label == label and predicted != label for row, predicted in zip(units, predictions))
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    nll = mean(-math.log(values[row.label]) if values[row.label] > 0 else math.inf
               for row, values in zip(units, probabilities))
    brier = mean(sum((value - float(index == row.label)) ** 2 for index, value in enumerate(values))
                 for row, values in zip(units, probabilities))
    bins: dict[int, list[tuple[float, bool]]] = {index: [] for index in range(10)}
    for row, predicted, values in zip(units, predictions, probabilities):
        confidence = values[predicted]
        bins[min(9, int(confidence * 10))].append((confidence, predicted == row.label))
    ece = sum(len(values) / len(units) * abs(mean(confidence for confidence, _ in values)
              - mean(correct for _, correct in values)) for values in bins.values() if values)
    return {"macro_f1": mean(scores), "class_f1": dict(zip(labels, scores)), "nll": nll,
            "brier": brier, "ece": ece, "ece_bins": 10, "uncalibrated": True,
            "unit_count": len(units), "unit_ids": [row.unit_id for row in units],
            "analysis_units": sorted({row.analysis_unit for row in units}), "label_vocabulary": list(labels)}
