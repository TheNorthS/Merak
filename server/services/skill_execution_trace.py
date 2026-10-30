"""Durable, auditable execution traces for workflow skills and runtimes."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Protocol

from .skill_registry import SkillRegistry
from ..utils.atomic_write import atomic_write_json, path_lock


class SkillPlanLike(Protocol):
    node_id: str
    policy_required: bool
    registry_total: int

    def as_dict(self) -> dict[str, Any]: ...


def trace_path(project_path: str, run_id: str) -> Path:
    return (
        Path(project_path).expanduser().resolve()
        / ".merak"
        / "runs"
        / f"{run_id}.skills.json"
    )


def load_skill_state(path: Path) -> dict[str, Any]:
    """Load one canonical trace without erasing malformed evidence."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Skill execution trace is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Skill execution trace root must be an object: {path}")
    if not isinstance(payload.get("stages", {}), dict):
        raise RuntimeError(f"Skill execution trace stages must be an object: {path}")
    return payload


def verified_model_invocation(invocation: dict[str, Any]) -> bool:
    try:
        skill_bytes = int(invocation.get("skill_bytes") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        invocation.get("status") == "completed"
        and invocation.get("policy_loaded") is True
        and str(invocation.get("session_id") or "").strip()
        and str(invocation.get("skill_sha256") or "").strip()
        and skill_bytes > 0
        and invocation.get("execution_kind") in {"model_owned", "hybrid"}
    )


def stage_execution_evidence(stage: dict[str, Any], run_id: str = "") -> dict[str, Any]:
    verified_models = [
        item for item in stage.get("invocations", [])
        if isinstance(item, dict) and verified_model_invocation(item)
        and (not run_id or not item.get("run_id") or item.get("run_id") == run_id)
    ]
    primary_skill = str(stage.get("primary") or "").lstrip("/")
    primary_models = [
        item for item in verified_models
        if item.get("role") == "primary"
        and (
            not primary_skill
            or str(item.get("skill") or "").lstrip("/") == primary_skill
        )
    ]
    expected_runtime = str(stage.get("runtime_service") or "")
    runtime_records = [item for item in stage.get("runtime_invocations", [])
                       if isinstance(item, dict)
                       and (not run_id or not item.get("run_id") or item.get("run_id") == run_id)]
    latest_runtime = runtime_records[-1] if runtime_records else {}
    verified_runtime = [latest_runtime] if (expected_runtime and latest_runtime.get("runtime_service") == expected_runtime
                                          and latest_runtime.get("status") == "completed"
                                          and str(latest_runtime.get("operation_id") or "").strip()) else []
    return {
        "execution_kind": str(stage.get("execution_kind") or "model_owned"),
        "policy_required": bool(stage.get("policy_required", True)),
        "model_execution_verified": bool(verified_models),
        "primary_model_execution_verified": bool(primary_models),
        "primary_skill": primary_skill,
        "runtime_execution_verified": bool(verified_runtime),
        "model_sessions": sorted({
            str(item.get("session_id") or "") for item in verified_models
            if item.get("session_id")
        }),
        "skills_executed": sorted({
            str(item.get("skill") or "") for item in verified_models
            if item.get("skill")
        }),
        "runtime_services_executed": sorted({
            str(item.get("runtime_service") or "") for item in verified_runtime
            if item.get("runtime_service")
        }),
    }


def execution_summary(stages: dict[str, Any], registry_total: int) -> dict[str, Any]:
    candidates = _skill_candidates(stages)
    verified = [
        item
        for stage in stages.values()
        if isinstance(stage, dict)
        for item in stage.get("invocations", [])
        if isinstance(item, dict) and verified_model_invocation(item)
    ]
    executed = sorted({str(item.get("skill") or "") for item in verified if item.get("skill")})
    unverified = _unverified_completed(stages, set(executed))
    runtimes = _verified_runtime_services(stages)
    return {
        "unique_skills_candidates": candidates,
        "unique_skills_selected": executed,
        "unique_skills_executed": executed,
        "verified_model_invocation_count": len(verified),
        "unverified_completed_skills": unverified,
        "runtime_services_executed": runtimes,
        "stage_execution": {
            str(node_id): stage_execution_evidence(stage)
            for node_id, stage in stages.items() if isinstance(stage, dict)
        },
        "coverage_ratio": round(len(executed) / registry_total, 4) if registry_total else 0.0,
    }


