"""Fixed toy records verify CSFS-v1 estimands; no research training or data runs."""

from __future__ import annotations

from dataclasses import replace
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from server.experiment_protocols.csfs_v1.metrics import SegmentPrediction, aggregate_predictions, classification_metrics
from server.experiment_protocols.csfs_v1.protocol import METHOD_IDS, PROTOCOL_ID, SEEDS, VIEW_KEYS
from server.experiment_protocols.csfs_v1.statistics import (
    AnchorChoice, EligibilityRecord, FailureRecord, HASH_BINDINGS, ScoreRecord,
    c3_decision, complete_score_matrix, evaluate_claims, holm_adjust, paired_target_statistics,
)
from server.experiment_protocols.csfs_v1.evaluation import (
    EvaluationBindings, evaluate_frozen_probe, evaluate_paired_condition, label_vocabulary_hash,
    temperature_sensitivity,
)


VOCAB = ("negative", "positive")


def test_segments_then_recordings_then_subjects_get_equal_recording_weight():
    rows = [SegmentPrediction("D", "S", "R1", f"a{i}", 1, (0.9, 0.1)) for i in range(9)]
    rows += [SegmentPrediction("D", "S", "R2", "b", 1, (0.1, 0.9))]
    before = copy.deepcopy(rows)
    units = aggregate_predictions(rows, VOCAB)
    assert len(units) == 1 and units[0].probabilities == pytest.approx((0.5, 0.5))
    assert units[0].recording_ids == ("R1", "R2") and len(units[0].segment_ids) == 10
    assert rows == before


def test_recording_fallback_only_when_explicitly_declared_and_subject_ids_absent():
    rows = [SegmentPrediction("D", None, "R", "segment", 1, (0.2, 0.8))]
    with pytest.raises(ValueError, match="Subject-level"):
        aggregate_predictions(rows, VOCAB)
    units = aggregate_predictions(rows, VOCAB, recording_fallback_datasets=("D",))
    assert units[0].analysis_unit == "recording" and units[0].unit_id == "R"
    with pytest.raises(ValueError, match="discard known"):
        aggregate_predictions([replace(rows[0], subject_id="S")], VOCAB, recording_fallback_datasets=("D",))


@pytest.mark.parametrize("defect", ["duplicate", "label", "probability", "vocabulary", "recording_label", "subject_label"])
def test_aggregation_rejects_identity_label_or_probability_drift(defect):
    rows = [SegmentPrediction("D", "S", "R1", "one", 0, (0.7, 0.3)),
            SegmentPrediction("D", "S", "R2", "two", 0, (0.6, 0.4))]
    vocabulary = VOCAB
    if defect == "duplicate": rows[1] = replace(rows[1], segment_id="one")
    elif defect == "label": rows[1] = replace(rows[1], label=2)
    elif defect == "probability": rows[1] = replace(rows[1], probabilities=(float("nan"), 0.4))
    elif defect == "vocabulary": vocabulary = ("same", "same")
    elif defect == "recording_label": rows[1] = replace(rows[1], recording_id="R1", label=1)
    else: rows[1] = replace(rows[1], label=1)
    with pytest.raises(ValueError): aggregate_predictions(rows, vocabulary)


def test_metric_vocabulary_stays_complete_and_calibration_is_unit_level_ten_bins():
    units = aggregate_predictions([SegmentPrediction("D", "S1", "R1", "one", 0, (0.8, 0.2)),
                                  SegmentPrediction("D", "S2", "R2", "two", 1, (0.1, 0.9))], VOCAB)
    metrics = classification_metrics(units, VOCAB)
    assert metrics["macro_f1"] == 1.0 and metrics["brier"] == pytest.approx(0.05)
    assert metrics["ece"] == pytest.approx(0.15) and metrics["ece_bins"] == 10
    assert metrics["nll"] == pytest.approx((-np.log(0.8) - np.log(0.9)) / 2)
    only_negative = classification_metrics(units[:1], VOCAB)
    assert only_negative["macro_f1"] == 0.5 and only_negative["class_f1"]["positive"] == 0


