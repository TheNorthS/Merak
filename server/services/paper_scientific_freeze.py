"""Scientific-input freeze and verified layout-only rebinding."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from ..utils.atomic_write import atomic_write_json
from . import paper_draft_state
from .manuscript_text import read_json, read_owned_state, stable_source_hash, write_json
from .paper_artifacts import semantic_derived_hash, semantic_derived_payload

HASH_MODE = "semantic-derived-v1"


def scientific_freeze_inputs(root: Path) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for path in paper_draft_state.source_paths(root):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and relative in paper_draft_state.DERIVED_SOURCE_PATHS:
            inputs[relative] = _semantic_or_file_hash(path, relative)
        else:
            inputs[relative] = stable_source_hash(path) or "<missing>"
    return inputs


def _semantic_or_file_hash(path: Path, relative: str) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return stable_source_hash(path) or "<missing>"
    return semantic_derived_hash(relative, payload)






def rebind_layout_only_derived_inputs(
    root: Path,
    options: Optional[dict[str, Any]] = None,
    *,
    before_manifest: Optional[dict[str, Any]] = None,
    target_files: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    targets = _normalized_table_targets(target_files)
    if not targets:
        return {"passed": False, "issues": [
            "layout-only rebind requires bounded paper/tables/*.tex targets"
        ]}
    freeze_path = root / "paper" / "SCIENTIFIC_FREEZE.json"
    freeze_before = read_json(freeze_path)
    # Reject unsupported bindings before touching table manifests or hashes.
    if freeze_before.get("schema_version") != 1 or freeze_before.get("input_hash_mode") != HASH_MODE:
        return {"passed": False, "issues": ["Scientific freeze is missing or unsupported"]}
    if "paper/tables/synthetic_preview_results.tex" in targets:
        issues = refresh_simulation_table_binding(root)
        if issues:
            return {"passed": False, "issues": issues}
    bound = _rebind_table_manifest(root, targets, before_manifest)
    if not bound["passed"]:
        return bound
    freeze = freeze_scientific_inputs(root, options)
    _bind_draft_state(root, freeze, options)
    return {
        "passed": True,
        "freeze_id": str(freeze.get("freeze_id") or ""),
        "generation": int(freeze.get("generation") or 0),
        "target_files": sorted(targets),
        "semantic_rebound": True,
    }


def _normalized_table_targets(targets: Optional[Iterable[str]]) -> set[str]:
    normalized = {
        str(item or "").replace("\\", "/").casefold()
        for item in (targets or []) if str(item or "").strip()
    }
    if not normalized or any(
        not item.startswith("paper/tables/") or not item.endswith(".tex")
        for item in normalized
    ):
        return set()
    return normalized




def _rebind_table_manifest(
    root: Path, targets: set[str], before: Optional[dict[str, Any]]
) -> dict[str, Any]:
    path = root / "paper" / "tables" / "TABLE_MANIFEST.json"
    current = _read_json_object(path)
    if current is None:
        return {"passed": False, "issues": [
            "paper/tables/TABLE_MANIFEST.json is missing or invalid"
        ]}
    entries = [item for item in current.get("tables") or [] if isinstance(item, dict)]
    changed, issue = _rebind_latex_hashes(root, entries, targets)
    if issue:
        return {"passed": False, "issues": [issue]}
    from .paper_artifacts import bind_table_manifest_hashes

    bound, issues, _ = bind_table_manifest_hashes(root, current)
    if issues:
        return {"passed": False, "issues": list(issues)}
    if before is not None and _table_projection(before) != _table_projection(bound):
        return {"passed": False, "issues": [
            "bounded table repair changed scientific manifest fields; only renderer/layout fields may be rebound"
        ]}
    if changed:
        bound["updated_at"] = time.time()
        atomic_write_json(path, bound)
    return {"passed": True}


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _rebind_latex_hashes(
    root: Path, entries: list[dict[str, Any]], targets: set[str]
) -> tuple[bool, str]:
    changed = False
    for item in entries:
        relative = str(item.get("latex_path") or "").replace("\\", "/").casefold()
        if relative not in targets:
            continue
        candidate = root / Path(relative)
        if not candidate.is_file() or candidate.stat().st_size == 0:
            return changed, f"edited table source is missing: {relative}"
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if item.get("latex_sha256") != digest:
            item["latex_sha256"] = digest
            changed = True
    return changed, ""


def _table_projection(payload: dict[str, Any]) -> Any:
    return semantic_derived_payload("paper/tables/TABLE_MANIFEST.json", payload)


def refresh_simulation_table_binding(root: Path) -> list[str]:
    """Verify paper-owned layout projection; never rewrite frozen scientific hashes."""
    simulation_path = root / "experiments" / "results" / "simulated" / "SIMULATION_MANIFEST.json"
    if not simulation_path.is_file():
        return []
    payload = _read_json_object(simulation_path)
    if payload is None:
        return ["simulation manifest is missing or invalid"]
    expected = str(payload.get("paper_table") or "").replace("\\", "/")
    if expected != "paper/tables/synthetic_preview_results.tex":
        return ["simulation manifest is not bound to the canonical preview table"]
    table_path = root / Path(expected)
    if not table_path.is_file() or table_path.stat().st_size == 0:
        return ["canonical synthetic preview table is missing"]
    from .simulation_table_projection_binding import verify_simulation_table_projection
    try:
        verify_simulation_table_projection(root, payload)
    except (ValueError, OSError, KeyError, TypeError) as error:
        return [f"paper table layout source verification failed: {error}"]
    return []


def freeze_scientific_inputs(
    root: Path, options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Bind current scientific inputs; never reinterpret unsupported hash modes."""
    path = root / "paper" / "SCIENTIFIC_FREEZE.json"
    previous = read_json(path)
    if previous and (
        previous.get("schema_version") != 1
        or previous.get("input_hash_mode") != HASH_MODE
    ):
        raise ValueError("Unsupported scientific freeze; create a new current-schema draft.")
    current = scientific_freeze_inputs(root)
    normalized_options = paper_draft_state.signature_options(options)
    evidence = paper_draft_state.evidence_status(root)
    if _unchanged(previous, current, normalized_options, evidence):
        return previous
    payload = _new_freeze_payload(previous, current, normalized_options, evidence)
    write_json(path, payload)
    return payload


