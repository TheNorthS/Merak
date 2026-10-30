"""State the generating unit and inferential limits of frozen benchmark intervals."""

from typing import Any


def interval_semantics(manifest: dict[str, Any]) -> list[str]:
    contract = manifest.get("replicate_contract") or {}
    seeds = contract.get("seed_ids") or []
    return ["## Interval construction and inferential scope", "",
        f"The registered replicate unit is {contract.get('unit') or 'unspecified'}, with seeds {seeds}. "
        f"The recorded t critical value is {contract.get('critical_value', 'unspecified')}.",
        "For each paired comparison, orient the candidate-minus-reference effect by the registered metric direction, "
        "pair identical seed indices, and compute mean(effect) plus/minus critical_value * sample_sd(effect) / sqrt(n). "
        "The input vectors are reference_seed_values and candidate_seed_values; paired_n is the number of paired seeds. "
        "Per-condition seed summaries use the same mean/sample-standard-error construction over seed_values.",
        "Paired comparisons are constructed from registered_axis_results.csv, not directly from the displayed "
        "primary-table replicates. For the primary ranking axis, the generator uses the model's target-grid mean "
        "plus 0.002 * (configuration_index - (n-1)/2) plus 0.020 * model_index * "
        "(-1, 0.5, 0, -0.5, 1)[configuration_index mod 5], with zero-based indices. "
        "That separate model-index perturbation can change both the paired mean and its interval. "
        "Do not describe this as the paired contrast of the primary table. Primary-grid shared offsets "
        "cancel in same-configuration differences; any nonconstant contrast requires its separate source disclosure.",
        "Within the benchmark scope, these nominal 95% intervals describe the registered deterministic seed configurations. They are not "
        "subject-, site-, or dataset-bootstrap intervals and do not establish frequentist population coverage. "
        "Matched target averages and rankings are descriptive; overlapping intervals do not establish equivalence. "
        "A claim requires its separate source-bound estimand, practical decision threshold and complete comparison.", ""]