def _bindings(target, role="target_test", **extra):
    return {**{key: "a" * 64 for key in HASH_BINDINGS}, "protocol_id": PROTOCOL_ID,
            "evaluation_dataset_id": target, "evaluation_role": role,
            "fit_role": "source_training" if role == "target_test" else "target_local_training", **extra}


def _scores(targets, *, role="target_test", methods=METHOD_IDS, values=None):
    values = values or {method: 0.8 if method == "csfs" else 0.6 for method in methods}
    return [ScoreRecord(target, method, seed, values[method] + (index % 3) * 0.001,
                        (target + "-subject",), (target + "-segment",), _bindings(target, role))
            for index, target in enumerate(targets) for method in methods for seed in SEEDS]


def test_complete_family_first_averages_five_seeds_within_target_and_all_nine_methods():
    targets = tuple(f"T{i}" for i in range(6))
    rows = _scores(targets)
    report = evaluate_claims(rows, targets)
    assert report["complete"] and report["methods"] == list(METHOD_IDS) and "no_private" in report["summaries"]
    assert report["claims"]["C1"]["status"] == "supported" and report["claims"]["C2"]["status"] == "supported"
    c1 = report["claims"]["C1"]["comparisons"]["bendr_context"]
    assert c1["sign_flip_count"] == 64 and c1["p_value"] == pytest.approx(1 / 64)
    assert c1["holm_adjusted_p"] == pytest.approx(2 / 64)
    assert c1["bootstrap_resamples"] == 10_000 and c1["target_deltas"] == pytest.approx([0.2] * 6)
    assert report["summaries"]["csfs"]["target_macro_mean"] == pytest.approx(0.801)


def test_missing_run_has_no_intersection_drop_imputation_or_supported_claim():
    targets = ("A", "B", "C")
    rows = _scores(targets)
    missing = rows.pop()
    failure = FailureRecord(missing.target_id, missing.method_id, missing.seed, "immutable failed attempt", "f" * 64)
    report = evaluate_claims(rows, targets, failure_records=(failure,))
    assert not report["complete"] and report["missing"] == [("C", "random_init", SEEDS[-1])]
    assert report["claims"]["C1"]["status"] == "incomplete" and report["summaries"] == {}
    assert report["failure_records"][0]["artifact_sha256"] == "f" * 64


@pytest.mark.parametrize("defect", ["foreign", "duplicate", "units", "segments", "role", "hash", "nonfinite", "seed"])
def test_paired_family_rejects_foreign_incomplete_or_unbound_outcomes(defect):
    targets = ("A", "B", "C")
    rows = _scores(targets)
    if defect == "foreign": rows[0] = replace(rows[0], method_id="invented")
    elif defect == "duplicate": rows.append(rows[0])
    elif defect == "units": rows[0] = replace(rows[0], unit_ids=("foreign-subject",))
    elif defect == "segments": rows[0] = replace(rows[0], segment_ids=("foreign-segment",))
    elif defect == "role": rows[0] = replace(rows[0], bindings=_bindings("A", "source_validation"))
    elif defect == "hash": rows[0] = replace(rows[0], bindings={**_bindings("A"), "checkpoint_sha256": ""})
    elif defect == "nonfinite": rows[0] = replace(rows[0], score=float("nan"))
    else: rows[0] = replace(rows[0], seed=999)
    with pytest.raises(ValueError): complete_score_matrix(rows, targets)


def test_small_dataset_count_cannot_be_treated_as_thirty_independent_seed_replicates():
    report = evaluate_claims(_scores(("A", "B", "C")), ("A", "B", "C"))
    assert report["claims"]["C1"]["status"] == "not_supported"
    assert report["claims"]["C1"]["comparisons"]["bendr_context"]["holm_adjusted_p"] == 0.25
    assert holm_adjust([0.01, 0.04]) == pytest.approx((0.02, 0.04))