def _skill_candidates(stages: dict[str, Any]) -> list[str]:
    selected = {
        str(name)
        for stage in stages.values() if isinstance(stage, dict)
        for name in stage.get("selected", []) if str(name)
    }
    invoked = {
        str(item.get("skill") or "")
        for stage in stages.values() if isinstance(stage, dict)
        for item in stage.get("invocations", [])
        if isinstance(item, dict) and item.get("skill")
    }
    return sorted(selected | invoked)


def _unverified_completed(stages: dict[str, Any], executed: set[str]) -> list[str]:
    return sorted({
        str(item.get("skill") or "")
        for stage in stages.values() if isinstance(stage, dict)
        for item in stage.get("invocations", [])
        if isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("skill")
        and not verified_model_invocation(item)
    } - executed)


def _verified_runtime_services(stages: dict[str, Any]) -> list[str]:
    return sorted({
        str(item.get("runtime_service") or "")
        for stage in stages.values() if isinstance(stage, dict)
        for item in stage.get("runtime_invocations", [])
        if isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("runtime_service")
        and item.get("operation_id")
    })


def _writable_trace(path: Path, run_id: str) -> dict[str, Any]:
    """Never relabel an existing trace from another run or unsupported format."""
    payload = load_skill_state(path)
    if payload and (payload.get("schema") != 2 or payload.get("run_id") != run_id):
        raise RuntimeError(f"Skill execution trace identity or schema is invalid: {path}")
    if payload.get("project_path") and Path(str(payload["project_path"])).resolve() != path.parents[2].resolve():
        raise RuntimeError(f"Skill execution trace belongs to a different project: {path}")
    return payload


