"""Mixed rejection grammar counts real independent contributions, never duplicates."""

from __future__ import annotations

import pytest

from server.services.paper_contribution_validation import falsifiable_contribution_structure


@pytest.mark.parametrize("subject", ["it", "the proposed protocol"])
def test_adverse_conditions_precluding_or_defeating_interpretation_are_recognized(subject):
    text = (
        f"First, {subject} specifies a same-mask intervention with two prespecified interval criteria. "
        "Failure of either criterion precludes the proposed robustness-and-preservation conclusion. "
        f"Second, {subject} specifies a topology-by-removal comparison. "
        "Disappearance after balancing or an alternative-control explanation would defeat a topology-specific interpretation. "
        "Third, we document a generated scenario without empirical claims."
    )
    assert falsifiable_contribution_structure(text) == {"contributions": 3, "falsification_conditions": 2}


def test_generic_robustness_language_without_adverse_condition_does_not_count():
    text = ("First, the proposed protocol improves robustness and strengthens our conclusion. "
            "Second, the comparison supports our interpretation under several conditions.")
    assert falsifiable_contribution_structure(text) == {"contributions": 2, "falsification_conditions": 0}


@pytest.mark.parametrize("approach", [
    "Our approach keeps a fixed mask bank across matched encoder conditions.",
    "Our protocol pairs subjects across conditions.",
    "We therefore propose a fixed-mask test.",
    "Our approach prospectively defines matched endpoint-specific estimands.",
])
def test_explicit_approach_preview_accepts_subject_and_transition_variants(approach):
    from types import SimpleNamespace
    from server.services.paper_section_review import _review_introduction
    text = ("Yet the causal account remains unresolved. " + approach +
            " First, it specifies an intervention. Failure of either criterion precludes the conclusion. "
            "Second, it specifies a factorial test. Disappearance after matching would defeat this interpretation.")
    context = SimpleNamespace(text=text, lower=text.lower(), issues=[])
    _review_introduction(context)
    assert context.issues == []


def test_conditional_withdrawal_and_reproducibility_failure_count_across_fields():
    prose = (r'\begin{enumerate}\item Endpoint-separated estimands. '
             'The design fails as reproducible if exposure and analysis units cannot be fixed before inspection. '
             r'\item Mechanism alternatives. '
             'The radiative interpretation weakens if shade fails to covary with radiant indicators. '
             r'\item Decision criteria. '
             'The primary association claim is withdrawn if support checks yield null or opposite contrasts. '
             r'\end{enumerate}')
    assert falsifiable_contribution_structure(prose) == {'contributions': 3, 'falsification_conditions': 3}
    assert falsifiable_contribution_structure(
        r'\item Our interpretation weakens. \item Our claim is withdrawn.')['falsification_conditions'] == 0


def test_mixed_direct_and_semantic_rejection_rules_are_counted_together():
    """Run 106 attempt 2 contained both real rules but max(detectors) counted one."""
    prose = (
        "First, we test cross-dataset transfer against matched anchors. "
        "This transfer claim fails if the method does not surpass either anchor. "
        "Second, we test whether shared-private factorization is necessary. "
        "Practical equivalence of either factorization control falsifies this mechanism claim. "
        "Third, we test the intervention signature and report adverse outcomes."
    )
    assert falsifiable_contribution_structure(prose) == {
        "contributions": 3, "falsification_conditions": 2,
    }


@pytest.mark.parametrize("second_rule", [
    "Equivalence of the factorization controls falsifies this mechanism claim.",
    "The method is effective across a broad collection of tasks.",
])
def test_introduction_gate_keeps_the_two_independent_rules_threshold(second_rule):
    from types import SimpleNamespace
    from server.services.paper_section_review import _review_introduction

    prose = (
        "However, the transfer mechanism remains unresolved. "
        "First, we test transfer. This claim fails if matched controls tie. "
        "Second, we test factorization. " + second_rule
    )
    context = SimpleNamespace(text=prose, lower=prose.casefold(), issues=[])
    _review_introduction(context)
    expected_pass = "falsifies" in second_rule
    assert (not context.issues) is expected_pass
    if not expected_pass:
        assert context.issues == ["introduction lacks two or more falsifiable contributions"]


@pytest.mark.parametrize("style", ["ordinal", "numbered", "latex"])
def test_mixed_rules_do_not_depend_on_list_styling(style):
    conditions = [
        "We test transfer. This claim fails if matched anchors reach the same score.",
        "We test factorization. Equivalence of the controls falsifies this mechanism claim.",
    ]
    prefixes = {"ordinal": ["First, ", "Second, "], "numbered": ["(1) ", "(2) "],
                "latex": [r"\item ", r"\item "]}[style]
    prose = " ".join(prefix + condition for prefix, condition in zip(prefixes, conditions))
    assert falsifiable_contribution_structure(prose) == {
        "contributions": 2, "falsification_conditions": 2,
    }


