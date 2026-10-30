"""Four genuine paired CSFS composites and balanced source-corpus sampling.

This module performs deterministic local data transforms only. It has no model,
training loop, network loader or synthetic-data fallback. A parent segment has
one stable identity across its channel and frequency interventions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterator, Sequence

import numpy as np

from .data_contract import DataContractError, FoldSpec, InDomainFold, VerifiedCorpus, verify_current_corpus
from .preprocessing import Segment, SourceNormalizer, butterworth, _validate_fold, fit_source_normalizer, segment_recording
from .protocol import (CANONICAL_CHANNELS, WINDOW_SAMPLES, STRIDE_SAMPLES, VIEW_KEYS, LOW_BAND,
                       HIGH_BAND, MIN_CHANNELS, PRETRAIN_WINDOWS, SAMPLING_RATE_HZ, FINAL_PROBE_UPDATES, BATCH_SIZE)


def identity_seed(run_seed: int, identity: str, namespace: str = "csfs-v1") -> int:
    """Hash explicitly bound identities, never Python hash or input enumeration."""
    if type(run_seed) is not int or not isinstance(identity, str) or not identity:
        raise DataContractError("Deterministic view sampling needs a run seed and bound parent identity")
    return int.from_bytes(hashlib.sha256(json.dumps([namespace, run_seed, identity],
        separators=(",", ":")).encode()).digest()[:8], "big")


def validate_segment(segment: Segment) -> None:
    if (not isinstance(segment, Segment) or segment.signal.shape != (len(CANONICAL_CHANNELS), WINDOW_SAMPLES)
            or segment.channel_mask.shape != (len(CANONICAL_CHANNELS),) or segment.channel_mask.dtype != np.bool_
            or np.count_nonzero(segment.channel_mask) < MIN_CHANNELS
            or not np.isfinite(segment.signal).all() or np.any(segment.signal[~segment.channel_mask] != 0)
            or not segment.segment_id or not segment.raw_id or len(segment.raw_sha256) != 64
            or not segment.recording_id or not segment.normalization_sha256):
        raise DataContractError("Composite inputs need a complete finite source-bound canonical segment and mask")
    expected = hashlib.sha256(f"{segment.raw_id}:{segment.raw_sha256}:{segment.start_sample}:{WINDOW_SAMPLES}".encode()).hexdigest()
    if (type(segment.start_sample) is not int or segment.start_sample < 0 or segment.start_sample % STRIDE_SAMPLES
            or segment.segment_id != expected or type(segment.label) is not int or segment.label < 0):
        raise DataContractError("Segment identity, registered stride or canonical label is inconsistent")


def channel_subsets(segment: Segment, run_seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Exact floor-half subsets and ceil-half overlap with disjoint remainders."""
    validate_segment(segment)
    available = np.flatnonzero(segment.channel_mask)
    k, overlap = max(4, len(available) // 2), (max(4, len(available) // 2) + 1) // 2
    if 2 * k - overlap > len(available):
        raise DataContractError("Channel inventory cannot support the registered overlapping subsets")
    rng = np.random.default_rng(identity_seed(run_seed, segment.segment_id, "M1-channel-subsets"))
    ordered = rng.permutation(available)
    shared, remaining = ordered[:overlap], ordered[overlap:]
    a = np.zeros(len(CANONICAL_CHANNELS), dtype=bool)
    b = a.copy()
    a[np.concatenate((shared, remaining[:k - overlap]))] = True
    b[np.concatenate((shared, remaining[k - overlap:2 * (k - overlap)]))] = True
    return a, b


def four_composites(segment: Segment, run_seed: int) -> dict[str, Any]:
    """Apply both registered spectral filters to BOTH independently sampled subsets."""
    a, b = channel_subsets(segment, run_seed)
    low, high = butterworth(segment.signal[segment.channel_mask], *LOW_BAND), butterworth(segment.signal[segment.channel_mask], *HIGH_BAND)
    full_low, full_high = np.zeros_like(segment.signal), np.zeros_like(segment.signal)
    full_low[segment.channel_mask], full_high[segment.channel_mask] = low, high
    values = {}
    for side, mask in (("a", a), ("b", b)):
        for frequency, source in (("low", full_low), ("high", full_high)):
            data = np.zeros_like(segment.signal, dtype=np.float32)
            data[mask] = source[mask]
            values[f"{side}_{frequency}"] = data
    return {**values, "a_mask": a, "b_mask": b, "metadata": segment.metadata(),
            "composite_parent_ids": {key: segment.segment_id for key in VIEW_KEYS}}


def stack_composites(values: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not values:
        raise DataContractError("Cannot construct an empty CSFS batch")
    for value in values:
        if (any(np.asarray(value.get(key)).shape != (len(CANONICAL_CHANNELS), WINDOW_SAMPLES) for key in VIEW_KEYS)
                or any(np.asarray(value.get(key)).shape != (len(CANONICAL_CHANNELS),) for key in ("a_mask", "b_mask"))):
            raise DataContractError("CSFS batch has incomplete composites or canonical masks")
    return {**{key: np.stack([value[key] for value in values]) for key in (*VIEW_KEYS, "a_mask", "b_mask")},
            "metadata": [value["metadata"] for value in values],
            "composite_parent_ids": {key: [value["composite_parent_ids"][key] for value in values] for key in VIEW_KEYS}}


def make_batch(segments: Sequence[Segment], run_seed: int) -> dict[str, Any]:
    """Create CPU tensors; the model alone owns the shuffled-pair control permutation."""
    import torch

    batch = stack_composites([four_composites(segment, run_seed) for segment in segments])
    return {**batch, **{key: torch.from_numpy(batch[key].copy()) for key in (*VIEW_KEYS, "a_mask", "b_mask")},
            "labels": torch.tensor([item.label for item in segments], dtype=torch.long)}


@dataclass(frozen=True)
class PreparedFold:
    normalizer: SourceNormalizer
    training: tuple[Segment, ...]
    validation: tuple[Segment, ...]
    target: tuple[Segment, ...]


def prepare_fold(corpus: VerifiedCorpus, fold: FoldSpec) -> PreparedFold:
    """Fit exclusively on source train, then transform all three disjoint partitions."""
    normalizer = fit_source_normalizer(corpus, fold)
    groups = [tuple(segment for record in records for segment in segment_recording(corpus, fold, record, normalizer))
              for records in (fold.training, fold.validation, fold.target)]
    ids = [segment.segment_id for group in groups for segment in group]
    if len(set(ids)) != len(ids):
        raise DataContractError("Prepared parent segments leak across fold partitions")
    verify_current_corpus(corpus)
    return PreparedFold(normalizer, *groups)


@dataclass(frozen=True)
class PreparedInDomainFold:
    normalizer: SourceNormalizer
    training: tuple[Segment, ...]
    validation: tuple[Segment, ...]
    testing: tuple[Segment, ...]

    @property
    def target(self) -> tuple[Segment, ...]:
        return self.testing


def prepare_in_domain_fold(corpus: VerifiedCorpus, fold: InDomainFold) -> PreparedInDomainFold:
    """The secondary reference never borrows LDO fitted state or test labels/data."""
    normalizer = fit_source_normalizer(corpus, fold)
    groups = [tuple(segment for record in records for segment in segment_recording(corpus, fold, record, normalizer))
              for records in (fold.training, fold.validation, fold.testing)]
    verify_current_corpus(corpus)
    return PreparedInDomainFold(normalizer, *groups)


class BalancedSourceSampler:
    """Equal dataset → equal subject/declared recording unit → equal window draws."""

    def __init__(self, corpus: VerifiedCorpus, fold: FoldSpec | InDomainFold, segments: Sequence[Segment],
                 run_seed: int, window_budget: int = PRETRAIN_WINDOWS, *, sampling_role: str = "pretrain"):
        _validate_fold(corpus, fold)
        if sampling_role not in {"pretrain", "probe"}:
            raise DataContractError("Source sampling must declare its registered pretrain or probe role")
        maximum = PRETRAIN_WINDOWS if sampling_role == "pretrain" else FINAL_PROBE_UPDATES * BATCH_SIZE
        if type(window_budget) is not int or not 0 < window_budget <= maximum or type(run_seed) is not int:
            raise DataContractError("Source sampler requires a bounded registered window budget and integer seed")
        allowed = {record.recording_id: record for record in fold.training}
        source_ids = (fold.dataset_id,) if isinstance(fold, InDomainFold) else fold.source_ids
        self.groups: dict[str, dict[str, list[Segment]]] = {}
        seen = set()
        for segment in segments:
            validate_segment(segment)
            record = allowed.get(segment.recording_id)
            if (record is None or segment.dataset_id not in source_ids
                    or segment.raw_sha256 != record.sha256 or segment.raw_id != record.raw_id
                    or segment.subject_id != record.subject_id or segment.label != record.label
                    or segment.segment_id in seen):
                raise DataContractError("Source sampler refuses validation/target, duplicate or foreign parent inputs")
            seen.add(segment.segment_id)
            self.groups.setdefault(segment.dataset_id, {}).setdefault(segment.unit_id, []).append(segment)
        if set(self.groups) != set(source_ids):
            raise DataContractError("Source sampler cannot silently omit an eligible source dataset")
        if {segment.recording_id for segment in segments} != set(allowed):
            raise DataContractError("Source sampler must inventory every eligible source-training recording")
        for identity, record in allowed.items():
            samples = math.ceil(record.sample_count * SAMPLING_RATE_HZ / record.sample_rate)
            expected_starts = set(range(0, samples - WINDOW_SAMPLES + 1, STRIDE_SAMPLES))
            if {segment.start_sample for segment in segments if segment.recording_id == identity} != expected_starts:
                raise DataContractError("Source sampler must inventory every registered window without subtraction")
        if len({segment.normalization_sha256 for segment in segments}) != 1:
            raise DataContractError("Source sampler mixes foreign fitted normalization states")
        self.seed, self.window_budget, self.sampling_role = run_seed, window_budget, sampling_role

    def __iter__(self) -> Iterator[Segment]:
        rng = np.random.default_rng(self.seed)
        datasets = sorted(self.groups)
        for _ in range(self.window_budget):
            dataset = datasets[int(rng.integers(len(datasets)))]
            units = sorted(self.groups[dataset])
            unit = units[int(rng.integers(len(units)))]
            windows = sorted(self.groups[dataset][unit], key=lambda item: item.segment_id)
            yield windows[int(rng.integers(len(windows)))]
