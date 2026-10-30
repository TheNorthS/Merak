"""Build benchmark analysis only from registered, hash-verified simulation tables.

The manifest owns data identity; this module owns the corresponding analytical
text. Renderer-only changes must not alter the semantic analysis binding.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from ..services.manuscript_text import atomic_write_text
from ..services.paper_artifacts import simulation_manifest_semantic_hash
from .models import WorkflowRun
from .simulation_report_contract import report_role_headings


ROLE_HEADINGS = {
    "main_comparison": "Primary comparison",
    "component_ablation": "Component analysis",
    "training_dynamics": "Training dynamics",
    "robustness_sensitivity": "Robustness and sensitivity",
    "error_analysis": "Failure and error analysis",
    "calibration_risk_coverage": "Calibration and selective risk",
    "efficiency_tradeoff": "Performance--resource trade-off",
}


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error):
        return []


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "/").split())


def _number(value: Any) -> float:
    try:
        return float(str(value or "").strip())
    except (TypeError, ValueError):
        return 0.0


def _manifest_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("path") or "").replace("\\", "/"): str(item.get("sha256") or "")
        for item in manifest.get("data_files") or []
        if isinstance(item, dict)
    }


def _verified_rows(
    root: Path,
    simulated: Path,
    profile: dict[str, Any],
    hashes: dict[str, str],
) -> tuple[list[dict[str, str]], str]:
    filename = str(profile.get("data_file") or "").strip()
    if not filename:
        return [], "data file is not declared"
    path = (simulated / filename).resolve()
    try:
        path.relative_to(simulated.resolve())
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return [], "data file leaves the simulation directory"
    expected = hashes.get(relative, "")
    if not expected or not path.is_file():
        return [], f"{relative} is missing or not hash-bound"
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        return [], f"{relative} does not match its SHA-256 binding"
    rows = _csv_rows(path)
    return rows, "" if rows else f"{relative} contains no records"


def _table_inventory(
    root: Path,
    simulated: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    hashes = _manifest_hashes(manifest)
    tables: dict[str, list[dict[str, str]]] = {}
    issues = _data_binding_issues(root, manifest)
    observed = set()
    for profile in manifest.get("domain_asset_profile") or []:
        if not isinstance(profile, dict):
            continue
        role = str(profile.get("stable_role") or "")
        if role not in ROLE_HEADINGS:
            continue
        if role in observed:
            issues.append(f"{role}: duplicate registered analysis profile")
        observed.add(role)
        rows, issue = _verified_rows(root, simulated, profile, hashes)
        axis = str(profile.get("axis_field") or "")
        if rows and (not axis or any(axis not in row for row in rows)):
            issue = f"{role}: registered analysis axis is absent from its data rows"
            rows = []
        tables[role] = rows
        if issue:
            issues.append(f"{role}: {issue}")
    if observed != set(ROLE_HEADINGS):
        issues.append("The benchmark analysis profile does not cover exactly its seven registered scientific roles")
    return tables, issues


def _data_binding_issues(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Claims, paired outcomes and provenance are evidence too, not unverified sidecars."""
    records = manifest.get("data_files")
    if not isinstance(records, list) or not records:
        return ["The benchmark analysis has no declared data file bindings"]
    issues, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            issues.append("A benchmark analysis data binding is not a record")
            continue
        relative = str(record.get("path") or "")
        candidate = (root / relative).resolve()
        if relative in seen:
            issues.append(f"{relative}: duplicate benchmark data binding")
        seen.add(relative)
        if not relative or not candidate.is_relative_to(root) or not candidate.is_file():
            issues.append(f"{relative}: benchmark data file is absent or outside its project")
        elif not record.get("sha256") or hashlib.sha256(candidate.read_bytes()).hexdigest() != record["sha256"]:
            issues.append(f"{relative} does not match its SHA-256 binding")
    package = manifest.get("evidence_package")
    package = package if isinstance(package, dict) else {}
    claim = manifest.get("claim_evidence_contract")
    claim = claim if isinstance(claim, dict) else {}
    for name, relative in (("paired comparisons", package.get("paired_comparisons")),
                           ("provenance join audit", package.get("provenance_join_audit")),
                           ("claim evidence", claim.get("data_file"))):
        if not isinstance(relative, str) or relative not in seen:
            issues.append(f"The {name} report input is not a declared hash-bound data file")
    return issues


