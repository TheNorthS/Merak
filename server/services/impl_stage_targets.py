"""Resolve explicit stage-owned package targets, never guess retired flat aliases.

RUN_SPEC.implementation_stage_targets is optional runtime-owned metadata. When
present it declares the complete five-stage mapping. Only paths change; stages,
ordering, purposes and all semantic validators retain the current contract.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .implementation_stages import (
    ImplementationStage, ML_STAGES, COMPUTATIONAL_STAGES, PROTOCOL_STAGES, FORMAL_STAGES,
)
from .implementation_state_io import load_implementation_state


FIELD = "implementation_stage_targets"
_INTEGRATION_CONTRACTS = {"experiments/RUN_SPEC.json", "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"}


def _canonical_target(root: Path, raw: Any, stage_id: str) -> str:
    if (not isinstance(raw, str) or not raw or raw != raw.strip() or "\\" in raw or ":" in raw
            or PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute()
            or PurePosixPath(raw).as_posix() != raw or any(part in {".", ".."} for part in raw.split("/"))):
        raise ValueError("Implementation stage targets require exact canonical project-relative paths")
    parsed = PurePosixPath(raw)
    source = parsed.parts[:2] == ("experiments", "src") and parsed.suffix == ".py" and len(parsed.parts) >= 3
    config = parsed.parts[:2] == ("experiments", "configs") and parsed.suffix in {".json", ".yaml", ".yml"} and len(parsed.parts) >= 3
    if not source and not (stage_id == "integration" and (raw in _INTEGRATION_CONTRACTS or config)):
        raise ValueError("Implementation stage target is outside its declared source/config ownership: " + raw)
    unresolved, target = root / raw, (root / raw).resolve()
    parents = (unresolved, *unresolved.parents)
    if (not target.is_relative_to(root) or target.relative_to(root).as_posix() != raw
            or any(path.is_symlink() or (path.exists() and getattr(path, "is_junction", lambda: False)())
                   for path in parents if path != root.parent)
            or target.exists() and (not target.is_file() or target.stat().st_nlink > 1)):
        raise ValueError("Implementation target is linked, non-file or outside the owned project: " + raw)
    return raw


def target_declaration(root: str | Path) -> dict[str, list[str]] | None:
    """Validate a complete declaration before blueprint changes or model writes."""
    root = Path(root).resolve()
    run = load_implementation_state(root / "experiments/RUN_SPEC.json")
    if FIELD not in run:
        return None
    value = run[FIELD]
    ids = {stage.id for stage in ML_STAGES}
    if not isinstance(value, dict) or set(value) != ids:
        raise ValueError("Implementation stage targets must map exactly the five registered stage IDs")
    declared, owned = {}, set()
    for stage in ML_STAGES:
        rows = value[stage.id]
        if not isinstance(rows, list) or not rows:
            raise ValueError("Every implementation stage must have a nonempty explicit target list")
        checked = [_canonical_target(root, raw, stage.id) for raw in rows]
        keys = {path.casefold() for path in checked}
        if len(keys) != len(checked) or keys & owned:
            raise ValueError("Stage targets require unique, non-overlapping artifact ownership")
        owned.update(keys)
        declared[stage.id] = checked
    integration = declared["integration"]
    if not _INTEGRATION_CONTRACTS <= set(integration) or not any(path.startswith("experiments/configs/") for path in integration):
        raise ValueError("Integration must own RUN_SPEC, its evidence patch and current configuration")
    if not any(path.endswith(".py") for path in integration):
        raise ValueError("Integration must declare its bounded source/test artifacts")
    return declared


def project_stages(project_path: str | Path, family: str,
                   defaults: tuple[ImplementationStage, ...] | None = None) -> tuple[ImplementationStage, ...]:
    """Project only target paths; no output or accepted-stage record is created."""
    base = defaults or {"machine_learning": ML_STAGES, "computational_general": COMPUTATIONAL_STAGES,
                        "external_protocol": PROTOCOL_STAGES, "formal_verification": FORMAL_STAGES}.get(family, COMPUTATIONAL_STAGES)
    declared = target_declaration(project_path)
    return base if declared is None else tuple(replace(stage, targets=tuple(declared[stage.id])) for stage in base)


def declared_entrypoint(root: Path, fallback: str) -> str:
    declared = target_declaration(root)
    if declared is None:
        return fallback
    value = load_implementation_state(root / "experiments/RUN_SPEC.json").get("entrypoint")
    checked = _canonical_target(root, value, "training")
    if checked not in {path for targets in declared.values() for path in targets}:
        raise ValueError("Declared scientific entrypoint must belong to the exact stage source inventory")
    return checked


def existing_stage_review_instruction(root: Path, stage_id: str, report: dict[str, Any]) -> str:
    """Only a complete fresh semantic PASS may request review without needless edits."""
    declared = target_declaration(root)
    targets = declared[stage_id] if declared else report.get("targets") or []
    if (not targets or report.get("stage_id") != stage_id
            or report.get("passed") is not True or report.get("issues")
            or set(report.get("existing_targets") or []) != set(targets)):
        return "Implement or repair the listed missing/invalid targets; a prose-only completion is insufficient."
    return ("Fresh deterministic validation has passed every current canonical stage target. Read and review the existing "
            "substantive implementation against the frozen scientific contracts; do not rewrite correct source merely "
            "to produce byte changes. Return the checks performed and any actual unresolved defects. Your real model "
            "invocation and the subsequent fresh deterministic gate, not a prose assertion or old acceptance, certify this stage.")
