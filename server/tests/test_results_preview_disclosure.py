"""Internal synthetic evidence reports can truthfully disclose their limitations."""

import pytest

from server.services import node_risk_audit  # Initialize the risk coordinator before its rule modules.
from server.services.risk_stage_results import _rule_2
from server.workflows.simulation_result_analysis import _assemble


@pytest.mark.parametrize("direction", [
    "EEG channel masking with explicitly labelled synthetic previews; no real EEG training.",
    "Simulation preview: planned sensor robustness study.",
    "NOT EXPERIMENTAL RESULTS — benchmark diagnostics only.",
])
def test_generated_analysis_disclosure_is_not_a_manuscript_label_violation(tmp_path, direction):
    text = _assemble(tmp_path, tmp_path / "manifest.json", {
        "metric_direction": "maximize", "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark", "asset_domain": "algorithmic",
        "simulation_id": "fixture", "simulation_seed": 13, "domain_asset_profile": [],
        "claim_ids": [],
    }, {}, ["fixture has no bound evidence"], direction)
    assert direction in text
    findings = []
    _rule_2(findings, {"non_experiment_evidence_mode": "synthetic_preview"}, tmp_path, set(), True, text)
    assert "RESULT-SIM-003" not in {item["id"] for item in findings}
    # Removing a presentation-only restriction must not waive evidence binding.
    assert "RESULT-SIM-001" in {item["id"] for item in findings}


def test_scope_requirement_still_blocks_unqualified_synthetic_results(tmp_path):
    findings = []
    _rule_2(findings, {"non_experiment_evidence_mode": "synthetic_preview"}, tmp_path, set(), True,
            "Our method is superior on every task.")
    assert {"RESULT-SIM-001", "RESULT-SIM-002"} <= {item["id"] for item in findings}
