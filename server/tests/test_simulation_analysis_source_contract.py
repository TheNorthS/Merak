"""Report subtraction stays bound to declared axes and verified scientific files."""

from __future__ import annotations

import hashlib
from pathlib import Path

from server.services.simulation_asset_profile import simulation_asset_profile
from server.workflows.simulation_report_contract import report_role_headings
from server.workflows.simulation_result_analysis import (
    ROLE_HEADINGS, _assemble, _data_binding_issues, _role_sentence,
)


def test_declared_axis_wins_over_first_bookkeeping_column() -> None:
    rows = [{"row_id": "bookkeeping-1", "validation_fraction": "0.10", "value": "0.52"},
            {"row_id": "bookkeeping-2", "validation_fraction": "0.80", "value": "0.61"}]
    text = _role_sentence("training_dynamics", rows, "maximize", "validation_fraction")
    assert "validation fraction ranges from 0.10 to 0.80" in text
    assert "bookkeeping" not in text and "row id" not in text


def test_missing_declared_axis_never_falls_back_to_bookkeeping() -> None:
    text = _role_sentence("training_dynamics", [{"row_id": "bookkeeping", "value": "0.52"}], "maximize", "proof_stage")
    assert "declared scientific axis is not available" in text
    assert "bookkeeping" not in text


def test_clinical_role_names_project_from_frozen_domain_producer() -> None:
    profile = simulation_asset_profile({"family": "clinical_biomedical", "study_archetype": "diagnostic_prognostic"})
    manifest = {"research_family": "clinical_biomedical", "study_archetype": "diagnostic_prognostic",
                "asset_domain": "clinical", "domain_asset_profile": [
                    {"stable_role": item["completeness_role"], "domain_role": item["domain_asset_role"]}
                    for item in profile["assets"].values()
                ]}
    headings, issues = report_role_headings(manifest, ROLE_HEADINGS)
    assert issues == []
    assert headings["training_dynamics"] == "Validation trajectory"
    assert headings["error_analysis"] == "Prespecified subgroup outcome analysis"
    assert "Training dynamics" not in headings.values()


def test_conflicting_frozen_domain_role_does_not_get_a_plausible_heading() -> None:
    headings, issues = report_role_headings({
        "research_family": "clinical_biomedical", "study_archetype": "diagnostic_prognostic",
        "asset_domain": "clinical", "domain_asset_profile": [{"stable_role": "training_dynamics", "domain_role": "training_dynamics"}],
    }, ROLE_HEADINGS)
    assert headings == {} and issues


def test_hash_validation_includes_claim_and_provenance_sidecars(tmp_path: Path) -> None:
    path = tmp_path / "claim_evidence.csv"
    path.write_bytes(b"claim_id,decision\nC1,supported\n")
    manifest = {"data_files": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
                "evidence_package": {"paired_comparisons": path.name, "provenance_join_audit": path.name},
                "claim_evidence_contract": {"data_file": path.name}}
    assert _data_binding_issues(tmp_path, manifest) == []
    path.write_bytes(path.read_bytes() + b"changed")
    assert any("SHA-256 binding" in issue for issue in _data_binding_issues(tmp_path, manifest))


def test_used_sidecar_paths_must_be_declared_before_claims_or_provenance(tmp_path: Path) -> None:
    from server.workflows.simulation_result_analysis import _package_rows, _claim_rows
    path = tmp_path / "unbound.csv"
    path.write_bytes(b"claim_id,decision,supports_claim,claim_status\nC1,supported,true,supported\n")
    manifest = {"data_files": [{"path": "unrelated.csv", "sha256": "fake"}],
                "evidence_package": {"paired_comparisons": path.name, "provenance_join_audit": path.name},
                "claim_evidence_contract": {"data_file": path.name}}
    assert _package_rows(tmp_path, manifest, "paired_comparisons") == []
    assert _claim_rows(tmp_path, manifest) == []
    issues = _data_binding_issues(tmp_path, manifest)
    assert sum("not a declared hash-bound data file" in issue for issue in issues) == 3


def test_invalid_evidence_never_emits_complete_provenance_or_supported_claim(tmp_path: Path) -> None:
    text = _assemble(tmp_path, tmp_path / "SIMULATION_MANIFEST.json", {
        "metric_direction": "maximize", "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark", "asset_domain": "algorithmic",
        "simulation_id": "frozen", "simulation_seed": "13", "domain_asset_profile": [],
        "claim_ids": ["C1"],
    }, {"main_comparison": [{"source_run_id": "run", "simulation_seed": "13"}]}, ["data hash mismatch"], "Study")
    assert "## Package completeness" in text and "## Package identity status" in text
    assert "## Metric provenance and run identity" not in text
    assert "The joint decision is complete" not in text and "SUPPORTED" not in text


def test_calibration_analysis_uses_bound_risk_without_relabelling_generic_values():
    import copy
    from server.workflows.simulation_result_analysis import _role_sentence

    rows = [
        {"coverage": "0.50", "dataset": "A", "value": "0.032", "risk": "0.129", "risk_ci_low": "0.119", "risk_ci_high": "0.139"},
        {"coverage": "1.00", "dataset": "B", "value": "0.054", "risk": "0.217", "risk_ci_low": "0.207", "risk_ci_high": "0.227"},
    ]
    before = copy.deepcopy(rows)
    text = _role_sentence("calibration_risk_coverage", rows, "minimize", "coverage")
    assert "0.129 to 0.217" in text and "0.032 to 0.054" not in text
    assert "risk_ci_low/risk_ci_high" in text and "must not be substituted" in text
    assert "do not identify a within-population" in text
    assert rows == before


def test_partial_risk_records_are_rejected_instead_of_falling_back_to_value():
    import pytest
    from server.workflows.simulation_result_analysis import _role_sentence

    with pytest.raises(ValueError, match="lack complete"):
        _role_sentence("calibration_risk_coverage", [{"coverage": "0.5", "value": "0.03", "risk": "0.13"}],
                       "minimize", "coverage")


def test_report_range_uses_all_rows_not_first_and_last_method_endpoints():
    rows = [{"stress": "0.0", "value": "0.662"}, {"stress": "0.5", "value": "0.454"},
            {"stress": "0.0", "value": "0.711"}, {"stress": "0.5", "value": "0.567"}]
    text = _role_sentence("robustness_sensitivity", rows, "maximize", "stress")
    assert "from 0.454 to 0.711 over all rows" in text
    assert "not a within-method trend" in text