def _primary_sentence(rows: list[dict[str, str]], direction: str) -> str:
    if not rows:
        return "No hash-verified rows are available for this registered analysis."
    from ..services.simulation_claim_decision_report import primary_table_summary

    try:
        summary = primary_table_summary(rows)
    except (KeyError, TypeError, ValueError) as error:
        return f"The complete matched primary comparison cannot be interpreted: {error}."
    descriptions = [f"{_clean(item['method'])}: target-macro mean {item['target_macro_mean']:.6f}, "
                    f"target ranks {','.join(map(str, item['target_ranks']))}/{item['condition_count']}"
                    for item in summary["methods"]]
    return (f"Across all {len(summary['datasets'])} registered targets, " + "; ".join(descriptions) + ". "
            "These are descriptive simulation-table aggregates, not trained empirical outcomes. "
            "Every original row's nominal 95% seed-summary interval remains in the registered table; "
            "these summaries do not supply a new aggregate confidence interval or a claim decision.")


def _role_sentence(
    role: str,
    rows: list[dict[str, str]],
    direction: str,
    axis: str,
) -> str:
    if role == "main_comparison":
        return _primary_sentence(rows, direction)
    if not rows:
        return "No hash-verified rows are available for this registered analysis."
    if not axis or any(axis not in row for row in rows):
        return "The declared scientific axis is not available in the registered data."
    if role == "calibration_risk_coverage" and any("risk" in row for row in rows):
        return _calibration_sentence(rows)
    first, last = rows[0], rows[-1]
    import math
    values = [float(row["value"]) for row in rows]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Registered analysis endpoints must be finite")
    lowest, highest = rows[values.index(min(values))], rows[values.index(max(values))]
    return (
        f"Across {len(rows)} registered rows, {axis.replace('_', ' ')} ranges from "
        f"{_clean(first.get(axis))} to {_clean(last.get(axis))}; the endpoint ranges "
        f"from {_clean(lowest.get('value'))} to {_clean(highest.get('value'))} over all rows. "
        "This is the complete-row endpoint range, not a within-method trend. "
        "Seed-summary intervals and boundary cases remain in the registered table."
    )


def _calibration_sentence(rows: list[dict[str, str]]) -> str:
    """Name the published risk field; a generic value column is not the same estimand."""
    import math

    required = ("risk", "risk_ci_low", "risk_ci_high", "coverage")
    if any(any(not str(row.get(key) or "").strip() for key in required) for row in rows):
        raise ValueError("Calibration risk records lack complete bound risk, interval or coverage fields")
    values = [{key: float(row[key]) for key in required} for row in rows]
    if any(not all(math.isfinite(value) for value in row.values())
           or not row["risk_ci_low"] <= row["risk"] <= row["risk_ci_high"] for row in values):
        raise ValueError("Calibration risk records contain invalid numeric bounds")
    low, high = min(row["risk"] for row in values), max(row["risk"] for row in values)
    coverage = (min(row["coverage"] for row in values), max(row["coverage"] for row in values))
    return (f"Across {len(rows)} registered rows, the publication table/figure uses the explicit risk field, "
        f"which ranges from {low:.3f} to {high:.3f}, with coverage from {coverage[0]:.2f} to {coverage[1]:.2f}. "
        "Its bounds are risk_ci_low/risk_ci_high; generic value/ci_low/ci_high columns describe a different "
        "recorded quantity and must not be substituted for selective risk. The seed_values column does not "
        "by itself establish the generation or inferential coverage of the separate risk bounds. "
        "Where dataset/task changes alongside coverage, these rows do not identify a within-population "
        "risk--coverage trend. Preserve all frozen values and distinguish the field definitions explicitly.")


def _package_rows(
    root: Path, manifest: dict[str, Any], key: str
) -> list[dict[str, str]]:
    package = manifest.get("evidence_package")
    package = package if isinstance(package, dict) else {}
    relative = str(package.get(key) or "")
    rows, _issue = _verified_rows(root, root, {"data_file": relative}, _manifest_hashes(manifest))
    return rows


