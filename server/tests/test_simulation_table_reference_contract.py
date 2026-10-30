"""Contribution selection, source labels, CSV binding and authoring references agree."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from server.services.paper_asset_reference_contract import selected_reference_prompt, selected_publication_references
from server.services.paper_evidence import PaperEvidence
from server.services.paper_section_review import _required_preview_labels
from server.services.paper_stage_prompts import _synthetic_results_prompt
from server.services.paper_submission_tables import _synthetic_preview_entries
from server.services.simulation_asset_profile import simulation_asset_profile
from server.services.simulation_table_portfolio import (
    selected_simulation_table_bindings, simulation_table_bindings_from_manifest,
)
from server.services.simulation_table_projection import _select_manuscript_tables, _analysis_bodies


def _manifest(profile: dict) -> dict:
    roles = [("main_comparison", "main", "main_comparison.csv"),
             ("component_ablation", "sensitivity", "ablation.csv"),
             ("robustness_sensitivity", "robustness", "robustness.csv"),
             ("calibration_risk_coverage", "coverage", "calibration.csv"),
             ("error_analysis", "case_analysis", "error_analysis.csv"),
             ("efficiency_tradeoff", "burden", "efficiency.csv")]
    from server.services.simulation_policy import SIMULATION_STABLE_IDS
    return {"schema": 11, "renderer_version": 18, "domain_asset_profile": [
        {"stable_role": role, "semantic_id": SIMULATION_STABLE_IDS[role], "data_file": filename}
        for role, _key, filename in roles
    ], "data_files": [{"path": "experiments/results/simulated/" + filename, "sha256": "unused-fixture"}
                      for _role, _key, filename in roles]}


def _table_source(profile: dict) -> str:
    return "\n".join(rf"\begin{{table*}}\caption{{{role} outcomes}}\label{{{asset['table_label']}}}"
                     r"\begin{tabular}{ll}\midrule Named A & 0.73\\ Named B & 0.68\\\bottomrule\end{tabular}\end{table*}"
                     for role, asset in profile["assets"].items() if asset["table_label"])


def _project(root: Path) -> tuple[PaperEvidence, dict, str]:
    profile = simulation_asset_profile({"study_archetype": "algorithm_benchmark"})
    profile["contribution_type"] = "objective_mechanism"
    selected = _select_manuscript_tables(_table_source(profile), profile)
    data_root = root / "experiments/results/simulated"
    data_root.mkdir(parents=True)
    manifest = _manifest(profile)
    (data_root / "SIMULATION_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    for entry in manifest["data_files"]:
        (root / entry["path"]).write_text("method,score\nNamed A,0.73\nNamed B,0.68\n", encoding="utf-8")
    tables = root / "paper/tables"
    tables.mkdir(parents=True)
    (tables / "synthetic_preview_results.tex").write_text(selected, encoding="utf-8")
    evidence = PaperEvidence(root, "Study", "", "", "", "", "", "",
                             asset_plan={"evidence_mode": "synthetic_preview"},
                             selected_idea={"publication": {"contribution_type": "objective_mechanism"}})
    return evidence, profile, selected


def test_selected_registration_uses_exact_domain_filenames_and_source_labels(tmp_path) -> None:
    evidence, _profile, selected = _project(tmp_path)
    entries = _synthetic_preview_entries(evidence, tmp_path / "paper/tables")
    assert {item["label"] for item in entries} == set(re.findall(r"\\label\{([^}]+)\}", selected))
    assert len(entries) == 4
    paths = {item["data_path"] for item in entries}
    assert "experiments/results/simulated/robustness.csv" in paths
    assert "experiments/results/simulated/calibration.csv" in paths
    assert not any(path.endswith("robustness_sensitivity.csv") for path in paths)
    (tmp_path / "paper/tables/TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": entries}))
    prompt = _synthetic_results_prompt("algorithm_benchmark", "Declared comparisons", root=tmp_path)
    for entry in entries:
        assert rf"\ref{{{entry['label']}}}" in prompt
    for absent in ("tab:paired-reversals", "tab:preview-efficiency", "tab:preview-error-analysis"):
        assert rf"\ref{{{absent}}}" not in prompt


def test_authoring_manifest_excludes_unselected_complete_package_figures(tmp_path) -> None:
    evidence, _profile, _selected = _project(tmp_path)
    entries = _synthetic_preview_entries(evidence, tmp_path / "paper/tables")
    (tmp_path / "paper/tables/TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": entries}))
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [
        {"id": "selected", "metadata": {"label": "fig:selected", "scientific_role": "result", "paper_selected": True}},
        {"id": "unselected", "metadata": {"label": "fig:unselected", "scientific_role": "result", "paper_selected": False}},
    ]}))
    from server.services.paper_draft_stages import write_authoring_asset_manifest
    target = tmp_path / "paper/AUTHORING_ASSET_MANIFEST.json"
    write_authoring_asset_manifest(tmp_path, target, evidence_mode="synthetic_preview")
    authoring = json.loads(target.read_text())
    assert [item["label"] for item in authoring["figures"]] == ["fig:selected"]
    assert len(authoring["tables"]) == 4


def test_local_prose_checks_follow_selected_union_and_do_not_require_unselected_roles(tmp_path) -> None:
    evidence, _profile, _selected = _project(tmp_path)
    entries = _synthetic_preview_entries(evidence, tmp_path / "paper/tables")
    (tmp_path / "paper/tables/TABLE_MANIFEST.json").write_text(json.dumps({"schema": 3, "tables": entries}))
    from server.services.paper_asset_reference_contract import selected_result_analysis_requirements
    checks = {
        "comparison and apparent ordering": "comparison", "uncertainty interpretation": "interval",
        "component-ablation interpretation": "ablation", "robustness or stress interpretation": "shift",
        "calibration or selective-risk interpretation": "calibration", "training trend or convergence behavior": "training",
        "failure or error-slice interpretation": "error", "performance-resource trade-off": "tradeoff",
    }
    selected = selected_result_analysis_requirements(tmp_path, checks)
    assert set(selected) == {
        "comparison and apparent ordering", "uncertainty interpretation", "component-ablation interpretation",
        "robustness or stress interpretation", "calibration or selective-risk interpretation",
    }
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [{
        "id": "progression", "metadata": {"label": "fig:progression", "scientific_role": "analysis", "paper_selected": True},
    }]}))
    assert "training trend or convergence behavior" in selected_result_analysis_requirements(tmp_path, checks)


def test_missing_selected_source_label_is_a_blocker_not_silently_removed(tmp_path) -> None:
    evidence, _profile, selected = _project(tmp_path)
    target = tmp_path / "paper/tables/synthetic_preview_results.tex"
    target.write_text(selected.replace("tab:preview-calibration", "tab:undeclared-alternative"))
    with pytest.raises(ValueError, match="no current bound source"):
        _synthetic_preview_entries(evidence, target.parent)


def test_current_manifest_unsupported_or_unbound_profile_is_not_migrated() -> None:
    profile = simulation_asset_profile({})
    payload = _manifest(profile)
    payload["schema"] = 10
    with pytest.raises(ValueError, match="current schema"):
        simulation_table_bindings_from_manifest(payload, "objective_mechanism")
    payload["schema"] = 11
    payload["domain_asset_profile"][2]["data_file"] = "guessed_alias.csv"
    with pytest.raises(ValueError, match="frozen simulation profile"):
        simulation_table_bindings_from_manifest(payload, "objective_mechanism")


def test_label_selection_requires_one_real_source_block_for_every_declared_selected_role() -> None:
    profile = simulation_asset_profile({})
    profile["contribution_type"] = "objective_mechanism"
    text = _table_source(profile)
    selected = _select_manuscript_tables(text, profile)
    assert len(re.findall(r"\\label", selected)) == 4
    with pytest.raises(ValueError, match="missing or duplicate"):
        _select_manuscript_tables(text.replace("tab:preview-ablation", "tab:invented"), profile)
    with pytest.raises(ValueError, match="missing or duplicate"):
        _select_manuscript_tables(text + selected, profile)


def test_public_ablation_names_come_from_bound_conditions_not_machine_factor_ids() -> None:
    profile = {"sensitivity_field": "component_setting", "slice_field": "slice"}
    ablation = [{"component_setting": "Without Restricted task readout", "changed_factor": "registered_factor_1",
                 "delta": "-0.012", "primary_effect_vs_full": "-0.012"}]
    body = _analysis_bodies(ablation, [], [], [{"method": "Named control", **{
        f"resource_{index}": "0.5" for index in range(1, 6)
    }}], [], "missing_channel_rate", profile)["ABLATION_BODY"]
    assert "Without Restricted task readout" in body
    assert "registered" not in body
    assert "-0.012" in body


def test_public_source_preflight_checks_every_selected_table_body(tmp_path) -> None:
    from server.services.publication_table_policy import publication_table_issues
    table_dir = tmp_path / "tables"
    table_dir.mkdir()
    table = table_dir / "selected.tex"
    table.write_text(
        r"\begin{table}\midrule Named A & 0.73\\ Named B & 0.68\\\bottomrule\end{table}" + "\n"
        + r"\begin{table}\midrule Named A & " + "Long" * 60 + r"\\ Named B & 0.68\\\bottomrule\end{table}",
        encoding="utf-8",
    )
    assert any("paragraph-length" in issue for issue in publication_table_issues(tmp_path))
