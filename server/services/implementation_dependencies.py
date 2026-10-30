"""Stage-specific semantic dependencies for bounded invalidation."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import yaml


_STAGE_INPUTS = {
    "data": (
        "experiments/IMPLEMENTATION_BLUEPRINT.json",
        "experiments/configs/main.yaml",
    ),
    "method": (
        "experiments/IMPLEMENTATION_BLUEPRINT.json",
        "experiments/configs/main.yaml",
    ),
    "training": (
        "experiments/IMPLEMENTATION_BLUEPRINT.json",
        "experiments/RUN_SPEC.json",
        "experiments/configs/main.yaml",
    ),
    "evaluation": (
        "experiments/IMPLEMENTATION_BLUEPRINT.json",
        "experiments/configs/main.yaml",
    ),
    "integration": (
        "ideas/SELECTED_IDEA.json",
        "experiments/IMPLEMENTATION_BLUEPRINT.json",
        "experiments/EXPERIMENT_PLAN.md",
        "experiments/METHOD_CONTRACT.json",
        "experiments/RUN_SPEC.json",
        "experiments/configs/main.yaml",
    ),
}


def stage_semantic_inputs(root: Path, stage_id: str) -> tuple[Path, ...]:
    """Return only inputs whose semantics can invalidate this stage."""
    try:
        values = _STAGE_INPUTS[stage_id]
    except KeyError as error:
        raise ValueError(f"Unknown implementation stage: {stage_id}") from error
    from .impl_stage_targets import target_declaration
    declared = target_declaration(root)
    if declared is None:
        return tuple(root / value for value in values)
    configured = [path for path in declared["integration"] if path.startswith("experiments/configs/")]
    return tuple(root / value for value in dict.fromkeys([
        *(value for value in values if not value.startswith("experiments/configs/")), *configured,
    ]))


def stage_input_fingerprint(path: Path, *, stage_id: str = "") -> str:
    """Canonicalize science; integration diagnostics have a separate obligation gate."""
    if not path.is_file():
        return "missing"
    data = path.read_bytes()
    suffix = path.suffix.casefold()
    try:
        if suffix == ".json":
            payload = json.loads(data.decode("utf-8-sig"))
        elif suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(data.decode("utf-8-sig"))
        else:
            return hashlib.sha256(data).hexdigest()
        if stage_id == "training" and path.name == "RUN_SPEC.json" and isinstance(payload, dict):
            # Closing an integration finding is not a new training protocol.
            # stage_obligations still routes every open blocker; integration and
            # independent review retain the full document in their fingerprints.
            payload = {key: value for key, value in payload.items() if key not in {
                "integration_readiness", "integration_blockers", "integration_resolution",
                "current_static_review", "integration_reclassification_rationale",
                "integration_reclassification_rationale_current",
            }}
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError):
        encoded = data  # Invalid declarations cannot become reusable through normalization.
    return hashlib.sha256(encoded).hexdigest()
