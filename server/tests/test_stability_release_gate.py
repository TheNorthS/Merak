"""A smoke test or another package's successful workflow cannot certify a release."""

from copy import deepcopy
import pytest

from scripts.verify_stability_evidence import validate_reports
from scripts.verify_stability_live import CASES, NODES


def receipts():
    identity = {"installer_sha256": "fixture-candidate"}
    cases = [{"case": name, "run_id": f"fixture-{name}", "accepted": True, "real_models": True,
              "entrypoint": "packaged_http_api", "status": "completed",
              "phases": {node: "accepted" for node in NODES}} for name in CASES]
    live = {"accepted": True, "identity": identity, "package_unchanged": True, "sources_unchanged": True,
            "cases": cases, "sidebar_revision": {key: True for key in
             ("accepted", "real_models", "run_unchanged", "no_new_runs")}}
    recovery = {"accepted": True, "identity": identity, "package_unchanged": True,
                "accepted_phases_preserved": {"lit": True}}
    return identity, live, recovery


def test_all_required_exact_candidate_receipts_pass():
    validate_reports(*receipts())


@pytest.mark.parametrize("mutation", ["package", "missing_run", "duplicate_input", "duplicate_run",
    "mock_model", "node_failed", "sidebar_restarted", "source_changed", "recovery_lost_acceptance"])
def test_incomplete_or_mismatched_receipts_cannot_certify_release(mutation):
    identity, live, recovery = deepcopy(receipts())
    if mutation == "package":
        live["identity"] = {"installer_sha256": "different"}
    elif mutation == "missing_run":
        live["cases"].pop()
    elif mutation == "duplicate_input":
        live["cases"][1]["case"] = live["cases"][0]["case"]
    elif mutation == "duplicate_run":
        live["cases"][1]["run_id"] = live["cases"][0]["run_id"]
    elif mutation == "mock_model":
        live["cases"][0]["real_models"] = False
    elif mutation == "node_failed":
        live["cases"][0]["phases"]["compile"] = "failed"
    elif mutation == "sidebar_restarted":
        live["sidebar_revision"]["no_new_runs"] = False
    elif mutation == "source_changed":
        live["sources_unchanged"] = False
    else:
        recovery["accepted_phases_preserved"]["lit"] = False
    with pytest.raises(ValueError):
        validate_reports(identity, live, recovery)
