"""Local geometry regressions for source-bound evaluation diagrams."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from server.services.evaluation_design_svg import _evaluation_design_svg, _text_width
from server.services.figure_print_policy import svg_print_contract_issues
from server.services.figure_svg_text_geometry import rendered_svg_text_geometry
from server.services.publication_figure_labels import concept_labels
from server.services.svg_variant_conversion import convert_svg_variants


_SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def _group_text(root: ET.Element, group_id: str) -> str:
    group = root.find(f".//svg:g[@id='{group_id}']", _SVG_NS)
    assert group is not None
    return " ".join((item.text or "") for item in group.iterfind(".//svg:text", _SVG_NS))


def _render_and_find_text_geometry(tmp_path: Path, svg: str) -> list[dict[str, object]]:
    source = tmp_path / "evaluation_design.svg"
    pdf = tmp_path / "evaluation_design.pdf"
    png = tmp_path / "evaluation_design.png"
    source.write_text(svg, encoding="utf-8")
    converted, error = convert_svg_variants(source, pdf, png)
    assert converted, error
    return rendered_svg_text_geometry(pdf)


def test_non_latin_label_width_does_not_collapse_to_helvetica_missing_glyphs() -> None:
    assert _text_width("患者随访", 22) >= 88


def test_long_primary_outcome_wraps_inside_paired_contrast(tmp_path: Path) -> None:
    outcome = "external-test subject-level macro-F1"
    svg, _ = _evaluation_design_svg({
        "method_brief": {
            "mechanism_nodes": [{"id": "M1", "publication_name": "Predictive encoder"}],
            "comparators": ["temporal-only"],
            "study_conditions": ["held-out operating regime"],
            "evaluation_contract": {"primary_outcomes": [outcome],
                "primary_comparator": "temporal-only", "focal_condition": "Predictive encoder"},
            "evaluation_protocol": {"primary_split": "external_test", "analysis_unit": "subject"},
        },
    })
    root = ET.fromstring(svg)
    decision = root.find(".//svg:g[@id='eval_decision_rule']", _SVG_NS)
    assert decision is not None
    lines = [item.text for item in decision.findall("svg:text", _SVG_NS)]
    assert " ".join(lines[1:]) == outcome
    assert all(item.get("font-size") == "22" for item in decision.findall("svg:text", _SVG_NS))
    assert _render_and_find_text_geometry(tmp_path, svg) == []


def test_long_source_labels_wrap_without_losing_words(tmp_path: Path) -> None:
    comparator = "compute matched alternative without shared channel perturbation"
    outcome = "cross-domain subject-level macro-F1 at a preregistered operating point"
    labels = concept_labels([
        "Mechanism removal under matched compute and paired seeds",
        "Alternative control with an unchanged feature budget",
        "Held-out test with a locked external operating condition",
    ], namespace="evaluation.term", limit=3)
    svg, _ = _evaluation_design_svg({
        "publication_labels": labels,
        "method_brief": {
            "mechanism_nodes": [{"publication_name": "Predictive encoder"}],
            "study_conditions": ["remove prediction objective"],
            "comparators": [comparator],
            "evaluation_contract": {"primary_outcomes": [outcome],
                "primary_comparator": comparator, "focal_condition": "Predictive encoder"},
            "evaluation_protocol": {"primary_split": "external_test", "analysis_unit": "subject"},
        },
    })
    root = ET.fromstring(svg)
    decision = root.find(".//svg:g[@id='eval_decision_rule']", _SVG_NS)
    nuisance = root.find(".//svg:g[@id='eval_nuisance_condition']", _SVG_NS)
    footer = root.find(".//svg:g[@id='eval_publication_labels']", _SVG_NS)
    assert decision is not None and nuisance is not None and footer is not None
    assert " ".join(item.text or "" for item in decision.findall("svg:text", _SVG_NS)).endswith(outcome)
    assert " ".join(item.text or "" for item in nuisance.findall("svg:text", _SVG_NS)[1:]) == comparator
    assert {item.get("data-label-id") for item in root.findall(".//svg:text", _SVG_NS)
            if item.get("data-label-id")} == {
        label["id"] for label in labels
    }
    assert _render_and_find_text_geometry(tmp_path, svg) == []


def test_declared_external_test_and_comparator_are_not_recast_as_nuisance(
    tmp_path: Path,
) -> None:
    svg, mappings = _evaluation_design_svg({
        "source_data": ["ideas/SELECTED_IDEA.json", "experiments/METHOD_CONTRACT.json",
                        "experiments/RUN_SPEC.json"],
        "method_brief": {
            "mechanism_nodes": [{"id": "M1", "publication_name": "Complementary self-supervision"}],
            "study_conditions": ["hybrid", "temporal only", "remove temporal context",
                                 "remove channel masked"],
            "evaluation_contract": {
                "comparators_or_controls": ["temporal-only", "channel-masked-only"],
                "primary_comparator": "temporal-only", "focal_condition": "Complementary self-supervision",
                "primary_outcomes": ["external-test subject-level macro-F1"],
                "statistics": "paired seed comparisons on identical registered seeds",
            },
            "evaluation_protocol": {
                "primary_split": "external_test", "analysis_unit": "subject",
                "require_subject_isolation": True, "require_session_isolation": True,
                "require_external_group": True,
            },
        },
    })
    root = ET.fromstring(svg)
    assert _group_text(root, "eval_removed_condition_1") == (
        "Matched removal remove temporal context"
    )
    assert _group_text(root, "eval_removed_condition_2") == (
        "Matched removal remove channel masked"
    )
    assert "temporal-only" in _group_text(root, "eval_nuisance_condition")
    secondary = root.find("svg:metadata[@id='eval-secondary-controls']", _SVG_NS)
    assert secondary is not None and json.loads(secondary.text or "") == ["channel-masked-only"]
    contrast = _group_text(root, "eval_paired_contrast")
    assert "Intact vs temporal-only" in contrast
    assert "Intact vs remove temporal context" in _group_text(
        root, "eval_removed_contrast_1",
    )
    assert "Intact vs remove channel masked" in _group_text(
        root, "eval_removed_contrast_2",
    )
    assert "each removal" not in contrast
    for index in (1, 2):
        path = root.find(f".//svg:g[@id='eval_removed_path_{index}']/svg:path", _SVG_NS)
        assert path is not None and "M476" in path.get("d", "")
        assert "M748" in path.get("d", "")
        left = root.find(f".//svg:g[@id='eval_removed_condition_{index}']/svg:rect", _SVG_NS)
        right = root.find(f".//svg:g[@id='eval_removed_contrast_{index}']/svg:rect", _SVG_NS)
        assert left is not None and right is not None
        assert int(left.get("y", "-1")) == int(right.get("y", "-2"))
        assert int(left.get("height", "-1")) == int(right.get("height", "-2"))
    assert "nuisance" not in contrast.casefold()
    assert "external test" in _group_text(root, "eval_locked_perturbation")
    assert "Unit: subject" in _group_text(root, "eval_group_split")
    assert "External group required" in _group_text(root, "eval_group_split")
    visible = " ".join(item.text or "" for item in root.findall(".//svg:text", _SVG_NS))
    assert "M1" not in visible and "perturbation" not in visible.casefold()
    bindings = {item["element_id"]: item["source_path"] for item in mappings}
    assert bindings["eval_locked_perturbation"] == "experiments/RUN_SPEC.json"
    assert bindings["eval_nuisance_condition"] == "experiments/METHOD_CONTRACT.json"
    assert bindings["eval_removed_condition_1"] == "experiments/METHOD_CONTRACT.json"
    assert bindings["eval_removed_condition_2"] == "experiments/METHOD_CONTRACT.json"
    assert svg_print_contract_issues(svg, root, {"scene_contract": {
        "target_width_fraction": 1.0, "minimum_placed_font_pt": 8.0,
    }}) == []
    assert float(root.get("height", "0")) / float(root.get("width", "1")) < 0.7
    assert _render_and_find_text_geometry(tmp_path, svg) == []


def test_many_controls_preserve_explicit_primary_and_all_secondary_conditions(
    tmp_path: Path,
) -> None:
    controls = ["temporal-only", "channel-masked-only", "autoregressive", "supervised",
                "no-pretraining", "capacity-matched", "extra-update", "deduplication",
                "temporal/channel correspondence shuffle", "subject/session probes"]
    svg, _ = _evaluation_design_svg({"method_brief": {
        "mechanism_nodes": [{"publication_name": "Complementary self-supervision"}],
        "study_conditions": ["remove temporal context", "remove channel masked"],
        "evaluation_contract": {
            "comparators_or_controls": controls,
            "primary_comparator": "temporal-only", "focal_condition": "Complementary self-supervision",
            "primary_outcomes": ["external-test macro-F1"],
        },
        "evaluation_protocol": {"primary_split": "external_test"},
    }})
    root = ET.fromstring(svg)
    assert "Intact vs temporal-only" in _group_text(root, "eval_paired_contrast")
    assert "not shown" not in svg
    for index, control in enumerate(controls[1:], start=1):
        assert control in _group_text(root, f"eval_secondary_condition_{index}")
    secondary = root.find("svg:metadata[@id='eval-secondary-controls']", _SVG_NS)
    assert secondary is not None and json.loads(secondary.text or "") == controls[1:]
    assert root.find(".//svg:g[@id='eval_removed_condition_2']", _SVG_NS) is not None
    assert _render_and_find_text_geometry(tmp_path, svg) == []


def test_explicit_primary_comparator_must_be_declared() -> None:
    with pytest.raises(ValueError, match="not a declared control"):
        _evaluation_design_svg({"method_brief": {
            "publication": {"method_name": "Treatment A"},
            "evaluation_contract": {
                "primary_comparator": "undeclared",
                "comparators_or_controls": ["placebo"],
                "primary_outcomes": ["response rate"],
            },
            "evaluation_protocol": {"primary_split": "external_test"},
        }})


def test_cross_domain_protocol_omits_unregistered_removal_and_heldout_claims(
    tmp_path: Path,
) -> None:
    svg, mappings = _evaluation_design_svg({
        "method_brief": {
            "publication": {"method_name": "Intervention A"},
            "evaluation_contract": {
                "comparators_or_controls": ["placebo"],
                "primary_comparator": "placebo",
                "primary_outcomes": ["clinical response rate"],
            },
            "evaluation_protocol": {"primary_split": "follow_up", "analysis_unit": "patient"},
        },
    })
    root = ET.fromstring(svg)
    assert root.find(".//svg:g[@id='eval_removed_condition']", _SVG_NS) is None
    assert root.find(".//svg:g[@id='eval_removed_contrast_1']", _SVG_NS) is None
    assert "Evaluation split" in _group_text(root, "eval_group_split")
    assert "follow up" in _group_text(root, "eval_locked_perturbation")
    assert "Declared contrasts" in svg
    assert "Focal vs placebo" in _group_text(root, "eval_paired_contrast")
    assert "Held-out test" not in svg and "paired seed" not in svg
    assert len(mappings) == 7
    assert _render_and_find_text_geometry(tmp_path, svg) == []


def test_excess_removals_require_companion_figures_instead_of_truncation() -> None:
    with pytest.raises(ValueError, match="split them into companion evaluation figures"):
        _evaluation_design_svg({"method_brief": {
            "publication": {"method_name": "Treatment A"},
            "study_conditions": [f"remove component {index}" for index in range(4)],
            "evaluation_contract": {
                "comparators_or_controls": ["standard care"],
                "primary_outcomes": ["response rate"],
            },
            "evaluation_protocol": {"primary_split": "external_test"},
        }})


@pytest.mark.parametrize("missing", ["comparator", "outcome", "split"])
def test_missing_evaluation_source_fact_fails_closed(missing: str) -> None:
    contract = {"comparators_or_controls": ["placebo"], "primary_outcomes": ["response"]}
    protocol = {"primary_split": "follow_up"}
    if missing == "comparator":
        contract["comparators_or_controls"] = []
    elif missing == "outcome":
        contract["primary_outcomes"] = []
    else:
        protocol.clear()
    with pytest.raises(ValueError, match="source contract missing"):
        _evaluation_design_svg({"method_brief": {
            "publication": {"method_name": "Intervention A"},
            "evaluation_contract": contract,
            "evaluation_protocol": protocol,
        }})


def test_internal_mechanism_id_in_old_label_contract_requires_regeneration() -> None:
    with pytest.raises(ValueError, match="internal mechanism IDs"):
        _evaluation_design_svg({
            "publication_labels": concept_labels(
                ["M1 Predictive encoder", "Matched removal", "Held-out test"],
                namespace="evaluation.term",
            ),
            "method_brief": {
                "mechanism_nodes": [{"publication_name": "Predictive encoder"}],
                "study_conditions": ["remove encoder"],
                "evaluation_contract": {
                    "comparators_or_controls": ["placebo"],
                    "primary_outcomes": ["response"],
                },
                "evaluation_protocol": {"primary_split": "external_test"},
            },
        })
