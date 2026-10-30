"""Narrative claims follow current source-bound decisions, never stale success prose."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from server.services.narrative_rendering import narrative_context, render_narrative
from server.services.narrative_evidence import claim_decision
from server.services.scientific_narrative import scientific_narrative_service as service
from server.services.protocol_conformance import LEDGER_RELATIVE, build_protocol_conformance_ledger
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION


def _json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _source_project(root):
    claims = [{"id": f"C{i}", "statement": f"Scientific causal effect {i}."} for i in range(1, 4)]
    _json(root / "ideas/SELECTED_IDEA.json", {"schema": 2, "title": "Matched causal comparison", "claims": claims})
    _json(root / "experiments/METHOD_CONTRACT.json", {"schema": 2, "claim_evidence_plan": [
        {"idea_claim_id": row["id"], "outcomes": ["Registered endpoint"], "failure_conditions": ["Null comparison"]}
        for row in claims]})
    _json(root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json", {"schema": 5, "evidence_mode": "synthetic_preview"})
    primary = root / "experiments/results/simulated/primary.csv"
    _csv(primary, [{"dataset": dataset, "method": f"Variant{i}" if i < 8 else "Full configuration",
                    "metric": "AUROC", "metric_direction": "maximize", "value": str(1 - i / 100)}
                   for dataset in ("Target A", "Target B") for i in range(1, 9)])
    evidence = root / "experiments/results/simulated/claim_evidence.csv"
    claim_rows = [{"row_id": f"row-{i}", "claim_id": row["id"], "registered_outcome": "Registered endpoint",
                   "evidence_kind": "registered endpoint readout", "value": "0.99",
                   "claim_status": "supported", "supports_claim": "true"} for i, row in enumerate(claims)]
    _csv(evidence, claim_rows)
    paired = root / "experiments/results/simulated/paired_comparisons.csv"
    _csv(paired, [{"pair_id": "historical-table-only", "value": "0.42"}])
    _json(root / "experiments/results/simulated/SIMULATION_MANIFEST.json", {
        "schema": SIMULATION_MANIFEST_SCHEMA, "renderer_version": SIMULATION_RENDERER_VERSION,
        "data_files": [{"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in (primary, evidence, paired)],
        "domain_asset_profile": [{"stable_role": "main_comparison", "data_file": "primary.csv"}],
        "claim_evidence_contract": {"data_file": evidence.relative_to(root).as_posix(), "rows": [
            {key: row[key] for key in ("row_id", "claim_id", "registered_outcome", "evidence_kind")} for row in claim_rows]},
        "evidence_package": {"paired_comparisons": paired.relative_to(root).as_posix()},
        "claim_ids": [row["id"] for row in claims]})
    (root / "experiments/results/analysis.md").write_text("Older prose. " * 1000 + "C1 C2 C3 SUPPORTED; full configuration ranks first.")
    return primary, evidence, paired


def _ledger(root):
    (root / "experiments/EXPERIMENT_PLAN.md").write_text("Registered protocol.")
    _json(root / "experiments/RUN_SPEC.json", {"run_experiment_authorized": False,
        "execution_prohibited_in_this_stage": True, "execution_status": "not_executed"})
    (root / "experiments/src").mkdir()
    (root / "experiments/src/data.py").write_text("raise RuntimeError('Never execute research source in narrative')")
    _json(root / "experiments/configs/main.json", {"research_contract": {"execution_authorized": False},
                                                   "execution": {"execution_prohibited_in_this_stage": True}})
    finding = {"id": "PROTO-VIEWS", "status": "mismatch", "area": "view construction",
               "declared": "Four composite interventions", "observed": "Independent interventions, unvalidated",
               "evidence": ["experiments/EXPERIMENT_PLAN.md", "experiments/src/data.py"]}
    ledger = build_protocol_conformance_ledger(root, [finding], config_relative="experiments/configs/main.json")
    _json(root / LEDGER_RELATIVE, ledger)


def test_fresh_claims_survive_long_analysis_without_promoting_historical_support_or_ranking(tmp_path):
    paths = _source_project(tmp_path)
    _ledger(tmp_path)
    original = {path: path.read_bytes() for path in paths}
    # A self-signed persisted report is deliberately false; the consumer recomputes.
    _json(tmp_path / "experiments/results/CLAIM_DECISIONS.json", {"schema": 1, "all_claims_supported": True})
    context = narrative_context(tmp_path, "Causal comparison")
    text = render_narrative(context)
    for identity in ("C1", "C2", "C3"):
        assert claim_decision(context, identity)[0] == "UNRESOLVED"
        assert identity + ": Scientific causal effect" in text
    assert "Full configuration: target-macro mean 0.92; target ranks 8, 8" in text
    assert "full configuration ranks first" not in text
    assert "SUPPORTED;" not in text and "complete and auditable deterministic benchmark study" not in text
    assert "Current protocol implementation status: MISMATCH" in text and "PROTO-VIEWS" in text
    assert "Scientific execution is prohibited" in text and "registered research was executed" in text
    assert {path: path.read_bytes() for path in paths} == original


@pytest.mark.parametrize("defect", ["stale_claim_csv", "stale_protocol", "missing_manifest"])
def test_invalid_or_missing_current_evidence_is_explicit_not_supported(tmp_path, defect):
    _source_project(tmp_path)
    _ledger(tmp_path)
    if defect == "stale_claim_csv":
        path = tmp_path / "experiments/results/simulated/claim_evidence.csv"
        path.write_bytes(path.read_bytes() + b"tampered\n")
    elif defect == "stale_protocol":
        (tmp_path / "experiments/src/data.py").write_text("Different implementation.")
    else:
        (tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json").unlink()
    text = render_narrative(narrative_context(tmp_path, "Causal comparison"))
    assert "UNRESOLVED" in text and "SUPPORTED_WITHIN_REGISTERED" not in text
    if defect == "stale_protocol":
        assert "Protocol readiness is BLOCKED" in text
    else:
        assert "source-bound benchmark decision audit is unavailable" in text


@pytest.mark.parametrize("status,complete,expected", [
    ("supported", "true", "SUPPORTED_WITHIN_REGISTERED_SIMULATION_STATISTICS_ONLY"),
    ("not_supported", "true", "NOT_SUPPORTED_WITHIN_REGISTERED_SIMULATION_STATISTICS_ONLY"),
    ("supported", "false", "UNRESOLVED"), ("unresolved", "false", "UNRESOLVED"),
])
def test_render_status_preserves_current_complete_decision_without_empirical_upgrade(status, complete, expected):
    context = {"claim_decision_report": {"rows": [{"claim_id": "C1", "claim_status": status,
                                                 "decision_complete": complete, "decision": "Bound registered rule"}]}}
    assert claim_decision(context, "C1")[0] == expected
    assert claim_decision(context, "missing")[0] == "UNRESOLVED"


@pytest.mark.parametrize("relative", ["experiments/results/CLAIM_DECISIONS.json", LEDGER_RELATIVE,
    "experiments/results/simulated/primary.csv", "experiments/configs/main.json", "experiments/src/data.py"])
def test_every_current_decision_protocol_and_consumed_numeric_input_invalidates_narrative_cache(tmp_path, relative):
    _source_project(tmp_path)
    _ledger(tmp_path)
    paths = service._source_paths(tmp_path)
    assert tmp_path / "experiments/results/CLAIM_DECISIONS.json" in paths
    before = service._source_hash(tmp_path, paths)
    path = tmp_path / relative
    if path.exists():
        path.write_bytes(path.read_bytes() + b"\nChanged current input.\n")
    else:
        _json(path, {"schema": 1, "current": True})
    assert service._source_hash(tmp_path, service._source_paths(tmp_path)) != before


@pytest.mark.parametrize("qualifying,expected", [(True, "SUPPORTED_WITHIN_REGISTERED_SIMULATION_STATISTICS_ONLY"),
                                               (False, "NOT_SUPPORTED_WITHIN_REGISTERED_SIMULATION_STATISTICS_ONLY")])
def test_real_bound_rule_consumer_preserves_positive_or_negative_statistical_status_only(tmp_path, qualifying, expected):
    from server.tests.test_simulation_claim_decisions import _rule

    primary, claim_csv, paired_csv = _source_project(tmp_path)
    rows, method, selected, pairs, contract = _rule(qualifying)
    _json(tmp_path / "experiments/METHOD_CONTRACT.json", method)
    _json(tmp_path / "ideas/SELECTED_IDEA.json", selected)
    _csv(claim_csv, rows)
    _csv(paired_csv, pairs)
    manifest_path = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(claim_ids=["H17"], registered_model_suite=[{"model_id": item} for item in contract["model_ids"]],
        replicate_contract={"seed_ids": contract["seed_ids"]}, registered_ranking_axes=contract["axes"],
        registered_pair_contract={"holm_alpha": contract["holm_alpha"]})
    manifest["claim_evidence_contract"]["rows"] = [
        {key: row[key] for key in ("row_id", "claim_id", "registered_outcome", "evidence_kind")} for row in rows]
    manifest["data_files"] = [{"path": path.relative_to(tmp_path).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                             for path in (primary, claim_csv, paired_csv)]
    _json(manifest_path, manifest)
    context = narrative_context(tmp_path, "Registered reversal")
    assert context["claim_decision_report"]["rows"][0]["claim_status"] == ("supported" if qualifying else "not_supported")
    assert claim_decision(context, "H17")[0] == expected
    text = render_narrative(context)
    assert expected in text and "not proof that the registered research was executed" in text


def test_implementation_change_invalidates_existing_narrative_acceptance_not_just_new_generation(tmp_path, monkeypatch):
    _source_project(tmp_path)
    paths = service._source_paths(tmp_path)
    before = service._source_hash(tmp_path, paths)
    original = Path.read_bytes

    def modified(path):
        content = original(path)
        return content + b"\n# Updated truthful decision consumer.\n" if path.name == "narrative_evidence.py" else content

    monkeypatch.setattr(Path, "read_bytes", modified)
    assert service._source_hash(tmp_path, paths) != before
