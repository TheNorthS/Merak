"""Complete-pair CSFS-v1 dataset-level inference; seeds are not datasets.

Only fixed, successful target/seed/method outcomes are aggregated. Missing or
failed outcomes remain incomplete, never intersected away or replaced. Statistics
are pure and persist neither scores nor fabricated execution records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from statistics import mean
from typing import Any, Iterable, Sequence

import numpy as np

from .protocol import (BOOTSTRAP_RESAMPLES, EQUIVALENCE_MARGIN, HOLM_ALPHA, IN_DOMAIN_MARGIN,
                       METHOD_IDS, PROTOCOL_ID, SEEDS, SIGNFLIP_RESAMPLES)


@dataclass(frozen=True)
class ScoreRecord:
    target_id: str
    method_id: str
    seed: int
    score: float
    unit_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]
    bindings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureRecord:
    target_id: str
    method_id: str
    seed: int
    reason: str
    artifact_sha256: str


@dataclass(frozen=True)
class AnchorChoice:
    target_id: str
    seed: int
    method_id: str
    source_validation_scores: dict[str, float]
    source_validation_dataset_id: str
    selected_before_target_scoring: bool
    selection_sha256: str


@dataclass(frozen=True)
class EligibilityRecord:
    target_id: str
    seed: int
    condition: str
    clean_segment_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    available_channels: tuple[tuple[str, int], ...]
    ineligible_segments: tuple[tuple[str, str], ...]
    corpus_manifest_sha256: str
    declared_before_scoring: bool
    all_clean_segment_ids: tuple[str, ...] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True).encode()).hexdigest()


HASH_BINDINGS = ("checkpoint_sha256", "probe_sha256", "config_sha256", "source_sha256",
                 "manifest_sha256", "split_sha256", "normalization_sha256", "label_vocabulary_sha256")


def _identity(record: ScoreRecord | FailureRecord) -> tuple[str, str, int]:
    return record.target_id, record.method_id, record.seed


def _valid_record(row: ScoreRecord) -> None:
    if (isinstance(row.score, bool) or not math.isfinite(row.score) or not 0 <= row.score <= 1
            or not row.unit_ids or not row.segment_ids or len(set(row.unit_ids)) != len(row.unit_ids)
            or len(set(row.segment_ids)) != len(row.segment_ids)
            or any(not isinstance(value, str) or not value for value in (*row.unit_ids, *row.segment_ids))):
        raise ValueError("CSFS-v1 requires finite macro-F1 and unique complete analysis identities")
    if (row.bindings.get("protocol_id") != PROTOCOL_ID
            or row.bindings.get("evaluation_dataset_id") != row.target_id
            or row.bindings.get("evaluation_role") not in {"target_test", "target_local_test"}
            or row.bindings.get("fit_role") != ("source_training" if row.bindings.get("evaluation_role") == "target_test"
                                                  else "target_local_training")
            or type(row.seed) is not int
            or any(not re.fullmatch(r"[a-f0-9]{64}", str(row.bindings.get(key) or "")) for key in HASH_BINDINGS)):
        raise ValueError("CSFS-v1 score lacks immutable runtime/config/source/data provenance")


def complete_score_matrix(
    records: Sequence[ScoreRecord], expected_targets: Sequence[str], *,
    methods: Sequence[str] = METHOD_IDS, failure_records: Sequence[FailureRecord] = (),
    evaluation_role: str = "target_test",
) -> dict[str, Any]:
    """No intersection drop: exact method/target/seed grid and paired identities."""
    targets = tuple(expected_targets)
    if len(targets) < 3 or len(set(targets)) != len(targets) or any(not target for target in targets):
        raise ValueError("CSFS-v1 requires at least three unique registered eligible targets")
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("CSFS-v1 requires unique predeclared method conditions")
    expected = {(target, method, seed) for target in targets for method in methods for seed in SEEDS}
    return _score_matrix(records, targets, expected, failure_records, evaluation_role)


def _score_matrix(records: Sequence[ScoreRecord], targets: Sequence[str], expected: set,
                  failure_records: Sequence[FailureRecord], evaluation_role: str = "target_test") -> dict[str, Any]:
    indexed = {}
    for row in records:
        key = _identity(row)
        if key not in expected or key in indexed:
            raise ValueError("CSFS-v1 refuses foreign or duplicate target/method/seed outcomes")
        _valid_record(row)
        if row.bindings["evaluation_role"] != evaluation_role:
            raise ValueError("CSFS-v1 cannot substitute validation or in-domain outcomes for the registered LDO role")
        indexed[key] = row
    failures = {}
    for row in failure_records:
        if (_identity(row) not in expected or not row.reason
                or not re.fullmatch(r"[a-f0-9]{64}", row.artifact_sha256)):
            raise ValueError("A failed run must retain its registered identity and immutable reason record")
        failures.setdefault(_identity(row), []).append(row)
    missing = sorted(expected - set(indexed))
    if missing:
        return {"complete": False, "missing": missing,
                "missing_without_failure_record": [key for key in missing if key not in failures],
                "failure_records": [row.__dict__ for row in failure_records], "indexed": indexed}
    for target in targets:
        rows = [row for key, row in indexed.items() if key[0] == target]
        identities = {(tuple(sorted(row.unit_ids)), tuple(sorted(row.segment_ids)),
                       row.bindings["split_sha256"], row.bindings["manifest_sha256"],
                       row.bindings["label_vocabulary_sha256"]) for row in rows}
        if len(identities) != 1:
            raise ValueError("CSFS-v1 paired comparisons do not use exactly the same eligible units and split")
    return {"complete": True, "targets": targets, "indexed": indexed,
            "failure_records": [row.__dict__ for row in failure_records], "missing": []}


def _resampling_seed(identity: str, targets: Sequence[str], deltas: Sequence[float]) -> int:
    text = json.dumps({"protocol": PROTOCOL_ID, "comparison": identity, "targets": list(targets),
                       "deltas": list(deltas)}, sort_keys=True)
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def paired_target_statistics(deltas: Sequence[float], targets: Sequence[str], identity: str) -> dict[str, Any]:
    """10,000 paired target bootstraps; exact one-sided sign flips through D=20."""
    values = np.asarray(deltas, dtype=np.float64)
    if len(values) != len(targets) or len(values) < 3 or not np.isfinite(values).all():
        raise ValueError("Paired inference requires all finite registered target deltas")
    seed = _resampling_seed(identity, targets, deltas)
    rng, flip_rng = np.random.default_rng(seed), np.random.default_rng(seed ^ 0x43534653)
    boot = np.concatenate([values[rng.integers(0, len(values), size=(min(512, BOOTSTRAP_RESAMPLES - start), len(values)))].mean(axis=1)
                           for start in range(0, BOOTSTRAP_RESAMPLES, 512)])
    lower, upper = np.percentile(boot, [2.5, 97.5])
    observed, extreme = float(values.sum()), 0
    exact = len(values) <= 20
    count = 2 ** len(values) if exact else SIGNFLIP_RESAMPLES
    for start in range(0, count, 2048):
        size = min(2048, count - start)
        if exact:
            signs = 1 - 2 * ((np.arange(start, start + size, dtype=np.uint64)[:, None]
                             >> np.arange(len(values), dtype=np.uint64)) & 1).astype(np.int8)
        else:
            signs = 1 - 2 * flip_rng.integers(0, 2, size=(size, len(values)), dtype=np.int8)
        extreme += int(np.count_nonzero(signs @ values >= observed - 1e-12))
    p_value = extreme / count if exact else (extreme + 1) / (count + 1)
    return {"effect": float(values.mean()), "ci_low": float(lower), "ci_high": float(upper),
            "target_deltas": list(map(float, values)), "target_ids": list(targets), "independent_axis": "target_dataset",
            "seed_aggregation": "five_seed_mean_within_target_first", "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_interval": "percentile_2.5_97.5", "p_value": p_value,
            "test": "one_sided_paired_sign_flip", "sign_flip_count": count, "exact": exact, "resampling_seed": seed}


def _comparison(matrix: dict, reference: str, candidate: str = "csfs") -> dict:
    indexed, targets = matrix["indexed"], matrix["targets"]
    deltas = [mean(indexed[target, candidate, seed].score - indexed[target, reference, seed].score for seed in SEEDS)
              for target in targets]
    return paired_target_statistics(deltas, targets, candidate + "-minus-" + reference)


def holm_adjust(p_values: Sequence[float]) -> tuple[float, ...]:
    if not p_values or any(not math.isfinite(value) or not 0 <= value <= 1 for value in p_values):
        raise ValueError("Holm correction requires valid complete p-values")
    adjusted, running = [0.0] * len(p_values), 0.0
    for rank, index in enumerate(sorted(range(len(p_values)), key=lambda item: p_values[item])):
        running = max(running, min(1.0, p_values[index] * (len(p_values) - rank)))
        adjusted[index] = running
    return tuple(adjusted)


def c1_c2_decisions(matrix: dict[str, Any]) -> dict[str, Any]:
    if not matrix.get("complete"):
        return {"C1": {"status": "incomplete"}, "C2": {"status": "incomplete"}}
    c1 = {method: _comparison(matrix, method) for method in ("bendr_context", "masked_latent")}
    adjusted = holm_adjust([row["p_value"] for row in c1.values()])
    for row, p_value in zip(c1.values(), adjusted):
        row["holm_adjusted_p"] = p_value
    c1_supported = all(row["ci_low"] > 0 and row["holm_adjusted_p"] < HOLM_ALPHA for row in c1.values())
    c2 = {method: _comparison(matrix, method) for method in ("full_latent", "no_private", "shuffled_pair")}
    equivalent = [method for method, row in c2.items() if row["ci_high"] < EQUIVALENCE_MARGIN]
    c2_supported = not equivalent and all(c2[method]["ci_low"] > 0 for method in ("full_latent", "no_private"))
    return {"C1": {"status": "supported" if c1_supported else "not_supported", "familywise_alpha": HOLM_ALPHA,
                   "comparisons": c1, "family": ["bendr_context", "masked_latent"]},
            "C2": {"status": "supported" if c2_supported else "not_supported", "equivalence_margin": EQUIVALENCE_MARGIN,
                   "equivalent_controls": equivalent, "comparisons": c2, "scope": "secondary_exploratory"}}


def validate_anchor_choices(choices: Sequence[AnchorChoice], targets: Sequence[str]) -> dict[tuple[str, int], AnchorChoice]:
    expected = {(target, seed) for target in targets for seed in SEEDS}
    result = {}
    for choice in choices:
        key = choice.target_id, choice.seed
        scores = choice.source_validation_scores
        if (key not in expected or key in result or set(scores) != {"bendr_context", "masked_latent"}
                or choice.selected_before_target_scoring is not True or choice.source_validation_dataset_id == choice.target_id
                or choice.source_validation_dataset_id not in targets or not re.fullmatch(r"[a-f0-9]{64}", choice.selection_sha256)
                or any(not math.isfinite(value) or not 0 <= value <= 1 for value in scores.values())):
            raise ValueError("C3 anchor selection lacks complete source-validation-only pre-scoring provenance")
        selected = max(("bendr_context", "masked_latent"), key=lambda method: scores[method])
        if choice.method_id != selected:
            raise ValueError("C3 anchor was not fixed by its registered source-validation score")
        result[key] = choice
    if set(result) != expected:
        raise ValueError("C3 anchor inventory is incomplete")
    return result


def _c3_comparison(matrix: dict, choices: dict[tuple[str, int], AnchorChoice], identity: str) -> dict:
    indexed, targets = matrix["indexed"], matrix["targets"]
    deltas = [mean(indexed[target, "csfs", seed].score - indexed[target, choices[target, seed].method_id, seed].score
                   for seed in SEEDS) for target in targets]
    return paired_target_statistics(deltas, targets, "C3-" + identity)


def _c3_matrix(records: Sequence[ScoreRecord], targets: Sequence[str], choices: dict,
               failures: Sequence[FailureRecord]) -> dict[str, Any]:
    expected = {(target, method, seed) for target in targets for seed in SEEDS
                for method in ("csfs", choices[target, seed].method_id)}
    return _score_matrix(records, targets, expected, failures)


def _eligibility_inventory(records: Sequence[EligibilityRecord], targets: Sequence[str], conditions: set[str]) -> dict:
    expected = {(target, seed, condition) for target in targets for seed in SEEDS for condition in conditions}
    result = {}
    for record in records:
        key = record.target_id, record.seed, record.condition
        channels = dict(record.available_channels)
        excluded = dict(record.ineligible_segments)
        minimum = 16 if record.condition.startswith("random_") else 8
        region_ineligible = record.condition == "region_deletion" and not record.clean_segment_ids and bool(excluded)
        if (key not in expected or key in result or record.declared_before_scoring is not True
                or (not region_ineligible and (not record.clean_segment_ids or not record.unit_ids))
                or len(set(record.clean_segment_ids)) != len(record.clean_segment_ids)
                or len(set(record.unit_ids)) != len(record.unit_ids)
                or set(channels) != set(record.clean_segment_ids) or len(channels) != len(record.available_channels)
                or any(type(value) is not int or not minimum <= value <= 19 for value in channels.values())
                or len(excluded) != len(record.ineligible_segments) or set(excluded) & set(channels)
                or not record.all_clean_segment_ids
                or len(set(record.all_clean_segment_ids)) != len(record.all_clean_segment_ids)
                or set(channels) | set(excluded) != set(record.all_clean_segment_ids)
                or any(not reason for reason in excluded.values())
                or not re.fullmatch(r"[a-f0-9]{64}", record.corpus_manifest_sha256)):
            raise ValueError("C3 lacks a complete pre-scoring eligibility and ineligible-record ledger")
        result[key] = record
    if set(result) != expected:
        raise ValueError("C3 eligibility inventory does not cover every target/seed/condition")
    return result


def _validate_condition_pairs(matrix: dict, clean: dict, condition: str, inventory: dict) -> None:
    for key, row in matrix["indexed"].items():
        baseline = clean["indexed"][key]
        eligibility = inventory[row.target_id, row.seed, condition]
        expected = (tuple(sorted(eligibility.unit_ids)), tuple(sorted(eligibility.clean_segment_ids)))
        for observed in (row, baseline):
            actual = tuple(sorted(observed.unit_ids)), tuple(sorted(observed.segment_ids))
            if (actual != expected or observed.bindings["manifest_sha256"] != eligibility.corpus_manifest_sha256
                    or observed.bindings.get("eligibility_sha256") != eligibility.sha256):
                raise ValueError("C3 clean/perturbed predictions differ from the exact predeclared eligible inventory")


def _region_comparisons(condition_records: dict, clean_records: dict, inventory: dict, choices: dict) -> dict[str, Any]:
    eligible_keys = {(target, seed) for target, seed, condition in inventory
                     if condition == "region_deletion" and inventory[target, seed, condition].clean_segment_ids}
    expected = {(target, method, seed) for target, seed in eligible_keys
                for method in ("csfs", choices[target, seed].method_id)}
    if not expected:
        if condition_records.get("region_deletion") or clean_records.get("region_deletion"):
            raise ValueError("Region-ineligible targets cannot receive imputed region scores")
        return {"status": "ineligible", "paired_scores": []}
    outputs = []
    indexed_groups = []
    for groups in (condition_records, clean_records):
        rows = groups.get("region_deletion") or []
        indexed = {}
        for row in rows:
            key = _identity(row)
            _valid_record(row)
            if key not in expected or key in indexed:
                raise ValueError("Region scores contain foreign, duplicate or unregistered eligible outcomes")
            indexed[key] = row
        if set(indexed) != expected:
            return {"status": "incomplete", "reason": "missing_predeclared_eligible_region_scores"}
        indexed_groups.append(indexed)
    _validate_condition_pairs({"indexed": indexed_groups[0]}, {"indexed": indexed_groups[1]}, "region_deletion", inventory)
    for target, seed in sorted(eligible_keys):
        anchor = choices[target, seed].method_id
        output = {"target_id": target, "seed": seed, "fixed_anchor": anchor}
        for label, indexed in zip(("perturbed_effect", "clean_effect"), indexed_groups):
            output[label] = indexed[target, "csfs", seed].score - indexed[target, anchor, seed].score
        outputs.append(output)
    return {"status": "reported", "paired_scores": outputs, "scope": "eligible_region_secondary_not_primary_estimand"}


def c3_decision(
    expected_targets: Sequence[str], condition_records: dict[str, Sequence[ScoreRecord]],
    anchor_choices: Sequence[AnchorChoice], in_domain_records: Sequence[ScoreRecord], *,
    clean_subset_records: dict[str, Sequence[ScoreRecord]],
    eligibility_records: Sequence[EligibilityRecord],
    failure_records: Sequence[FailureRecord] = (),
) -> dict[str, Any]:
    """Only exact eligible paired units and pre-scoring anchors enter C3 effects."""
    expected_conditions = {"random_deletion_25", "random_deletion_50", "bandstop_8_13", "bandpass_1_8"}
    allowed_conditions = expected_conditions | {"region_deletion"}
    if set(condition_records) - allowed_conditions or set(clean_subset_records) - allowed_conditions:
        raise ValueError("C3 cannot add unregistered perturbation conditions after scoring")
    if not expected_conditions <= set(condition_records) or not expected_conditions <= set(clean_subset_records):
        return {"status": "incomplete", "reason": "missing_registered_perturbation_or_clean_subset"}
    choices = validate_anchor_choices(anchor_choices, expected_targets)
    inventory = _eligibility_inventory(eligibility_records, expected_targets, expected_conditions | {"region_deletion"})
    region = _region_comparisons(condition_records, clean_subset_records, inventory, choices)
    if region["status"] == "incomplete":
        return {"status": "incomplete", "reason": region["reason"]}
    comparisons = {}
    for condition in sorted(expected_conditions):
        matrix = _c3_matrix(condition_records[condition], expected_targets, choices, failure_records)
        clean = _c3_matrix(clean_subset_records[condition], expected_targets, choices, failure_records)
        if not matrix["complete"] or not clean["complete"]:
            return {"status": "incomplete", "condition": condition, "reason": "incomplete_paired_condition"}
        _validate_condition_pairs(matrix, clean, condition, inventory)
        comparisons[condition] = _c3_comparison(matrix, choices, condition)
        comparisons[condition]["paired_clean_effect"] = _c3_comparison(clean, choices, condition)["effect"]
    in_domain = complete_score_matrix(in_domain_records, expected_targets, methods=("csfs", "random_init"),
                                     failure_records=failure_records, evaluation_role="target_local_test")
    if not in_domain["complete"]:
        return {"status": "incomplete", "reason": "missing_in_domain_comparison"}
    margin = _comparison(in_domain, "random_init")
    random_pass = any(comparisons[key]["ci_low"] > 0 for key in ("random_deletion_25", "random_deletion_50"))
    spectral_pass = any(comparisons[key]["ci_low"] > 0 for key in ("bandstop_8_13", "bandpass_1_8"))
    supported = random_pass and spectral_pass and margin["ci_low"] >= -IN_DOMAIN_MARGIN
    return {"status": "supported" if supported else "not_supported", "comparisons": comparisons,
            "in_domain": margin, "in_domain_margin": IN_DOMAIN_MARGIN, "random_family_pass": random_pass,
            "spectral_family_pass": spectral_pass, "scope": "secondary_exploratory",
            "anchor_choices": [choice.__dict__ for choice in anchor_choices],
            "region_comparison": region,
            "region_eligibility": [{**row.__dict__, "sha256": row.sha256} for row in eligibility_records
                                   if row.condition == "region_deletion"],
            "eligibility_inventory": [{**row.__dict__, "sha256": row.sha256} for row in eligibility_records]}


def evaluate_claims(
    records: Sequence[ScoreRecord], expected_targets: Sequence[str], *,
    failure_records: Sequence[FailureRecord] = (),
    c3_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Complete nine-condition LDO family; C3 remains incomplete until supplied."""
    matrix = complete_score_matrix(records, expected_targets, failure_records=failure_records)
    result = c1_c2_decisions(matrix)
    summaries = {}
    if matrix["complete"]:
        for method in METHOD_IDS:
            by_target = {target: mean(matrix["indexed"][target, method, seed].score for seed in SEEDS) for target in expected_targets}
            summaries[method] = {"per_target_seed_mean": by_target, "target_macro_mean": mean(by_target.values())}
    c3 = c3_decision(expected_targets, **c3_inputs) if matrix["complete"] and c3_inputs is not None else {"status": "incomplete"}
    return {"protocol_id": PROTOCOL_ID, "complete": matrix["complete"], "missing": matrix["missing"],
            "failure_records": matrix["failure_records"], "seed_ids": list(SEEDS), "target_ids": list(expected_targets),
            "methods": list(METHOD_IDS), "summaries": summaries, "claims": {**result, "C3": c3}}
