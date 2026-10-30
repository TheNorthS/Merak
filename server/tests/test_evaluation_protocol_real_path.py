"""Frozen multi-axis declarations reach the publication producer without guessing."""

from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from server.services.evaluation_design_contract import GENERIC_PLANNED_COMPARATORS
from server.services.evaluation_design_svg import _evaluation_design_svg, _condition_specs
from server.services.evaluation_design_content import evaluation_content
from server.services.evaluation_protocol_projection import project_evaluation_protocol
from server.services.evaluation_conditions_projection import project_evaluation_conditions
from server.services.figure_print_policy import svg_print_contract_issues
from server.services.scientific_asset_builders import design_assets, _evaluation_caption
from server.services.scientific_asset_contract import build_contract_context
from server.services.svg_variant_conversion import convert_svg_variants
from server.services.figure_svg_text_geometry import rendered_svg_text_geometry


AXES = ["subject", "site_dataset", "montage"]
CONDITIONS = [
    "Source-constrained shared representation",
    "Matched single-latent prediction control",
    "Informative latent-prediction control",
    "Structured latent-prediction control where reproducible",
    "Restricted-readout ablation with source-state task access",
    "Contrastive masked-prediction control",
]
NS = {"svg": "http://www.w3.org/2000/svg"}


def _run_spec() -> dict:
    return {
        "schema": 1,
        "evaluation": {"holdout_axes": AXES,
                       "primary_metric": "macro_f1 pooled by analysis_unit_id"},
        "data_requirements": {
            "analysis_unit": "independent subject; epochs remain nested observations",
            "manifest_paths": {axis: f"data/{axis}.jsonl" for axis in AXES},
        },
    }


def _config() -> dict:
    return {
        "data": {"active_holdout_axis": "subject",
                 "split_manifests": {axis: f"data/{axis}.jsonl" for axis in AXES}},
        "evaluation": {"holdout_axes": AXES, "analysis_unit_key": "analysis_unit_id", "primary_split": "subject held-out"},
    }


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _context(tmp_path: Path) -> dict:
    _write(tmp_path / "ideas/SELECTED_IDEA.json", {
        "schema": 2, "status": "accepted", "title": "Source-aware prediction",
        "hypothesis": "The restriction changes transfer.",
        "claims": [{"id": "C1", "publication_statement": "Transfer changes."}],
        "mechanisms": [{"id": "M1", "publication_name": "Shared/source latent factorization",
                        "publication_description": "Preserve task information."}],
        "publication": {"language": "en", "method_name": "Shared predictor",
                        "contribution_type": "objective_mechanism",
                        "comparator_names": CONDITIONS},
    })
    _write(tmp_path / "experiments/METHOD_CONTRACT.json", {
        "schema": 2, "status": "implemented",
        "evaluation_contract": {
            "primary_outcomes": ["Claim prose is not the quantitative endpoint."],
            "comparators_or_controls": list(GENERIC_PLANNED_COMPARATORS),
        },
        "scientific_scene": {"schema": 1, "objects": [
            {"id": "signal", "kind": "input", "label": "Observed signal",
             "source_path": "ideas/SELECTED_IDEA.json"},
            {"id": "shared", "kind": "operation", "label": "Shared representation",
             "source_path": "experiments/METHOD_CONTRACT.json"},
        ], "relations": [{"from": "signal", "to": "shared", "kind": "data"}]},
    })
    _write(tmp_path / "experiments/RUN_SPEC.json", _run_spec())
    _write(tmp_path / "experiments/configs/main.yaml", _config())
    return build_contract_context(tmp_path, lambda *_args: {})


def test_explicit_active_axis_preserves_all_declared_splits_and_sources() -> None:
    run, config = _run_spec(), _config()
    before = copy.deepcopy((run, config))
    protocol = project_evaluation_protocol(run, config)
    assert protocol["primary_split"] == "subject held-out"
    assert protocol["holdout_axes"] == AXES
    assert [item["manifest_path"] for item in protocol["declared_splits"]] == [
        f"data/{axis}.jsonl" for axis in AXES
    ]
    assert protocol["source_bindings"]["primary_split"] == {
        "source_path": "experiments/configs/main.yaml", "source_symbol": "evaluation.primary_split",
    }
    assert protocol["primary_metric_publication"] == "Macro-F1 (group-pooled)"
    assert (run, config) == before


