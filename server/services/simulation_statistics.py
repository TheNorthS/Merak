"""Dependency-free statistical primitives for deterministic simulation data."""

from __future__ import annotations

import math
import itertools
import random


def paired_seed_bootstrap_interval(effects: list[float]) -> tuple[float, float]:
    """Percentile bootstrap of paired seed effects; no subject-level inference is implied."""
    if len(effects) < 2 or any(not math.isfinite(value) for value in effects):
        raise ValueError("Paired seed bootstrap requires at least two finite effects")
    size = len(effects)
    if size <= 5:
        means = sorted(sum(sample) / size for sample in itertools.product(effects, repeat=size))
    else:
        generator = random.Random(1729)
        means = sorted(sum(generator.choices(effects, k=size)) / size for _ in range(10000))
    def percentile(probability: float) -> float:
        position = (len(means) - 1) * probability
        lower = int(position)
        fraction = position - lower
        return means[lower] * (1 - fraction) + means[min(lower + 1, len(means) - 1)] * fraction
    return percentile(.025), percentile(.975)


def _continued_beta_fraction(a: float, b: float, x: float) -> float:
    maximum_iterations = 200
    epsilon = 3.0e-14
    floor = 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (floor if abs(d) < floor else d)
    result = d
    for iteration in range(1, maximum_iterations + 1):
        doubled = 2 * iteration
        coefficient = iteration * (b - iteration) * x / (
            (qam + doubled) * (a + doubled)
        )
        d = 1.0 + coefficient * d
        d = 1.0 / (floor if abs(d) < floor else d)
        c = 1.0 + coefficient / c
        c = floor if abs(c) < floor else c
        result *= d * c
        coefficient = -(
            (a + iteration) * (qab + iteration) * x
            / ((a + doubled) * (qap + doubled))
        )
        d = 1.0 + coefficient * d
        d = 1.0 / (floor if abs(d) < floor else d)
        c = 1.0 + coefficient / c
        c = floor if abs(c) < floor else c
        delta = d * c
        result *= delta
        if abs(delta - 1.0) <= epsilon:
            break
    return result


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    scale = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return scale * _continued_beta_fraction(a, b, x) / a
    return 1.0 - scale * _continued_beta_fraction(b, a, 1.0 - x) / b


def paired_t_two_sided_p(effects: list[float]) -> float:
    """Return a two-sided paired Student-t p-value without SciPy."""
    sample_size = len(effects)
    if sample_size < 2:
        return 1.0
    mean_effect = sum(effects) / sample_size
    variance = sum((value - mean_effect) ** 2 for value in effects) / (
        sample_size - 1
    )
    if variance <= 1.0e-24:
        return 0.0 if abs(mean_effect) > 1.0e-12 else 1.0
    statistic = abs(mean_effect) / math.sqrt(variance / sample_size)
    degrees_of_freedom = float(sample_size - 1)
    probability = _regularized_incomplete_beta(
        degrees_of_freedom / 2.0,
        0.5,
        degrees_of_freedom / (degrees_of_freedom + statistic * statistic),
    )
    return min(1.0, max(0.0, probability))
