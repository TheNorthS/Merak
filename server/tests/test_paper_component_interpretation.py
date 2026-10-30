"""Recognize meaningful component-removal terminology without requiring one literal word."""

import re

import pytest

from server.services.paper_drafting import synthetic_analysis_requirements


@pytest.mark.parametrize("prose", [
    "Removal of controlled remapping changes the recorded endpoint by -0.024.",
    "The registered removals are a component diagnostic, not an attribution result.",
    "The component ablation is interpreted against a matched control.",
])
def test_removal_and_component_diagnostic_language_satisfy_the_term_check(prose):
    pattern = synthetic_analysis_requirements("algorithm_benchmark")["component-ablation interpretation"]
    assert re.search(pattern, prose.casefold())


def test_unrelated_results_do_not_satisfy_component_interpretation():
    pattern = synthetic_analysis_requirements("algorithm_benchmark")["component-ablation interpretation"]
    assert not re.search(pattern, "The plot reports the overall endpoint and interval.")


def test_explicit_lack_of_support_and_plausible_alternative_are_recognized():
    from server.services.paper_drafting import ALTERNATIVE_EXPLANATION_RE, NEGATIVE_RESULT_RE

    assert NEGATIVE_RESULT_RE.search("The scenario supplies no support for the hypothesized advantage.")
    assert ALTERNATIVE_EXPLANATION_RE.search("One plausible explanation is conditional prediction difficulty.")
    assert not NEGATIVE_RESULT_RE.search("We report the score and method.")


def test_fixed_configuration_interval_interpretation_does_not_require_confidence_label():
    pattern = synthetic_analysis_requirements("algorithm_benchmark")["uncertainty interpretation"]
    assert re.search(pattern, "these intervals summarize variation across fixed configurations, not population confidence.")
    assert re.search(pattern, "both intervals cross zero despite negative point estimates.")
    assert not re.search(pattern, "the table gives a value.")