def test_manifest_and_analysis_key_sources_remain_separate_from_split_declaration() -> None:
    run, config = _run_spec(), _config()
    run["data_requirements"].pop("manifest_paths")
    protocol = project_evaluation_protocol(run, config)
    split = protocol["declared_splits"][0]
    assert split["source_path"] == "experiments/RUN_SPEC.json"
    assert split["manifest_source_path"] == "experiments/configs/main.yaml"
    assert protocol["source_bindings"]["analysis_unit_key"]["source_symbol"] == (
        "evaluation.analysis_unit_key"
    )


def test_multiple_axes_without_explicit_selection_do_not_guess_first() -> None:
    config = _config()
    config["data"].pop("active_holdout_axis")
    config["evaluation"].pop("primary_split")
    protocol = project_evaluation_protocol(_run_spec(), config)
    assert "primary_split" not in protocol
    assert len(protocol["declared_splits"]) == 3
    with pytest.raises(ValueError, match="primary evaluation split"):
        _evaluation_design_svg({"method_brief": {
            "publication": {"method_name": "Treatment"},
            "evaluation_contract": {"comparators_or_controls": ["placebo"],
                                    "primary_outcomes": ["response"]},
            "evaluation_protocol": protocol,
        }})


@pytest.mark.parametrize("change,match", [
    ("active", "not a declared holdout axis"),
    ("axes", "different holdout axes"),
    ("manifest", "conflicting split manifest"),
])
def test_conflicting_execution_declarations_fail_without_rewriting(change: str, match: str) -> None:
    run, config = _run_spec(), _config()
    if change == "active":
        config["data"]["active_holdout_axis"] = "undeclared"
    elif change == "axes":
        config["evaluation"]["holdout_axes"] = ["subject"]
    else:
        config["data"]["split_manifests"]["subject"] = "different.jsonl"
    before = copy.deepcopy((run, config))
    with pytest.raises(ValueError, match=match):
        project_evaluation_protocol(run, config)
    assert (run, config) == before


def test_context_asset_and_svg_preserve_real_multi_axis_condition_path(tmp_path: Path) -> None:
    context = _context(tmp_path)
    context["adaptation_regimes"] = ["remove source state"]
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    asset = next(item for item in design_assets(context, {}, True)
                 if item["id"] == "evaluation_design")
    svg, mappings = _evaluation_design_svg(asset)
    root = ET.fromstring(svg)
    visible = " ".join(item.text or "" for item in root.findall(".//svg:text", NS))
    assert all(condition in visible for condition in CONDITIONS)
    assert "Intact vs" not in visible and "strongest declared prior work" not in visible
    assert "Matched removal" not in visible and "Declared removal" in visible
    assert "Macro-F1 (group-pooled)" in visible and "analysis_unit_id" not in visible
    assert "Shared/source latent factorization" in visible
    assert all(axis.replace("_", " ") + " held-out" in visible for axis in AXES)
    assert "Active execution axis: subject" in visible
    facts = json.loads(root.find("svg:metadata[@id='eval-declared-splits']", NS).text)
    assert [item["split_id"] for item in facts] == AXES
    assert len(root.findall(".//svg:g[@id='eval_declared_condition_1']", NS)) == 1
    sources = {item["element_id"]: item["source_path"] for item in mappings}
    assert sources["eval_declared_condition_1"] == "ideas/SELECTED_IDEA.json"
    assert sources["eval_decision_rule"] == "experiments/RUN_SPEC.json"
    assert "experiments/configs/main.yaml" in asset["source_data"]
    assert {path: path.read_bytes() for path in before} == before
    assert svg_print_contract_issues(svg, root, {"scene_contract": {
        "target_width_fraction": 1.0, "minimum_placed_font_pt": 8.0,
    }}) == []
    source, pdf, png = (tmp_path / f"evaluation.{suffix}" for suffix in ("svg", "pdf", "png"))
    source.write_text(svg, encoding="utf-8")
    converted, error = convert_svg_variants(source, pdf, png)
    assert converted, error
    assert rendered_svg_text_geometry(pdf) == []


