"""Project discovered implementation components into a bounded paper architecture."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def project_architecture(
    *, root: Path, implementation_family: str, method: dict[str, Any],
    components: list[dict[str, Any]], flows: list[dict[str, str]],
    source_paths: list[str], constraints: list[dict[str, str]],
    verification_symbols: list[dict[str, str]],
) -> dict[str, Any]:
    completeness, inference_ids = _ensure_prediction_head(
        method, components
    )
    lanes = _lane_ids(components)
    entry, output = _representation_terminals(components, flows, lanes)
    _infer_cross_lane_flows(
        components, flows, lanes, entry, output, inference_ids
    )
    training_paths, inference_paths, auxiliary = _scientific_paths(
        components, flows, lanes, inference_ids
    )
    check, ready = _implementation_readiness(
        root, source_paths, method, implementation_family, completeness
    )
    selected = _selected_component_ids(
        components, training_paths, inference_paths, auxiliary
    )
    visual_components = [
        item for item in components if str(item.get("id") or "") in selected
    ]
    visual_flows = [
        item for item in flows
        if str(item.get("from") or "") in selected
        and str(item.get("to") or "") in selected
    ][:40]
    return _projection_payload(
        root, implementation_family, visual_components, visual_flows,
        training_paths, inference_paths, auxiliary, selected, source_paths,
        constraints, verification_symbols, completeness, lanes, check, ready,
    )


def _ensure_prediction_head(
    method: dict[str, Any], components: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    evaluation = method.get("evaluation_contract") or {}
    outcomes = list(evaluation.get("primary_outcomes") or [])
    predictive = any(
        term in str(value).casefold()
        for value in outcomes
        for term in (
            "accuracy", "f1", "auroc", "classification", "prediction",
            "forecast", "regression", "diagnosis", "risk score", "c-index",
        )
    )
    inference_ids = [
        str(item.get("id") or "") for item in components
        if any(term in " ".join((
            str(item.get("label") or ""), str(item.get("source_symbol") or ""),
            str(item.get("display_name") or ""),
            str(item.get("operation") or ""),
        )).casefold() for term in (
            "classifier", "classification head", "task head", "prediction head",
            "predictor", "logits", "regressor", "risk head", "probe",
        ))
    ]
    issues: list[str] = []
    if predictive and not inference_ids:
        issues.append(
            "predictive evaluation is declared but no classifier/task head is implemented; the diagram marks a contract-inferred prediction adapter"
        )
        component_id = _unique_id(components, "contract_inferred_task_head")
        components.append({
            "id": component_id, "label": "Downstream Task Head",
            "display_name": "Downstream Task Head",
            "operation": (
                "Contract-required prediction adapter for " + ", ".join(map(str, outcomes))
                if outcomes else "Contract-required prediction adapter"
            ),
            "lane": "evaluation", "source_path": "experiments/METHOD_CONTRACT.json",
            "source_symbol": "evaluation_contract.primary_outcomes",
            "parent_component": "", "required_visual": True,
            "publication_visible": True, "evidence_status": "contract_inferred",
            "visual_style": "dashed_planned",
        })
        inference_ids = [component_id]
    return issues, inference_ids


def _unique_id(components: list[dict[str, Any]], base: str) -> str:
    existing = {str(item.get("id") or "") for item in components}
    candidate, index = base, 2
    while candidate in existing:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _lane_ids(components: list[dict[str, Any]]) -> dict[str, list[str]]:
    lanes: dict[str, list[str]] = {}
    for item in components:
        lanes.setdefault(str(item.get("lane") or "model"), []).append(
            str(item.get("id") or "")
        )
    return lanes


def _component_priority(
    component_id: str, terms: tuple[str, ...], by_id: dict[str, dict[str, Any]]
) -> int:
    item = by_id.get(component_id, {})
    text = " ".join((
        str(item.get("label") or ""), str(item.get("source_symbol") or ""),
        str(item.get("operation") or ""),
    )).casefold()
    return max(
        (len(terms) - index for index, term in enumerate(terms) if term in text),
        default=0,
    )


def _representation_terminals(
    components: list[dict[str, Any]], flows: list[dict[str, str]],
    lanes: dict[str, list[str]],
) -> tuple[str, str]:
    by_id = {str(item.get("id") or ""): item for item in components}
    parents = {str(item.get("parent_component") or "") for item in components
               if str(item.get("parent_component") or "")}
    data_edges = [item for item in flows if item.get("flow_kind") == "data"]
    incoming = {str(item.get("to") or "") for item in data_edges}
    outgoing = {str(item.get("from") or "") for item in data_edges}
    leaves = [item for item in lanes.get("representation_model", []) if item not in parents]
    entries = [item for item in leaves if item not in incoming] or leaves
    outputs = [item for item in leaves if item not in outgoing] or leaves
    entry = max(
        entries,
        key=lambda item: _component_priority(
            item, ("stem", "patch", "token", "input", "embedding", "encoder"), by_id
        ),
        default="",
    )
    output = max(
        outputs,
        key=lambda item: _component_priority(
            item, ("projection", "embedding", "pool", "readout", "encoder"), by_id
        ),
        default="",
    )
    return entry, output


def _append_flow(
    flows: list[dict[str, str]], source: str, target: str,
    operation: str, kind: str,
) -> None:
    if not source or not target or source == target:
        return
    if any(item.get("from") == source and item.get("to") == target for item in flows):
        return
    flows.append({
        "from": source, "to": target, "operation": operation,
        "flow_kind": kind, "source_path": "experiments/METHOD_CONTRACT.json",
        "source_symbol": "architecture_contract_inference",
    })


def _infer_cross_lane_flows(
    components: list[dict[str, Any]], flows: list[dict[str, str]],
    lanes: dict[str, list[str]], entry: str, output: str,
    inference_ids: list[str],
) -> None:
    by_id = {str(item.get("id") or ""): item for item in components}
    def priority(item: str, terms: tuple[str, ...]) -> int:
        return _component_priority(item, terms, by_id)
    data_ids = lanes.get("data_and_sampling", [])
    loaders = [item for item in data_ids if priority(item, ("load", "reader", "manifest", "dataset"))]
    splits = [item for item in data_ids if priority(item, ("split", "sampler", "partition", "fold"))]
    conditioning = [item for item in data_ids if priority(
        item, ("mask", "augment", "corrupt", "topology", "view", "perturb")
    )]
    chain = list(dict.fromkeys(loaders + splits))
    for source, target in zip(chain, chain[1:]):
        _append_flow(flows, source, target, "data contract", "inferred_data_contract")
    if chain and entry:
        _append_flow(flows, chain[-1], entry, "batch input", "inferred_data_contract")
    for component_id in conditioning:
        _append_flow(flows, component_id, entry, "conditioning or transformed input", "inferred_data_contract")
    _infer_objective_and_output_flows(
        components, flows, lanes, output, inference_ids, priority
    )


def _infer_objective_and_output_flows(
    components: list[dict[str, Any]], flows: list[dict[str, str]],
    lanes: dict[str, list[str]], output: str, inference_ids: list[str],
    priority: Any,
) -> None:
    parents = {str(item.get("parent_component") or "") for item in components
               if str(item.get("parent_component") or "")}
    incoming = {str(item.get("to") or "") for item in flows}
    for component_id in lanes.get("training_objective", []):
        if component_id in incoming or component_id in parents:
            continue
        if priority(component_id, ("loss", "objective", "xent", "contrastive", "criterion")):
            _append_flow(flows, output, component_id, "optimization objective", "inferred_objective_contract")
    for component_id in inference_ids:
        if component_id not in incoming:
            _append_flow(flows, output, component_id, "downstream prediction", "inferred_inference_contract")


def _scientific_paths(
    components: list[dict[str, Any]], flows: list[dict[str, str]],
    lanes: dict[str, list[str]], inference_ids: list[str],
) -> tuple[list[list[str]], list[list[str]], list[str]]:
    edges = [
        (str(item.get("from") or ""), str(item.get("to") or ""))
        for item in flows if item.get("flow_kind") not in {"containment", "module_reference"}
    ]
    incoming: dict[str, list[str]] = {}
    for source, target in edges:
        incoming.setdefault(target, []).append(source)

    def longest(target: str, seen: set[str] | None = None) -> list[str]:
        seen = seen or set()
        if target in seen or not incoming.get(target):
            return [target]
        return max(
            (longest(parent, seen | {target}) + [target] for parent in incoming[target]),
            key=len,
        )

    objectives = lanes.get("training_objective", [])
    training = [longest(item) for item in objectives if item in incoming]
    inference = [longest(item) for item in inference_ids]
    auxiliary = [
        item for lane in ("diagnostics_and_accounting", "evaluation")
        for item in lanes.get(lane, []) if item not in inference_ids
    ]
    return training, inference, auxiliary


def _implementation_readiness(
    root: Path, source_paths: list[str], method: dict[str, Any],
    family: str, issues: list[str],
) -> tuple[dict[str, Any], bool]:
    from .scientific_assets import _json

    path = root / ".merak" / "quality" / "training_check.json"
    check = _json(path)
    if check and path.is_file():
        checked_at = path.stat().st_mtime_ns
        sources = [root / relative for relative in source_paths if (root / relative).is_file()]
        sources.extend(item for item in (
            root / "experiments" / "IMPLEMENTATION_BLUEPRINT.json",
            root / "experiments" / "METHOD_CONTRACT.json",
            root / "experiments" / "RUN_SPEC.json",
        ) if item.is_file())
        if any(item.stat().st_mtime_ns > checked_at for item in sources):
            check = {}
    ready = bool(
        not check.get("blocking")
        and str(check.get("verdict") or "").casefold() in {"pass", "passed", "ready", "warn"}
    )
    if check and not ready:
        issues.append("Static implementation review has unresolved blockers; execution is not established by this review")
    return check, ready


def _selected_component_ids(
    components: list[dict[str, Any]], training: list[list[str]],
    inference: list[list[str]], auxiliary: list[str],
) -> set[str]:
    priority = list(dict.fromkeys(item for path in training + inference for item in path))
    priority.extend(
        str(item.get("id") or "") for item in components
        if str(item.get("source_path") or "").casefold().endswith((
            "/models.py", "/model.py", "/network.py", "/networks.py",
            "/architecture.py", "/architectures.py",
        )) and str(item.get("id") or "") not in priority
    )
    priority.extend(item for item in auxiliary if item not in priority)
    priority.extend(str(item.get("id") or "") for item in components
                    if str(item.get("id") or "") not in priority)
    return set(priority[:28])


def _projection_payload(
    root: Path, family: str, components: list[dict[str, Any]],
    flows: list[dict[str, str]], training: list[list[str]],
    inference: list[list[str]], auxiliary: list[str], selected: set[str],
    source_paths: list[str], constraints: list[dict[str, str]],
    verification: list[dict[str, str]], issues: list[str],
    lanes: dict[str, list[str]], check: dict[str, Any], ready: bool,
) -> dict[str, Any]:
    architecture_name = {
        "machine_learning": "model_architecture",
        "formal_verification": "formal_reasoning_architecture",
        "external_protocol": "protocol_analysis_architecture",
        "computational_general": "computational_method_architecture",
    }.get(family, "scientific_method_architecture")
    unique_verification = _unique_verification(verification)
    return {
        "schema": 1, "implementation_family": family,
        "diagram_kind": f"implementation_bound_{architecture_name}" if ready or not check else f"design_scaffold_{architecture_name}",
        "implementation_status": "statically_reviewed" if ready else "review_blocked" if check else "contract_mapped",
        "verification_scope": "static_source_review; neither PASS nor WARN proves scientific execution",
        "components": components, "tensor_flow": flows,
        "training_paths": [[item for item in path if item in selected] for path in training if len([item for item in path if item in selected]) >= 2],
        "inference_paths": [[item for item in path if item in selected] for path in inference if len([item for item in path if item in selected]) >= 2],
        "auxiliary_paths": [auxiliary] if auxiliary else [],
        "source_paths": source_paths, "configuration_constraints": constraints[:20],
        "model_configuration": _model_configuration(root),
        "verification_symbols": unique_verification[:20], "completeness_issues": issues,
        "requires_multi_lane_layout": len(lanes) >= 3 or bool(auxiliary),
        "generic_topology_forbidden": True,
        "required_distinctions": _required_distinctions(family),
    }


def _unique_verification(items: list[dict[str, str]]) -> list[dict[str, str]]:
    unique, seen = [], set()
    for item in items:
        key = (str(item.get("source_path") or ""), str(item.get("source_symbol") or ""))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _model_configuration(root: Path) -> dict[str, Any]:
    """Read declared model facts without changing the flat model output contract."""
    try:
        import yaml
    except ImportError:
        return {}
    try:
        path = root / "experiments" / "configs" / "main.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    if not isinstance(payload, dict):
        return {}
    method = payload.get("method")
    method = method if isinstance(method, dict) else {}
    # A declared top-level section wins even when it is intentionally empty.
    configuration = {**method, **payload}
    raw_model = configuration.get("model")
    model = dict(raw_model) if isinstance(raw_model, dict) else {}
    suite = configuration.get("model_suite")
    calibration = configuration.get("calibration")
    model["model_suite"] = list(suite) if isinstance(suite, list) else []
    model["calibration"] = dict(calibration) if isinstance(calibration, dict) else {}
    for section in ("objective", "data", "ablations"):
        value = configuration.get(section)
        if isinstance(value, dict):
            model[section] = dict(value)
    return model


def _required_distinctions(family: str) -> list[str]:
    return {
        "machine_learning": ["data or sampling intervention", "representation/model internals", "training objective", "diagnostic or evaluation-only branches"],
        "formal_verification": ["definitions and assumptions", "lemmas/construction and logical dependencies", "proof obligations or claims", "checker, counterexample, bound, and complexity branches"],
        "external_protocol": ["population/corpus and eligibility or sampling", "procedure, estimand, coding, or analysis internals", "intervention/exposure/interpretive mechanism", "outcome, sensitivity, subgroup, triangulation, or negative-case branches"],
        "computational_general": ["inputs, parameters, and scenarios", "algorithm/numerical-method internals", "objectives, constraints, or boundary conditions", "outputs, sensitivity, stability, failure, and resource branches"],
    }.get(family, ["scientific inputs", "method internals", "mechanism or constraints", "evaluation and failure branches"])
