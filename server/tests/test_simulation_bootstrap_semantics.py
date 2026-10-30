"""Bootstrap fields must come from actual paired resampling, never padded t intervals."""

import pytest

from server.services.simulation_statistics import paired_seed_bootstrap_interval
from server.services.simulation_ranking_evidence import _paired_row


def test_two_seed_exact_percentile_bootstrap_has_known_support():
    assert paired_seed_bootstrap_interval([0.0, 2.0]) == pytest.approx((.075, 1.925))
    assert paired_seed_bootstrap_interval([3.0, 3.0, 3.0]) == (3.0, 3.0)


def test_sampled_bootstrap_is_reproducible_and_stays_within_effect_support():
    effects = [float(index) for index in range(8)]
    result = paired_seed_bootstrap_interval(effects)
    assert result == paired_seed_bootstrap_interval(effects)
    assert min(effects) <= result[0] < result[1] <= max(effects)


def test_paired_row_binds_bootstrap_method_and_does_not_pad_t_bounds():
    item = {"mean_effect": 1, "ci_low": -10, "ci_high": 12, "mpid": .1,
        "effects": [0.0, 2.0], "axis_id": "accuracy", "metric": "accuracy", "metric_direction": "maximize",
        "reference_method": "Reference", "reference_model_id": "ref", "candidate_method": "Candidate", "candidate_model_id": "candidate",
        "reference_values": [0, 0], "candidate_values": [0, 2], "paired_n": 2, "p_value": .5}
    row = _paired_row(1, item, item, .5, .05, 1, False, [1, 2], lambda value: value)
    assert float(row["bootstrap_ci_low"]) == pytest.approx(.075)
    assert float(row["bootstrap_ci_high"]) == pytest.approx(1.925)
    assert row["bootstrap_method"] == "paired_seed_percentile_v1" and row["bootstrap_resamples"] == "4"


def test_report_keeps_seed_unit_and_does_not_claim_subject_bootstrap():
    from server.services.simulation_interval_semantics import interval_semantics
    text = "\n".join(interval_semantics({"replicate_contract": {
        "unit": "random_seed", "seed_ids": [13, 42, 73], "critical_value": 4.303}}))
    assert "[13, 42, 73]" in text and "4.303" in text and "sqrt(n)" in text
    assert "do not establish frequentist population coverage" in text