def test_undeclared_condition_source_is_rejected_before_rendering(tmp_path: Path) -> None:
    context = _context(tmp_path)
    asset = next(item for item in design_assets(context, {}, True)
                 if item["id"] == "evaluation_design")
    asset["method_brief"]["evaluation_conditions"].pop("source_path")
    with pytest.raises(ValueError, match="source-bound facts"):
        _evaluation_design_svg(asset)


def test_explicit_named_method_comparison_remains_authoritative(tmp_path: Path) -> None:
    context = _context(tmp_path)
    context["method_contract"]["evaluation_contract"] = {
        "comparators_or_controls": ["Matched A", "Matched B"],
        "primary_comparator": "Matched B", "primary_outcomes": ["response"],
    }
    asset = next(item for item in design_assets(context, {}, True)
                 if item["id"] == "evaluation_design")
    assert asset["method_brief"]["evaluation_conditions"] == {}
    svg, _ = _evaluation_design_svg(asset)
    assert "Intact vs Matched B" in svg and "Shared predictor" in svg
    assert "Intact mechanism" in svg and "Shared/source latent factorization" in svg


def _plan(split: str) -> bytes:
    return ("# Registered evaluation\n\n| Field | Protocol | Evidence |\n|---|---|---|\n"
            f"| Primary split | {split} | Frozen group membership |\n").encode("utf-8")


@pytest.mark.parametrize("split,metric,public_metric", [
    ("Leave-one-dataset-out (LDO): one target is excluded from all fitting and selection", "macro_f1", "Macro-F1"),
    ("Held-out hospital cohort: an external hospital is excluded from model selection", "auroc", "AUROC"),
])
def test_explicit_plan_split_and_native_scientific_metric_project_without_changing_source(split, metric, public_metric):
    run = {"scientific_outputs": {"primary_metric": metric, "analysis_unit": "subject"}}
    before, plan = copy.deepcopy(run), _plan(split)
    protocol = project_evaluation_protocol(run, {}, plan_bytes=plan)
    assert protocol["primary_split"] == split.partition(":")[0]
    assert protocol["primary_metric"] == metric
    assert protocol["primary_metric_publication"] == public_metric
    assert protocol["source_bindings"]["primary_metric"] == {
        "source_path": "experiments/RUN_SPEC.json", "source_symbol": "scientific_outputs.primary_metric"}
    source = protocol["source_bindings"]["primary_split"]
    assert source == {"source_path": "experiments/EXPERIMENT_PLAN.md",
        "source_symbol": "markdown.table.Primary split:line:5",
        "source_sha256": hashlib.sha256(plan).hexdigest(), "source_text": split}
    assert run == before


def test_canonical_plan_context_reaches_typed_evaluation_producer_without_writing(tmp_path):
    context = _context(tmp_path)
    run = {"schema": 1, "scientific_outputs": {"primary_metric": "macro_f1", "analysis_unit": "subject"}}
    _write(tmp_path / "experiments/RUN_SPEC.json", run)
    _write(tmp_path / "experiments/configs/main.yaml", {})
    split = "Leave-one-dataset-out (LDO): exclude the target and keep source validation separate"
    plan = _plan(split)
    (tmp_path / "experiments/EXPERIMENT_PLAN.md").write_bytes(plan)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    context = build_contract_context(tmp_path, lambda *_arguments: {})
    asset = next(item for item in design_assets(context, {}, True) if item["id"] == "evaluation_design")
    content = evaluation_content(asset)
    assert content.primary_split == "Leave-one-dataset-out (LDO)"
    assert content.endpoint_label == "Macro-F1"
    assert content.declared_conditions == tuple(CONDITIONS)
    assert content.source_bindings["primary_split"]["source_sha256"] == hashlib.sha256(plan).hexdigest()
    assert "experiments/EXPERIMENT_PLAN.md" in asset["source_data"]
    assert {path: path.read_bytes() for path in before} == before


def test_explicit_structured_split_remains_primary_when_plan_agrees():
    run = {"scientific_outputs": {"primary_split": "external_test"}}
    protocol = project_evaluation_protocol(run, plan_bytes=_plan("external test: untouched cohort"))
    assert protocol["primary_split"] == "external_test"
    assert protocol["source_bindings"]["primary_split_plan"]["source_text"] == "external test: untouched cohort"


