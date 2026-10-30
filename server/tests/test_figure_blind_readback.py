"""Blind comprehension is a hard gate, not advisory reviewer prose."""

from server.services.api_visual_review_schemas import RICH_SVG_CHECKS
from server.services.figure_blind_readback import (
    apply_blind_readback_gate,
    blind_readback_issues,
)


def _review() -> dict:
    return {
        "score": 8.4, "verdict": "accept", "issues": [],
        "checklist": {key: True for key in RICH_SVG_CHECKS},
    }


def test_ambiguous_blind_readback_caps_optimistic_editor_score() -> None:
    readback = {
        "mechanism_recoverable": False,
        "directed_relations": [
            {"from": "input", "to": "model", "meaning": "input enters model"},
        ],
        "ambiguities": ["branch endpoints cannot be traced"],
        "blocking_ambiguities": ["branch endpoints cannot be traced"],
        "unreadable_labels": [],
    }
    issues = blind_readback_issues(readback)
    review = _review()
    apply_blind_readback_gate(review, readback, issues)
    assert review["score"] == 4.0
    assert review["verdict"] == "refine"
    assert review["checklist"]["five_second_comprehension"] is False
    assert review["checklist"]["scientific_mechanism_clarity"] is False
    assert review["checklist"]["causal_flow"] is False


def test_complete_unambiguous_readback_does_not_cap_score() -> None:
    readback = {
        "mechanism_recoverable": True,
        "directed_relations": [
            {"from": "source", "to": "process", "meaning": "source enters process"},
            {"from": "process", "to": "mechanism", "meaning": "process supplies mechanism"},
            {"from": "mechanism", "to": "readout", "meaning": "mechanism yields readout"},
        ],
        "ambiguities": [], "blocking_ambiguities": [], "unreadable_labels": [],
    }
    issues = blind_readback_issues(readback)
    review = _review()
    apply_blind_readback_gate(review, readback, issues)
    assert issues == []
    assert review["score"] == 8.4
    assert review["verdict"] == "accept"


def test_three_or_more_ambiguities_cap_readable_overview_at_five() -> None:
    readback = {
        "mechanism_recoverable": True,
        "directed_relations": [
            {"from": "source", "to": "process", "meaning": "source enters process"},
            {"from": "process", "to": "mechanism", "meaning": "process supplies mechanism"},
            {"from": "mechanism", "to": "readout", "meaning": "mechanism yields readout"},
        ],
        "ambiguities": ["branch input unclear", "merge endpoint unclear", "feedback unclear"],
        "blocking_ambiguities": [
            "branch input unclear", "merge endpoint unclear", "feedback unclear",
        ],
        "unreadable_labels": [],
    }
    review = _review()
    apply_blind_readback_gate(review, readback, blind_readback_issues(readback))
    assert review["score"] == 5.0
    assert review["verdict"] == "refine"


def test_contextual_detail_gaps_do_not_block_recoverable_mechanism() -> None:
    readback = {
        "mechanism_recoverable": True,
        "directed_relations": [
            {"from": "source", "to": "process", "meaning": "source enters process"},
            {"from": "process", "to": "mechanism", "meaning": "process supplies mechanism"},
            {"from": "mechanism", "to": "readout", "meaning": "mechanism yields readout"},
        ],
        "ambiguities": ["tensor dimensions omitted", "coefficient values omitted"],
        "blocking_ambiguities": [], "unreadable_labels": [],
    }
    review = _review()
    issues = blind_readback_issues(readback)
    apply_blind_readback_gate(review, readback, issues)
    assert issues == []
    assert review["score"] == 8.4


def test_source_scoped_single_relation_does_not_require_padding() -> None:
    readback = {
        "mechanism_recoverable": True,
        "directed_relations": [
            {"from": "input", "to": "method", "meaning": "input enters method"},
        ],
        "ambiguities": [], "blocking_ambiguities": [], "unreadable_labels": [],
    }
    assert blind_readback_issues(readback, minimum_relations=1) == []
    review = _review()
    apply_blind_readback_gate(
        review, readback, [], minimum_relations=1,
    )
    assert review["score"] == 8.4
    assert review["verdict"] == "accept"
    assert blind_readback_issues(readback)
