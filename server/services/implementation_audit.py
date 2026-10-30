"""Composable audit of generated experiment implementation reachability."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Callable

from .method_contract import (
    implementation_evidence_register_map,
    normalize_implementation_evidence,
    resolve_implementation_evidence,
)
from .implementation_configuration import active_probe_configuration_findings
from .run_spec import run_spec_scientific_command
from .implementation_scopes import _active_scopes


FindingAdder = Callable[[str, str, list[str], str], None]


def source_context(service: Any, root: Path, run_spec: dict[str, Any]) -> dict[str, Any]:
    entrypoints = service._entrypoints(root, run_spec)
    source_root = root / "experiments" / "src"
    paths = sorted(source_root.rglob("*.py")) if source_root.is_dir() else []
    trees: dict[Path, ast.Module] = {}
    definitions: dict[Path, dict[str, ast.AST]] = {}
    source_parts: list[str] = []
    parse_issues: list[str] = []
    parse_targets: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            parse_issues.append(f"cannot parse {service._relative(root, path)}: {exc}")
            parse_targets.append(service._relative(root, path))
            continue
        source_parts.append(text)
        trees[path] = tree
        definitions[path] = service._definition_nodes(tree)
    calls: set[str] = set()
    reached: list[ast.AST] = []
    scientific_spec = {key: value for key, value in run_spec.items() if key in {
        "entrypoint", "evaluation_entrypoint", "command", "execution_command",
        "scientific_command", "evaluation_command", "execution_matrix",
    }}
    scientific_entries = service._entrypoints(root, scientific_spec)
    for entrypoint in scientific_entries:
        current_calls, current_nodes = service._reachable_graph(trees, entrypoint)
        calls.update(current_calls)
        reached.extend(current_nodes)
    reachable_source = service._nodes_source(reached)
    from .implementation_model_bindings import has_bound_model_forward

    capabilities = service._source_capabilities(reachable_source)
    capabilities["model_forward"] |= has_bound_model_forward(trees, reached)
    return {
        "entrypoints": entrypoints,
        "entrypoint": scientific_entries[0] if scientific_entries else None,
        "source_paths": paths,
        "trees": trees,
        "definitions": definitions,
        "combined_source": "\n".join(source_parts),
        "parse_issues": parse_issues,
        "parse_targets": parse_targets,
        "reachable_calls": calls,
        "reached_definition_ids": {id(scope) for node in reached for scope, _ in _active_scopes(node)},
        "reachable_source": reachable_source,
        "capabilities": capabilities,
    }


def status_findings(
    service: Any,
    root: Path,
    method: dict[str, Any],
    run_spec: dict[str, Any],
    context: dict[str, Any],
    *,
    claimed_executable: bool,
    add: FindingAdder,
) -> None:
    if context["parse_issues"]:
        add("IMPL-PARSE-001", "; ".join(context["parse_issues"][:4]), context["parse_targets"], "Repair Python syntax before claiming that the method is implemented.")
    scientific_command = run_spec_scientific_command(run_spec)
    declaration = " ".join((str(run_spec.get("implementation_status") or ""), str(run_spec.get("implementation_level") or "")))
    execution_markers = " ".join((str(run_spec.get("status") or ""), str(run_spec.get("execution_mode") or ""), str(run_spec.get("execution_policy") or ""), str(run_spec.get("static_check_command") or "")))
    scaffold = service._SCAFFOLD_MARKERS.search(declaration) or (
        not scientific_command and service._SCAFFOLD_MARKERS.search(execution_markers)
    )
    if claimed_executable and scaffold:
        add("IMPL-STATUS-001", "METHOD_CONTRACT claims implemented, but RUN_SPEC declares only a scaffold/code-check implementation and no runnable scientific command.", ["experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json"], "Declare a runnable scientific command separately from the current-stage not-executed/preflight status, or downgrade the method implementation status.")
    readiness = " ".join((
        str(method.get("implementation_level") or ""),
        str(run_spec.get("implementation_readiness") or ""),
        str(run_spec.get("implementation_status") or ""),
        " ".join(str(item or "") for item in run_spec.get("blocked_required_steps") or []),
    ))
    if claimed_executable and service._BLOCKED_IMPLEMENTATION_MARKERS.search(readiness):
        targets = ["experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", *[service._relative(root, path) for path in context["source_paths"]]]
        add("IMPL-STATUS-002", "METHOD_CONTRACT claims implemented, but the implementation readiness contract declares required scientific steps blocked, incomplete, or unreachable.", list(dict.fromkeys(targets)), "Wire every required scientific step into the declared entrypoint and record implementation readiness as implemented.")
    if claimed_executable and context["entrypoint"] is None:
        add("IMPL-ENTRY-001", "Implemented method has no existing project-local Python entrypoint.", ["experiments/RUN_SPEC.json", "experiments/src"], "Create the declared executable entrypoint and bind RUN_SPEC.entrypoint/command to it.")


def capability_findings(
    service: Any,
    root: Path,
    context: dict[str, Any],
    *,
    claimed_executable: bool,
    machine_learning: bool,
    add: FindingAdder,
) -> None:
    if not claimed_executable or not machine_learning:
        return
    required = {
        "data_loading": "load real or configured study data into batches",
        "model_forward": "execute the declared model forward path",
        "objective": "compute the declared scientific objective or loss",
        "optimization": "perform backward/gradient calculation and optimizer updates",
        "evaluation": "run inference and compute registered evaluation outputs",
        "persistence": "persist checkpoints, predictions, metrics, or provenance",
        "iteration": "iterate over batches, steps, epochs, samples, or simulation units",
    }
    target = service._relative(root, context["entrypoint"]) if context["entrypoint"] else "experiments/src"
    for capability, requirement in required.items():
        if not context["capabilities"][capability]:
            add(f"IMPL-FLOW-{capability.upper()}", f"Implemented ML method does not {requirement}.", [target], "Implement the missing operation in the reachable training/evaluation path; a static validator or named class is insufficient.")


def _check_symbols(
    service: Any,
    root: Path,
    check: dict[str, Any],
    check_id: str,
    registered: Any,
    definitions: dict[Path, dict[str, ast.AST]],
) -> list[tuple[Path, str]]:
    symbols: list[tuple[Path, str]] = []
    value = resolve_implementation_evidence(check, registered)
    for evidence in normalize_implementation_evidence(value):
        raw_path = str(evidence.get("path") or "").strip()
        candidate = (root / raw_path).resolve() if raw_path else None
        if candidate is None:
            continue
        symbols.extend(
            (candidate, str(symbol).strip())
            for symbol in evidence.get("symbols") or [] if str(symbol).strip()
        )
    return symbols


def implementation_check_findings(
    service: Any,
    root: Path,
    method: dict[str, Any],
    run_spec: dict[str, Any],
    context: dict[str, Any],
    *,
    claimed_executable: bool,
    add: FindingAdder,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    coverage: dict[str, dict[str, Any]] = {}
    unreachable: list[str] = []
    register = implementation_evidence_register_map(method)
    from .implementation_check_evidence import check_coverage
    for check in method.get("implementation_checks") or []:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or check.get("check_id") or "").strip() or "unknown-check"
        symbols = _check_symbols(service, root, check, check_id, register.get(check_id), context["definitions"])
        coverage[check_id] = check_coverage(service, symbols, context)
        substantive = coverage[check_id]["substantive_symbols"]
        required = coverage[check_id]["required_symbols"]
        missing = coverage[check_id]["missing_symbols"]
        if claimed_executable and symbols and not substantive:
            add(f"IMPL-MECH-{check_id}-EMPTY", f"Implementation check {check_id} names symbols but none contains a substantive implementation.", sorted({service._relative(root, path) for path, _ in symbols}), "Replace placeholder/static-only definitions with the actual mechanism computation.")
        if claimed_executable and symbols and (missing or not required):
            unreachable.append(check_id)
            targets = sorted({service._relative(root, path) for path, _ in symbols})
            if context["entrypoint"]:
                targets.append(service._relative(root, context["entrypoint"]))
            if run_spec:
                targets.append("experiments/RUN_SPEC.json")
            add(f"IMPL-MECH-{check_id}-UNREACHABLE", f"Implementation check {check_id} lacks substantive reachable runtime symbols: {', '.join(missing) or 'runtime evidence'}.", list(dict.fromkeys(targets)), "Wire every required runtime symbol into the declared entrypoint; supporting tests and static validators cannot substitute for runtime evidence.")
    return coverage, unreachable


def _prediction_repair_targets(service: Any, root: Path, context: dict[str, Any]) -> list[str]:
    """A missing prediction path needs source repair, not a model-edited status."""
    models = [
        path for path, definitions in context["definitions"].items()
        if path.name == "models.py" or any(
            isinstance(node, ast.ClassDef) and any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name in {"forward", "predict", "__call__"}
                for child in node.body
            ) for node in definitions.values()
        )
    ]
    targets = [*models, *context["entrypoints"]]
    return list(dict.fromkeys(service._relative(root, path) for path in targets))


def audit_result(
    service: Any,
    root: Path,
    method: dict[str, Any],
    run_spec: dict[str, Any],
) -> dict[str, Any]:
    status = str(method.get("status") or "").strip().casefold()
    claimed_implemented = status in service._IMPLEMENTED
    level = str(method.get("implementation_level") or "").strip().casefold()
    deep = bool(run_spec) or level in {"executable_training_pipeline", "executable_experiment_pipeline"}
    claimed_executable = claimed_implemented and deep
    context = source_context(service, root, run_spec)
    contract_text = service._flatten_text(method)
    run_text = service._flatten_text(run_spec)
    from .implementation_blueprint import FAMILIES
    declared = str(method.get('implementation_family') or run_spec.get('implementation_family') or '')
    machine_learning = declared == 'machine_learning' if declared in FAMILIES else bool(
        service._ML_MARKERS.search(" ".join((contract_text, run_text, context["combined_source"][:100000]))))
    findings: list[dict[str, Any]] = []

    def add(identity: str, message: str, targets: list[str], remediation: str) -> None:
        findings.append({
            "id": identity, "severity": "blocker", "category": "implementation",
            "message": message, "plain_message": message,
            "target_files": targets, "evidence": targets,
            "remediation": remediation, "owner_node": "exp-design",
            "upstream_node": "exp-design",
        })

    status_findings(service, root, method, run_spec, context, claimed_executable=claimed_executable, add=add)
    from .implementation_readiness_checks import readiness_findings
    findings.extend(readiness_findings(root, run_spec))
    capability_findings(service, root, context, claimed_executable=claimed_executable, machine_learning=machine_learning, add=add)
    checks, unreachable = implementation_check_findings(service, root, method, run_spec, context, claimed_executable=claimed_executable, add=add)
    probe_configuration = active_probe_configuration_findings(
        root, method, run_spec, add=add if claimed_executable else lambda *_: None
    )
    predictive = machine_learning and bool(re.search(
        r"(?:accuracy|auroc|f1|classification|brier|ece|calibration)", contract_text, re.IGNORECASE))
    if claimed_executable and predictive and not re.search(r"(?:classifier|classification_head|task_head|prediction_head|predictor|logits)", context["reachable_source"], re.IGNORECASE):
        targets = _prediction_repair_targets(service, root, context)
        add("IMPL-INFERENCE-001", "Predictive metrics are registered, but the implementation has no explicit classifier/task head or logits path.", targets, "Implement and invoke the downstream prediction head used to produce the registered metrics.")
    from .evaluation_protocol_validation import evaluation_contract_findings
    findings.extend(evaluation_contract_findings(root))
    if (root / "experiments/METHOD_CONTRACT.json").is_file():
        from .evaluation_conditions_projection import project_evaluation_conditions
        from ..contracts.preparation import PreparationContractError
        try:
            project_evaluation_conditions(method, {})
        except PreparationContractError as error:
            findings.append(error.finding())
    if run_spec.get("scheduled_runs") is not None:
        from .execution_matrix import compile_execution_cells
        from ..contracts.preparation import PreparationContractError
        try:
            compile_execution_cells(run_spec)
        except PreparationContractError as error:
            findings.append(error.finding())
    blocking = bool(findings)
    return {
        "schema_version": 1, "status_claim": status,
        "claimed_implemented": claimed_implemented,
        "deep_audit_applicable": deep, "claimed_executable": claimed_executable,
        "is_machine_learning": machine_learning,
        "entrypoint": service._relative(root, context["entrypoint"]) if context["entrypoint"] else "",
        "entrypoints": [service._relative(root, path) for path in context["entrypoints"]],
        "capabilities": context["capabilities"],
        "reachable_calls": sorted(context["reachable_calls"])[:120],
        "reachable_source_files": [service._relative(root, path) for path, definitions in context["definitions"].items()
                                   if any(id(node) in context["reached_definition_ids"] for node in definitions.values())],
        "implementation_checks": checks,
        "probe_configuration": probe_configuration,
        "unreachable_implementation_checks": unreachable,
        "blocking": blocking, "verdict": "FAIL" if blocking else "PASS",
        "findings": findings,
    }
