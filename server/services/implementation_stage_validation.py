"""Family-aware validation for one staged experiment implementation."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Protocol

from .experiment_implementation import experiment_implementation_service
from .implementation_stages import ImplementationStage
from .method_contract import method_contract_service
from .run_spec import (
    run_spec_requires_seeds,
    run_spec_scientific_command,
    run_spec_seed_groups,
    unresolved_command_placeholders,
)
from ..contracts.entrypoints import parse_python_entrypoint
from ..contracts.implementation_evidence import parse_evidence_patch_document


class ImplementationBuildPort(Protocol):
    def ensure_blueprint(self, project_path: str | Path, direction: str = "") -> dict[str, Any]: ...
    def output_hash(self, project_path: str | Path, stage_id: str) -> str: ...
    def _stage_by_id(self, stage_id: str, family: str) -> ImplementationStage: ...
    def _stages_for_family(self, family: str) -> tuple[ImplementationStage, ...]: ...
    def project_stages(self, project_path: str | Path, family: str) -> tuple[ImplementationStage, ...]: ...
    def project_stage_by_id(self, project_path: str | Path, stage_id: str, family: str) -> ImplementationStage: ...
    def _family(self, blueprint: dict[str, Any]) -> str: ...
    def _method_contract(self, root: Path) -> dict[str, Any]: ...
    def _run_spec(self, root: Path) -> dict[str, Any]: ...
    def _selected_contract(self, root: Path) -> dict[str, Any]: ...


def target_paths(root: Path, stage: ImplementationStage) -> list[Path]:
    return [root / relative for relative in stage.targets]


def source_text(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            parts.append(path.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def python_issues(paths: list[Path]) -> list[str]:
    issues: list[str] = []
    for path in paths:
        if path.suffix.casefold() != ".py" or not path.is_file():
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8-sig", errors="strict"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            issues.append(f"{path.name} is not valid Python: {exc}")
    return issues


def config_parse_issues(paths: list[Path]) -> list[str]:
    issues: list[str] = []
    try:
        import yaml
    except ImportError:
        yaml = None
    for path in paths:
        suffix = path.suffix.casefold()
        if suffix not in {".json", ".yaml", ".yml"} or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="strict")
            if suffix == ".json":
                json.loads(text)
            elif yaml is None:
                issues.append(f"{path.name} cannot be syntax-checked because PyYAML is unavailable")
            else:
                yaml.safe_load(text)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"{path.name} is not valid structured config: {exc}")
        except Exception as exc:
            issues.append(f"{path.name} is not valid structured config: {type(exc).__name__}: {exc}")
    return issues


def _validate_data(
    family: str, existing: list[Path], normalized: str,
) -> list[str]:
    issues = [] if existing else ["data stage produced no source artifact"]
    patterns = {
        "external_protocol": (
            r"(?:protocol|participant|cohort|sampling|recruit|consent|inclusion|exclusion|qc|missing|codebook)",
            "protocol data stage has no sampling, eligibility, consent, or quality-control path",
        ),
        "formal_verification": (
            r"(?:definition|assumption|axiom|instance|input|domain|constraint)",
            "formal data stage has no explicit definitions, assumptions, or problem instances",
        ),
        "computational_general": (
            r"(?:input|parameter|scenario|instance|dataset|load|read_|sample|split|validate|constraint)",
            "computational data stage has no configured inputs, scenarios, units, or validation contract",
        ),
    }
    if family == "machine_learning":
        if not re.search(r"(?:dataset|dataloader|load_(?:data|manifest)|read_(?:csv|json|parquet)|batch)", normalized):
            issues.append("data stage has no configured loading or batching path")
        if not re.search(r"(?:split|train|validation|test|group|subject|leakage)", normalized):
            issues.append("data stage has no split-isolation or leakage contract")
    elif family in patterns and not re.search(patterns[family][0], normalized):
        issues.append(patterns[family][1])
    return issues


def _validate_method(
    family: str, existing: list[Path], text: str, normalized: str,
    blueprint: dict[str, Any],
) -> list[str]:
    issues = [] if existing else ["method stage produced no source artifact"]
    if family == "machine_learning" and not re.search(
        r"(?:def\s+forward|class\s+\w*(?:model|encoder|decoder|head)|objective|loss)", normalized,
    ):
        issues.append("method stage has no substantive model/objective implementation")
    mechanisms = [
        str(item.get("id") or "").strip()
        for item in blueprint.get("mechanisms") or []
        if isinstance(item, dict) and item.get("required", True) is not False
    ]
    if mechanisms and len(re.findall(r"(?:class|def)\s+\w+", text)) < 2:
        issues.append("method stage is too thin to implement the frozen mechanisms")
    patterns = {
        "external_protocol": (
            r"(?:analysis|estimand|outcome|endpoint|confound|adjust|regression|coding|theme|triangulat)",
            "protocol method stage has no declared analysis, endpoint, adjustment, or coding path",
        ),
        "formal_verification": (
            r"(?:theorem|lemma|proof|derive|construction|invariant|verify|checker)",
            "formal method stage has no theorem, proof, construction, or checker path",
        ),
        "computational_general": (
            r"(?:algorithm|simulate|solver|estimate|optimi[sz]e|transform|compute|model|mechanism)",
            "computational method stage has no substantive algorithm, solver, estimator, or mechanism",
        ),
    }
    if family in patterns and not re.search(patterns[family][0], normalized):
        issues.append(patterns[family][1])
    return issues


def _validate_training(
    family: str, root: Path, text: str, normalized: str, blueprint: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    try:
        entrypoint = parse_python_entrypoint(
            blueprint.get("entrypoint") or "experiments/src/train.py"
        )
        issues.extend(entrypoint.validation_issues(root))
    except ValueError as error:
        issues.append(f"training stage has an invalid entrypoint contract: {error}")
    if family == "machine_learning":
        required = {
            "batch/step iteration": r"\b(?:for|while)\s+.+:",
            "objective/loss": r"(?:loss\s*=|criterion\s*\(|objective\s*\()",
            "gradient update": r"(?:\.backward\s*\(|gradienttape|train_on_batch|\.fit\s*\()",
            "optimizer step": r"(?:optimizer\s*\.\s*step\s*\(|apply_gradients)",
        }
        issues.extend(f"training stage is missing {label}" for label, pattern in required.items() if not re.search(pattern, normalized))
    elif family == "external_protocol" and not re.search(
        r"(?:def\s+(?:run|execute|analy[sz]e|estimate|fit)|regression|effect|endpoint|statistic|model)", normalized,
    ):
        issues.append("protocol execution stage has no executable analysis or estimation entrypoint")
    elif family == "formal_verification" and not re.search(
        r"(?:verify|proof|checker|counterexample|smt|theorem|invariant)", normalized,
    ):
        issues.append("formal execution stage has no proof checker, verification, or counterexample path")
    elif family == "computational_general":
        if not re.search(r"def\s+(?:main|run|execute|simulate|analy[sz]e)", normalized):
            issues.append("computational execution stage has no real run/analysis entrypoint")
        if not re.search(r"\b(?:for|while)\s+.+:", text):
            issues.append("computational execution stage has no iteration over configured units, scenarios, or parameters")
    return issues


def _validate_evaluation(
    family: str, existing: list[Path], normalized: str,
) -> list[str]:
    issues = [] if existing else ["evaluation stage produced no source artifact"]
    patterns = {
        "machine_learning": (
            r"(?:metric|accuracy|auroc|f1|brier|calibration|evaluate|predict)",
            "evaluation stage has no registered metric/inference path",
        ),
        "external_protocol": (
            r"(?:effect|estimate|confidence|interval|sensitivity|subgroup|external|validation|result|metric)",
            "protocol evaluation stage has no effect, uncertainty, robustness, or result path",
        ),
        "formal_verification": (
            r"(?:bound|complexity|counterexample|boundary|verify|validation|result|corollary)",
            "formal evaluation stage has no bound, counterexample, boundary-case, or verification result",
        ),
        "computational_general": (
            r"(?:metric|estimate|effect|error|uncertainty|confidence|sensitivity|robust|validation|result)",
            "computational evaluation stage has no registered output, uncertainty, sensitivity, or validation path",
        ),
    }
    pattern, message = patterns[family]
    if not re.search(pattern, normalized):
        issues.append(message)
    if not re.search(r"(?:json\.dump|write_text|to_csv|torch\.save|checkpoint|provenance|sha256)", normalized):
        issues.append("evaluation stage has no result/provenance persistence")
    return issues


def _integration_contract_issues(
    service: ImplementationBuildPort, root: Path, family: str,
    blueprint: dict[str, Any], paths: list[Path],
) -> tuple[list[str], list[str]]:
    issues = config_parse_issues(paths)
    patch_path = root / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    try:
        patch_payload = json.loads(patch_path.read_text(encoding="utf-8-sig"))
        patches = parse_evidence_patch_document(patch_payload)
        from .method_contract_persistence import validate_implementation_evidence_patches

        validate_implementation_evidence_patches(root / "experiments/METHOD_CONTRACT.json", patches)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        issues.append(f"integration evidence patch is invalid: {error}")
    method = service._method_contract(root)
    if str(method.get("status") or "").strip().casefold() not in {"implemented", "ready", "complete"}:
        issues.append("integration stage did not finalize METHOD_CONTRACT.status as implemented")
    selected = service._selected_contract(root)
    expected_title = str(selected.get("title") or blueprint.get("title") or "").strip()
    valid, contract_issues, _details = method_contract_service.validate_method_contract(root, expected_title)
    if not valid:
        issues.extend(f"integration METHOD_CONTRACT: {item}" for item in contract_issues)
    run_spec = service._run_spec(root)
    seed_contract = {**run_spec, "implementation_family": run_spec.get("implementation_family") or family}
    if run_spec_requires_seeds(seed_contract) and not run_spec_seed_groups(run_spec):
        issues.append("integration RUN_SPEC must declare an explicit seed list for reproducible repetitions")
    placeholders = unresolved_command_placeholders(run_spec_scientific_command(run_spec))
    if placeholders:
        issues.append("integration RUN_SPEC scientific command contains unresolved placeholder(s): " + ", ".join(placeholders))
    blockers = [
        item for item in experiment_implementation_service.audit(
            root, method_contract={**method, "status": "implemented"},
        ).get("findings", [])
        if isinstance(item, dict) and str(item.get("severity") or "").casefold() == "blocker"
    ]
    issues.extend(str(item.get("message") or "") for item in blockers)
    valid_targets = {target for stage in service.project_stages(root, family) for target in stage.targets}
    repairs = _legal_stage_repair_targets(blockers, valid_targets)
    return issues, repairs


def _legal_stage_repair_targets(blockers: list[dict[str, Any]], valid_targets: set[str]) -> list[str]:
    """Expand source-directory findings only to the declared stage-owned files.

    A broad diagnostic is not permission for arbitrary files or runtime-owned
    contracts. Exact parse/head targets remain exact; undeclared paths stay out.
    """
    repairs: list[str] = []
    for finding in blockers:
        if finding.get("stage_id") in {"data", "method", "training", "evaluation"}:
            continue  # Route these obligations back to their owner; never widen integration writes.
        for raw in finding.get("target_files") or []:
            target = str(raw or "").strip().replace("\\", "/").rstrip("/")
            if target in valid_targets:
                repairs.append(target)
            elif target == "experiments/src":
                repairs.extend(sorted(path for path in valid_targets if path.startswith("experiments/src/")))
    return list(dict.fromkeys(repairs))


def validate_stage(
    service: ImplementationBuildPort,
    project_path: str | Path,
    stage_id: str,
    direction: str = "",
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    blueprint = service.ensure_blueprint(root, direction)
    family = service._family(blueprint)
    stage = service.project_stage_by_id(root, stage_id, family)
    paths = target_paths(root, stage)
    existing = [path for path in paths if path.is_file() and path.stat().st_size > 0]
    text = source_text(paths)
    normalized = text.casefold()
    issues = python_issues(paths)
    from .impl_stage_targets import target_declaration
    if target_declaration(root) is not None:
        issues.extend("declared stage target is missing or empty: " + path.relative_to(root).as_posix()
                      for path in paths if path not in existing)
    repair_targets: list[str] = []
    if stage_id == "data":
        issues.extend(_validate_data(family, existing, normalized))
    elif stage_id == "method":
        issues.extend(_validate_method(family, existing, text, normalized, blueprint))
    elif stage_id == "training":
        issues.extend(_validate_training(family, root, text, normalized, blueprint))
    elif stage_id == "evaluation":
        issues.extend(_validate_evaluation(family, existing, normalized))
    elif stage_id == "integration":
        integration_issues, repair_targets = _integration_contract_issues(
            service, root, family, blueprint, paths,
        )
        issues.extend(integration_issues)
    else:
        raise ValueError(f"Unknown implementation stage: {stage_id}")
    issues = list(dict.fromkeys(item for item in issues if item))
    return {
        "stage_id": stage_id, "title": stage.title, "passed": not issues,
        "issues": issues, "targets": list(stage.targets),
        "existing_targets": [path.relative_to(root).as_posix() for path in existing],
        "output_sha256": service.output_hash(root, stage_id),
        "repair_targets": list(dict.fromkeys(repair_targets)),
    }


def integration_candidate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Ignore only runtime-owned final-state findings before finalization."""
    lifecycle = (
        "integration stage did not finalize METHOD_CONTRACT.status as implemented",
        "integration METHOD_CONTRACT: method contract status must be implemented, ready, or complete",
    )
    issues = [
        str(item) for item in report.get("issues") or []
        if str(item) not in lifecycle
    ]
    return {**report, "passed": not issues, "issues": issues}