def _paired_family(root: Path, manifest: dict[str, Any]) -> list[str]:
    pairs = _package_rows(root, manifest, "paired_comparisons")
    joins = _package_rows(root, manifest, "provenance_join_audit")
    contract = manifest.get("registered_pair_contract")
    contract = contract if isinstance(contract, dict) else {}
    count = int(contract.get("observed_comparison_count") or len(pairs))
    model_count = int(
        contract.get("model_count")
        or len(
            {
                value
                for row in pairs
                for value in (
                    row.get("reference_model_id"),
                    row.get("candidate_model_id"),
                )
                if value
            }
        )
    )
    complete = sum(
        _clean(row.get("join_complete")).casefold() in {"true", "1", "yes"}
        for row in joins
    )
    return [
        "## Registered cross-axis paired family",
        "",
        f"The complete family contains {count} unordered paired comparisons across "
        f"{model_count} declared models. Each row retains matched seeds, oriented "
        "effects, paired interval fields, practical thresholds, and "
        "Holm-adjusted decisions.",
        ("Bootstrap interval fields attest actual percentile resampling of paired seed effects; "
         "they do not resample subjects, datasets or acquisition sites."
         if pairs and all(row.get("bootstrap_method") == "paired_seed_percentile_v1" for row in pairs)
         else "The frozen bootstrap_ci fields have no verified resampling-method provenance. "
         "They must not be described as bootstrap confidence intervals or used as confirmatory evidence; "
         "retain the original bytes and request an explicit new evidence version to replace them."),
        f"Provenance joins are complete for {complete} of {len(joins)} ledger rows. "
        "Complete pair inventory does not establish that frozen claims have been adjudicated.",
        "",
    ]


