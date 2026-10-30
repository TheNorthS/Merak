"""Composable semantic validation for deterministic simulation manifests."""

from __future__ import annotations

import re
from typing import Any

from .publication_figure_labels import validate_publication_labels


def version(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def core_issues(
    payload: dict[str, Any],
    *,
    schema: int,
    renderer: int,
    roles: tuple[str, ...],
    ids: dict[str, str],
    plot_families: dict[str, str],
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    if version(payload, "schema") < schema:
        issues.append(f"manifest schema is older than {schema}")
    if version(payload, "renderer_version") < renderer:
        issues.append(f"renderer version is older than {renderer}")
    metric = str(payload.get("primary_metric") or "").strip()
    direction = str(payload.get("metric_direction") or "").strip().casefold()
    if not metric:
        issues.append("primary_metric is missing")
    if direction not in {"maximize", "minimize"}:
        issues.append("metric_direction must be maximize or minimize")
    if str(payload.get("asset_domain") or "").strip().casefold() not in {
        "algorithmic", "clinical", "formal", "qualitative",
    }:
        issues.append("asset_domain is missing or unsupported")
    if tuple(payload.get("completeness_pack") or ()) != roles:
        issues.append("completeness_pack does not match the stable seven-role contract")
    profiles = {
        str(item.get("stable_role") or "").strip(): item
        for item in payload.get("domain_asset_profile") or []
        if isinstance(item, dict) and str(item.get("stable_role") or "").strip()
    }
    if set(profiles) != set(roles):
        issues.append("domain_asset_profile does not contain exactly seven stable roles")
    for role in roles:
        profile = profiles.get(role)
        if not isinstance(profile, dict):
            continue
        expected_direction = "minimize" if role in {"error_analysis", "calibration_risk_coverage"} else direction
        checks = (
            ("semantic_id", ids[role], f"{role} has an unstable semantic_id"),
            ("plot_family", plot_families[role], f"{role} must use plot_family {plot_families[role]}"),
            ("metric_direction", expected_direction, f"{role} has an inconsistent metric_direction"),
        )
        for field, expected, message in checks:
            if str(profile.get(field) or "").strip().casefold() != str(expected).casefold():
                issues.append(message)
        for field in ("data_file", "domain_role", "analysis_subtype", "label", "axis_field"):
            if not str(profile.get(field) or "").strip():
                issues.append(f"{role} has no {field}")
    return issues, {"direction": direction, "profiles": profiles}


def figure_issues(
    payload: dict[str, Any],
    *,
    ids: dict[str, str],
    plot_families: dict[str, str],
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    figures = {
        str(item.get("id") or "").strip(): item
        for item in payload.get("figure_files") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    observed: set[str] = set()
    for role, identity in ids.items():
        figure = figures.get(identity)
        if not isinstance(figure, dict):
            issues.append(f"{role} has no figure_files entry")
            continue
        if figure.get('producer_kind') != 'deterministic':
            issues.append(f'{role} figure must declare its deterministic producer')
        _, label_issues = validate_publication_labels(figure.get('publication_labels'))
        issues.extend(f'{role} figure: {issue}' for issue in label_issues)
        family = str(figure.get("plot_family") or "").strip()
        if family != plot_families[role]:
            issues.append(f"{role} figure must use plot_family {plot_families[role]}")
        if family:
            observed.add(family)
    if len(observed) < 6:
        issues.append("scientific figure pack must contain at least six distinct plot families")
    return issues, {"figures": figures, "observed_families": observed}


def claim_issues(
    payload: dict[str, Any],
    figures: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    claim_ids = [str(item).strip() for item in payload.get("claim_ids") or [] if str(item).strip()]
    claim_map = payload.get("claim_evidence_map")
    claim_map = claim_map if isinstance(claim_map, dict) else {}
    declared_data = {
        str(item.get("path") or "").strip()
        for item in payload.get("data_files") or []
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    if not claim_ids:
        issues.append("claim_ids are missing")
    if set(claim_map) != set(claim_ids):
        issues.append("claim_evidence_map does not cover exactly the declared claims")
    for claim_id in claim_ids:
        evidence = claim_map.get(claim_id)
        if not isinstance(evidence, dict):
            continue
        mapped_figures = {str(item).strip() for item in evidence.get("figure_ids") or [] if str(item).strip()}
        mapped_data = {str(item).strip() for item in evidence.get("data_files") or [] if str(item).strip()}
        if not mapped_figures or not mapped_figures.issubset(figures):
            issues.append(f"{claim_id} is not bound to valid figure evidence")
        if not mapped_data or not mapped_data.issubset(declared_data):
            issues.append(f"{claim_id} is not bound to valid result data")
        if not str(evidence.get("table") or "").strip():
            issues.append(f"{claim_id} has no result table binding")
    return issues, {
        "claim_ids": claim_ids, "claim_map": claim_map,
        "declared_data": declared_data,
    }


def claim_contract_issues(
    payload: dict[str, Any],
    claim_ids: list[str],
    claim_map: dict[str, Any],
    declared_data: set[str],
) -> list[str]:
    contract = payload.get("claim_evidence_contract")
    if contract is None:
        return []
    if not isinstance(contract, dict):
        return ["claim_evidence_contract is not an object"]
    issues: list[str] = []
    if version(contract, "schema") < 1:
        issues.append("claim_evidence_contract schema is missing or invalid")
    rows = [item for item in contract.get("rows") or [] if isinstance(item, dict) and str(item.get("row_id") or "").strip()]
    row_ids = {str(item.get("row_id") or "").strip() for item in rows}
    if len(row_ids) != len(rows):
        issues.append("claim_evidence_contract row IDs are not unique")
    covered = {str(item.get("claim_id") or "").strip() for item in rows if str(item.get("claim_id") or "").strip()}
    if not rows or covered != set(claim_ids):
        issues.append("claim_evidence_contract rows do not cover every declared claim")
    data_file = str(contract.get("data_file") or "").strip()
    if not data_file or data_file not in declared_data:
        issues.append("claim_evidence_contract has no bound data file")
    for claim_id in claim_ids:
        evidence = claim_map.get(claim_id) or {}
        claim_rows = [item for item in rows if str(item.get("claim_id") or "").strip() == claim_id]
        expected_rows = {str(item.get("row_id") or "").strip() for item in claim_rows}
        bound_rows = {str(item).strip() for item in evidence.get("evidence_row_ids") or [] if str(item).strip()}
        if not bound_rows or bound_rows != expected_rows:
            issues.append(f"{claim_id} is not bound exactly to its claim-specific evidence rows")
        outcomes = {str(item.get("registered_outcome") or "").strip() for item in claim_rows if str(item.get("registered_outcome") or "").strip()}
        required = {str(item).strip() for item in evidence.get("required_outcomes") or [] if str(item).strip()}
        if not required or required != outcomes:
            issues.append(f"{claim_id} required outcomes do not match its evidence rows")
        if data_file and data_file not in {str(item).strip() for item in evidence.get("data_files") or [] if str(item).strip()}:
            issues.append(f"{claim_id} is not bound to the claim evidence data file")
    return issues


def evidence_package_issues(
    payload: dict[str, Any],
    declared_data: set[str],
    *,
    extended: bool,
) -> list[str]:
    package = payload.get("evidence_package")
    if not isinstance(package, dict):
        return ["evidence_package is missing"]
    issues: list[str] = []
    required = {
        "run_level_results": "experiments/results/simulated/run_level_results.csv",
        "paired_comparisons": "experiments/results/simulated/paired_comparisons.csv",
        "run_ledger": "experiments/results/simulated/run_ledger.csv",
        "latency_samples": "experiments/results/simulated/latency_samples.csv",
    }
    if extended:
        required.update({
            "registered_axis_results": "experiments/results/simulated/registered_axis_results.csv",
            "provenance_join_audit": "experiments/results/simulated/provenance_join_audit.csv",
            "runtime_artifacts": "experiments/results/simulated/runtime_artifacts.json",
            "data_manifest": "experiments/results/simulated/data_manifest.csv",
            "raw_checkpoints": "experiments/results/simulated/raw_checkpoints.jsonl",
            "raw_predictions": "experiments/results/simulated/raw_predictions.jsonl",
            "raw_measurements": "experiments/results/simulated/raw_measurements.jsonl",
            "generator_source": "experiments/results/simulated/reproducibility/generator_source.py",
            "scenario_parameters": "experiments/results/simulated/reproducibility/scenario_parameters.json",
            "reconstruction_tool": "experiments/results/simulated/reproducibility/verify_bundle.py",
        })
    for key, expected in required.items():
        value = str(package.get(key) or "").strip().replace("\\", "/")
        if value != expected:
            issues.append(f"evidence_package {key} is missing or noncanonical")
        elif value not in declared_data:
            issues.append(f"evidence_package {key} is not hash-bound in data_files")
    if not str(package.get("reconstruction_contract") or "").strip():
        issues.append("evidence_package reconstruction_contract is missing")
    if extended:
        for path_key, hash_key in (
            ("generator_source", "generator_source_sha256"),
            ("scenario_parameters", "scenario_parameters_sha256"),
            ("scenario_config", "scenario_config_sha256"),
            ("run_spec", "run_spec_sha256"),
            ("method_contract", "method_contract_sha256"),
            ("reconstruction_tool", "reconstruction_tool_sha256"),
        ):
            if not str(package.get(path_key) or "").strip():
                issues.append(f"evidence_package {path_key} is missing")
            if not re.fullmatch(r"[0-9a-f]{64}", str(package.get(hash_key) or "").strip()):
                issues.append(f"evidence_package {hash_key} is invalid")
        if not str(package.get("reconstruction_command") or "").strip():
            issues.append("evidence_package reconstruction_command is missing")
        join = package.get("provenance_join_contract")
        join = join if isinstance(join, dict) else {}
        try:
            coverage = float(join.get("coverage") or 0.0)
        except (TypeError, ValueError):
            coverage = 0.0
        if not join.get("complete") or coverage != 1.0:
            issues.append("evidence_package provenance joins are incomplete")
    return issues


def ranking_issues(payload: dict[str, Any]) -> list[str]:
    models = [item for item in payload.get("registered_model_suite") or [] if isinstance(item, dict) and str(item.get("model_id") or "").strip() and str(item.get("method") or "").strip()]
    model_ids = {str(item.get("model_id") or "").strip() for item in models}
    axes = [item for item in payload.get("registered_ranking_axes") or [] if isinstance(item, dict) and str(item.get("axis_id") or "").strip()]
    axis_ids = {str(item.get("axis_id") or "").strip() for item in axes}
    issues: list[str] = []
    if len(models) < 2 or len(model_ids) != len(models):
        issues.append("registered_model_suite must contain at least two unique models")
    if not axes or len(axis_ids) != len(axes):
        issues.append("registered_ranking_axes must contain unique axis contracts")
    for axis in axes:
        if str(axis.get("direction") or "").strip().casefold() not in {"maximize", "minimize"}:
            issues.append("registered ranking axis has an invalid direction")
        try:
            float(axis.get("mpid"))
        except (TypeError, ValueError):
            issues.append("registered ranking axis has no numeric MPID")
    pair = payload.get("registered_pair_contract")
    pair = pair if isinstance(pair, dict) else {}
    unordered = len(model_ids) * max(0, len(model_ids) - 1) // 2
    expected = unordered * len(axis_ids)
    try:
        declared = int(pair.get("expected_comparison_count") or -1)
        observed = int(pair.get("observed_comparison_count") or -1)
    except (TypeError, ValueError):
        declared = observed = -1
    if not pair.get("complete") or declared != expected or observed != expected:
        issues.append("registered unordered-pair by axis comparison family is incomplete")
    reference_axes = sum(
        str(item.get("family_role") or "").casefold() == "primary_reference"
        or ("iid" in str(item.get("axis_id") or "").casefold() and "acc" in str(item.get("axis_id") or "").casefold())
        for item in axes
    )
    reference_count = unordered * reference_axes
    try:
        holm_size = int(pair.get("holm_family_size", -1))
        recorded_reference = int(pair.get("reference_row_count", -1))
    except (TypeError, ValueError):
        holm_size = recorded_reference = -1
    if (
        pair.get("pairing") != "all_unordered_pairs"
        or pair.get("holm_family_scope") != "unordered_model_pairs_by_non_iid_target_axis"
        or pair.get("test_method") != "paired_student_t_two_sided"
        or holm_size != expected - reference_count
        or recorded_reference != reference_count
    ):
        issues.append("registered non-i.i.d. Holm family contract is inconsistent")
    return issues