class SkillExecutionTrace:
    """Repository for execution ownership evidence, independent of routing."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def execution_gate(self, project_path: str, run_id: str, node_id: str) -> dict[str, Any]:
        path = trace_path(project_path, run_id)
        try:
            payload = _writable_trace(path, run_id)
        except RuntimeError as exc:
            return _missing_trace_gate(path, str(exc))
        if payload.get("schema") != 2 or payload.get("run_id") != run_id:
            return _missing_trace_gate(path, "missing verified current-run execution trace identity or schema")
        if payload.get("project_path") and Path(str(payload["project_path"])).resolve() != Path(project_path).resolve():
            return _missing_trace_gate(path, "execution trace project identity differs from the current project")
        raw_stage = (payload.get("stages") or {}).get(node_id)
        if not isinstance(raw_stage, dict):
            return _missing_trace_gate(path, "missing verified current-run execution stage identity")
        stage = dict(raw_stage)
        if stage.get("node_id") != node_id or (stage.get("run_id") and stage["run_id"] != run_id):
            return _missing_trace_gate(path, "missing verified current-run execution stage identity")
        evidence = stage_execution_evidence(stage, run_id)
        gate = _evaluate_stage_gate(path, stage, evidence)
        gate["issues"].extend(str(item) for item in stage.get("execution_contract_issues") or [])
        if node_id == "figure":
            from .figure_execution_evidence import figure_stage_execution_issues

            invocations = [item for item in stage.get("invocations") or [] if isinstance(item, dict)
                           and (not item.get("run_id") or item["run_id"] == run_id)]
            try:
                issues, models_verified = figure_stage_execution_issues(project_path, stage, invocations)
            except (OSError, ValueError, RuntimeError) as exc:
                issues, models_verified = [f"figure execution evidence is invalid: {exc}"], False
            gate["issues"].extend(issues)
            if gate["requires_model"]:
                gate["model_requirement_verified"] = models_verified
        gate["accepted"] = not gate["issues"]
        return gate

    def workflow_execution_gate(
        self, project_path: str, run_id: str, node_ids: Iterable[str],
    ) -> dict[str, Any]:
        stages: dict[str, Any] = {}
        issues: list[str] = []
        for node_id in dict.fromkeys(str(item) for item in node_ids if str(item)):
            gate = self.execution_gate(project_path, run_id, node_id)
            stages[node_id] = gate
            issues.extend(f"{node_id}: {issue}" for issue in gate.get("issues", []))
        return {"accepted": not issues, "issues": issues, "stages": stages}

    def record(self, project_path: str, run_id: str, plan: SkillPlanLike) -> Path:
        path = trace_path(project_path, run_id)
        with path_lock(path):
            payload = _writable_trace(path, run_id)
            stages = dict(payload.get("stages") or {})
            previous = dict(stages.get(plan.node_id) or {})
            stage = plan.as_dict()
            stage.update({
                "run_id": run_id,
                "applied_at": time.time(),
                "primary_status": previous.get("primary_status") or (
                    "selected" if plan.policy_required else "not_applicable_runtime_owned"
                ),
                "specialist_status": "available-on-demand",
                "validator_status": "reserved-independent",
                "invocations": list(previous.get("invocations") or [])[-40:],
                "runtime_invocations": list(previous.get("runtime_invocations") or [])[-40:],
            })
            stages[plan.node_id] = stage
            self._write_payload(path, payload, run_id, stages, plan.registry_total, include_digest=True)
        return path

    def mark_execution(
        self, project_path: str, run_id: str, node_id: str, skill_name: str,
        status: str, **details: Any,
    ) -> Path:
        path = trace_path(project_path, run_id)
        with path_lock(path):
            payload = _writable_trace(path, run_id)
            stages = dict(payload.get("stages") or {})
            stage = dict(stages.get(node_id) or {"node_id": node_id})
            invocations = list(stage.get("invocations") or [])
            record = self._model_record(skill_name, status, invocations, details)
            record["run_id"] = run_id
            invocations.append(record)
            stage["invocations"] = invocations[-40:]
            if details.get("role", "primary") == "primary":
                stage["primary_status"] = status
                stage["primary_session_id"] = str(details.get("session_id") or "")
            stages[node_id] = stage
            total = int(payload.get("registry_total") or self.registry.total_skills)
            self._write_payload(path, payload, run_id, stages, total)
        return path

    def mark_runtime_execution(
        self, project_path: str, run_id: str, node_id: str, runtime_service: str,
        status: str, **details: Any,
    ) -> Path:
        path = trace_path(project_path, run_id)
        with path_lock(path):
            payload = _writable_trace(path, run_id)
            stages = dict(payload.get("stages") or {})
            stage = dict(stages.get(node_id) or {"node_id": node_id})
            invocations = list(stage.get("runtime_invocations") or [])
            record = _runtime_record(runtime_service, status, details)
            record["run_id"] = run_id
            invocations.append(record)
            stage.update({
                "runtime_invocations": invocations[-40:],
                "runtime_status": str(status),
                "last_runtime_service": str(runtime_service),
            })
            stages[node_id] = stage
            total = int(payload.get("registry_total") or self.registry.total_skills)
            self._write_payload(path, payload, run_id, stages, total)
        return path

    def _model_record(
        self, skill_name: str, status: str, invocations: list[Any], details: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = skill_name.lstrip("/")
        role = str(details.get("role") or "primary")
        session_id = str(details.get("session_id") or "")
        record: dict[str, Any] = {
            "skill": normalized, "role": role, "status": status,
            "session_id": session_id,
            "execution_kind": str(details.get("execution_kind") or "model_owned"),
            "updated_at": time.time(),
        }
        previous = next((
            item for item in reversed(invocations)
            if isinstance(item, dict)
            and str(item.get("session_id") or "") == session_id
            and str(item.get("skill") or "").lstrip("/") == normalized
            and str(item.get("role") or "") == role
        ), None)
        _copy_previous_model_fields(record, previous)
        self._attach_skill_source(record, normalized)
        _attach_model_details(record, details)
        record["execution_verified"] = verified_model_invocation(record)
        return record

    def _attach_skill_source(self, record: dict[str, Any], skill_name: str) -> None:
        metadata = self.registry.get_skill(skill_name)
        if not metadata or not metadata.file_path:
            return
        source = Path(metadata.file_path)
        try:
            content = source.read_bytes()
        except OSError:
            return
        if content:
            record.update({
                "skill_source": str(source),
                "skill_sha256": hashlib.sha256(content).hexdigest(),
                "skill_bytes": len(content),
            })

    @staticmethod
    def _write_payload(
        path: Path, payload: dict[str, Any], run_id: str, stages: dict[str, Any],
        registry_total: int, *, include_digest: bool = False,
    ) -> None:
        update = {
            "schema": 2, "run_id": run_id, "registry_total": registry_total,
            "project_path": str(path.parents[2].resolve()),
            "stages": stages, "updated_at": time.time(),
            **execution_summary(stages, registry_total),
        }
        if include_digest:
            update["selection_digest"] = hashlib.sha256(
                json.dumps(stages, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
        payload.update(update)
        atomic_write_json(path, payload)


def _copy_previous_model_fields(record: dict[str, Any], previous: Any) -> None:
    if not isinstance(previous, dict):
        return
    for key in ("skill_source", "skill_sha256", "skill_bytes", "model_provider", "model_name"):
        if previous.get(key):
            record[key] = previous[key]


def _attach_model_details(record: dict[str, Any], details: dict[str, Any]) -> None:
    policy_loaded = details.get("policy_loaded")
    record["policy_loaded"] = (
        bool(policy_loaded) if policy_loaded is not None else bool(record.get("skill_sha256"))
    )
    for key in ("model_provider", "model_name", "completion_mode"):
        if details.get(key):
            record[key] = str(details[key])
    output = str(details.get("output") or "")
    if output:
        record["output_sha256"] = hashlib.sha256(
            output.encode("utf-8", errors="replace")
        ).hexdigest()[:16]
    error = str(details.get("error") or "")
    if error:
        record["error"] = error[:1000]


def _runtime_record(runtime_service: str, status: str, details: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(details.get("operation_id") or "")
    record: dict[str, Any] = {
        "runtime_service": str(runtime_service), "status": str(status),
        "operation_id": operation_id, "execution_kind": "runtime",
        "policy_loaded": False, "updated_at": time.time(),
    }
    record["execution_verified"] = bool(
        status == "completed" and runtime_service and operation_id
    )
    output = str(details.get("output") or "")
    if output:
        record["output_sha256"] = hashlib.sha256(
            output.encode("utf-8", errors="replace")
        ).hexdigest()[:16]
    error = str(details.get("error") or "")
    if error:
        record["error"] = error[:1000]
    return record


def _evaluate_stage_gate(path: Path, stage: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    kind = str(stage.get("execution_kind") or evidence.get("execution_kind") or "model_owned")
    policy_required = bool(stage.get("policy_required", True))
    requires_model = policy_required and kind in {"model_owned", "hybrid"}
    requires_runtime = kind in {"runtime_owned", "hybrid"}
    mode = str(stage.get("model_execution_mode") or "primary")
    model_verified = bool(
        evidence["model_execution_verified"]
        if mode == "any_component" else evidence["primary_model_execution_verified"]
    )
    issues: list[str] = []
    if requires_model and not model_verified:
        primary = evidence.get("primary_skill") or "stage owner"
        issues.append(
            "missing verified current-run model execution for any declared component"
            if mode == "any_component"
            else f"missing verified current-run model execution for /{primary}"
        )
    if requires_runtime and not evidence["runtime_execution_verified"]:
        issues.append(
            f"missing verified current-run runtime execution for "
            f"{stage.get('runtime_service') or 'declared runtime service'}"
        )
    return {
        "accepted": not issues, "issues": issues, "trace_path": str(path),
        "requires_model": requires_model, "requires_runtime": requires_runtime,
        "model_execution_mode": mode, "model_requirement_verified": model_verified,
        **evidence,
    }


def _missing_trace_gate(path: Path, issue: str) -> dict[str, Any]:
    return {
        "accepted": False, "issues": [issue], "trace_path": str(path),
        "requires_model": True, "requires_runtime": False,
        "model_execution_mode": "primary", "model_requirement_verified": False,
        "execution_kind": "unknown", "policy_required": True,
        "model_execution_verified": False,
        "primary_model_execution_verified": False, "primary_skill": "",
        "runtime_execution_verified": False, "model_sessions": [],
        "skills_executed": [], "runtime_services_executed": [],
    }
