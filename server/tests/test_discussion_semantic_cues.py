"""Scientific discussion cues should recognize actual adverse-result interpretations."""

from types import SimpleNamespace

from server.services.paper_drafting import ALTERNATIVE_EXPLANATION_RE, NEGATIVE_RESULT_RE
from server.services.paper_section_review import _review_discussion


def _issues(text):
    context = SimpleNamespace(text=text, issues=[], policy=SimpleNamespace(
        alternative_explanation=ALTERNATIVE_EXPLANATION_RE, negative_result=NEGATIVE_RESULT_RE))
    _review_discussion(context)
    return context.issues


def test_observed_adverse_ordering_and_competing_causes_do_not_require_magic_phrases():
    text = ("The deterministic observation-layout scenario does not support the intended positive transfer narrative. "
        "Several explanations remain compatible with the ordering. First, generic exposure to missing channels "
        "may regularize prediction more effectively. Second, equal mask ratios do not equalize spatial information. "
        "A component diagnostic cannot override the adverse primary ordering or establish a montage-specific mechanism.")
    assert _issues(text) == []


def test_positive_result_with_no_explanations_still_requires_both_discussion_moves():
    assert len(_issues("The positive result demonstrates improved transfer on this benchmark.")) == 2


def test_multiple_explanations_do_not_substitute_for_negative_result_interpretation():
    assert _issues("Multiple explanations remain compatible with the gain, including capacity and unequal tuning.") == [
        "discussion omits negative/null-result interpretation"]


def test_null_interaction_interpretation_and_line_wrapped_alternatives_are_recognized():
    text = (
        "Several alternative\nexplanations remain plausible, including unequal decoder capacity. "
        "A null subject-clustered interaction in a completed evaluation would mean that the proposed "
        "boundary was not detected under the registered tasks, deletion definition, and resource scope; "
        "it would not show that spatially focal information is absent from EEG representations."
    )
    assert _issues(text) == []


def test_negative_transfer_and_zero_crossing_are_actual_adverse_outcomes():
    text = (
        "Competing explanations include unequal masking difficulty. "
        "Negative transfer relative to random initialization must be reported as a failure of the practical claim. "
        "An interval spanning zero does not license a directional conclusion."
    )
    assert _issues(text) == []


def test_mention_of_a_null_hypothesis_alone_is_not_negative_result_interpretation():
    assert _issues("Alternative explanations were considered. The null hypothesis was preregistered.") == [
        "discussion omits negative/null-result interpretation"]


def test_near_zero_and_reversed_interactions_explain_what_would_weaken_the_claim():
    text = (
        "Several alternative explanations remain central. "
        "A subject-clustered estimate near zero, an interaction in the opposite direction, "
        "or comparable deletion effects for waveform reconstruction would all weaken "
        "the sparse-event invariance account rather than constitute partial support for it."
    )
    assert _issues(text) == []