def test_five_seed_means_precede_unweighted_target_macro_average():
    targets = ("A", "B", "C")
    rows = _scores(targets)
    rows = [replace(row, score=(0.1, 0.2, 0.3, 0.4, 0.5)[SEEDS.index(row.seed)])
            if row.target_id == "A" and row.method_id == "csfs" else row for row in rows]
    summary = evaluate_claims(rows, targets)["summaries"]["csfs"]
    assert summary["per_target_seed_mean"]["A"] == pytest.approx(0.3)
    assert summary["target_macro_mean"] == pytest.approx((0.3 + 0.801 + 0.802) / 3)


def test_large_target_signflip_is_deterministic_and_exact_zero_effect_is_not_significant():
    targets = tuple(f"T{i}" for i in range(21))
    first = paired_target_statistics([0.02] * 21, targets, "toy")
    assert first == paired_target_statistics([0.02] * 21, targets, "toy")
    assert first["sign_flip_count"] == 100_000 and not first["exact"]
    zero = paired_target_statistics([0.0] * 3, ("A", "B", "C"), "zero")
    assert zero["p_value"] == 1.0 and zero["ci_low"] == zero["ci_high"] == 0


@pytest.mark.parametrize("equivalent", ["full_latent", "no_private", "shuffled_pair"])
def test_any_registered_equivalence_control_rejects_c2_necessity(equivalent):
    targets = tuple(f"T{i}" for i in range(6))
    values = {method: 0.8 if method == "csfs" else 0.6 for method in METHOD_IDS}
    values[equivalent] = 0.795
    report = evaluate_claims(_scores(targets, values=values), targets)
    c2 = report["claims"]["C2"]
    assert c2["status"] == "not_supported" and equivalent in c2["equivalent_controls"]


def _c3_fixture():
    targets = ("A", "B", "C")
    choices = [AnchorChoice(target, seed, "bendr_context", {"bendr_context": 0.7, "masked_latent": 0.65},
                            next(value for value in targets if value != target), True, "b" * 64) for target in targets for seed in SEEDS]
    conditions = ("random_deletion_25", "random_deletion_50", "bandstop_8_13", "bandpass_1_8", "region_deletion")
    eligibility = [EligibilityRecord(target, seed, condition, (target + "-segment",), (target + "-subject",),
                                     ((target + "-segment", 16),), ((target + "-excluded", "ineligible channel count"),),
                                     "a" * 64, True, (target + "-segment", target + "-excluded"))
                   for target in targets for seed in SEEDS for condition in conditions]
    lookup = {(row.target_id, row.seed, row.condition): row for row in eligibility}
    perturbed, clean = {}, {}
    for condition in conditions:
        perturbed[condition] = _scores(targets, methods=("csfs", "bendr_context"), values={"csfs": 0.8, "bendr_context": 0.6})
        clean[condition] = _scores(targets, methods=("csfs", "bendr_context"), values={"csfs": 0.85, "bendr_context": 0.65})
        for groups in (perturbed, clean):
            groups[condition] = [replace(row, bindings={**row.bindings, "eligibility_sha256": lookup[row.target_id, row.seed, condition].sha256})
                                 for row in groups[condition]]
    in_domain = _scores(targets, role="target_local_test", methods=("csfs", "random_init"), values={"csfs": 0.79, "random_init": 0.8})
    return targets, perturbed, choices, in_domain, clean, eligibility


def _c3(bundle):
    targets, perturbed, choices, in_domain, clean, eligibility = bundle
    return c3_decision(targets, perturbed, choices, in_domain, clean_subset_records=clean, eligibility_records=eligibility)