def test_overlapping_direct_and_semantic_matches_count_the_same_rule_once():
    prose = (
        "First, we define a transfer criterion. If the anchor is equivalent, "
        "this claim is rejected and would not hold. "
        "Second, we introduce a broader benchmark."
    )
    assert falsifiable_contribution_structure(prose) == {
        "contributions": 2, "falsification_conditions": 1,
    }


def test_repeating_the_same_rejection_sentence_cannot_satisfy_two_contributions():
    prose = (
        "First, we test transfer. The claim is rejected if the control performs equivalently. "
        "Second, we test a protocol. The claim is rejected if the control performs equivalently."
    )
    assert falsifiable_contribution_structure(prose) == {
        "contributions": 2, "falsification_conditions": 1,
    }


def test_multiple_rejection_sentences_for_one_contribution_do_not_certify_another():
    prose = (
        "First, we test transfer. This claim fails if the control ties. "
        "This claim is rejected if leakage explains the gain. "
        "Second, we introduce an efficient encoder."
    )
    assert falsifiable_contribution_structure(prose) == {
        "contributions": 2, "falsification_conditions": 1,
    }


def test_marketing_and_commented_out_rules_never_supply_rejection_evidence():
    prose = (
        "First, we propose an effective method. Second, we provide a broad study.\n"
        "% \\item The claim is rejected if controls tie.\n"
        "% \\item Equivalence falsifies the claim.\n"
    )
    assert falsifiable_contribution_structure(prose) == {
        "contributions": 2, "falsification_conditions": 0,
    }


def test_explicit_necessary_condition_counts_with_direct_falsification():
    prose = (
        r"\item We specify a matched-control protocol. Its rationale is falsified when the matched control performs as well. "
        r"\item We report a bounded benchmark finding. "
        r"\item We test preservation: the intervention preserves performance only if a paired loss remains within a predeclared tolerance."
    )
    assert falsifiable_contribution_structure(prose) == {"contributions": 3, "falsification_conditions": 2}


def test_repeated_necessary_condition_cannot_certify_two_contributions():
    sentence = "The intervention preserves performance only if the loss remains within a predeclared tolerance."
    prose = "First, we test preservation. " + sentence + " Second, we test transfer. " + sentence
    assert falsifiable_contribution_structure(prose) == {"contributions": 2, "falsification_conditions": 1}


@pytest.mark.parametrize("verb", ["instantiate", "specify"])
def test_method_instantiation_or_protocol_specification_is_an_approach_preview(verb):
    from types import SimpleNamespace
    from server.services.paper_section_review import _review_introduction
    text = (f"However, correspondence remains unresolved. We {verb} a metadata-conditioned encoder. "
            "First, we test transfer. The claim fails if controls tie. "
            "Second, we test preservation. The claim is rejected if matched loss exceeds tolerance.")
    context = SimpleNamespace(text=text, lower=text.lower(), issues=[])
    _review_introduction(context)
    assert context.issues == []


def test_observed_falsifying_result_counts_as_independent_rejection_evidence():
    text = ("First, we specify a protocol. This account is falsified when the control ties. "
            "Second, we state identification requirements. "
            "Third, we instantiate the protocol. The all-target ordering is a falsifying directional result for the positive narrative.")
    assert falsifiable_contribution_structure(text) == {"contributions": 3, "falsification_conditions": 2}


def test_explicit_claim_redirection_by_adverse_outcomes_survives_reproduction_caveat():
    text = (r'\item We define a protocol. The specification fails if pairing leaves conditions unmatched. '
            r'\item We state future estimands. Future transfer, mechanism, and preservation claims are redirected by, '
            'respectively, a non-positive or inadequate paired effect, generic channel-dropout replication, '
            'or loss beyond the prespecified tolerance; independent units are required. '
            r'\item We report records. Record-level reproduction or falsification would require release and independent validation.')
    assert falsifiable_contribution_structure(text) == {'contributions': 3, 'falsification_conditions': 2}


def test_vague_redirection_does_not_supply_falsification_evidence():
    text = 'First, we define a useful model. Its claims are redirected by new research. Second, we discuss reproduction.'
    assert falsifiable_contribution_structure(text)['falsification_conditions'] == 0


def test_explicit_directional_support_condition_is_a_falsifiable_boundary():
    text = ('First, it specifies a primary interaction comparison. The directional hypothesis is supported '
            'only when the subject-cluster interval for this interaction lies strictly below zero under the fixed rule. '
            'Second, it defines a control. This mechanism is falsified if the contrast reverses.')
    assert falsifiable_contribution_structure(text) == {'contributions': 2, 'falsification_conditions': 2}


def test_vague_support_condition_does_not_satisfy_rejection_criterion():
    text = ('First, we present a model. The hypothesis is supported only when the evidence is convincing. '
            'Second, we describe a protocol.')
    assert falsifiable_contribution_structure(text)['falsification_conditions'] == 0
