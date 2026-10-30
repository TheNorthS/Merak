"""CSFS-v1 fixed signal transforms and source-training-only normalization.

Implementation conventions not specified by the registration are explicit:
polyphase rational resampling, linear detrending/filtering of each entire
recording before windowing, population standard deviation, and no padding of a
short final window. Missing channels remain zero storage with a false mask;
their values never enter fitted statistics or model inputs as observed data.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from typing import Any

import numpy as np
from scipy import signal

from .data_contract import (DataContractError, FoldSpec, InDomainFold, Recording, VerifiedCorpus,
                           load_recording, verify_current_corpus)
from .protocol import (CANONICAL_CHANNELS, SAMPLING_RATE_HZ as SAMPLE_RATE, WINDOW_SECONDS, STRIDE_SECONDS,
                       FILTER_ORDER, PREPROCESS_BAND)


def butterworth(values: np.ndarray, low: float, high: float, *, kind: str = "bandpass") -> np.ndarray:
    """Fourth-order SOS forward/backward filtering; no causal phase substitution."""
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] <= 30 or not np.isfinite(array).all():
        raise DataContractError("Filtering requires finite channel-by-time data with sufficient boundary samples")
    if kind not in {"bandpass", "bandstop"} or not 0 < low < high < SAMPLE_RATE / 2:
        raise DataContractError("Filtering requires a valid fixed pass/stop frequency interval")
    sos = signal.butter(FILTER_ORDER, (low, high), btype=kind, fs=SAMPLE_RATE, output="sos")
    filtered = signal.sosfiltfilt(sos, array, axis=-1)
    if not np.isfinite(filtered).all():
        raise DataContractError("Signal preprocessing produced non-finite samples")
    return filtered


def prepare_recording(corpus: VerifiedCorpus, record: Recording) -> tuple[np.ndarray, np.ndarray]:
    """Apply no fitted target transformation and preserve canonical channel positions."""
    raw = load_recording(corpus, record)
    ratio = Fraction(SAMPLE_RATE) / Fraction(str(record.sample_rate))
    if ratio.numerator > 100_000 or ratio.denominator > 100_000:
        raise DataContractError("Manifest sample rate has an unsupported exact polyphase ratio")
    resampled = signal.resample_poly(raw, ratio.numerator, ratio.denominator, axis=-1)
    filtered = butterworth(signal.detrend(resampled, axis=-1, type="linear"), *PREPROCESS_BAND)
    canonical = np.zeros((len(CANONICAL_CHANNELS), filtered.shape[1]), dtype=np.float64)
    mask = np.zeros(len(CANONICAL_CHANNELS), dtype=bool)
    for index, name in enumerate(record.canonical_channels):
        if name:
            slot = CANONICAL_CHANNELS.index(name)
            canonical[slot], mask[slot] = filtered[index], True
    if int(mask.sum()) < 8:
        raise DataContractError("CSFS-v1 clean recordings require at least eight canonical channels")
    return canonical, mask


@dataclass(frozen=True)
class SourceNormalizer:
    means: tuple[float, ...]
    standard_deviations: tuple[float, ...]
    counts: tuple[int, ...]
    source_recordings: tuple[tuple[str, str], ...]
    corpus_sha256: str
    fold_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema": 1, "protocol": "CSFS-v1", "fit_partition": "source_training_only",
                "means": list(self.means), "standard_deviations": list(self.standard_deviations),
                "counts": list(self.counts), "source_recordings": dict(self.source_recordings),
                "corpus_sha256": self.corpus_sha256, "fold_sha256": self.fold_sha256,
                "variance_convention": "population_ddof_0", "window_overlap_not_recounted": True}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


def _validate_fold(corpus: VerifiedCorpus, fold: FoldSpec | InDomainFold, *, verify_files: bool = True) -> None:
    if verify_files:
        verify_current_corpus(corpus)
    if isinstance(fold, InDomainFold):
        _validate_in_domain(corpus, fold)
        return
    if (not isinstance(fold, FoldSpec) or fold.corpus_sha256 != corpus.sha256 or not fold.training
            or any(record not in corpus.recordings or record.dataset_id not in fold.source_ids for record in fold.training)
            or fold.target_id in fold.source_ids or fold.validation_id in fold.source_ids
            or set(fold.source_ids) | {fold.target_id, fold.validation_id} != set(corpus.datasets)
            or set(fold.training) != {record for record in corpus.recordings if record.dataset_id in fold.source_ids}
            or set(fold.validation) != {record for record in corpus.recordings if record.dataset_id == fold.validation_id}
            or set(fold.target) != {record for record in corpus.recordings if record.dataset_id == fold.target_id}):
        raise DataContractError("Fitted preprocessing requires the exact frozen disjoint source-training partition")


def _validate_in_domain(corpus: VerifiedCorpus, fold: InDomainFold) -> None:
    expected = {record for record in corpus.recordings if record.dataset_id == fold.dataset_id}
    groups = [set(fold.training), set(fold.validation), set(fold.testing)]
    units = [{record.unit_id for record in group} for group in groups]
    if (fold.corpus_sha256 != corpus.sha256 or any(not group for group in groups)
            or set.union(*groups) != expected
            or any(record.within_dataset_split != "train" for record in fold.training)
            or any(record.within_dataset_split != "validation" for record in fold.validation)
            or any(record.within_dataset_split != "test" for record in fold.testing)
            or any(units[i] & units[j] for i, j in ((0, 1), (0, 2), (1, 2)))):
        raise DataContractError("In-domain normalization requires the exact declared isolated target-local training units")


def fit_source_normalizer(corpus: VerifiedCorpus, fold: FoldSpec | InDomainFold) -> SourceNormalizer:
    """Fit each channel once over source-training recordings, not overlapping windows."""
    _validate_fold(corpus, fold)
    counts = np.zeros(len(CANONICAL_CHANNELS), dtype=np.int64)
    means, m2 = np.zeros(len(CANONICAL_CHANNELS)), np.zeros(len(CANONICAL_CHANNELS))
    for record in sorted(fold.training, key=lambda item: item.recording_id):
        values, mask = prepare_recording(corpus, record)
        n = values.shape[1]
        local_mean = values[mask].mean(axis=1)
        local_m2 = np.sum((values[mask] - local_mean[:, None]) ** 2, axis=1)
        old, total = counts[mask].copy(), counts[mask] + n
        delta = local_mean - means[mask]
        m2[mask] += local_m2 + delta ** 2 * old * n / total
        means[mask] += delta * n / total
        counts[mask] = total
    deviation = np.zeros(len(CANONICAL_CHANNELS))
    present = counts > 0
    deviation[present] = np.sqrt(m2[present] / counts[present])
    if not np.isfinite(means).all() or not np.isfinite(deviation).all() or np.any(deviation[present] <= 0):
        raise DataContractError("A source-trained canonical channel has invalid or zero variance")
    verify_current_corpus(corpus)
    return SourceNormalizer(tuple(map(float, means)), tuple(map(float, deviation)), tuple(map(int, counts)),
                            tuple(sorted((record.recording_id, record.sha256) for record in fold.training)),
                            corpus.sha256, fold.sha256)


@dataclass(frozen=True)
class Segment:
    signal: np.ndarray
    channel_mask: np.ndarray
    dataset_id: str
    subject_id: str | None
    recording_id: str
    segment_id: str
    raw_id: str
    raw_sha256: str
    start_sample: int
    label: int
    normalization_sha256: str

    @property
    def unit_id(self) -> str:
        return self.subject_id if self.subject_id is not None else self.recording_id

    def metadata(self) -> dict[str, Any]:
        return {"dataset_id": self.dataset_id, "subject_id": self.subject_id,
                "recording_id": self.recording_id, "segment_id": self.segment_id,
                "raw_id": self.raw_id, "raw_sha256": self.raw_sha256, "start_sample": self.start_sample,
                "label": self.label, "normalization_sha256": self.normalization_sha256}


def segment_recording(corpus: VerifiedCorpus, fold: FoldSpec | InDomainFold, record: Recording,
                      normalizer: SourceNormalizer) -> tuple[Segment, ...]:
    """Transform any allowed split with the immutable source-only fitted state."""
    _validate_fold(corpus, fold, verify_files=False)
    expected = tuple(sorted((item.recording_id, item.sha256) for item in fold.training))
    if (normalizer.corpus_sha256 != corpus.sha256 or normalizer.fold_sha256 != fold.sha256
            or normalizer.source_recordings != expected or record not in corpus.recordings):
        raise DataContractError("Normalization is foreign, stale, or fitted outside this source-training fold")
    if isinstance(fold, InDomainFold) and record not in (*fold.training, *fold.validation, *fold.testing):
        raise DataContractError("In-domain preprocessing cannot read an LDO or foreign dataset input")
    values, mask = prepare_recording(corpus, record)
    means, deviation, counts = map(np.asarray, (normalizer.means, normalizer.standard_deviations, normalizer.counts))
    if any(array.shape != (len(CANONICAL_CHANNELS),) for array in (means, deviation, counts)):
        raise DataContractError("Normalization state lacks the complete canonical channel inventory")
    if np.any(counts[mask] <= 0) or np.any(deviation[mask] <= 0):
        raise DataContractError("A target channel has no source-trained normalization; target fitting is prohibited")
    if not np.isfinite(means).all() or not np.isfinite(deviation).all():
        raise DataContractError("Normalization contains non-finite fitted state")
    values[mask] = (values[mask] - means[mask, None]) / deviation[mask, None]
    samples, stride = SAMPLE_RATE * WINDOW_SECONDS, SAMPLE_RATE * STRIDE_SECONDS
    segments = []
    for start in range(0, values.shape[1] - samples + 1, stride):
        window = values[:, start:start + samples].astype(np.float32, copy=True)
        window_mask = mask.copy()
        window.setflags(write=False)
        window_mask.setflags(write=False)
        identity = hashlib.sha256(f"{record.raw_id}:{record.sha256}:{start}:{samples}".encode()).hexdigest()
        segments.append(Segment(window, window_mask, record.dataset_id, record.subject_id,
            record.recording_id, identity, record.raw_id, record.sha256, start, record.label, normalizer.sha256))
    if not segments:
        raise DataContractError("Recording has no complete registered thirty-second window")
    return tuple(segments)
