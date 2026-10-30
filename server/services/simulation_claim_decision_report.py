"""Read a source-bound claim audit without rewriting frozen simulation files.

The current report supersedes legacy support labels, not their raw observations.
Every consumed CSV retains its manifest identity; derived summaries are explicit
table-local descriptions, never evidence that the scientific study was executed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from .simulation_claim_decisions import _number, correct_claim_decisions, paired_decision_contract
from .simulation_policy import SIMULATION_MANIFEST_SCHEMA


MANIFEST = "experiments/results/simulated/SIMULATION_MANIFEST.json"


def _read(root: Path, relative: str, hashes: dict[str, str]) -> bytes:
    path = (root / relative).resolve()
    if not relative or not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Claim decision input is missing or outside its project: {relative}")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if relative in hashes and hashes[relative] != digest:
        raise ValueError(f"Claim decision input changed during its audit: {relative}")
    hashes[relative] = digest
    return content


def _object(root: Path, relative: str, hashes: dict[str, str]) -> dict[str, Any]:
    try:
        payload = json.loads(_read(root, relative, hashes).decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Claim decision input is not readable JSON: {relative}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Claim decision input is not an object: {relative}")
    return payload


def _csv(root: Path, relative: str, declared: dict[str, str], hashes: dict[str, str]) -> list[dict[str, str]]:
    if relative not in declared or not declared[relative]:
        raise ValueError(f"Claim decision CSV lacks a declared manifest binding: {relative}")
    try:
        content = _read(root, relative, hashes)
        if hashes[relative] != declared[relative]:
            raise ValueError(f"Claim decision CSV differs from its frozen manifest: {relative}")
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"Claim decision CSV cannot be read: {relative}") from error
    if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Claim decision CSV is empty or malformed: {relative}")
    return rows


def primary_table_summary(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    """Describe the complete matched table, preserving ties and every target."""
    if not rows:
        raise ValueError("Primary table has no observations")
    directions, metrics = {row.get("metric_direction") for row in rows}, {row.get("metric") for row in rows}
    if len(directions) != 1 or rows[0].get("metric_direction") not in {"maximize", "minimize"} or len(metrics) != 1:
        raise ValueError("Primary table has inconsistent metric or direction")
    maximize = rows[0]["metric_direction"] == "maximize"
    methods = list(dict.fromkeys(row["method"] for row in rows))
    datasets = list(dict.fromkeys(row.get("dataset") or "aggregate" for row in rows))
    indexed = {(row.get("dataset") or "aggregate", row["method"]): row for row in rows}
    if len(indexed) != len(rows) or len(rows) != len(methods) * len(datasets):
        raise ValueError("Primary table has incomplete or duplicate matched comparisons")
    descriptions = []
    for method in methods:
        values, ranks = [], []
        for dataset in datasets:
            value = _number(indexed[dataset, method]["value"])
            better = sum((_number(indexed[dataset, other]["value"]) > value if maximize
                          else _number(indexed[dataset, other]["value"]) < value) for other in methods)
            values.append(value)
            ranks.append(1 + better)
        descriptions.append({"method": method, "target_count": len(datasets), "condition_count": len(methods),
                             "target_macro_mean": mean(values), "target_ranks": ranks,
                             "minimum": min(values), "maximum": max(values)})
    return {"metric": rows[0]["metric"], "metric_direction": rows[0]["metric_direction"],
            "datasets": datasets, "methods": descriptions, "scope": "descriptive_simulation_table_only"}


def _manifest_inputs(manifest: dict[str, Any]) -> tuple[dict[str, str], str, str, str]:
    if manifest.get("schema") != SIMULATION_MANIFEST_SCHEMA:
        raise ValueError("Claim decisions require the current scientific simulation manifest schema")
    records = manifest.get("data_files") or []
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError("Claim decisions require explicit scientific data bindings")
    declared = {str(item.get("path") or ""): str(item.get("sha256") or "") for item in records}
    if (len(declared) != len(records) or "" in declared
            or any(not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in declared.values())):
        raise ValueError("Claim decisions refuse duplicate or missing scientific data identities")
    primary = [item for item in manifest.get("domain_asset_profile") or []
               if isinstance(item, dict) and item.get("stable_role") == "main_comparison"]
    if (len(primary) != 1 or not isinstance(primary[0].get("data_file"), str)
            or not primary[0]["data_file"] or "/" in primary[0]["data_file"] or "\\" in primary[0]["data_file"]):
        raise ValueError("Claim decisions require one explicit primary comparison source")
    primary_path = "experiments/results/simulated/" + str(primary[0]["data_file"])
    claim_path = str((manifest.get("claim_evidence_contract") or {}).get("data_file") or "")
    paired_path = str((manifest.get("evidence_package") or {}).get("paired_comparisons") or "")
    return declared, primary_path, claim_path, paired_path


def build_claim_decision_report(root: str | Path) -> dict[str, Any]:
    """Build a fresh hash-bound decision artifact in memory; never modify a CSV.

    A caller may persist the returned report as CLAIM_DECISIONS.json in an
    explicitly authorized copy. Existing claim CSV labels remain historical.
    """
    root, hashes = Path(root).resolve(), {}
    manifest = _object(root, MANIFEST, hashes)
    declared, primary_path, claim_path, paired_path = _manifest_inputs(manifest)
    primary, claims = _csv(root, primary_path, declared, hashes), _csv(root, claim_path, declared, hashes)
    paired = _csv(root, paired_path, declared, hashes)
    method = _object(root, "experiments/METHOD_CONTRACT.json", hashes)
    selected = _object(root, "ideas/SELECTED_IDEA.json", hashes)
    if method.get("schema") != 2 or selected.get("schema") != 2:
        raise ValueError("Claim decisions require current authored scientific contracts")
    expected = manifest.get("claim_ids") or []
    if (not expected or len(set(expected)) != len(expected)
            or {row.get("claim_id") for row in claims} != set(expected)):
        raise ValueError("Claim decision rows do not cover the frozen claim inventory")
    _verify_claim_source_bindings(manifest, claims, method, selected)
    correction = correct_claim_decisions(claims, method_contract=method, selected_contract=selected,
                                         paired_rows=paired, paired_contract=paired_decision_contract(manifest))
    summary = primary_table_summary(primary)
    for relative in list(hashes):
        _read(root, relative, hashes)
    return {"schema": 1, "producer": "simulation-claim-decision-audit", "source_hashes": hashes,
            "rows": list(correction.rows), "decision_changes": list(correction.changes),
            "unresolved_claim_ids": sorted({row["claim_id"] for row in correction.rows if row["claim_status"] == "unresolved"}),
            "primary_comparison": summary, "raw_numerical_fields_preserved": True,
            "scientific_execution_verified": False,
            "scope": "Simulation statistics describe this table only; they do not establish trained or empirical research claims.",
            "historical_claim_values": "Legacy claim CSV point values and support labels are not claim-level measurements or accepted decisions."}


def _verify_claim_source_bindings(manifest: dict, rows: list[dict], method: dict, selected: dict) -> None:
    """Current claim text and exact row inventory must agree before any decision."""
    registered = (manifest.get("claim_evidence_contract") or {}).get("rows")
    if not isinstance(registered, list) or any(not isinstance(item, dict) for item in registered):
        raise ValueError("Claim decisions require the exact declared claim row inventory")
    actual = [{key: row.get(key) for key in ("row_id", "claim_id", "registered_outcome", "evidence_kind")} for row in rows]
    if registered != actual or len({row.get("row_id") for row in rows}) != len(rows):
        raise ValueError("Claim CSV rows differ from their frozen claim-specific identities")
    claim_ids = set(manifest["claim_ids"])
    authored = selected.get("claims") or []
    plans = method.get("claim_evidence_plan") or []
    if (not isinstance(authored, list) or not isinstance(plans, list)
            or any(not isinstance(item, dict) for item in [*authored, *plans])
            or {item.get("id") for item in authored} != claim_ids
            or {item.get("idea_claim_id") for item in plans} != claim_ids):
        raise ValueError("Claim decisions do not cover the current authored scientific claims")
    for plan in plans:
        outcomes = plan.get("outcomes")
        bound = [row.get("registered_outcome") for row in rows if row.get("claim_id") == plan["idea_claim_id"]]
        if not isinstance(outcomes, list) or not outcomes or outcomes != bound:
            raise ValueError("Claim decision outcomes differ from the current authored evidence plan")
