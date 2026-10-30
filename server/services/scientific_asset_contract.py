"""Build publication-facing scientific context from frozen project contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .scientific_assets import _clean_name, _contract_json

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ArchitectureBuilder = Callable[[Path, dict[str, Any]], dict[str, Any]]


def build_contract_context(
    root: Path, architecture_builder: ArchitectureBuilder
) -> dict[str, Any]:
    selected = _contract_json(root / "ideas" / "SELECTED_IDEA.json")
    method = _contract_json(root / "experiments" / "METHOD_CONTRACT.json")
    run_spec = _contract_json(root / "experiments" / "RUN_SPEC.json")
    implementation = _contract_json(
        root / "experiments" / "IMPLEMENTATION_BLUEPRINT.json"
    )
    config = _load_config(root / "experiments" / "configs" / "main.yaml")
    claims = _claims(selected)
    mechanisms = _mechanisms(selected)
    architecture = architecture_builder(root, method)
    sources = _source_artifacts(root, architecture)
    probes = _probe_configuration(root, method, run_spec)
    sources.extend(
        str(item["source_path"]) for item in probes
        if item.get("source_path") and str(item["source_path"]) not in sources
    )
    containers = (run_spec, selected, method, implementation, config)
    return {
        "title": _clean_name(selected.get("title"), "Selected research idea", 320),
        "hypothesis": _clean_name(
            selected.get("hypothesis"), claims[0]["statement"], 800
        ),
        "claims": claims,
        "mechanisms": mechanisms,
        "problem_statement": _clean_name(
            selected.get("problem_statement"), selected.get("hypothesis"), 1200
        ),
        "endpoints": _endpoints(selected),
        "comparators": _clean_list(
            selected.get("recommended_baselines_or_comparators"), 120
        ),
        "datasets": _declared_list(
            containers, "datasets", "dataset", "dataset_id", "cohorts", "cohort_id"
        ),
        "models": _declared_list(
            containers, "models", "model", "model_id", "architecture", "backbones"
        ),
        "adaptation_regimes": _declared_list(
            containers, "adaptation_regimes", "study_conditions", "stress_conditions",
            "training_conditions", "objective_conditions", "conditions",
        ),
        "tasks": _declared_list(
            containers, "tasks", "task", "task_id", "task_type", "downstream_tasks"
        ),
        "inputs": _declared_list(
            containers, "inputs", "observed_inputs", "input_modalities", "modalities"
        ),
        "outputs": _declared_list(
            containers, "outputs", "reported_endpoints", "primary_endpoints"
        ),
        "falsification": _clean_list(selected.get("falsification_conditions"), 1000),
        "method_contract": method,
        "probe_configuration": probes,
        "architecture_blueprint": architecture,
        "run_spec": run_spec,
        "config": config,
        "experiment_plan_bytes": _registered_plan_bytes(root),
        "source_artifacts": sources,
        "publication": dict(selected.get("publication") or {}),
    }


def _registered_plan_bytes(root: Path) -> bytes | None:
    """Read the canonical plan only; a foreign source cannot supply split semantics."""
    path = root / "experiments/EXPERIMENT_PLAN.md"
    if not path.exists():
        return None
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("evaluation_design registered plan source is linked, foreign or not a file")
    return path.read_bytes()


def _load_config(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _probe_configuration(
    root: Path, method: dict[str, Any], run_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    from .implementation_configuration import active_probe_configuration_findings

    return active_probe_configuration_findings(
        root, method, run_spec, add=lambda *_args: None,
    )


def _claims(selected: dict[str, Any]) -> list[dict[str, str]]:
    claims = [
        {
            "id": str(item.get("id") or f"C{index + 1}").strip(),
            "statement": _clean_name(item.get("publication_statement"), "", 600),
        }
        for index, item in enumerate(selected.get("claims") or [])
        if isinstance(item, dict)
    ]
    if claims:
        return claims
    return [{
        "id": "C1",
        "statement": _clean_name(
            selected.get("hypothesis"),
            "The selected mechanism changes the declared primary outcome.",
            600,
        ),
    }]


def _mechanisms(selected: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for item in selected.get("mechanisms") or []:
        if not isinstance(item, dict):
            continue
        name = _clean_name(item.get("publication_name"), "", 240)
        description = _clean_name(item.get("publication_description"), "", 800)
        result.append({
            "id": str(item.get("id") or "").strip(),
            "name": name,
            "description": description,
            "role": _mechanism_role(name, description),
        })
    return result


def _mechanism_role(name: str, description: str) -> str:
    name_text, description_text = name.casefold(), description.casefold()
    name_groups = (
        ("training", ("dropout", "augmentation", "corruption", "perturbation",
                      "distillation", "regularization", "training objective")),
        ("output", ("head", "decoder", "classifier", "predictor", "prediction",
                    "output", "readout", "regressor", "calibrator")),
        ("core", ("token", "encoder", "backbone", "attention", "representation",
                  "fusion", "mixer", "graph", "embedding", "feature extractor")),
        ("conditioning", ("mask", "metadata", "condition", "availability", "context",
                          "side information", "prompt", "control variable")),
    )
    for role, markers in name_groups:
        if any(marker in name_text for marker in markers):
            return role
    description_groups = (
        ("training", ("during training", "during pretraining", "training-only",
                      "augment the", "corrupt the", "remove or transform")),
        ("output", ("output a prediction", "produces predictions",
                    "estimate uncertainty", "predict or estimate uncertainty", "task output")),
        ("conditioning", ("first-class model inputs", "supplied as input",
                          "conditioning signal", "observation state", "availability state")),
    )
    for role, markers in description_groups:
        if any(marker in description_text for marker in markers):
            return role
    return "core"


def _endpoints(selected: dict[str, Any]) -> list[str]:
    return [
        cleaned
        for claim in selected.get("claims") or [] if isinstance(claim, dict)
        for endpoint in claim.get("measurable_endpoints") or []
        if (cleaned := _clean_name(endpoint, "", 240))
    ]


def _clean_list(value: Any, limit: int) -> list[str]:
    return [
        cleaned for item in (value if isinstance(value, list) else [])
        if (cleaned := _clean_name(item, "", limit))
    ]


def _declared_list(
    containers: tuple[dict[str, Any], ...], *names: str
) -> list[str]:
    wanted = {name.casefold() for name in names}
    found: list[str] = []
    for container in containers:
        _visit_declarations(container, wanted, found)
    return list(dict.fromkeys(found))[:8]


def _visit_declarations(value: Any, wanted: set[str], found: list[str]) -> None:
    if isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                _visit_declarations(child, wanted, found)
        return
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        if str(key).casefold() in wanted:
            candidates = child if isinstance(child, list) else [child]
            for candidate in candidates:
                _add_declaration(candidate, wanted, found)
        if isinstance(child, (dict, list)):
            _visit_declarations(child, wanted, found)


def _add_declaration(candidate: Any, wanted: set[str], found: list[str]) -> None:
    if isinstance(candidate, dict):
        for key in (
            "name", "title", "id", "type", "architecture", "task_type",
            "dataset_id", "task_id",
        ):
            _append_declaration(candidate.get(key), found)
        if wanted & {
            "conditions", "study_conditions", "training_conditions",
            "objective_conditions",
        }:
            for identity in candidate:
                _append_declaration(identity, found)
        return
    _append_declaration(candidate, found)


def _append_declaration(candidate: Any, found: list[str]) -> None:
    if isinstance(candidate, (dict, list)):
        return
    clean = _clean_name(candidate, "", 120)
    clean = re.split(
        r"\b(?:pending (?:data compatibility|from data contract|experiment)|"
        r"runtime required|not executed|integration blocked|unreachable|"
        r"implementation in progress)\b",
        clean,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" -:/")
    if clean and clean.casefold() not in {"pending", "none", "null"}:
        found.append(clean)


def _source_artifacts(
    root: Path, architecture: dict[str, Any]
) -> list[str]:
    sources = [
        path.relative_to(root).as_posix()
        for path in (
            root / "ideas" / "SELECTED_IDEA.json",
            root / "experiments" / "METHOD_CONTRACT.json",
            root / "experiments" / "RUN_SPEC.json",
            root / "experiments" / "EXPERIMENT_PLAN.md",
            root / "experiments" / "configs" / "main.yaml",
        )
        if path.is_file() and path.stat().st_size > 0
    ]
    sources.extend(
        str(path)
        for path in architecture.get("source_paths") or []
        if str(path).strip() and str(path) not in sources
    )
    return sources
