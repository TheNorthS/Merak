"""Read-only identity and frozen-input checks for an explicitly authorized copy."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


UPSTREAM = ("lit", "idea", "novelty", "exp-design", "exp-run", "results")
ALLOWED_NODES = ("narrative", "figure", "paper", "review", "audit", "compile", "ppt")


def validate_copy_boundary(root: Path) -> None:
    """Reject link-based escapes before even a diagnostic or temporary write."""
    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_file() and path.stat().st_nlink > 1:
            raise ValueError("Snapshot continuation rejects hard-linked files that may share original content")
    for name in (".merak", "ideas", "literature", "experiments", "paper", "figures", "review-stage", "audit-results", "slides"):
        directory = root / name
        if directory.exists() and (directory.is_symlink() or not directory.resolve().is_relative_to(root)):
            raise ValueError("Snapshot continuation directory escapes its isolated copy")
        for path in directory.rglob("*") if directory.is_dir() else ():
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Snapshot continuation rejects linked metadata or scientific inputs")


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Snapshot continuation requires object-shaped evidence")
    return value


def scientific_digest(inputs: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def _source_archives(root: Path, original: Path, run_id: str) -> tuple[dict, dict]:
    source = {}
    for suffix in ("run", "skills", "specialists"):
        relative = f".merak/runs/{run_id}" + (".json" if suffix == "run" else f".{suffix}.json")
        current = original / relative
        archive = root / f".merak/snapshot-source-traces/{run_id}.{suffix}.original.json"
        if not archive.is_file() or archive.read_bytes() != current.read_bytes():
            raise ValueError("Snapshot source archive no longer matches its stopped original")
        source[suffix] = _json(current)
    if source["run"].get("run_id") != run_id or source["run"].get("status") != "cancelled":
        raise ValueError("Snapshot continuation cannot resume an active or different original run")
    if (source["skills"].get("schema") != 2 or source["skills"].get("run_id") != run_id
            or Path(str(source["skills"].get("project_path") or "")).resolve() != original):
        raise ValueError("Source execution trace has a different run or project identity")
    plan = source["specialists"]
    if (plan.get("schema") != 1 or plan.get("run_id") != run_id
            or plan.get("project_path") and Path(str(plan["project_path"])).resolve() != original):
        raise ValueError("Source specialist plan has a different run or project identity")
    for current in (original / ".merak/skill-invocations").glob("*.json"):
        copied = root / current.relative_to(original)
        if not copied.is_file() or copied.read_bytes() != current.read_bytes():
            raise ValueError("Original skill invocation bytes changed in the verification copy")
    return source["run"], source["skills"]


def _config_identity(copied: dict, source: dict, root: Path, original: Path, run_id: str) -> None:
    previous, current = dict(source.get("config") or {}), dict(copied.get("config") or {})
    previous_options = dict(previous.pop("options", {}) or {})
    current_options = dict(current.pop("options", {}) or {})
    for name in set(previous_options) | set(current_options):
        if previous_options.get(name) == current_options.get(name):
            continue
        if (name == "reused_search_evidence_run_id" and current_options.get(name) == run_id
                and previous_options.get(name) in {None, run_id}):
            continue
        if name == "specialist_plan_path":
            relative = f".merak/runs/{run_id}.specialists.json"
            if (Path(str(previous_options.get(name) or "")).resolve() == original / relative
                    and Path(str(current_options.get(name) or "")).resolve() == root / relative):
                continue
        raise ValueError("Snapshot configuration changed outside the two verified runtime metadata bindings")
    if previous != current:
        raise ValueError("Snapshot research direction, effort or assurance differs from its source")


def _copied_identity(root: Path, original: Path, run_id: str, source: dict, source_trace: dict,
                     local_acceptance: bool = False) -> dict:
    copied = _json(root / f".merak/runs/{run_id}.json")
    trace = _json(root / f".merak/runs/{run_id}.skills.json")
    if (copied.get("schema") != 1 or copied.get("run_id") != run_id
            or copied.get("status") != "incomplete" or trace.get("schema") != 2
            or trace.get("run_id") != run_id or Path(str(trace.get("project_path") or "")).resolve() != root
            or copied.get("input_baseline") != source.get("input_baseline")):
        raise ValueError("Only the same stopped, incomplete verification copy may continue")
    provenance = trace.get("snapshot_provenance") or {}
    source_trace_digest = hashlib.sha256((original / f".merak/runs/{run_id}.skills.json").read_bytes()).hexdigest()
    if (Path(str(provenance.get("source_project") or "")).resolve() != original
            or provenance.get("source_run_id") != run_id
            or provenance.get("source_trace_sha256") != source_trace_digest
            or provenance.get("upstream_invocations_rewritten") is not False
            or provenance.get("new_upstream_execution_claimed") is not False):
        raise ValueError("Copied execution provenance does not preserve its original upstream owners")
    _config_identity(copied, source, root, original, run_id)
    expected = set(UPSTREAM) | set(ALLOWED_NODES)
    if set(copied.get("phases") or {}) != expected:
        raise ValueError("Copied workflow node inventory differs from the authorized pipeline")
    for node in UPSTREAM:
        original_phase = source["phases"][node]
        phase = copied["phases"][node]
        source_stage = source_trace.get("stages", {}).get(node)
        if (not isinstance(source_stage, dict) or not source_stage
                or not local_acceptance and any(phase.get(key) != original_phase.get(key) for key in
                ("status", "verdict_id", "reviewer", "accepted_at")) or phase.get("status") != "accepted"
                or trace.get("stages", {}).get(node) != source_trace.get("stages", {}).get(node)):
            raise ValueError("Copied upstream acceptance or execution identity changed")
    return copied


def validate_resume_identity(root: Path, original: Path, run_id: str,
                             expected_scientific: str, expected_report: str, expected_source_trace: str,
                             inputs: dict[str, str], repository: Path,
                             local_receipt_pin: str = "") -> dict:
    root, original, repository = root.resolve(), original.resolve(), repository.resolve()
    if (root == original or not root.is_relative_to(repository) or root.parent != repository
            or not root.name.startswith("live-verification-106-")
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_scientific)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_report)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_source_trace)
            or local_receipt_pin and not re.fullmatch(r"[a-f0-9]{64}", local_receipt_pin)
            or not inputs or scientific_digest(inputs) != expected_scientific):
        raise ValueError("Continuation requires the recorded isolated copy and pinned frozen scientific digest")
    validate_copy_boundary(root)
    report_path = root / ".merak/LIVE_VERIFICATION_REPORT.json"
    if hashlib.sha256(report_path.read_bytes()).hexdigest() != expected_report:
        raise ValueError("Previous verification report changed from its independently recorded digest")
    source, source_trace = _source_archives(root, original, run_id)
    if hashlib.sha256((original / f".merak/runs/{run_id}.skills.json").read_bytes()).hexdigest() != expected_source_trace:
        raise ValueError("Original execution trace changed from its independently recorded digest")
    copied = _copied_identity(root, original, run_id, source, source_trace, bool(local_receipt_pin))
    receipt = None
    if local_receipt_pin:
        from scripts.live_snapshot_reaccept_receipt import validate_local_receipt
        receipt = validate_local_receipt(root, run_id, local_receipt_pin, copied,
                                         expected_scientific, expected_report, expected_source_trace)
    report = _json(report_path)
    source_hash = hashlib.sha256((original / f".merak/runs/{run_id}.json").read_bytes()).hexdigest()
    if (report.get("accepted") is not False or report.get("status") != "incomplete"
            or Path(str(report.get("snapshot_path") or "")).resolve() != root
            or report.get("real_model_execution") is not True
            or report.get("training_authorized") is not False or report.get("original_workflow_resumed") is not False
            or report.get("scientific_inputs_unchanged") is not True
            or report.get("original_inputs_unchanged") is not True
            or report.get("blocked_operations") != []
            or (report.get("source_specialist_snapshot") or {}).get("source_plan_sha256") != hashlib.sha256(
                (original / f".merak/runs/{run_id}.specialists.json").read_bytes()).hexdigest()
            or (report.get("upstream_readonly_revalidation") or {}).get("source_run_state_sha256") != source_hash
            or not receipt and report.get("phases") != {node: phase.get("status") for node, phase in copied["phases"].items()}):
        raise ValueError("Prior independent real verification report does not match the stopped copy")
    options = dict((copied.get("config") or {}).get("options") or {})
    if options.get("run_experiment") is not False or options.get("non_experiment_evidence_mode") != "synthetic_preview":
        raise ValueError("Snapshot continuation does not authorize scientific execution or evidence mode changes")
    return {"scientific_inputs_sha256": expected_scientific, "source_run_state_sha256": source_hash,
            "source_run_id": run_id, "previous_report_sha256": expected_report,
            "source_execution_trace_sha256": expected_source_trace,
            **({"local_acceptance_receipt_sha256": local_receipt_pin} if receipt else {})}