def _unchanged(
    previous: dict[str, Any], inputs: dict[str, str],
    options: dict[str, Any], evidence: dict[str, Any],
) -> bool:
    return bool(
        previous.get("schema_version") == 1
        and previous.get("input_hash_mode") == HASH_MODE
        and previous.get("inputs") == inputs
        and previous.get("options") == options
        and previous.get("evidence") == evidence
    )


def _new_freeze_payload(
    previous: dict[str, Any], inputs: dict[str, str], options: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Advance identity only after the scientific inputs or options change."""
    stable = {
        "schema_version": 1,
        "input_hash_mode": HASH_MODE,
        "generation": max(0, int(previous.get("generation") or 0)) + 1,
        "inputs": inputs,
        "options": options,
        "evidence": evidence,
    }
    freeze_id = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:20]
    return {
        **stable,
        "freeze_id": freeze_id,
        "changed_inputs": _changed_inputs(previous, inputs),
        "previous_freeze_id": str(previous.get("freeze_id") or ""),
        "created_at": time.time(),
        "history": _history(previous),
    }


def _changed_inputs(previous: dict[str, Any], current: dict[str, str]) -> list[str]:
    old = dict(previous.get("inputs") or {})
    return sorted(key for key in set(old) | set(current) if old.get(key) != current.get(key))


def _history(previous: dict[str, Any]) -> list[dict[str, Any]]:
    history = [dict(item) for item in list(previous.get("history") or [])[-19:] if isinstance(item, dict)]
    if previous.get("freeze_id"):
        history.append({"freeze_id": str(previous.get("freeze_id") or ""),
                        "generation": int(previous.get("generation") or 0),
                        "created_at": float(previous.get("created_at") or 0.0)})
    return history[-20:]




def validate_scientific_freeze(
    root: Path, options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Reject unsupported formats before comparing current semantic bindings."""
    freeze = read_json(root / "paper" / "SCIENTIFIC_FREEZE.json")
    if freeze.get("schema_version") != 1 or freeze.get("input_hash_mode") != HASH_MODE:
        return {"passed": False, "issues": [
            "paper/SCIENTIFIC_FREEZE.json is missing or unsupported"
        ]}
    current = scientific_freeze_inputs(root)
    current_options = paper_draft_state.signature_options(options)
    changed = _changed_inputs(freeze, current)
    issues = _freeze_issues(root, freeze, current_options, changed)
    return {
        "passed": not issues, "issues": issues,
        "freeze_id": str(freeze.get("freeze_id") or ""),
        "generation": int(freeze.get("generation") or 0),
        "changed_inputs": changed, "input_hash_mode": HASH_MODE,
    }


def _freeze_issues(
    root: Path, freeze: dict[str, Any], options: dict[str, Any],
    changed: list[str],
) -> list[str]:
    issues: list[str] = []
    if changed:
        issues.append("scientific inputs changed after paper freeze: " + ", ".join(changed))
    if freeze.get("options") != options:
        issues.append("paper authoring options changed after scientific freeze")
    if freeze.get("evidence") != paper_draft_state.evidence_status(root):
        issues.append("paper evidence status changed after scientific freeze")
    return issues


def source_signature(root: Path, options: Optional[dict[str, Any]] = None) -> str:
    digest = hashlib.sha256()
    inputs = scientific_freeze_inputs(root)
    for relative in sorted(inputs):
        digest.update(relative.encode("utf-8"))
        digest.update(str(inputs[relative]).encode("ascii"))
    digest.update(json.dumps(paper_draft_state.signature_options(options), sort_keys=True).encode())
    return digest.hexdigest()


def authoring_signature(root: Path, options: Optional[dict[str, Any]] = None) -> str:
    payload = {
        "schema_version": 2,
        "inputs": paper_draft_state.authoring_input_hashes(root),
        "options": paper_draft_state.signature_options(options),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _bind_draft_state(
    root: Path, freeze: dict[str, Any], options: Optional[dict[str, Any]]
) -> None:
    paths = paper_draft_state.drafting_paths(root)
    state = read_owned_state(paths["state"])
    state["scientific_freeze_id"] = str(freeze.get("freeze_id") or "")
    state["scientific_freeze_generation"] = int(freeze.get("generation") or 0)
    state["source_signature"] = source_signature(root, options)
    state["updated_at"] = time.time()
    write_json(paths["state"], state)
    reviews = read_owned_state(paths["reviews"])
    if isinstance(reviews, dict):
        reviews["source_signature"] = state["source_signature"]
        write_json(paths["reviews"], reviews)
