"""Read-only, asset-scoped execution attestation for current figure producers.

Producer declarations select obligations; completed traces and hash-current,
accepted artifacts discharge them. Neither a selected skill nor runtime work
may manufacture evidence that a model-owned asset was authored by a model.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .figure_execution_policy import FIGURE_RUNTIME_SERVICE, resolve_figure_execution_policy


def _entry_paths(root: Path, identity: str, entry: dict[str, Any]) -> list[str]:
    metadata = entry.get("metadata") or {}
    variants = dict(metadata.get("rendered_variants") or {})
    hashes = dict(metadata.get("rendered_variant_sha256") or {})
    paths = [(key, entry.get(key), entry.get(digest)) for key, digest in (
        ("source_path", "source_sha256"), ("output_path", "output_sha256"),
    )]
    paths.extend((f"variant {key}", value, hashes.get(key)) for key, value in variants.items())
    issues = []
    for label, value, expected in paths:
        candidate = (root / str(value or "")).resolve()
        if not value or not expected or not candidate.is_relative_to(root) or not candidate.is_file():
            issues.append(f"{identity}: current figure execution lacks bound {label}")
        elif hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
            issues.append(f"{identity}: current figure execution has stale {label} hash")
    if not variants or set(variants) != set(hashes):
        issues.append(f"{identity}: current figure execution lacks complete variant hashes")
    return issues


def _model_asset_issues(
    identity: str, asset: dict[str, Any], metadata: dict[str, Any],
    invocations: list[dict[str, Any]],
) -> list[str]:
    from .skill_execution_trace import verified_model_invocation

    skill = str(asset.get("recommended_skill") or "").lstrip("/")
    session = str(metadata.get("skill_session_id") or "")
    matching = [item for item in invocations if item.get("role") in {"primary", "delegate"}
               and str(item.get("skill") or "").lstrip("/") == skill
               and str(item.get("session_id") or "") == session]
    if not (session and metadata.get("model_authored") is True
            and metadata.get("skill_invocation_verified") is True
            and str(metadata.get("generator_skill") or metadata.get("skill") or "").lstrip("/") == skill
            and matching and verified_model_invocation(matching[-1])):
        return [f"{identity}: missing verified current-run model execution for /{skill} and its accepted asset session"]
    return []


def figure_stage_execution_issues(
    project_path: str, stage: dict[str, Any], invocations: list[dict[str, Any]],
) -> tuple[list[str], bool]:
    """Check the recorded contract against current canonical assets, never mutate it."""
    root = Path(project_path).expanduser().resolve()
    policy = resolve_figure_execution_policy(root)
    issues = list(policy.issues)
    expected = {"execution_kind": policy.kind, "policy_required": policy.policy_required,
                "model_execution_mode": policy.model_execution_mode, "runtime_service": FIGURE_RUNTIME_SERVICE}
    if any(stage.get(key) != value for key, value in expected.items()):
        issues.append("figure execution trace contract differs from current canonical producer ownership; record the current plan before execution")
    if issues:
        return issues, False
    from .figure_artifacts import figure_artifact_registry

    manifest = figure_artifact_registry.load(root / "figures", strict=True)
    entries = {str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or ""): item
               for item in manifest.get("figures") or [] if isinstance(item, dict)}
    model_issues = []
    for asset in policy.assets:
        identity = str(asset["id"])
        entry = entries.get(identity) or {}
        metadata = entry.get("metadata") or {}
        if (asset.get("required") is False and asset.get("producer_kind") == "deterministic"
                and asset.get("production_strategy") == "deterministic_plot"
                and (not entry or (isinstance(metadata, dict) and metadata.get("paper_selected") is False
                                   and entry.get("paper_ready") is not True))):
            continue
        if not isinstance(metadata, dict):
            issues.append(f"{identity}: current figure producer metadata is invalid")
            continue
        if entry.get("paper_ready") is not True or metadata.get("paper_selected") is False:
            issues.append(f"{identity}: current figure execution has no accepted paper-ready asset")
            if asset.get("producer_kind") == "model":
                model_issues.append(f"{identity}: missing accepted asset provenance for its current-run model execution")
            continue
        if any(metadata.get(key) != asset.get(key) for key in ("producer_kind", "production_strategy")):
            issues.append(f"{identity}: accepted figure producer differs from its current canonical declaration")
        issues.extend(_entry_paths(root, identity, entry))
        if asset.get("producer_kind") == "model":
            model_issues.extend(_model_asset_issues(identity, asset, metadata, invocations))
    issues.extend(model_issues)
    if not issues:
        issues.extend(figure_artifact_registry.scientific_quality_issues(root / "figures"))
        issues.extend(figure_artifact_registry.scientific_alignment_issues(root / "figures"))
    return list(dict.fromkeys(issues)), not model_issues