def test_c3_uses_fixed_source_validation_anchor_paired_subsets_and_in_domain_margin():
    bundle = _c3_fixture()
    report = _c3(bundle)
    assert report["status"] == "supported" and report["random_family_pass"] and report["spectral_family_pass"]
    assert report["in_domain"]["ci_low"] == pytest.approx(-0.01)
    assert len(report["region_eligibility"]) == 15
    assert all(row["method_id"] == "bendr_context" for row in report["anchor_choices"])


@pytest.mark.parametrize("defect", ["anchor_target", "anchor_reselect", "late_anchor", "pair_drop", "ledger_drop", "wrong_sha", "random_channels", "missing_condition"])
def test_c3_refuses_anchor_leakage_or_any_unmatched_or_unregistered_subset(defect):
    bundle = _c3_fixture()
    targets, perturbed, choices, _domain, clean, eligibility = bundle
    if defect == "anchor_target": choices[0] = replace(choices[0], source_validation_dataset_id="A")
    elif defect == "anchor_reselect": choices[0] = replace(choices[0], method_id="masked_latent")
    elif defect == "late_anchor": choices[0] = replace(choices[0], selected_before_target_scoring=False)
    elif defect == "pair_drop": perturbed["random_deletion_25"][0] = replace(perturbed["random_deletion_25"][0], segment_ids=("foreign",))
    elif defect == "ledger_drop": eligibility[0] = replace(eligibility[0], ineligible_segments=())
    elif defect == "wrong_sha": clean["random_deletion_25"][0] = replace(clean["random_deletion_25"][0], bindings={**clean["random_deletion_25"][0].bindings, "eligibility_sha256": "e" * 64})
    elif defect == "random_channels": eligibility[0] = replace(eligibility[0], available_channels=(("A-segment", 8),))
    else:
        perturbed.pop("bandpass_1_8")
        assert _c3(bundle)["status"] == "incomplete"
        return
    with pytest.raises(ValueError): _c3(bundle)


def test_c3_requires_both_perturbation_families_and_does_not_hide_material_in_domain_loss():
    bundle = _c3_fixture()
    targets, perturbed, choices, domain, clean, eligibility = bundle
    domain[:] = [replace(row, score=0.7) if row.method_id == "csfs" else row for row in domain]
    assert _c3(bundle)["status"] == "not_supported"
    bundle = _c3_fixture()
    for condition in ("bandstop_8_13", "bandpass_1_8"):
        bundle[1][condition] = [replace(row, score=0.5) if row.method_id == "csfs" else row for row in bundle[1][condition]]
    assert _c3(bundle)["status"] == "not_supported"


def test_region_ineligible_inventory_is_reported_not_imputed_or_required_as_positive():
    bundle = _c3_fixture()
    for index, row in enumerate(bundle[5]):
        if row.condition == "region_deletion":
            bundle[5][index] = replace(row, clean_segment_ids=(), unit_ids=(), available_channels=(),
                                        ineligible_segments=tuple((identity, "no region leaves eight channels")
                                                                  for identity in row.all_clean_segment_ids))
    bundle[1].pop("region_deletion")
    bundle[4].pop("region_deletion")
    report = _c3(bundle)
    assert report["status"] == "supported" and report["region_comparison"]["status"] == "ineligible"


class _FrozenToyProbe:
    training = False

    def __init__(self):
        self.encoder = SimpleNamespace(method_id="csfs", training=False)
        self.head = SimpleNamespace(weight=np.zeros((2, 128)), bias=np.zeros(2))
        self.rows = [SimpleNamespace(requires_grad=False)]

    def parameters(self): return iter(self.rows)

    def __call__(self, batch): return np.asarray([[0.0, 2.0] for _ in batch["metadata"]])


