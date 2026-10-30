"""Simulation statements cannot become scientific support without a bound rule."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from server.services.simulation_claim_decisions import DECISION_FIELDS, correct_claim_decisions
from server.services.simulation_claim_decision_report import build_claim_decision_report, primary_table_summary
from server.services.simulation_claim_evidence import claim_evidence_rows
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION
from server.services.simulation_ranking_evidence import RankingEvidence, paired_ranking_rows
from server.workflows.simulation_result_analysis import _claim_lines, _primary_sentence


def _row(claim_id="C1", outcome="The proposed objective improves held-out transfer"):
    return {"row_id": "claim-" + claim_id, "claim_id": claim_id, "registered_outcome": outcome,
            "value": "0.724", "ci_low": "0.716", "ci_high": "0.732", "seed_values": "0.7160|0.7240|0.7320",
            "seed": "13|42|73", "claim_status": "supported", "supports_claim": "true",
            "decision": "registered_outcome_observed", "decision_complete": "true",
            "evidence_kind": "mechanism readout", "analysis_unit": "random_seed"}


def _rule(qualifying=True):
    axes = [{"axis_id": "iid_accuracy", "metric_key": "accuracy", "direction": "maximize", "mpid": 0.01},
            {"axis_id": "shifted_nll", "metric_key": "shifted_nll", "direction": "minimize", "mpid": 0.01}]
    seeds = [13, 42, 73]
    values = {("reference", "iid_accuracy"): [0.60, 0.61, 0.62],
              ("candidate", "iid_accuracy"): [0.80, 0.81, 0.82],
              ("reference", "shifted_nll"): [0.70, 0.71, 0.72],
              ("candidate", "shifted_nll"): [0.90, 0.91, 0.92] if qualifying else [0.50, 0.51, 0.52]}
    paired = paired_ranking_rows(RankingEvidence([("Reference", "reference"), ("Candidate", "candidate")], values, []),
                                axes, seeds, 0.05, lambda axis: axis["axis_id"] == "iid_accuracy",
                                lambda row: {key: str(value) for key, value in row.items()})
    statement, outcome = "A ranking reversal occurs in the explicitly registered family.", "One registered cross-axis reversal"
    contract = {"model_ids": ["reference", "candidate"], "seed_ids": seeds, "axes": axes, "holm_alpha": 0.05}
    rule = {"schema": 1, "kind": "registered_cross_axis_reversal", "claim_id": "H17",
            "claim_statement": statement, "registered_outcomes": [outcome], **copy.deepcopy(contract),
            "reference_axis_id": "iid_accuracy", "minimum_qualifying_reversals": 1}
    selected = {"schema": 2, "claims": [{"id": "H17", "statement": statement}]}
    method = {"schema": 2, "claim_evidence_plan": [{"idea_claim_id": "H17", "outcomes": [outcome], "decision_rule": rule}]}
    return [_row("H17", outcome)], method, selected, paired, contract


def _correct(bundle):
    rows, method, selected, paired, contract = bundle
    return correct_claim_decisions(rows, method_contract=method, selected_contract=selected,
                                   paired_rows=paired, paired_contract=contract)


def test_unknown_scientific_claims_are_unresolved_not_assumed_supported_and_numbers_are_preserved():
    rows = [_row(), _row("C2", "Factorization is necessary"), _row("C3", "Robustness gain persists")]
    original = copy.deepcopy(rows)
    corrected = correct_claim_decisions(rows, method_contract={}, selected_contract={})
    assert {row["claim_status"] for row in corrected.rows} == {"unresolved"}
    assert {row["supports_claim"] for row in corrected.rows} == {"false"}
    assert {row["decision_complete"] for row in corrected.rows} == {"false"}
    for before, after in zip(rows, corrected.rows):
        assert {key: value for key, value in before.items() if key not in DECISION_FIELDS} == {
            key: value for key, value in after.items() if key not in DECISION_FIELDS}
    assert rows == original
    assert correct_claim_decisions(corrected.rows, method_contract={}, selected_contract={}).changes == ()


@pytest.mark.parametrize("qualifying,status", [(True, "supported"), (False, "not_supported")])
def test_explicit_complete_registered_reversal_rule_is_not_tied_to_c1(qualifying, status):
    bundle = _rule(qualifying)
    original = copy.deepcopy(bundle)
    corrected = _correct(bundle)
    assert corrected.rows[0]["claim_status"] == status
    assert corrected.rows[0]["decision_complete"] == "true"
    assert corrected.rows[0]["decision_scope"] == "registered_simulation_statistics_only"
    assert corrected.rows[0]["value"] == "0.724" and bundle == original


@pytest.mark.parametrize("defect", ["no_rule", "wrong_claim", "wrong_statement", "wrong_outcome", "wrong_models", "wrong_seeds", "wrong_axes",
                                  "missing_row", "duplicate_row", "foreign_row", "wrong_family", "fake_flag", "wrong_reference", "nonfinite"])
def test_missing_or_foreign_rule_and_false_statistical_flags_never_support_a_claim(defect):
    bundle = _rule()
    _rows, method, _selected, pairs, _contract = bundle
    rule = method["claim_evidence_plan"][0]["decision_rule"]
    if defect == "no_rule":
        method["claim_evidence_plan"][0].pop("decision_rule")
    elif defect in {"wrong_claim", "wrong_statement", "wrong_outcome", "wrong_models", "wrong_seeds", "wrong_axes"}:
        key, value = {"wrong_claim": ("claim_id", "C1"), "wrong_statement": ("claim_statement", "An unrelated scientific hypothesis"),
                      "wrong_outcome": ("registered_outcomes", ["Superiority to every comparator"]), "wrong_models": ("model_ids", ["other", "candidate"]),
                      "wrong_seeds": ("seed_ids", [1, 2, 3]), "wrong_axes": ("axes", [])}[defect]
        rule[key] = value
    elif defect == "missing_row":
        pairs.pop()
    elif defect == "duplicate_row":
        pairs.append(dict(pairs[0]))
    elif defect == "foreign_row":
        pairs[-1]["candidate_model_id"] = "foreign"
    elif defect == "wrong_family":
        pairs[-1]["family_size"] = "999"
    elif defect == "fake_flag":
        pairs[-1]["reversal_status"] = "no_qualifying_reversal"
    elif defect == "wrong_reference":
        pairs[-1]["iid_oriented_mean_effect"] = "+0.999"
    else:
        pairs[-1]["holm_adjusted_p"] = "nan"
    corrected = _correct(bundle)
    assert corrected.rows[0]["claim_status"] == "unresolved"
    assert corrected.rows[0]["supports_claim"] == "false" and corrected.rows[0]["decision_complete"] == "false"


def test_fresh_claim_producer_does_not_make_keyword_claims_supported_or_change_numeric_formula():
    rows = claim_evidence_rows(claim_ids=["C1", "C2"], method_contract={},
                              selected_contract={"claims": [{"id": "C1", "statement": "Frequency views improve transfer"},
                                                            {"id": "C2", "statement": "A paired Holm interval proves necessity"}]},
                              paired_rows=[], anchor=0.724, maximize_primary=True,
                              primary_metric="macro_f1", metric_direction="maximize", simulate=lambda row: dict(row))
    assert [row["value"] for row in rows] == ["0.724", "0.733"]
    assert {row["claim_status"] for row in rows} == {"unresolved"}
    assert {row["single_factor_matched"] for row in rows} == {"false"}


def _write_json(root: Path, relative: str, payload: dict):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(root: Path, name: str, rows: list[dict]) -> dict[str, str]:
    path = root / ("experiments/results/simulated/" + name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _report_fixture(root):
    primary = [{"method": method, "dataset": dataset, "metric": "macro_f1", "metric_direction": "maximize", "value": value}
               for method, scores in [("Focal", ["0.53", "0.57"]), ("Control", ["0.72", "0.76"])]
               for dataset, value in zip(["Target A", "Target B"], scores)]
    claim = _row()
    records = [_write_csv(root, "main_comparison.csv", primary), _write_csv(root, "claim_evidence.csv", [claim]),
               _write_csv(root, "paired_comparisons.csv", [{"row_id": "pair-1", "decision": "no_bound_rule"}])]
    manifest = {"schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
                "claim_ids": ["C1"], "data_files": records,
                "domain_asset_profile": [{"stable_role": "main_comparison", "data_file": "main_comparison.csv"}],
                "claim_evidence_contract": {"data_file": records[1]["path"], "rows": [
                    {key: claim[key] for key in ("row_id", "claim_id", "registered_outcome", "evidence_kind")}]},
                "evidence_package": {"paired_comparisons": records[2]["path"]}}
    _write_json(root, "experiments/results/simulated/SIMULATION_MANIFEST.json", manifest)
    _write_json(root, "experiments/METHOD_CONTRACT.json", {"schema": 2, "claim_evidence_plan": [{"idea_claim_id": "C1", "outcomes": [claim["registered_outcome"]]}]})
    _write_json(root, "ideas/SELECTED_IDEA.json", {"schema": 2, "claims": [{"id": "C1", "statement": claim["registered_outcome"]}]})
    return manifest, primary


def _hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}


def test_report_is_readonly_source_bound_and_report_consumer_does_not_trust_legacy_labels(tmp_path):
    manifest, primary = _report_fixture(tmp_path)
    before = _hashes(tmp_path)
    assert "value" not in DECISION_FIELDS and "seed_values" not in DECISION_FIELDS
    report = build_claim_decision_report(tmp_path)
    assert report == build_claim_decision_report(tmp_path) and _hashes(tmp_path) == before
    assert report["unresolved_claim_ids"] == ["C1"] and not report["scientific_execution_verified"]
    assert report["rows"][0]["value"] == "0.724" and report["rows"][0]["supports_claim"] == "false"
    assert report["primary_comparison"]["methods"][0]["target_macro_mean"] == pytest.approx(0.55)
    assert report["primary_comparison"]["methods"][0]["target_ranks"] == [2, 2]
    lines = "\n".join(_claim_lines(tmp_path, manifest))
    assert "C1 — UNRESOLVED" in lines and "C1 — SUPPORTED" not in lines
    assert "not an executed scientific study" in lines and _hashes(tmp_path) == before
    description = _primary_sentence(primary, "maximize")
    assert "Focal: target-macro mean 0.550000" in description and "Control: target-macro mean 0.740000" in description
    assert "strongest primary endpoint" not in description


@pytest.mark.parametrize("defect", ["claim_csv", "primary_csv", "paired_csv", "missing_binding", "foreign_path", "unsupported_schema", "claim_identity", "authored_outcome"])
def test_changed_scientific_sources_or_foreign_identity_are_rejected_before_audit(defect, tmp_path):
    manifest, _primary = _report_fixture(tmp_path)
    if defect.endswith("_csv"):
        filename = {"claim_csv": "claim_evidence.csv", "primary_csv": "main_comparison.csv", "paired_csv": "paired_comparisons.csv"}[defect]
        path = tmp_path / "experiments/results/simulated" / filename
        path.write_bytes(path.read_bytes() + b"changed")
    elif defect == "missing_binding":
        manifest["data_files"].pop()
    elif defect == "foreign_path":
        manifest["claim_evidence_contract"]["data_file"] = "../foreign.csv"
    elif defect == "claim_identity":
        manifest["claim_evidence_contract"]["rows"][0]["registered_outcome"] = "Foreign scientific claim"
    elif defect == "authored_outcome":
        method = json.loads((tmp_path / "experiments/METHOD_CONTRACT.json").read_text())
        method["claim_evidence_plan"][0]["outcomes"] = ["Changed scientific outcome"]
        _write_json(tmp_path, "experiments/METHOD_CONTRACT.json", method)
    else:
        manifest["schema"] -= 1
    _write_json(tmp_path, "experiments/results/simulated/SIMULATION_MANIFEST.json", manifest)
    before = _hashes(tmp_path)
    with pytest.raises((ValueError, OSError)):
        build_claim_decision_report(tmp_path)
    assert _hashes(tmp_path) == before


@pytest.mark.parametrize("defect", ["missing", "duplicate", "nonfinite", "direction"])
def test_primary_aggregation_refuses_subtraction_missing_targets_or_invalid_numbers(defect):
    rows = [{"method": method, "dataset": dataset, "metric": "error", "metric_direction": "minimize", "value": value}
            for method, values in [("Focal", ["0.1", "0.2"]), ("Control", ["0.3", "0.4"])]
            for dataset, value in zip(["A", "B"], values)]
    if defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows.append(dict(rows[0]))
    elif defect == "nonfinite":
        rows[0]["value"] = "nan"
    else:
        rows[0]["metric_direction"] = "maximize"
    with pytest.raises(ValueError):
        primary_table_summary(rows)


def test_primary_summary_preserves_minimize_and_tied_ranks():
    rows = [{"method": method, "dataset": "A", "metric": "error", "metric_direction": "minimize", "value": value}
            for method, value in [("A", "0.1"), ("B", "0.1"), ("C", "0.2")]]
    assert [item["target_ranks"] for item in primary_table_summary(rows)["methods"]] == [[1], [1], [3]]


def test_renderer_only_manifest_metadata_cannot_change_scientific_claim_text(tmp_path):
    manifest, _primary = _report_fixture(tmp_path)
    before = _claim_lines(tmp_path, manifest)
    manifest["renderer_version"] += 1
    manifest["generated_at"] = 12345
    _write_json(tmp_path, "experiments/results/simulated/SIMULATION_MANIFEST.json", manifest)
    assert _claim_lines(tmp_path, manifest) == before
