"""Pre-write validation and atomic persistence for versioned artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .registry import artifact_contract_registry


_BY_PATH = {
    contract.path: (identity, contract)
    for identity, contract in artifact_contract_registry.items()
}


def versioned_payload_issues(identity: str, payload: Any) -> list[str]:
    contract = artifact_contract_registry[identity]
    if not isinstance(payload, dict):
        return ["artifact root must be a JSON object"]
    issues: list[str] = []
    schema_value = payload.get("schema")
    if identity == "run_spec" and schema_value is None:
        schema_value = payload.get("schema_version")
    if contract.schema is not None:
        try:
            parsed_schema = int(schema_value or 0)
        except (TypeError, ValueError, OverflowError):
            parsed_schema = 0
        if parsed_schema != contract.schema:
            issues.append(f"unsupported schema; current schema={contract.schema}")
    if identity == "selected_idea":
        issues.extend(_selected_idea_issues(payload))
    elif identity == "method_contract":
        issues.extend(_method_contract_issues(payload))
    elif identity == "implementation_evidence_patch":
        try:
            from .implementation_evidence import parse_evidence_patch_document

            parse_evidence_patch_document(payload)
        except ValueError as error:
            issues.append(str(error))
    elif identity == "implementation_blueprint":
        issues.extend(_implementation_blueprint_issues(payload))
    elif identity == "run_spec":
        issues.extend(_run_spec_issues(payload))
    return issues


def _implementation_blueprint_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not str(payload.get("implementation_family") or "").strip():
        issues.append("implementation_family is required")
    if not str(payload.get("entrypoint") or "").strip():
        issues.append("entrypoint is required")
    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        issues.append("stages must be a non-empty list")
    return issues


def _run_spec_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    from .implementation_readiness import ExecutionReadiness, ImplementationReadiness
    for model, fields in (
        (ImplementationReadiness, {"integration_readiness", "integration_blockers"}),
        (ExecutionReadiness, {"execution_readiness", "execution_prerequisites"}),
    ):
        if fields.intersection(payload):
            try:
                model.model_validate(payload)
            except ValueError as error:
                issues.append(str(error))
    if not str(payload.get("implementation_family") or "").strip():
        issues.append("implementation_family is required")
    if not str(payload.get("entrypoint") or "").strip():
        issues.append("entrypoint is required")
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        issues.append("outputs object is required")
    from .evaluation import declaration_issues
    issues.extend(declaration_issues(payload.get("evaluation")))
    return issues


def _selected_idea_issues(payload: dict[str, Any]) -> list[str]:
    issues = []
    for field in ("title", "problem_statement", "hypothesis"):
        if not str(payload.get(field) or "").strip():
            issues.append(f"{field} is required")
    for field in ("claims", "mechanisms", "falsification_conditions"):
        if not isinstance(payload.get(field), list) or not payload[field]:
            issues.append(f"{field} must be a non-empty list")
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        issues.append("publication object is required")
    return issues


def _method_contract_issues(payload: dict[str, Any]) -> list[str]:
    issues = []
    scene = payload.get("scientific_scene")
    if not isinstance(scene, dict):
        issues.append("scientific_scene object is required")
    else:
        from ..services.scientific_scene import validate_scientific_scene

        issues.extend(validate_scientific_scene(scene))
    implemented = str(payload.get("status") or "").casefold() in {
        "implemented", "ready", "complete",
    }
    checks = payload.get("implementation_checks")
    if not isinstance(checks, list):
        issues.append("implementation_checks must be a list")
        return issues
    if implemented and not checks:
        issues.append("implementation_checks must be non-empty when implemented")
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            issues.append(f"implementation_checks[{index}] must be an object")
            continue
        for field in ("id", "description"):
            if not str(check.get(field) or "").strip():
                issues.append(f"implementation_checks[{index}].{field} is required")
        if implemented and not check.get("evidence"):
            issues.append(f"implementation_checks[{index}].evidence is required when implemented")
    return issues


def versioned_artifact_write_error(
    project_root: str | Path, target: str | Path, content: str,
    *, model_authored: bool = False,
) -> str:
    root = Path(project_root).expanduser().resolve()
    candidate = Path(target).expanduser().resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError:
        return ""
    if relative == "experiments/configs/main.yaml":
        import yaml
        from .evaluation import declaration_issues
        try:
            config = yaml.safe_load(content)
            issues = declaration_issues(config.get("evaluation")) if isinstance(config, dict) else ["configuration must be an object"]
        except yaml.YAMLError as error:
            issues = [str(error)]
        return "ARTIFACT_CONTRACT_ERROR: " + "; ".join(issues) if issues else ""
    registered = _BY_PATH.get(relative)
    if registered is None:
        return ""
    identity, _contract = registered
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        return f"ARTIFACT_CONTRACT_ERROR: {relative} is invalid JSON: {error}"
    issues = versioned_payload_issues(identity, payload)
    if model_authored and identity == "method_contract":
        issues.extend(_model_method_transition_issues(candidate, payload))
    return (
        f"ARTIFACT_CONTRACT_ERROR: {relative} violates {identity}: "
        + "; ".join(issues)
        if issues else ""
    )


def _model_method_transition_issues(
    path: Path, payload: dict[str, Any],
) -> list[str]:
    try:
        existing = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        existing = {}
    old_status = str(existing.get("status") or "").casefold()
    new_status = str(payload.get("status") or "").casefold()
    if existing and old_status != new_status:
        return [
            f"METHOD_CONTRACT lifecycle status is runtime-owned: /status={new_status!r}; preserve existing /status={old_status!r} "
            "and submit scientific/evidence changes separately"
        ]
    return []


def write_versioned_artifact(
    project_root: str | Path, identity: str, payload: dict[str, Any],
) -> Path:
    contract = artifact_contract_registry[identity]
    issues = versioned_payload_issues(identity, payload)
    if issues:
        raise ValueError(f"{identity} is invalid: " + "; ".join(issues))
    path = Path(project_root).expanduser().resolve() / contract.path
    atomic_write_json(path, payload)
    return path
