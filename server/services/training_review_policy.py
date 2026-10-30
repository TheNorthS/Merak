"""Separate physical execution prerequisites from implementation correctness."""
from typing import Any

PREREQUISITES = frozenset({"data_availability", "hardware_availability", "execution_budget", "runtime_telemetry"})


def execution_artifact_finding(item: dict) -> bool:
    """Only explicit, exclusively runtime-output findings may be deferred to their execution gate."""
    paths = item.get('target_files') or []
    return (item.get('scope') == 'execution_evidence' and bool(paths)
            and all(isinstance(path, str) and path.replace('\\', '/').startswith(
                ('experiments/results/', 'experiments/logs/', '.merak/experiments/'))
                    and '..' not in path.replace('\\', '/').split('/') for path in paths))


def current_review_findings(assessment: dict[str, Any], options: dict[str, Any]) -> list[dict]:
    findings = [item for item in assessment.get("findings") or []
                if isinstance(item, dict) and not execution_artifact_finding(item)]
    if options.get("run_experiment") is True:
        return findings
    # Unknown scope is never silently treated as missing hardware/data.
    return [item for item in findings if not (
        item.get("scope") == "execution_prerequisite" and item.get("category") in PREREQUISITES
    )]


def review_blocks(assessment: dict[str, Any], options: dict[str, Any]) -> bool:
    if not assessment.get("blocking"):
        return False
    if options.get("run_experiment") is True:
        findings = assessment.get('findings') or []
        if not findings:
            return True
    return any(str(item.get("severity", "blocker")).lower() in {"blocker", "critical", "error", "fail"}
               for item in current_review_findings(assessment, options))


def review_scope_instruction() -> str:
    return ("Each finding must include scope=implementation_correctness, execution_prerequisite, or execution_evidence. "
            "This is a SOURCE implementation review before the next scientific execution. Existing result files "
            "and analysis reports may belong to prior attempts. Missing/stale aggregate rows, accepted-matrix "
            "mismatches or outdated analysis prose alone are execution_evidence, not source defects. For that "
            "scope target ONLY exact files under experiments/results/, experiments/logs/, or .merak/experiments/. "
            "Their runtime output/analysis gates must reject them until current execution regenerates them; "
            "they cannot require editing correct source before permitting that execution. If source itself "
            "cannot produce/validate the required output, emit a separate implementation_correctness finding "
            "with its exact source path and defective operation. Never call merely unexecuted corrected source broken. "
            "execution_prerequisite is allowed only for category data_availability, hardware_availability, "
            "execution_budget, runtime_telemetry. Missing manifests/GPU or unfrozen physical budget can be "
            "execution prerequisites. Incorrect labels, untrained prediction heads, indistinguishable controls, "
            "missing matrix traversal, output overwrites and missing evaluation are implementation_correctness "
            "even when no experiment is requested. Inspect cell-specific axis resolution, homogeneous batch layouts, "
            "registered aggregate/contrast entrypoints, full subgroup metric keys and enforced resource counters. "
            "Missing implementation of declared budget enforcement is implementation_correctness, not missing telemetry. "
            "Split mixed findings: missing audited task metadata or unregistered numerical thresholds are "
            "data_availability execution prerequisites when their values require external evidence. Missing "
            "code to validate those values or apply the registered decision rule is a separate "
            "implementation_correctness finding. Never demand invented data, metrics or thresholds to "
            "pass a static implementation review; never let missing values excuse absent decision logic. "
            "Never downgrade such errors because run_experiment is false.")