@pytest.mark.parametrize("raw,match", [
    (_plan("pending"), "lacks an explicit named split"),
    (_plan(""), "lacks an explicit named split"),
    (_plan("External test") + _plan("External test"), "multiple Primary split"),
    (_plan("External test") + _plan("Temporal held-out"), "multiple Primary split"),
    (b"\xff", "not UTF-8"),
    ("not source bytes", "must be raw bytes"),
])
def test_missing_or_ambiguous_registered_field_is_not_a_default(raw, match):
    with pytest.raises(ValueError, match=match):
        project_evaluation_protocol({}, plan_bytes=raw)


def test_no_primary_field_or_only_code_example_keeps_split_undeclared():
    assert project_evaluation_protocol({}, plan_bytes=b"# Study with no primary declaration\n") == {}
    code_example = b"```markdown\n| Primary split | External test | demo example |\n```\n"
    assert project_evaluation_protocol({}, plan_bytes=code_example) == {}
    with pytest.raises(ValueError, match="primary evaluation split"):
        evaluation_content({"method_brief": {"publication": {"method_name": "Named intervention"},
            "evaluation_contract": {"comparators_or_controls": ["Named control"], "primary_outcomes": ["Outcome"]},
            "evaluation_protocol": project_evaluation_protocol({}, plan_bytes=code_example)}})


def test_conflicting_structured_split_is_rejected_instead_of_overridden():
    run = {"scientific_outputs": {"primary_split": "Temporal held-out"}}
    before = copy.deepcopy(run)
    with pytest.raises(ValueError, match="primary splits conflict"):
        project_evaluation_protocol(run, plan_bytes=_plan("External hospital held-out: different primary population"))
    assert run == before


def test_conflicting_native_metric_is_rejected_instead_of_using_claim_prose():
    run = {"evaluation": {"primary_metric": "rmse"}, "scientific_outputs": {"primary_metric": "macro_f1"}}
    before = copy.deepcopy(run)
    with pytest.raises(ValueError, match="primary metrics conflict"):
        project_evaluation_protocol(run)
    assert run == before


def test_linked_or_foreign_plan_source_is_rejected_before_projection(tmp_path, monkeypatch):
    from server.services.scientific_asset_contract import _registered_plan_bytes

    project = tmp_path / "project"
    plan = project / "experiments/EXPERIMENT_PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_bytes(_plan("Registered held-out cohort"))
    before = plan.read_bytes()
    original = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                        tmp_path / "foreign/EXPERIMENT_PLAN.md" if path == plan else original(path, *args, **kwargs))
    with pytest.raises(ValueError, match="linked, foreign or not a file"):
        _registered_plan_bytes(project)
    assert plan.read_bytes() == before


@pytest.mark.parametrize("definition", [r"External test: retain A\|B metadata", r"External test: retain C:\logs\\"])
def test_plan_table_escaped_pipe_and_backslash_preserve_full_field_and_ignore_evidence_columns(definition):
    plan = _plan(definition).replace(b"Frozen group membership", b"Evidence | Additional evidence column")
    protocol = project_evaluation_protocol({}, plan_bytes=plan)
    assert protocol["primary_split"] == "External test"
    assert protocol["source_bindings"]["primary_split"]["source_text"] == definition
    assert protocol["source_bindings"]["primary_split"]["source_sha256"] == hashlib.sha256(plan).hexdigest()


def test_bold_table_field_is_explicit_but_duplicate_empty_field_is_ambiguous():
    plan = _plan("External test").replace(b"| Primary split |", b"| **Primary split** |")
    assert project_evaluation_protocol({}, plan_bytes=plan)["primary_split"] == "External test"
    with pytest.raises(ValueError, match="multiple Primary split"):
        project_evaluation_protocol({}, plan_bytes=plan + b"| Primary split | | Missing evidence |\n")


@pytest.mark.parametrize("active", [None, "subject"])
def test_primary_scope_is_not_compared_with_generated_axis_caption(active):
    run = {"scientific_outputs": {"primary_split": "External test"},
           "evaluation": {"holdout_axes": ["subject"]}}
    config = {"data": {"active_holdout_axis": active}} if active else {}
    before = copy.deepcopy((run, config))
    protocol = project_evaluation_protocol(run, config, plan_bytes=_plan("External test: distinct cohort"))
    assert protocol["primary_split"] == "External test"
    assert protocol["holdout_axes"] == ["subject"]
    assert (run, config) == before