def _claim_rows(root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    contract = manifest.get("claim_evidence_contract")
    contract = contract if isinstance(contract, dict) else {}
    relative = str(contract.get("data_file") or "")
    rows, _issue = _verified_rows(root, root, {"data_file": relative}, _manifest_hashes(manifest))
    return rows


def _claim_lines(root: Path, manifest: dict[str, Any]) -> list[str]:
    from ..services.simulation_claim_decision_report import build_claim_decision_report

    lines = ["## Claim-level interpretation", ""]
    try:
        report = build_claim_decision_report(root)
    except (OSError, KeyError, TypeError, ValueError) as error:
        return [*lines, f"Claims remain UNRESOLVED: current source-bound decision audit failed: {_clean(error)}.", ""]
    rows = report["rows"]
    for claim_id in [str(value) for value in manifest.get("claim_ids") or []]:
        bound = [row for row in rows if _clean(row.get("claim_id")) == claim_id]
        supported = bool(bound) and all(
            _clean(row.get("supports_claim")).casefold() in {"true", "1", "yes"}
            and _clean(row.get("claim_status")).casefold() == "supported"
            and _clean(row.get("decision"))
            for row in bound
        )
        complete = bool(bound) and all(row.get("decision_complete") == "true" for row in bound)
        status = (
            "SUPPORTED" if supported else "NOT SUPPORTED" if complete else "UNRESOLVED"
        )
        decisions = "; ".join(
            f"{_clean(row.get('registered_outcome'))}: "
            f"{_clean(row.get('decision')).replace('_', ' ')}"
            for row in bound
        )
        lines.append(
            f"- {claim_id} — {status} within the registered deterministic benchmark: "
            f"{decisions or 'no complete explicit decision'}. The interpretation "
            "remains limited to the explicitly registered simulation statistic, not an executed scientific study."
        )
    if len(lines) == 2:
        lines.append(
            "- The central hypothesis is evaluated by the complete comparison pack; "
            "interpretation remains limited to the benchmark scope."
        )
    return [*lines, report["historical_claim_values"], report["scope"], ""]


def _provenance(
    root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    tables: dict[str, list[dict[str, str]]],
    *, valid_bindings: bool = True,
) -> list[str]:
    run_ids = sorted(
        {
            _clean(row.get("source_run_id"))
            for rows in tables.values()
            for row in rows
            if _clean(row.get("source_run_id"))
        }
    )
    seeds = {
        _clean(row.get("simulation_seed") or row.get("seed"))
        for rows in tables.values()
        for row in rows
        if _clean(row.get("simulation_seed") or row.get("seed"))
    }
    simulation_id = _clean(manifest.get("simulation_id"))
    manifest_seed = _clean(manifest.get("simulation_seed"))
    identity_complete = bool(
        valid_bindings
        and simulation_id
        and manifest_seed
        and len(run_ids) == 1
        and seeds == {manifest_seed}
    )
    if not identity_complete:
        return [
            "## Package identity status",
            "",
            "The available sidecars do not contain a complete metric-to-run binding. "
            "Regenerate the benchmark package before accepting this analysis.",
            "",
        ]
    run_text = ", ".join(f"`source_run_id={value}`" for value in run_ids)
    return [
        "## Metric provenance and run identity",
        "",
        f"Every reported metric is bound to {run_text or 'the registered run'}, "
        f"`simulation_id={_clean(manifest.get('simulation_id'))}`, and "
        f"`seed={_clean(manifest.get('simulation_seed'))}`.",
        f"The canonical metric artifact manifest is "
        f"`{manifest_path.relative_to(root).as_posix()}` "
        f"(semantic SHA-256 `{simulation_manifest_semantic_hash(manifest)}`). "
        "Renderer timestamps and output hashes are excluded from this identity.",
        "",
    ]


def _assemble(
    root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    tables: dict[str, list[dict[str, str]]],
    issues: list[str],
    direction: str,
) -> str:
    metric_direction = _clean(manifest.get("metric_direction")).casefold()
    headings, domain_issues = report_role_headings(manifest, ROLE_HEADINGS)
    issues = list(dict.fromkeys([*issues, *domain_issues]))
    profiles = {str(profile.get("stable_role") or ""): profile
                for profile in manifest.get("domain_asset_profile") or [] if isinstance(profile, dict)}
    from ..services.simulation_interval_semantics import interval_semantics
    lines = [
        "# Deterministic Benchmark Result Analysis",
        "",
        f"This report analyzes the registered benchmark for "
        f"**{_clean(manifest.get('title') or direction or 'registered study')}**.",
        f"The primary endpoint is {_clean(manifest.get('primary_metric') or 'the registered metric')}; "
        + (
            "higher values are better."
            if metric_direction == "maximize"
            else "lower values are better."
        ),
        "All interpretations below are bounded to the defined scenario and parameter ranges.",
        "",
        *_provenance(root, manifest_path, manifest, tables, valid_bindings=not issues),
        *(interval_semantics(manifest) if not issues else []),
        *(_paired_family(root, manifest) if not issues else []),
    ]
    if issues:
        lines.extend(
            ["## Package completeness", "", *[f"- {item}" for item in issues], ""]
        )
    for role, heading in headings.items():
        lines.extend(
            [
                f"## {heading}",
                "",
                _role_sentence(
                    role,
                    tables.get(role, []),
                    metric_direction,
                    str(profiles[role].get("axis_field") or ""),
                ),
                "",
            ]
        )
    lines.extend(_claim_lines(root, manifest) if not issues else [
        "## Claim-level interpretation", "", "Claim decisions remain unresolved because the evidence package is not fully hash-bound.", "",
    ])
    lines.extend(
        [
            "## Limitations and failure conditions",
            "",
            "The ordering is conditional on the registered simulator, model suite, axes, "
            "seeds, split, and resource contract. Interval overlap, adverse slices, "
            "calibration failures, and resource regressions remain contrary evidence. "
            "Claims are narrowed when registered effects or adjusted decisions fail.",
            "",
        ]
    )
    return "\n".join(lines)


def ensure_simulation_results_analysis(
    host: Any,
    run: WorkflowRun,
    research_direction: str,
    result: str = "",
) -> str:
    root = Path(run.project_path).resolve()
    simulated = root / "experiments" / "results" / "simulated"
    manifest_path = simulated / "SIMULATION_MANIFEST.json"
    manifest = _json_object(manifest_path)
    tables, issues = _table_inventory(root, simulated, manifest)
    if not issues:
        from ..services.simulation_replay_capsule import ensure_simulation_replay_capsule
        ensure_simulation_replay_capsule(root, research_direction)
    desired = _assemble(
        root,
        manifest_path,
        manifest,
        tables,
        issues,
        research_direction,
    )
    path = root / "experiments" / "results" / "analysis.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    )
    if existing != desired:
        atomic_write_text(path, desired)
    return result or "Deterministic benchmark result analysis written."
