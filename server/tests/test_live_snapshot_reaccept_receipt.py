"""Local receipts must prove fresh verdicts, frozen authorship and sidecar identity."""

import hashlib
import json

import pytest

from scripts.live_snapshot_reaccept_receipt import NODES, validate_local_receipt
from scripts.live_snapshot_resume_validation import scientific_digest, validate_resume_identity
from server.tests.test_live_snapshot_reaccept_identity import invalidated
from server.tests.test_live_snapshot_resume_validation import RUN_ID, evidence


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return _sha(path)


@pytest.fixture
def local_receipt(invalidated):
    root = invalidated["root"]
    state_path = root / f".merak/runs/{RUN_ID}.json"
    before = state_path.read_bytes()
    checkpoint = root / ".merak/transactions/before.state.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(before)
    state = json.loads(before)
    trace_path = root / f".merak/runs/{RUN_ID}.skills.json"
    gates = {}
    for index, node in enumerate(NODES):
        gate = {"accepted": True, "verdict_id": node + "-new-verdict", "reviewer": "genuine-gate",
                "details": {"execution_evidence": {"accepted": True, "issues": [], "trace_path": str(trace_path)}}}
        state["phases"][node].update({"status": "accepted", "accepted_at": 1000 + index,
                                      "verdict_id": gate["verdict_id"], "reviewer": gate["reviewer"]})
        gates[node] = gate
    after_hash = _write(state_path, state)
    frozen = root / "paper/sections/02_related_work.tex"
    frozen.parent.mkdir(parents=True)
    frozen.write_text("Authored chapter remains unchanged", encoding="utf-8")
    science = root / "experiments/frozen.csv"
    science.parent.mkdir(parents=True)
    science.write_text("fixed data", encoding="utf-8")
    science_pin = scientific_digest({"experiments/frozen.csv": _sha(science)})
    plan = root / f".merak/runs/{RUN_ID}.specialists.json"
    _write(plan, {"schema": 1, "run_id": RUN_ID, "subnodes": []})
    plan_checkpoint = root / ".merak/transactions/plan.original.json"
    plan_checkpoint.write_bytes(plan.read_bytes())
    manifests, old_hashes, checkpoints = {}, {}, {}
    for name in ("FIGURE_MANIFEST.json", "FIGURE_MANIFEST.md"):
        path = root / "figures" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("derived registration", encoding="utf-8")
        archived = root / ".merak/transactions" / (name + ".original")
        archived.write_bytes(path.read_bytes())
        relative = path.relative_to(root).as_posix()
        manifests[relative] = old_hashes[relative] = _sha(path)
        checkpoints[relative] = archived.relative_to(root).as_posix()
    source = root / f".merak/snapshot-source-traces/{RUN_ID}.run.original.json"
    receipt = {"schema": 1, "operation": "genuine_local_reacceptance", "run_id": RUN_ID,
        "snapshot_path": str(root), "accepted": True, "reaccepted_nodes": list(NODES),
        "model_invoked": False, "producer_invoked": False, "scientific_execution": False,
        "source_identity": {"science_sha256": science_pin, "previous_report_sha256": invalidated["report"],
            "source_trace_sha256": invalidated["trace"], "state_before_sha256": _sha(checkpoint),
            "source_run_state_sha256": _sha(source)},
        "state_after_sha256": after_hash, "state_before_sha256": _sha(checkpoint),
        "state_checkpoint": checkpoint.relative_to(root).as_posix(), "execution_trace_sha256": _sha(trace_path),
        "gates": gates, "accepted_phases": {node: state["phases"][node] for node in NODES},
        "frozen_inputs_sha256": {frozen.relative_to(root).as_posix(): _sha(frozen)},
        "specialist_plan_after_sha256": _sha(plan), "specialist_plan_before_sha256": _sha(plan_checkpoint),
        "specialist_plan_checkpoint": plan_checkpoint.relative_to(root).as_posix(),
        "figure_manifests_after_sha256": manifests, "figure_manifests_before_sha256": old_hashes,
        "figure_manifest_checkpoints": checkpoints}
    receipt_pin = _write(root / ".merak/LOCAL_REACCEPT_REPORT.json", receipt)
    return {**invalidated, "receipt_pin": receipt_pin, "receipt": receipt, "copied": state, "science_pin": science_pin}


def _validate(item):
    return validate_local_receipt(item["root"], RUN_ID, item["receipt_pin"], item["copied"],
                                   item["science_pin"], item["report"], item["trace"])


def test_full_pinned_local_receipt_verifies_exact_actual_state(local_receipt):
    assert _validate(local_receipt)["accepted"] is True


def test_complete_new_local_verdicts_can_continue_without_claiming_old_acceptance_identity(local_receipt):
    from scripts.verify_live_remaining_snapshot import protected_inputs

    result = validate_resume_identity(local_receipt["root"], local_receipt["original"], RUN_ID,
        local_receipt["science_pin"], local_receipt["report"], local_receipt["trace"],
        protected_inputs(local_receipt["root"]), local_receipt["repository"], local_receipt["receipt_pin"])
    assert result["local_acceptance_receipt_sha256"] == local_receipt["receipt_pin"]


@pytest.mark.parametrize("relative", ["figures/FIGURE_MANIFEST.json", "figures/FIGURE_MANIFEST.md",
    "paper/sections/02_related_work.tex", ".merak/transactions/plan.original.json",
    f".merak/runs/{RUN_ID}.specialists.json", f".merak/runs/{RUN_ID}.json"])
def test_post_gate_sidecar_author_or_transaction_drift_is_refused(local_receipt, relative):
    (local_receipt["root"] / relative).write_text("changed after real gate", encoding="utf-8")
    with pytest.raises(ValueError):
        _validate(local_receipt)


def test_true_boolean_cannot_replace_missing_actual_execution_proof(local_receipt):
    local_receipt["receipt"]["gates"]["results"]["details"]["execution_evidence"]["accepted"] = False
    local_receipt["receipt_pin"] = _write(local_receipt["root"] / ".merak/LOCAL_REACCEPT_REPORT.json", local_receipt["receipt"])
    with pytest.raises(ValueError, match="complete current local gate"):
        _validate(local_receipt)