NATIVE_CONDITIONS = ["CSFS joint shared-private objective", "BENDR-style contextual contrastive pretraining",
    "Waveform or latent masked-prediction pretraining", "Channel-subset-only shared objective",
    "Frequency-view-only shared objective", "Full-latent alignment without private factorization",
    "Shuffled cross-view pairing control", "Random initialization"]


def _comparison_brief(conditions=None):
    return {"publication": {"method_name": "CSFS", "comparator_names": list(NATIVE_CONDITIONS)},
        "mechanism_nodes": [{"name": "Channel-subset shared structure"}],
        "evaluation_contract": {"comparators_or_controls": list(conditions or NATIVE_CONDITIONS),
            "primary_outcomes": ["Measured endpoint"]},
        "evaluation_protocol": {"primary_split": "Leave-one-dataset-out (LDO)",
            "primary_metric_publication": "Macro-F1"}}


@pytest.mark.parametrize("order", [NATIVE_CONDITIONS, list(reversed(NATIVE_CONDITIONS)),
                                   NATIVE_CONDITIONS[2:] + NATIVE_CONDITIONS[:2]])
def test_named_native_conditions_never_infer_first_control_or_mechanism_as_focal(order):
    brief = _comparison_brief(order)
    before = copy.deepcopy(brief)
    projection = project_evaluation_conditions({"evaluation_contract": brief["evaluation_contract"]}, brief["publication"])
    assert projection["conditions"] == order
    assert projection["source_path"] == "experiments/METHOD_CONTRACT.json"
    assert projection["source_symbol"] == "evaluation_contract.comparators_or_controls"
    content = evaluation_content({"method_brief": brief})
    assert content.declared_conditions == tuple(order)
    assert content.focal_name == "CSFS" and content.comparator_name == "" and content.secondary_controls == ()
    rows = _condition_specs(content)
    assert len(rows) == 8 and {row[2] for row in rows} == set(NATIVE_CONDITIONS)
    assert all(row[1] == "Declared condition" and row[3] == "Macro-F1" for row in rows)
    caption = _evaluation_caption({**brief, "evaluation_conditions": projection})
    assert "Condition labels are shown in the diagram" in caption
    assert "does not enumerate the complete mechanism-test family" in caption
    svg, _ = _evaluation_design_svg({"method_brief": brief,
        "source_data": ["experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json"]})
    visible = " ".join(ET.fromstring(svg).itertext())
    assert all(name in visible for name in NATIVE_CONDITIONS)
    assert "Additional declared controls" not in caption
    assert brief == before


def test_source_bound_explicit_primary_and_whole_method_focal_keep_comparison_role():
    brief = _comparison_brief()
    brief["evaluation_contract"].update(primary_comparator=NATIVE_CONDITIONS[1], focal_condition=NATIVE_CONDITIONS[0])
    before = copy.deepcopy(brief)
    assert project_evaluation_conditions({"evaluation_contract": brief["evaluation_contract"]}, brief["publication"]) == {}
    content = evaluation_content({"method_brief": brief})
    assert content.declared_conditions == ()
    assert content.focal_name == NATIVE_CONDITIONS[0] and content.comparator_name == NATIVE_CONDITIONS[1]
    assert content.source_bindings["focal_condition"] == {
        "source_path": "experiments/METHOD_CONTRACT.json", "source_symbol": "evaluation_contract.focal_condition"}
    assert content.source_bindings["primary_comparator"]["source_symbol"] == "evaluation_contract.primary_comparator"
    assert brief == before


@pytest.mark.parametrize("defect,match", [("same_role", "must be distinct"),
    ("undeclared", "not a declared control"), ("missing_focal", "requires a declared focal condition"),
    ("empty_condition", "must contain names")])
