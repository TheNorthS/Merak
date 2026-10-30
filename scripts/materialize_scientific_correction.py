"""Produce truthful copy-only derived reports; no experiments or workflow verdicts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))


def materialize(root: Path, original: Path, findings: Path, baseline_pin: str) -> dict:
    from scripts.scientific_correction_boundary import verify_correction
    from scripts.local_acceptance_scope import local_reacceptance_scope
    from scripts.scientific_correction_writes import correction_report_write_scope
    from server.services.protocol_conformance import build_protocol_conformance_ledger, read_protocol_readiness
    from server.services.simulation_claim_decision_report import build_claim_decision_report
    from server.services.narrative_rendering import narrative_context, render_narrative
    from server.workflows.simulation_result_analysis import ensure_simulation_results_analysis
    from server.workflows.models import WorkflowRun
    from server.utils.atomic_write import atomic_write_json, atomic_write_text

    baseline = root / ".merak/authorized-corrections/BASELINE.json"
    before = verify_correction(root, original, baseline, baseline_pin)
    with local_reacceptance_scope(), correction_report_write_scope(root):
        ledger = build_protocol_conformance_ledger(root, json.loads(findings.read_text(encoding="utf-8-sig")))
        decisions = build_claim_decision_report(root)
        atomic_write_json(root / "experiments/PROTOCOL_CONFORMANCE.json", ledger)
        atomic_write_json(root / "experiments/results/CLAIM_DECISIONS.json", decisions)
        state = json.loads((root / f'.merak/runs/{before["run_id"]}.json').read_text(encoding="utf-8-sig"))
        direction = str((state.get("config") or {}).get("direction") or "")
        ensure_simulation_results_analysis(None, WorkflowRun(project_path=str(root)), direction)
        atomic_write_text(root / "NARRATIVE_REPORT.md", render_narrative(narrative_context(root, direction)))
        readiness = read_protocol_readiness(root)
        if readiness is None or readiness.cannot_execute is not True:
            raise ValueError("Correction did not retain its explicit non-executable boundary")
        if json.loads((root / "experiments/results/CLAIM_DECISIONS.json").read_text(encoding="utf-8-sig")) != build_claim_decision_report(root):
            raise ValueError("Corrected decision report does not match fresh source-bound producer output")
    after = verify_correction(root, original, baseline, baseline_pin)
    after.update({"protocol_status": readiness.status,
                  "unresolved_claim_ids": decisions["unresolved_claim_ids"],
                  "correction_reports_materialized": True})
    atomic_write_json(root / ".merak/authorized-corrections/VERIFICATION.json", after)
    return after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--allow-nonexecuting-correction", action="store_true", required=True)
    options = parser.parse_args()
    root = options.snapshot.resolve(strict=True)
    if root.parent != REPOSITORY or not root.name.startswith("live-verification-106-"):
        raise ValueError("Report correction must target an isolated authorized verification copy")
    result = materialize(root, options.project.resolve(strict=True), options.findings.resolve(strict=True),
                         options.baseline_sha256)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
