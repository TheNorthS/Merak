"""Paired, eligibility-explicit C3 channel and spectral interventions.

Integer deletion convention: floor the requested percentage of available
channels. A single identity-seeded permutation makes the 25% set a subset of
the 50% set. Largest eligible regions tie in registered region order. These
rounding/tie conventions are implementation choices, not measured results.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

import numpy as np

from .data import identity_seed, validate_segment
from .data_contract import DataContractError
from .preprocessing import Segment, butterworth
from .protocol import CANONICAL_CHANNELS, C3_MIN_CHANNELS, MIN_CHANNELS, REGIONS


@dataclass(frozen=True)
class PerturbedSegment:
    segment: Segment | None
    condition: str
    pair_id: str
    eligible: bool
    reason: str
    removed_channels: tuple[str, ...] = ()


def _channel_result(segment: Segment, condition: str, remove: np.ndarray) -> PerturbedSegment:
    mask = segment.channel_mask.copy()
    mask[remove] = False
    if mask.sum() < MIN_CHANNELS:
        return PerturbedSegment(None, condition, segment.segment_id, False, "deletion leaves fewer than eight channels")
    values = segment.signal.copy()
    values[~mask] = 0
    values.setflags(write=False)
    mask.setflags(write=False)
    changed = replace(segment, signal=values, channel_mask=mask)
    return PerturbedSegment(changed, condition, segment.segment_id, True, "eligible paired clean subset",
                            tuple(CANONICAL_CHANNELS[index] for index in sorted(remove)))


def random_deletion(segment: Segment, run_seed: int, percentage: int) -> PerturbedSegment:
    """Random-deletion clean and perturbed scores use exactly the >=16-channel subset."""
    validate_segment(segment)
    if percentage not in {25, 50} or type(percentage) is not int:
        raise DataContractError("C3 random deletion permits only registered 25% or 50%")
    available = np.flatnonzero(segment.channel_mask)
    condition = f"random_deletion_{percentage}"
    if len(available) < C3_MIN_CHANNELS:
        return PerturbedSegment(None, condition, segment.segment_id, False, "C3 random deletion requires sixteen clean channels")
    rng = np.random.default_rng(identity_seed(run_seed, segment.unit_id, "C3-random-deletion"))
    removed = rng.permutation(available)[:len(available) * percentage // 100]
    return _channel_result(segment, condition, removed)


def region_deletion(segment: Segment) -> PerturbedSegment:
    """Remove the largest present registered region only if eight channels survive."""
    validate_segment(segment)
    candidates = []
    for name, channels in REGIONS.items():
        remove = np.array([CANONICAL_CHANNELS.index(channel) for channel in channels
                           if segment.channel_mask[CANONICAL_CHANNELS.index(channel)]], dtype=int)
        if len(remove) and segment.channel_mask.sum() - len(remove) >= MIN_CHANNELS:
            candidates.append((name, remove))
    if not candidates:
        return PerturbedSegment(None, "region_deletion", segment.segment_id, False, "no present registered region leaves eight channels")
    name, remove = max(candidates, key=lambda item: len(item[1]))
    return _channel_result(segment, "region_deletion_" + name, remove)


def spectral_perturbation(segment: Segment, condition: str) -> PerturbedSegment:
    """Apply fixed fourth-order zero-phase shifts to all clean-eligible recordings."""
    validate_segment(segment)
    if condition not in {"bandstop_8_13", "bandpass_1_8"}:
        raise DataContractError("Unknown registered C3 spectral condition")
    kind, bands = ("bandstop", (8.0, 13.0)) if condition == "bandstop_8_13" else ("bandpass", (1.0, 8.0))
    values = np.zeros_like(segment.signal)
    values[segment.channel_mask] = butterworth(segment.signal[segment.channel_mask], *bands, kind=kind)
    values.setflags(write=False)
    return PerturbedSegment(replace(segment, signal=values), condition, segment.segment_id,
                            True, "all clean-eligible recordings")


def c3_evaluation_inventory(segments: Sequence[Segment], condition: str, run_seed: int) -> dict:
    """Return exact paired IDs and an exclusion ledger; never silently intersect scores."""
    if not segments or len({item.segment_id for item in segments}) != len(segments):
        raise DataContractError("C3 requires a nonempty unique locked clean inventory")
    outcomes = []
    for segment in segments:
        if condition in {"random_deletion_25", "random_deletion_50"}:
            outcome = random_deletion(segment, run_seed, int(condition.rsplit("_", 1)[1]))
        elif condition == "region_deletion":
            outcome = region_deletion(segment)
        else:
            outcome = spectral_perturbation(segment, condition)
        outcomes.append(outcome)
    eligible = [item for item in outcomes if item.eligible]
    return {"condition": condition, "clean_pair_ids": tuple(item.pair_id for item in eligible),
            "perturbed": tuple(item.segment for item in eligible),
            "ineligible": tuple({"segment_id": item.pair_id, "reason": item.reason} for item in outcomes if not item.eligible),
            "paired_recomputation_required": True}