def test_invalid_explicit_roles_or_empty_named_conditions_fail_closed(defect, match):
    brief = _comparison_brief()
    contract = brief["evaluation_contract"]
    contract.update(primary_comparator=NATIVE_CONDITIONS[1], focal_condition=NATIVE_CONDITIONS[0])
    if defect == "same_role":
        contract["focal_condition"] = contract["primary_comparator"]
    elif defect == "undeclared":
        contract["primary_comparator"] = "Unknown control"
    elif defect == "missing_focal":
        contract.pop("focal_condition")
        brief["publication"].pop("method_name")
    else:
        contract.pop("primary_comparator")
        contract["comparators_or_controls"].append("")
    with pytest.raises(ValueError, match=match):
        evaluation_content({"method_brief": brief})


def test_neutral_named_conditions_keep_independent_typed_removal_lanes_and_bindings():
    brief = _comparison_brief()
    brief["study_conditions"] = ["remove shared-private factorization", "remove spectral pairing"]
    original = copy.deepcopy(brief)
    content = evaluation_content({"method_brief": brief})
    rows = _condition_specs(content)
    assert content.removal_conditions == tuple(brief["study_conditions"])
    assert {row[2] for row in rows} == set(NATIVE_CONDITIONS + brief["study_conditions"])
    assert len(rows) == 10 and all("Intact" not in row[3] for row in rows)
    svg, mappings = _evaluation_design_svg({"method_brief": brief,
        "source_data": ["experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json"]})
    root = ET.fromstring(svg)
    visible = " ".join(item.text or "" for item in root.findall(".//svg:text", NS))
    assert "Alternative control" not in visible and "not shown" not in visible
    assert "Intact reference" not in visible and "Declared removal" in visible
    assert all(any(mapping["element_id"] == f"eval_removed_condition_{index}"
                   and mapping["source_path"] == "experiments/METHOD_CONTRACT.json" for mapping in mappings)
               for index in (1, 2))
    assert svg_print_contract_issues(svg, root, {"scene_contract": {
        "target_width_fraction": 1.0, "minimum_placed_font_pt": 8.0}}) == []
    assert brief == original


def test_explicit_primary_keeps_every_control_and_independent_removal_in_source_rows():
    brief = _comparison_brief()
    brief["evaluation_contract"].update(primary_comparator=NATIVE_CONDITIONS[1], focal_condition=NATIVE_CONDITIONS[0])
    brief["study_conditions"] = ["remove spectral pairing"]
    content = evaluation_content({"method_brief": brief})
    rows = _condition_specs(content)
    assert {row[2] for row in rows} == {*NATIVE_CONDITIONS, "remove spectral pairing"}
    assert sum(row[1] == "Matched removal" for row in rows) == 1
    assert sum(row[1] == "Alternative control" for row in rows) == 1
    assert sum(row[1] == "Declared control" for row in rows) == 6
    assert content.source_bindings["focal_condition"]["source_symbol"] == "evaluation_contract.focal_condition"


def test_native_eight_condition_svg_contains_all_names_with_no_inferred_alternative_role():
    brief = _comparison_brief()
    svg, mappings = _evaluation_design_svg({"method_brief": brief,
        "source_data": ["experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json"]})
    root = ET.fromstring(svg)
    visible = " ".join(item.text or "" for item in root.findall(".//svg:text", NS))
    assert all(name in visible for name in NATIVE_CONDITIONS)
    assert "Intact" not in visible and "Alternative control" not in visible and "not shown" not in visible
    assert len([mapping for mapping in mappings if mapping["semantic_role"] == "source-declared study condition"]) == 8
    assert svg_print_contract_issues(svg, root, {"scene_contract": {
        "target_width_fraction": 1.0, "minimum_placed_font_pt": 8.0}}) == []


def test_exact_focal_in_declared_inventory_is_shown_once_not_recast_as_secondary_control():
    brief = _comparison_brief(["Full method", "Primary anchor", "Secondary anchor"])
    brief["evaluation_contract"].update(focal_condition="Full method", primary_comparator="Primary anchor")
    content = evaluation_content({"method_brief": brief})
    rows = _condition_specs(content)
    assert [row[2] for row in rows] == ["Full method", "Primary anchor", "Secondary anchor"]
    assert content.secondary_controls == ("Secondary anchor",)
    caption = _evaluation_caption(brief)
    assert caption.endswith("Additional declared controls: Secondary anchor.")
    assert "Full method" not in caption
