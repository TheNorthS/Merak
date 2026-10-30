from __future__ import annotations

import json
from pathlib import Path

from server.services.experiment_placeholder_context import (
    infer_primary_metric,
    metric_direction,
    simulation_domain_context,
)
from server.services.simulation_artifact_io import clear_simulation_preview
from server.services.simulation_asset_profile import simulation_asset_profile
from server.services.experiment_placeholders import experiment_placeholder_service


def test_asset_profile_keeps_stable_roles_across_research_domains() -> None:
    expected = {
        "main_comparison", "component_ablation", "training_dynamics",
        "robustness_sensitivity", "error_analysis",
        "calibration_risk_coverage", "efficiency_tradeoff",
    }
    for family, archetype in (
        ("machine_learning", "algorithm_benchmark"),
        ("clinical_biomedical", "diagnostic_prognostic"),
        ("theoretical_formal", "formal_theory"),
        ("qualitative_humanities", "qualitative_mixed"),
    ):
        profile = simulation_asset_profile({
            "family": family, "study_archetype": archetype,
        })
        assert {asset["completeness_role"] for asset in profile["assets"].values()} == expected


def test_selected_contract_controls_specialized_domain() -> None:
    selected = simulation_domain_context(
        Path("."), direction="",
        selected_contract={"title": "Cross-domain image classifier"},
        method_contract={}, configured_contract={},
    )
    profile = simulation_asset_profile({}, selected)
    assert profile["specialized_domain"] == "vision"

    generic = simulation_domain_context(
        Path("."), direction="",
        selected_contract={"title": "Generic registered benchmark"},
        method_contract={}, configured_contract={},
    )
    generic_profile = simulation_asset_profile({}, generic)
    assert "specialized_domain" not in generic_profile


def test_metric_contract_prefers_explicit_direction_and_endpoint() -> None:
    assert metric_direction("RMSE") == "minimize"
    assert metric_direction("RMSE", "maximize") == "maximize"
    assert infer_primary_metric("image classification") == "Accuracy"
    assert infer_primary_metric("ignored", "AUROC") == "AUROC"


def test_cleanup_only_removes_managed_paths_inside_project(tmp_path: Path) -> None:
    simulated = tmp_path / "experiments" / "results" / "simulated"
    simulated.mkdir(parents=True)
    managed = simulated / "main_comparison.csv"
    managed.write_text("managed", encoding="utf-8")
    user_file = simulated / "user_notes.csv"
    user_file.write_text("keep", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("keep", encoding="utf-8")
    (simulated / "SIMULATION_MANIFEST.json").write_text(json.dumps({
        "data_files": [
            {"path": "experiments/results/simulated/main_comparison.csv"},
            {"path": f"../{outside.name}"},
        ],
    }), encoding="utf-8")

    clear_simulation_preview(tmp_path)

    assert not managed.exists()
    assert user_file.read_text(encoding="utf-8") == "keep"
    assert outside.read_text(encoding="utf-8") == "keep"
    outside.unlink()


def test_all_simulation_plot_builders_emit_valid_python() -> None:
    service = experiment_placeholder_service
    scripts = [
        service._bar_script("x.csv", "method", "Accuracy", "x", {}),
        service._robustness_script("x.csv", "severity", "Accuracy", {}),
        service._ablation_delta_script("x.csv", "method", "Accuracy", "x", {}, "Full", "maximize"),
        service._multitask_matrix_script("x.csv", "Accuracy", "x", {}, "maximize"),
        service._eeg_scaling_script("x.csv", "hours", "Accuracy", {}, "x"),
        service._domain_error_heatmap_script("x.csv", "slice", "Error", "x", {}),
        service._domain_efficiency_script("x.csv", "Accuracy", {}, "x"),
        service._eeg_shift_script("x.csv", "Accuracy", "x", {}),
        service._slice_risk_bar_script("x.csv", "slice", "Risk", "x", {}, "Overall"),
        service._risk_coverage_script("x.csv", {}),
        service._efficiency_script("x.csv", "Accuracy", "latency", "Latency", {}),
    ]
    for script in scripts:
        compile(script, "generated_simulation_plot.py", "exec")
