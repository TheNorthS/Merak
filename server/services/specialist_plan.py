"""Durable preparation of profile-specific specialist execution plans."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


def _existing_entry_valid(service: Any, root: Path, entry: dict[str, Any], old: dict[str, Any]) -> bool:
    artifact = root / str(entry["artifact"])
    if old.get("dependency_review"):
        from .specialist_dependency_review import dependency_review_valid
        if not dependency_review_valid(root, old["dependency_review"], entry["input_digest"], artifact):
            return False
    execution_valid = (
        old.get("status") == "completed" and service._invocation_trace_valid(root, old)[0]
    ) or (
        old.get("status") == "reused" and bool(str(old.get("reused_from_run") or "").strip())
    )
    return bool(
        old.get("input_digest") == entry["input_digest"]
        and old.get("status") in {"completed", "reused"}
        and old.get("artifact_sha256") == service._sha256(artifact)
        and service._artifact_valid(root, old)[0]
        and execution_valid
    )


def _restore_entry(
    service: Any,
    root: Path,
    plan_path: Path,
    entry: dict[str, Any],
    old: dict[str, Any],
) -> None:
    if _existing_entry_valid(service, root, entry, old):
        for key in (
            "status", "artifact_sha256", "session_id", "completed_at",
            "model_provider", "model_name", "invocation_trace",
        ):
            entry[key] = old.get(key, "" if key not in {"completed_at"} else None)
        if old.get("status") == "reused":
            for key in ("reused_from_run", "reused_model_session_id", "reused_invocation_trace"):
                if key in old:
                    entry[key] = old[key]
        if old.get("dependency_review"):
            entry["dependency_review"] = old["dependency_review"]
        return
    recovered = service._recover_project_trace_entry(root, entry)
    reusable = service._reusable_entry(root, plan_path, entry)
    transport_fallback = (
        service._completed_trace_fallback_entry(root, entry)
        if old.get("status") == "failed" and service._is_transient_failure(old.get("error"))
        else None
    )
    if recovered:
        entry.update(recovered)
    elif reusable:
        entry.update({
            "status": "reused",
            "artifact_sha256": reusable.get("artifact_sha256"),
            "session_id": "",
            "completed_at": time.time(),
            "reused_from_run": reusable.get("run_id", ""),
            "reused_model_session_id": reusable.get("session_id", ""),
            "reused_invocation_trace": reusable.get("invocation_trace", ""),
        })
    elif transport_fallback:
        entry.update(transport_fallback)
        entry["transport_warning"] = str(old.get("error") or "")[:2000]
    else:
        entry["status"] = "pending"


def prepare_specialist_plan(
    service: Any,
    project_path: str | Path,
    run_id: str,
    direction: str,
    options: dict[str, Any],
    selected_node_ids: list[str] | set[str] | tuple[str, ...],
) -> dict[str, Any]:
    from .publication_style import publication_style_service

    root = Path(project_path).expanduser().resolve()
    style = publication_style_service.prepare(
        root, direction,
        target_venue=str(options.get("target_venue") or ""),
        research_family=str(options.get("research_family") or ""),
        study_archetype=str(options.get("study_archetype") or ""),
    )
    family = str(style.get("family") or "generic_quantitative")
    archetype = str(style.get("study_archetype") or "generic_empirical")
    path = service.plan_path(root, run_id)
    previous = service.load(root, run_id)
    previous_entries = {
        str(item.get("id") or ""): item for item in previous.get("subnodes", [])
        if isinstance(item, dict)
    }
    enabled = {str(item) for item in selected_node_ids}
    enabled.update(
        str(item.get("node_id") or "") for item in previous.get("subnodes", [])
        if isinstance(item, dict) and str(item.get("node_id") or "").strip()
    )
    entries: list[dict[str, Any]] = []
    for spec in service._selected_specs(family, archetype):
        if spec.node_id not in enabled:
            continue
        entry = spec.as_dict()
        entry["input_digest"] = service._input_digest(root, style, spec, options)
        _restore_entry(service, root, path, entry, previous_entries.get(spec.id, {}))
        entry["run_id"] = run_id
        entries.append(entry)
    profile = {
        "family": family, "study_archetype": archetype,
        "target_venue": style.get("target_venue", ""),
        "evidence_mode": "executed" if options.get("run_experiment") is True
        else options.get("non_experiment_evidence_mode", "design_only"),
    }
    payload = {
        "schema": 1, "run_id": run_id, "generated_at": time.time(),
        "profile": profile, "subnodes": entries,
        "plan_digest": hashlib.sha256(
            json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16],
    }
    service._atomic_write(path, payload)
    return payload
