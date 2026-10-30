"""One durable repair worklist per report; authored changes are not resolved findings."""

import hashlib
from pathlib import Path
import time


def fingerprints(root: Path, targets: list[str]) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in targets}


def begin_report(state, plan: dict, root: Path, maximum: int) -> dict:
    """Persist intent before any edits, preserving historical acceptance and prior rounds."""
    current = fingerprints(root, plan["targets"])
    def update(saved: dict) -> None:
        if saved.get("status") in {"completed", "cancelled"}:
            raise ValueError("Terminal workflow must be explicitly resumed before a report repair")
        reports = saved.setdefault("report_revisions", {})
        old = reports.get(plan["id"])
        if old and old["status"] in {"editing", "verifying", "interrupted"}:
            return
        rounds = int(old.get("round", 0)) if old else 0
        all_rounds = sum(int(r.get("round", 0)) for r in reports.values() if r["consumer"] == plan["consumer"])
        if rounds >= maximum or all_rounds >= maximum:
            raise ValueError("Report revision budget exhausted; unresolved findings remain")
        if old:
            saved.setdefault("report_revision_history", []).append(old)
        reports[plan["id"]] = {**plan, "schema": 1, "round": rounds + 1, "status": "editing",
            "started_at": time.time(), "before": current, "expected": current, "completed_owners": [],
            "issues": [{"id": i, "status": "open"} for i in plan["finding_ids"]]}
        for phase_id in {g["owner"] for g in plan["groups"]} | {"paper", "review", "audit", "compile", "ppt"}:
            phase = saved.get("phases", {}).get(phase_id)
            if not phase:
                continue
            details = phase.setdefault("details", {})
            if phase.get("status") == "accepted":
                details["last_accepted_execution"] = {key: phase.get(key) for key in (
                    "verdict_id", "reviewer", "accepted_at", "artifact")}
                phase.update(status="pending", verdict_id="", reviewer="", accepted_at=None)
            details["current_validation"] = {"status": "revision_pending", "report_id": plan["id"],
                "reason": "Current report has targeted repairs; historical execution is preserved"}
    state.update_state(update)
    return state.load()["report_revisions"][plan["id"]]


def save_report(state, record: dict) -> None:
    state.update_state(lambda saved: saved.setdefault("report_revisions", {}).__setitem__(record["id"], record))


def require_expected(root: Path, record: dict) -> None:
    if fingerprints(root, record["targets"]) != record["expected"]:
        raise ValueError("Repair targets changed outside the saved worklist; preserve user changes and reassess")


def close_reports(saved: dict, consumer: str) -> None:
    """Only a fresh successful consumer gate can resolve findings, never an author's edit."""
    for record in saved.get("report_revisions", {}).values():
        if record["consumer"] != consumer or record["status"] != "awaiting_review":
            continue
        record.update(status="resolved", resolved_at=time.time())
        for issue in record["issues"]:
            issue["status"] = "resolved"
    phase = saved.get("phases", {}).get(consumer, {})
    if "current_validation" in phase.get("details", {}):
        phase["details"]["current_validation"] = {"status": "current"}
