"""One serialized, content-addressed scientific figure generation transaction."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional, Protocol

from .figure_architecture_request import prepare_method_architecture, reconcile_components
from .figure_models import FigureResult, FigureType
from .figure_routing import BACKEND_SKILLS


PUBLICATION_STYLE_PROFILE = "merak-publication-v1"


class FigureEnginePort(Protocol):
    async def _generate_matplotlib(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_figurespec(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_rich_svg(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_mermaid(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_tikz(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_gpt_image(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_nano_banana(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_drawio(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    async def _generate_excalidraw(self, *args: Any, **kwargs: Any) -> FigureResult: ...
    def _finalize_result(self, result: FigureResult, description: str, output_dir: str, metadata: dict) -> FigureResult: ...


def prepare_metadata(
    figure_type: FigureType, metadata: Optional[dict], output_dir: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = dict(metadata or {})
    value.setdefault("recommended_backend", figure_type.value)
    value.setdefault("recommended_skill", BACKEND_SKILLS.get(figure_type.value, "paper-figure"))
    value.setdefault("generator_skill", "")
    value.setdefault("skill", value.get("generator_skill") or "")
    value.setdefault("skill_invocation_verified", False)
    roles = {
        FigureType.MATPLOTLIB: "result", FigureType.FIGURESPEC: "method",
        FigureType.RICH_SVG: "method", FigureType.MERMAID: "protocol",
        FigureType.TIKZ: "method", FigureType.GPT_IMAGE: "qualitative",
        FigureType.NANO_BANANA: "qualitative", FigureType.DRAWIO: "method",
        FigureType.EXCALIDRAW: "method",
    }
    value.setdefault("scientific_role", roles.get(figure_type, "analysis"))
    value.setdefault("style_profile", PUBLICATION_STYLE_PROFILE)
    value.setdefault("claim_ids", [])
    value.setdefault("source_data", [])
    return value, reconcile_components(value, output_dir)


def _is_method_architecture(
    figure_type: FigureType, artifact_name: str, metadata: dict[str, Any],
    components: list[dict[str, Any]],
) -> bool:
    identity = str(
        artifact_name or metadata.get("semantic_key") or metadata.get("id") or ""
    ).strip()
    return (
        figure_type == FigureType.FIGURESPEC and identity == "method_architecture"
        and bool(components)
        and metadata.get("production_strategy") != "deterministic_architecture"
    )


def _source_bindings(
    metadata: dict[str, Any], project_root: Path, sha256_path: Any,
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for raw in metadata.get("source_data") or []:
        value = str(raw or "").strip()
        if not value:
            continue
        candidate = Path(value).expanduser()
        candidate = candidate if candidate.is_absolute() else project_root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(project_root)
        except (OSError, ValueError):
            bindings.append({"path": value, "status": "outside-project"})
            continue
        if not candidate.is_file():
            bindings.append({"path": value, "status": "missing"})
            continue
        try:
            bindings.append({
                "path": candidate.relative_to(project_root).as_posix(),
                "sha256": sha256_path(candidate),
            })
        except OSError:
            bindings.append({"path": value, "status": "unreadable"})
    return bindings


def bind_content_identity(
    description: str, code: str, figure_type: FigureType,
    metadata: dict[str, Any], project_root: Path, sha256_path: Any,
) -> None:
    if code and not metadata["source_data"]:
        metadata["source_data"] = sorted(set(re.findall(
            r"[A-Za-z0-9_./\\:-]+\.(?:csv|json|jsonl|parquet|npy|npz|tsv|xlsx)",
            code, re.IGNORECASE,
        )))[:12]
    bindings = _source_bindings(metadata, project_root, sha256_path)
    identity = {
        "content": code.strip() or description.strip(), "backend": figure_type.value,
        "style_profile": str(metadata.get("style_profile") or ""),
        "source_bindings": bindings,
    }
    metadata["content_sha256"] = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8", errors="replace")).hexdigest()
    metadata["source_bindings"] = bindings


def _resolve_reused_path(root: Path, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = Path(value)
    return str((candidate if candidate.is_absolute() else root / candidate).resolve())


def reusable_result(
    registry: Any, output_dir: str, semantic_key: str,
    figure_type: FigureType, description: str, metadata: dict[str, Any],
) -> FigureResult | None:
    existing = registry.find_reusable(
        output_dir, semantic_key, metadata["content_sha256"],
        require_output=registry._is_manuscript_asset(metadata),
    )
    if not existing:
        return None
    root = registry.project_root(output_dir)
    output_path = _resolve_reused_path(root, existing.get("output_path"))
    source_path = _resolve_reused_path(root, existing.get("source_path"))
    reused_metadata = {**dict(existing.get("metadata") or {}), **metadata, "reused": True}
    if figure_type == FigureType.RICH_SVG:
        from .rich_svg_visual_review import local_review_issues, native_review_issues

        png = dict(reused_metadata.get("rendered_variants") or {}).get("png")
        preview = Path(_resolve_reused_path(root, png)) if png else None
        if reused_metadata.get("production_strategy") == "deterministic_template":
            review_issues = local_review_issues(
                reused_metadata, Path(source_path) if source_path else root / "missing.svg",
                Path(output_path) if output_path else None, preview,
            )
        else:
            review_issues = (
                native_review_issues(reused_metadata, root, Path(source_path), preview)
                if source_path else ["editable SVG is missing"]
            )
        if review_issues:
            return None
    manifest_path, _entry = registry.record(
        output_dir=output_dir, figure_type=str(existing.get("type") or figure_type.value),
        description=description, output_path=output_path, source_path=source_path,
        metadata=reused_metadata,
    )
    return FigureResult(
        True, figure_type, output_path=output_path, source_path=source_path,
        manifest_path=str(manifest_path), metadata=reused_metadata,
    )


async def dispatch_backend(
    engine: FigureEnginePort, figure_type: FigureType, description: str,
    output_dir: str, style: str, code: str, image_size: str,
    image_quality: str, semantic_key: str, metadata: dict[str, Any],
) -> FigureResult:
    if figure_type == FigureType.MATPLOTLIB:
        return await engine._generate_matplotlib(
            description, output_dir, style, code=code, artifact_stem=semantic_key,
        )
    if figure_type == FigureType.FIGURESPEC:
        return await engine._generate_figurespec(
            code, output_dir, artifact_stem=semantic_key, metadata=metadata,
        )
    if figure_type == FigureType.RICH_SVG:
        return await engine._generate_rich_svg(
            code, output_dir, artifact_stem=semantic_key, metadata=metadata,
        )
    if figure_type == FigureType.MERMAID:
        return await engine._generate_mermaid(code or description, output_dir, artifact_stem=semantic_key)
    if figure_type == FigureType.TIKZ:
        return await engine._generate_tikz(code or description, output_dir, artifact_stem=semantic_key)
    if figure_type == FigureType.GPT_IMAGE:
        return await engine._generate_gpt_image(
            description, output_dir, size=image_size, quality=image_quality,
            artifact_stem=semantic_key,
        )
    if figure_type == FigureType.NANO_BANANA:
        return await engine._generate_nano_banana(
            description, output_dir, artifact_stem=semantic_key, metadata=metadata,
        )
    if figure_type == FigureType.DRAWIO:
        return await engine._generate_drawio(code or description, output_dir, artifact_stem=semantic_key)
    if figure_type == FigureType.EXCALIDRAW:
        return await engine._generate_excalidraw(
            code, output_dir, artifact_stem=semantic_key, metadata=metadata,
        )
    return FigureResult(False, figure_type, error="Unknown figure type")


def _merge_runtime_provenance(
    result: FigureResult, metadata: dict[str, Any],
) -> dict[str, Any]:
    backend = dict(result.metadata or {})
    runtime = {
        key: metadata[key] for key in (
            "generator_skill", "skill", "skill_invocation_verified",
            "skill_invocation_verified_by", "skill_session_id", "skill_context_key",
        ) if key in metadata
    }
    return {**metadata, **backend, **runtime}


def _commit_rich_svg_review(
    root: Path, semantic_key: str, finalized: FigureResult,
) -> None:
    """Commit only producer-specific evidence for the exact rendered variants."""
    from .rich_svg_visual_review import (
        commit_best_candidate, local_review_issues, native_review_issues,
    )

    metadata = dict(finalized.metadata or {})
    png = dict(metadata.get("rendered_variants") or {}).get("png")
    preview = Path(_resolve_reused_path(root, png)) if png else None
    source = Path(finalized.source_path) if finalized.source_path else root / "missing.svg"
    deterministic = metadata.get("production_strategy") == "deterministic_template"
    issues = (
        local_review_issues(
            metadata, source,
            Path(finalized.output_path) if finalized.output_path else None,
            preview,
        ) if deterministic else native_review_issues(metadata, root, source, preview)
    )
    if issues:
        raise ValueError("; ".join(issues))
    if not deterministic:
        commit_best_candidate(
            root, semantic_key,
            dict(metadata.get("independent_visual_review") or {}),
        )


async def generate_serialized(
    engine: FigureEnginePort, description: str, figure_type: FigureType,
    output_dir: str, style: str, code: str, image_size: str,
    image_quality: str, metadata: Optional[dict], artifact_name: str,
    *, semantic_stem: Any, sha256_path: Any,
) -> FigureResult:
    figure_metadata, components = prepare_metadata(figure_type, metadata, output_dir)
    if _is_method_architecture(figure_type, artifact_name, figure_metadata, components):
        code, failure = prepare_method_architecture(code, figure_metadata, components)
        if failure:
            return failure
    semantic_key = semantic_stem(description, figure_type, artifact_name, figure_metadata)
    figure_metadata["semantic_key"] = semantic_key
    figure_metadata.setdefault("managed_by", "merak")
    from .figure_artifacts import figure_artifact_registry

    root = figure_artifact_registry.project_root(output_dir)
    bind_content_identity(
        description, code, figure_type, figure_metadata, root, sha256_path,
    )
    reused = reusable_result(
        figure_artifact_registry, output_dir, semantic_key,
        figure_type, description, figure_metadata,
    )
    if reused:
        return reused
    from .figure_file_transaction import FigureFileTransaction

    transaction = FigureFileTransaction(root, Path(output_dir), semantic_key)
    try:
        result = await dispatch_backend(
            engine, figure_type, description, output_dir, style, code,
            image_size, image_quality, semantic_key, figure_metadata,
        )
    except BaseException:
        transaction.rollback()
        raise
    result.metadata = _merge_runtime_provenance(result, figure_metadata)
    if result.success and result.source_path:
        from .figure_result_finalizer import bind_rendered_variants
        from .figure_scientific_alignment import candidate_scientific_alignment_issues

        bind_rendered_variants(result.metadata, output_dir, figure_artifact_registry, sha256_path)
        issues = candidate_scientific_alignment_issues(
            figure_artifact_registry, root, result.metadata, result.source_path,
        )
        if issues:
            transaction.rollback()
            result.success = False
            result.error = "Candidate scientific alignment failed: " + "; ".join(issues)
            return result
    finalized = engine._finalize_result(result, description, output_dir, result.metadata)
    if not finalized.success:
        transaction.rollback()
    else:
        if figure_type == FigureType.RICH_SVG:
            try:
                _commit_rich_svg_review(root, semantic_key, finalized)
            except (OSError, ValueError, KeyError) as error:
                transaction.rollback()
                finalized.success = False
                finalized.error = f"Could not commit accepted figure candidate: {error}"
                return finalized
        transaction.close()
    return finalized
