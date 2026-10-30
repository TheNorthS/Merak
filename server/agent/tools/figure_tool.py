"""Project-grounded scientific figure generation tool."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_STAGED_RICH_SVG_SKILLS = {"rich-svg-figure", "model-svg-figure"}


@dataclass
class FigureRequest:
    description: str
    artifact_name: str = ""
    figure_type: str = ""
    output_dir: str = "./figures"
    code: str = ""
    source_path: str = ""
    image_size: str = "1024x1024"
    image_quality: str = "high"
    scientific_role: str = ""
    claim_ids: list[str] | None = None
    source_data: list[str] | None = None
    caption: str = ""
    scientific_question: str = ""
    intended_comparison: str = ""
    visual_encoding: str = ""
    uncertainty_encoding: str = ""
    evidence_status: str = ""
    manuscript_section: str = ""
    label: str = ""
    data_path: str = ""
    code_symbols: list[str] | None = None
    source_artifacts: list[str] | None = None
    element_mappings: list[dict] | None = None
    visual_blueprint: dict[str, Any] | None = None
    recommended_backend: str = ""
    recommended_skill: str = ""
    figure_budget: int = 6
    generator_skill: str = ""
    planned_spec: dict[str, Any] = field(default_factory=dict)


def _load_plan(figures_root: Path, artifact_name: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    path = figures_root / "FIGURE_SPECS.json"
    if not path.is_file():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"FIGURE_SPECS.json is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("FIGURE_SPECS.json must contain an object")
    specs = {
        str(item.get("id") or "").strip(): dict(item)
        for item in payload.get("figures") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    planned = specs.get(artifact_name.strip(), {})
    if artifact_name.strip() and not planned:
        raise ValueError(f"artifact_name {artifact_name!r} is not declared in FIGURE_SPECS.json")
    return planned, specs


def _current_file(project_root: Path, value: Any, expected_hash: Any = "") -> Path | None:
    if not str(value or "").strip():
        return None
    candidate = Path(str(value)).expanduser()
    candidate = (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        return None
    if str(expected_hash or "").strip():
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != str(expected_hash):
            return None
    return candidate


def _reuse_figure(registry: Any, figures_root: Path, artifact_name: str, backend: str) -> str:
    project_root = registry.project_root(figures_root)
    entry = next((
        item for item in reversed(registry.load(figures_root).get("figures", []))
        if isinstance(item, dict)
        and str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or "").strip() == artifact_name.strip()
        and _current_file(project_root, item.get("output_path"), item.get("output_sha256"))
        and _current_file(project_root, item.get("source_path"), item.get("source_sha256"))
    ), None)
    if entry:
        return (
            f"Figure reused ({entry.get('type') or backend}); canonical paper-ready file: "
            f"{entry.get('output_path')}; editable source: {entry.get('source_path')}. "
            "No new artifact was generated."
        )
    raise ValueError(
        f"artifact {artifact_name!r} is canonical and generation_policy=reuse, "
        "but its hash-current output/source pair is missing from FIGURE_MANIFEST.json; "
        "repair the owning upstream artifact instead of generating a duplicate"
    )


def _apply_plan(request: FigureRequest, registry: Any, figures_root: Path) -> str:
    from server.services.figure_routing import BACKEND_SKILLS

    planned = request.planned_spec
    if not planned:
        return ""
    policy = str(planned.get("generation_policy") or "generate").casefold()
    if policy == "skip":
        raise ValueError(f"artifact {request.artifact_name!r} is disabled by FIGURE_SPECS.json")
    if planned.get('producer_kind') == 'deterministic' and policy != 'reuse':
        raise ValueError(
            f"artifact {request.artifact_name!r} is runtime-owned; "
            'the model cannot replace its deterministic source through generate_figure'
        )
    backend = str(planned.get("recommended_backend") or "").strip().casefold()
    skill = str(planned.get("recommended_skill") or "").strip().lstrip("/")
    expected_skill = (
        "model-svg-figure"
        if planned.get("production_strategy") == "model_composed_full_svg"
        else BACKEND_SKILLS.get(backend, "")
    )
    if backend not in BACKEND_SKILLS or skill != expected_skill:
        raise ValueError(
            f"unsupported current figure route for {request.artifact_name}: "
            f"backend={backend or '<missing>'}, skill={skill or '<missing>'}"
        )
    if request.artifact_name.strip() == "method_architecture" and backend == "figurespec":
        backend, skill = "rich_svg", "rich-svg-figure"
    supplied_backend = str(request.recommended_backend or request.figure_type or "").strip().casefold()
    supplied_skill = str(request.recommended_skill or "").strip().lstrip("/")
    if backend and supplied_backend and supplied_backend != backend:
        raise ValueError(
            f"figure backend conflicts with FIGURE_SPECS.json for {request.artifact_name}: "
            f"expected {backend}, got {supplied_backend}"
        )
    if skill and supplied_skill and supplied_skill != skill:
        raise ValueError(
            f"figure skill conflicts with FIGURE_SPECS.json for {request.artifact_name}: "
            f"expected /{skill}, got /{supplied_skill}"
        )
    request.figure_type = backend or request.figure_type
    request.recommended_backend = backend or request.recommended_backend
    request.recommended_skill = skill or request.recommended_skill
    return _reuse_figure(registry, figures_root, request.artifact_name, backend) if policy == "reuse" else ""


def _metadata(request: FigureRequest) -> dict[str, Any]:
    from .figure_draft_tools import _probe_configuration_brief

    planned = request.planned_spec

    def choose_list(supplied: Any, key: str) -> list[Any]:
        return supplied if supplied is not None else list(planned.get(key) or [])

    return {
        **planned,
        "scientific_role": request.scientific_role or planned.get("scientific_role") or "",
        "claim_ids": choose_list(request.claim_ids, "claim_ids"),
        "source_data": choose_list(request.source_data, "source_data"),
        "caption": request.caption or planned.get("caption") or request.description,
        "scientific_question": request.scientific_question or planned.get("scientific_question") or "",
        "intended_comparison": request.intended_comparison or planned.get("intended_comparison") or "",
        "visual_encoding": request.visual_encoding or planned.get("visual_encoding") or "",
        "uncertainty_encoding": request.uncertainty_encoding or planned.get("uncertainty_encoding") or "",
        "evidence_status": request.evidence_status or planned.get("evidence_status") or "artifact",
        "manuscript_section": request.manuscript_section or planned.get("manuscript_section") or "",
        "label": request.label or planned.get("label") or "",
        "data_path": request.data_path or planned.get("data_path") or "",
        "semantic_key": request.artifact_name, "managed_by": "merak",
        "code_symbols": choose_list(request.code_symbols, "code_symbols"),
        "source_artifacts": choose_list(request.source_artifacts, "source_artifacts"),
        "element_mappings": choose_list(request.element_mappings, "element_mappings"),
        "probe_configuration": _probe_configuration_brief(planned),
        "visual_blueprint": (
            dict(request.visual_blueprint)
            if isinstance(request.visual_blueprint, dict) else {}
        ),
        "recommended_backend": request.recommended_backend or request.figure_type,
        "recommended_skill": request.recommended_skill,
        "generator_skill": request.generator_skill, "skill": request.generator_skill,
        "skill_invocation_verified": bool(request.generator_skill),
        "skill_invocation_verified_by": "agent-runtime" if request.generator_skill else "",
    }


def _figure_code(
    request: FigureRequest, registry: Any, figures_root: Path,
    metadata: dict[str, Any] | None = None,
) -> str:
    if request.figure_type != "rich_svg":
        return request.code
    if request.generator_skill in _STAGED_RICH_SVG_SKILLS and not request.source_path.strip():
        raise ValueError(
            "rich-svg-figure must finalize a staged SVG and pass source_path; "
            "single-call inline SVG authoring is unsupported"
        )
    if request.code.strip() and request.source_path.strip():
        raise ValueError("rich_svg accepts either code or source_path, not both")
    if request.source_path.strip():
        root = registry.project_root(figures_root)
        source = (root / request.source_path).resolve()
        try:
            source.relative_to(root)
        except ValueError as error:
            raise ValueError("rich_svg source_path escapes the project") from error
        if source.suffix.casefold() != ".svg" or not source.is_file():
            raise ValueError("rich_svg source_path must identify a current project SVG")
        if source.stat().st_size > 2_000_000:
            raise ValueError("rich_svg source_path exceeds the 2 MB authoring limit")
        request.code = source.read_text(encoding="utf-8-sig")
        if request.generator_skill in _STAGED_RICH_SVG_SKILLS:
            from .figure_draft_tools import require_current_composition_review

            require_current_composition_review(
                root, request.artifact_name, source,
                dict(request.visual_blueprint or {}),
            )
            manifest_path = (
                root / ".merak" / "figure-drafts" / request.artifact_name / "manifest.json"
            )
            try:
                staged = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                staged = {}
            if staged.get("production_strategy") == "model_composed_full_svg":
                review = staged.get("composition_review")
                review = review if isinstance(review, dict) else {}
                if metadata is not None:
                    metadata.update({
                        "production_strategy": "model_composed_full_svg",
                        "composition_owner": "model",
                        "source_bindings": list(staged.get("source_bindings") or []),
                        "source_bundle_sha256": staged.get("source_bundle_sha256"),
                        "figure_spec_sha256": staged.get("figure_spec_sha256"),
                        "element_mappings": [
                            dict(item) for item in staged.get("element_mappings") or []
                            if isinstance(item, dict)
                        ],
                        "element_mappings_sha256": staged.get(
                            "element_mappings_sha256"
                        ),
                        "independent_visual_review": dict(
                            review.get("independent_visual_review") or {}
                        ),
                    })
    if not request.code.strip().startswith("<svg"):
        raise ValueError("rich_svg requires complete model-authored SVG code or source_path")
    return request.code


def _budget_message(
    request: FigureRequest, registry: Any, figures_root: Path,
    specs: dict[str, dict[str, Any]], metadata: dict[str, Any],
) -> str:
    entries = [item for item in registry.load(figures_root).get("figures", []) if isinstance(item, dict)]
    semantic_key = registry.semantic_key(request.description, metadata)
    existing = {
        registry.semantic_key(
            str(item.get("description") or ""), item.get("metadata") or {},
        )
        for item in entries
    }
    counted: set[str] = set()
    for item in entries:
        item_metadata = item.get("metadata") or {}
        item_id = str(item_metadata.get("semantic_key") or item.get("id") or "").strip()
        policy = str(specs.get(item_id, {}).get("generation_policy") or item_metadata.get("generation_policy") or "generate").casefold()
        if policy != "reuse":
            counted.add(registry.semantic_key(
                str(item.get("description") or ""), item_metadata,
            ))
    budget = max(2, min(12, int(request.figure_budget)))
    if semantic_key not in existing and semantic_key not in counted and len(counted) >= budget:
        return (
            f"Figure budget reached ({budget}); no duplicate was generated. "
            "Repair or reuse an existing planned semantic figure."
        )
    return ""


def _result_message(result: Any, expected_backend: str) -> str:
    if not result.success:
        detail = result.error or result.install_hint or (
            f"{expected_backend or result.figure_type} produced neither a valid output nor editable source"
        )
        raise RuntimeError(f"Figure generation failed: {detail}")
    lines = [f"Figure generated ({result.figure_type.value})"]
    if result.output_path:
        lines.append(f"Canonical paper-ready file: {result.output_path}")
    metadata = result.metadata or {}
    variants = metadata.get("_rendered_variant_paths") or metadata.get("variant_paths") or {}
    if variants:
        lines.append("Rendered variants: " + ", ".join(
            f"{name}={path}" for name, path in variants.items()
        ))
    if result.source_path:
        lines.append(f"Editable source: {result.source_path}")
    if result.install_hint:
        lines.append(f"Dependency note: {result.install_hint}")
    if result.manifest_path:
        lines.append(f"Manifest: {result.manifest_path}")
    if result.svg_content:
        lines.append("SVG is available for inline preview")
    return "\n".join(lines)


async def generate_figure(
    description: str, artifact_name: str = "", figure_type: str = "",
    output_dir: str = "./figures", code: str = "", source_path: str = "",
    image_size: str = "1024x1024",
    image_quality: str = "high", scientific_role: str = "",
    claim_ids: list[str] | None = None, source_data: list[str] | None = None,
    caption: str = "", scientific_question: str = "", intended_comparison: str = "",
    visual_encoding: str = "", uncertainty_encoding: str = "", evidence_status: str = "",
    manuscript_section: str = "", label: str = "", data_path: str = "",
    code_symbols: list[str] | None = None, source_artifacts: list[str] | None = None,
    element_mappings: list[dict] | None = None, recommended_backend: str = "",
    visual_blueprint: dict[str, Any] | None = None,
    recommended_skill: str = "", figure_budget: int = 6, generator_skill: str = "",
    project_path: str = "",
) -> str:
    from server.services.figure_artifacts import figure_artifact_registry as registry
    from server.services.figure_engine import FigureType, figure_engine

    request = FigureRequest(
        description=description, artifact_name=artifact_name,
        figure_type=figure_type, output_dir=output_dir, code=code,
        source_path=source_path,
        image_size=image_size, image_quality=image_quality,
        scientific_role=scientific_role, claim_ids=claim_ids,
        source_data=source_data, caption=caption,
        scientific_question=scientific_question,
        intended_comparison=intended_comparison,
        visual_encoding=visual_encoding,
        uncertainty_encoding=uncertainty_encoding,
        evidence_status=evidence_status,
        manuscript_section=manuscript_section, label=label,
        data_path=data_path, code_symbols=code_symbols,
        source_artifacts=source_artifacts, element_mappings=element_mappings,
        visual_blueprint=visual_blueprint,
        recommended_backend=recommended_backend,
        recommended_skill=recommended_skill, figure_budget=figure_budget,
        generator_skill=generator_skill,
    )
    figures_root = registry.figures_root(output_dir)
    request.planned_spec, specs = _load_plan(figures_root, artifact_name)
    reuse = _apply_plan(request, registry, figures_root)
    if reuse:
        return reuse
    metadata = _metadata(request)
    budget = _budget_message(request, registry, figures_root, specs, metadata)
    if budget:
        return budget
    try:
        resolved_type = FigureType(request.figure_type) if request.figure_type else None
    except ValueError:
        resolved_type = None
    code_value = _figure_code(request, registry, figures_root, metadata)
    result = await figure_engine.generate(
        request.description, resolved_type, request.output_dir, code=code_value,
        image_size=request.image_size, image_quality=request.image_quality,
        artifact_name=request.artifact_name, metadata=metadata,
    )
    return _result_message(result, request.recommended_backend)