def _evaluation_fixture():
    hashes = {key: "a" * 64 for key in HASH_BINDINGS}
    hashes["label_vocabulary_sha256"] = label_vocabulary_hash(VOCAB)
    bindings = EvaluationBindings("csfs", "Target", 13, ("Source",), "Validation", "Target", "source_training", "target_test", **hashes)
    batch = {**{key: np.zeros((1, 19, 8)) for key in VIEW_KEYS}, "a_mask": np.ones((1, 19), dtype=bool),
             "b_mask": np.ones((1, 19), dtype=bool), "metadata": [{"dataset_id": "Target", "subject_id": "Subject",
             "recording_id": "Recording", "segment_id": "Segment", "label": 1}]}
    return _FrozenToyProbe(), bindings, batch


def test_evaluation_freezes_all_learning_and_binds_exact_complete_predictions():
    probe, bindings, batch = _evaluation_fixture()
    result = evaluate_frozen_probe(probe, [batch], bindings=bindings, label_vocabulary=VOCAB, expected_segment_ids=("Segment",))
    assert result["metrics"]["macro_f1"] == 0.5
    assert not result["fitting_performed"] and not result["calibration_applied"]
    assert result["score_record"].bindings["checkpoint_sha256"] == "a" * 64
    pair = evaluate_paired_condition(result, result, predeclared_pair_ids=("Segment",), eligibility_sha256="e" * 64)
    assert pair["pair_ids"] == ("Segment",)


@pytest.mark.parametrize("defect", ["unfrozen", "missing_view", "missing_segment", "foreign_target", "fitting_leak", "foreign_vocabulary"])
def test_evaluation_rejects_unfrozen_or_incomplete_runtime_boundary(defect):
    probe, bindings, batch = _evaluation_fixture()
    expected, vocabulary = ("Segment",), VOCAB
    if defect == "unfrozen": probe.rows[0].requires_grad = True
    elif defect == "missing_view": batch.pop("b_high")
    elif defect == "missing_segment": expected = ("Segment", "Missing")
    elif defect == "foreign_target": batch["metadata"][0]["dataset_id"] = "Foreign"
    elif defect == "fitting_leak": bindings = replace(bindings, source_training_dataset_ids=("Target",))
    else: vocabulary = ("other", "positive")
    with pytest.raises(ValueError): evaluate_frozen_probe(probe, [batch], bindings=bindings, label_vocabulary=vocabulary, expected_segment_ids=expected)


def test_secondary_temperature_sensitivity_never_replaces_primary_probabilities():
    units = aggregate_predictions([SegmentPrediction("Target", "S", "R", "segment", 1, (0.2, 0.8))], VOCAB)
    before = copy.deepcopy(units)
    result = temperature_sensitivity(units, VOCAB, temperature=2.0, fitted_dataset_id="Validation",
                                    source_validation_dataset_id="Validation", target_id="Target",
                                    fit_unit_ids=("validation-unit",), fitted_artifact_sha256="f" * 64)
    assert not result["primary_predictions_modified"] and units == before and not result["metrics"]["uncalibrated"]
    with pytest.raises(ValueError):
        temperature_sensitivity(units, VOCAB, temperature=2.0, fitted_dataset_id="Target",
                                source_validation_dataset_id="Target", target_id="Target",
                                fit_unit_ids=("unit",), fitted_artifact_sha256="f" * 64)


def test_target_local_validation_probe_score_cannot_enter_final_in_domain_statistics():
    probe, bindings, batch = _evaluation_fixture()
    bindings = replace(bindings, source_training_dataset_ids=("Target",), fit_role="target_local_training",
                       evaluation_role="target_local_validation")
    result = evaluate_frozen_probe(probe, [batch], bindings=bindings, label_vocabulary=VOCAB, expected_segment_ids=("Segment",))
    assert result["score_record"].bindings["evaluation_role"] == "target_local_validation"
    with pytest.raises(ValueError, match="runtime/config/source/data provenance"):
        complete_score_matrix([result["score_record"]], ("Target", "B", "C"), methods=("csfs",),
                              evaluation_role="target_local_test")
