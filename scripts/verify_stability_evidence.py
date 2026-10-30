"""Fail release acceptance unless real workflow receipts bind to the exact candidate."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.stability_package_runtime import digest, package_identity, write_json
from scripts.verify_stability_live import CASES, NODES


def validate_reports(identity: dict, live: dict, recovery: dict) -> None:
    for label, report in (("fresh workflows", live), ("interrupted recovery", recovery)):
        if report.get("accepted") is not True or report.get("identity") != identity:
            raise ValueError(f"{label}: missing success or candidate identity mismatch")
        if report.get("package_unchanged") is not True:
            raise ValueError(f"{label}: candidate changed during validation")
    cases = live.get("cases", [])
    if len(cases) != 3 or {case.get("case") for case in cases} != set(CASES):
        raise ValueError("Three distinct from-scratch research inputs must pass consecutively")
    if len({case.get("run_id") for case in cases if case.get("run_id")}) != 3:
        raise ValueError("Fresh acceptance requires three distinct real run IDs")
    for case in cases:
        if (case.get("accepted") is not True or case.get("real_models") is not True
                or case.get("entrypoint") != "packaged_http_api"
                or case.get("status") != "completed" or set(case.get("phases", {})) != set(NODES)
                or any(value != "accepted" for value in case["phases"].values())):
            raise ValueError("A fresh real-model workflow did not pass every required node")
    sidebar = live.get("sidebar_revision", {})
    if any(sidebar.get(key) is not True for key in ("accepted", "real_models", "run_unchanged", "no_new_runs")):
        raise ValueError("Completed-workflow sidebar revision was not verified")
    if live.get("sources_unchanged") is not True:
        raise ValueError("Workflow validation source snapshot changed")
    if not recovery.get("accepted_phases_preserved") or not all(recovery["accepted_phases_preserved"].values()):
        raise ValueError("Recovery did not preserve previously accepted nodes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--package", type=Path, default=ROOT / "release/win-unpacked")
    args = parser.parse_args()
    identity = package_identity(args.package.resolve())
    live, recovery = (json.loads(path.read_bytes()) for path in (args.live, args.recovery))
    validate_reports(identity, live, recovery)
    for folder in (args.live.parent, args.recovery.parent):
        sources = json.loads((folder / "source-manifest.json").read_bytes())
        for relative, checksum in sources.items():
            path = ROOT / relative
            if not path.resolve().is_relative_to(ROOT) or not path.is_file() or digest(path) != checksum:
                raise ValueError(f"Validation source no longer matches: {relative}")
    write_json(ROOT / "release/stability-acceptance.json", {
        "accepted": True, "identity": identity, "fresh_runs": [case["run_id"] for case in live["cases"]],
        "recovery_run": recovery["run_id"], "scope": "reviewable_draft_synthetic_preview",
        "external_services": "skipped_by_user", "real_training_verified": False,
        "live_report_sha256": digest(args.live), "recovery_report_sha256": digest(args.recovery),
    })
    print("Real-model workflow acceptance: PASS for the exact candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
