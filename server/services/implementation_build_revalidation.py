"""Atomic revalidation of previously attempted implementation stages."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

from ..utils.atomic_write import atomic_write_json
from .implementation_stages import ImplementationStage


class RevalidationPort(Protocol):
    def load_build(self, project_path: str | Path) -> dict[str, Any]: ...
    def ensure_blueprint(self, project_path: str | Path, direction: str = "") -> dict[str, Any]: ...
    def _family(self, blueprint: dict[str, Any]) -> str: ...
    def _stages_for_family(self, family: str) -> tuple[ImplementationStage, ...]: ...
    def project_stages(self, project_path: str | Path, family: str) -> tuple[ImplementationStage, ...]: ...
    def validate_stage(self, project_path: str | Path, stage_id: str, direction: str = "") -> dict[str, Any]: ...
    def output_hash(self, project_path: str | Path, stage_id: str) -> str: ...
    def input_hash(self, project_path: str | Path, stage_id: str, direction: str = "") -> str: ...
    def build_path(self, project_path: str | Path) -> Path: ...


def _validate_attempted_stages(
    service: RevalidationPort, root: Path, direction: str,
    stages: tuple[ImplementationStage, ...], records: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    reports: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for stage in stages:
        record = records.get(stage.id)
        if not isinstance(record, dict) or int(record.get("attempts") or 0) <= 0:
            issues.append(f"{stage.id}: no prior model-owned stage attempt is recorded")
            continue
        report = service.validate_stage(root, stage.id, direction)
        reports[stage.id] = report
        if not report.get("passed"):
            issues.extend(f"{stage.id}: {item}" for item in report.get("issues") or [])
        elif record.get("status") == "accepted" and str(record.get("output_sha256") or "") != service.output_hash(root, stage.id):
            issues.append(f"{stage.id}: accepted owned artifacts changed; model owner must re-run")
        elif record.get("input_sha256") != service.input_hash(root, stage.id, direction):
            issues.append(f"{stage.id}: scientific input contract changed; owning stage must reconcile before reuse")
    return reports, list(dict.fromkeys(issues))


def _refreshed_build(
    service: RevalidationPort, root: Path, direction: str,
    build: dict[str, Any], stages: tuple[ImplementationStage, ...],
    reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    refreshed = json.loads(json.dumps(build))
    records = refreshed.setdefault("stages", {})
    now = time.time()
    for stage in stages:
        record = dict(records[stage.id])
        report = reports[stage.id]
        record.update({
            "status": "accepted",
            "input_sha256": service.input_hash(root, stage.id, direction),
            "output_sha256": service.output_hash(root, stage.id),
            "targets": list(report.get("targets") or []),
            "issues": [], "updated_at": now,
        })
        records[stage.id] = record
    refreshed.update({
        "status": "complete", "accepted_stages": [stage.id for stage in stages],
        "current_stage": "", "updated_at": now,
    })
    return refreshed


def _finalize_existing_candidate(
    service: RevalidationPort, root: Path, direction: str,
    reports: dict[str, dict[str, Any]], issues: list[str],
) -> list[str]:
    """Finish a previously authored integration only after its full fresh gate.

    Validators may be repaired independently of model output. Lifecycle-only
    findings cannot require another model call to perform a runtime-owned write.
    Missing provenance, changed accepted owners and scientific blockers remain
    blocking; no stage can be fabricated by revalidation.
    """
    from .implementation_candidate_recovery import recover_integration_candidate

    integration = reports.get("integration")
    if not integration or integration.get("passed"):
        return issues
    if any(not issue.startswith("integration: ") for issue in issues):
        return issues
    record = (service.load_build(root).get("stages") or {}).get("integration") or {}
    if (record.get("status") == "accepted"
            and record.get("output_sha256") != service.output_hash(root, "integration")):
        return [*issues, "integration: accepted owned artifacts changed; model owner must re-run"]
    # METHOD_CONTRACT is an integration input: record fingerprints only after
    # this finalization and the subsequent full validator have succeeded.
    try:
        fresh = recover_integration_candidate(service, root, direction)
    except (ValueError, OSError, UnicodeError) as error:
        return [*issues, f"integration: existing evidence recovery failed: {error}"]
    reports["integration"] = fresh
    return [f"integration: {issue}" for issue in fresh.get("issues") or []]


def _build_is_current(
    service: RevalidationPort, root: Path, direction: str,
    build: dict[str, Any], stages: tuple[ImplementationStage, ...],
) -> bool:
    """A fresh successful gate need not churn current runtime hashes/timestamps."""
    if build.get("status") != "complete" or build.get("current_stage"):
        return False
    if build.get("accepted_stages") != [stage.id for stage in stages]:
        return False
    for stage in stages:
        record = (build.get("stages") or {}).get(stage.id) or {}
        if (record.get("status") != "accepted"
                or record.get("input_sha256") != service.input_hash(root, stage.id, direction)
                or record.get("output_sha256") != service.output_hash(root, stage.id)):
            return False
    return True


def _refresh_valid_owners(
    service: RevalidationPort, root: Path, direction: str,
    build: dict[str, Any], stages: tuple[ImplementationStage, ...],
    reports: dict[str, dict[str, Any]],
) -> list[str]:
    """Refresh unchanged passing owners even when a later stage is blocked."""
    records = build["stages"]
    refreshed: list[str] = []
    for stage in stages:
        record = records.get(stage.id)
        report = reports.get(stage.id) or {}
        if not isinstance(record, dict) or not report.get("passed"):
            break
        output_hash = service.output_hash(root, stage.id)
        if record.get("status") == "accepted" and record.get("output_sha256") != output_hash:
            break
        input_hash = service.input_hash(root, stage.id, direction)
        if record.get("input_sha256") != input_hash:
            break
        if record.get("status") == "accepted" and record.get("input_sha256") == input_hash:
            continue
        record.update({
            "status": "accepted", "input_sha256": input_hash,
            "output_sha256": output_hash, "issues": [], "updated_at": time.time(),
        })
        refreshed.append(stage.id)
    if refreshed:
        accepted = [
            stage.id for stage in stages
            if (record := records.get(stage.id) or {}).get("status") == "accepted"
            and record.get("input_sha256") == service.input_hash(root, stage.id, direction)
            and record.get("output_sha256") == service.output_hash(root, stage.id)
        ]
        build.update({
            "status": "in_progress", "accepted_stages": accepted,
            "current_stage": next((stage.id for stage in stages if stage.id not in accepted), ""),
            "updated_at": time.time(),
        })
        atomic_write_json(service.build_path(root), build)
    return refreshed


def revalidate_existing_build(
    service: RevalidationPort, project_path: str | Path, direction: str = "",
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    build = service.load_build(root)
    records = build.get("stages") if isinstance(build, dict) else None
    if not isinstance(records, dict):
        return {
            "refreshed": False, "complete": False,
            "issues": ["staged implementation build record is missing"],
        }
    blueprint = service.ensure_blueprint(root, direction)
    stages = service.project_stages(root, service._family(blueprint))
    reports, issues = _validate_attempted_stages(
        service, root, direction, stages, records,
    )
    issues = _finalize_existing_candidate(service, root, direction, reports, issues)
    if issues:
        refreshed = _refresh_valid_owners(service, root, direction, build, stages, reports)
        _mark_stale_build(service, root, direction, build, stages, issues)
        return {
            "refreshed": bool(refreshed), "complete": False, "issues": issues,
            "revalidated_stages": refreshed,
        }
    if _build_is_current(service, root, direction, build, stages):
        return {"refreshed": False, "complete": True, "issues": [], "build": build}
    refreshed = _refreshed_build(service, root, direction, build, stages, reports)
    atomic_write_json(service.build_path(root), refreshed)
    return {"refreshed": True, "complete": True, "issues": [], "build": refreshed}


def _mark_stale_build(service: RevalidationPort, root: Path, direction: str, build: dict,
                      stages: tuple[ImplementationStage, ...], issues: list[str]) -> None:
    """A blocked revalidation must never leave a runtime complete marker behind."""
    for stage in stages:
        record = build.get("stages", {}).get(stage.id)
        if not isinstance(record, dict):
            continue
        relevant = [issue for issue in issues if issue.startswith(stage.id + ":")]
        if relevant:
            record.update(status="needs_revision", issues=relevant)
    build["status"] = "in_progress"
    build["accepted_stages"] = [stage.id for stage in stages if (build.get("stages", {}).get(stage.id) or {}).get("status") == "accepted"]
    build["current_stage"] = next((stage.id for stage in stages if stage.id not in build["accepted_stages"]), "integration")
    atomic_write_json(service.build_path(root), build)
