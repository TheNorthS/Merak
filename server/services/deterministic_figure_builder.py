"""Build current deterministic figures only when typed producer inputs change."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .figure_producer_errors import (
    DeterministicFigureProducerError, UnchangedDeterministicFigureDefect,
    aggregate_producer_failures,
)


_TEMPLATE_VERSION = "mechanism-discrimination-evaluation-v2"
_ARCHITECTURE_VERSION = "source-scene-figurespec-v1"
_ARCHITECTURE_CODE_MODULES = (
    "scientific_scene_figure", "scientific_scene_topology_layout", "scientific_scene_geometry", "scientific_scene_placement", "scientific_scene_labels",
    "scientific_scene_partitions", "scientific_scene_panel_figure",
    "figurespec_backend", "figurespec_layout_policy", "figure_engine",
    "deterministic_figure_builder", "figure_producer_fingerprint",
    "figure_semantic_projection", "scientific_scene", "figure_generation_transaction", "figure_result_finalizer", "figure_diagram_text",
    "svg_variant_conversion", "svg_marker_fallback", "figure_svg_sources",
    "figure_raster_quality", "figure_scientific_alignment",
    "scientific_plotting", "scientific_plot_template",
)
_TEMPLATE_CODE_MODULES = (
    "evaluation_design_svg", "rich_svg_backend", "figure_print_policy",
    "figure_raster_quality", "svg_variant_conversion", "svg_marker_fallback",
    "figure_svg_sources", "figure_engine", "figure_generation_transaction", "figure_result_finalizer", "figure_diagram_text",
    "publication_figure_labels", "rich_svg_visual_review",
    "api_visual_review_schemas", "api_visual_review_invocation",
    "api_visual_reviewer", "figure_review_findings",
    "figure_scientific_alignment", "deterministic_native_review_cache",
    "evaluation_protocol_projection", "evaluation_plan_projection", "evaluation_conditions_projection",
    "evaluation_design_content",
    "scientific_plotting", "scientific_plot_template",
    "evaluation_design_contract", "scientific_asset_builders", "scientific_asset_contract",
    "deterministic_figure_builder", "figure_producer_fingerprint",
)
_CACHEABLE_TEMPLATE_ERRORS = (
    "Rich SVG source review failed;",
    "Rich SVG render review failed;",
    "Rich SVG local-pixel review failed:",
)


def _module_code_digest(name: str) -> bytes:
    """Fingerprint executing bytecode, not files edited after this process loaded."""
    from .figure_producer_fingerprint import loaded_module_digest

    return loaded_module_digest(name, __package__)


def _architecture_code_sha256(renderer: Any) -> str:
    """Bind executing placement, semantic rendering, conversion and validation."""
    from .figure_producer_fingerprint import loaded_module_digest, module_digest

    return hashlib.sha256(b"".join([
        *(loaded_module_digest(name, __package__) for name in _ARCHITECTURE_CODE_MODULES),
        module_digest(renderer), module_digest(renderer._SEMANTIC_RENDERER),
    ])).hexdigest()


def _template_code_sha256() -> str:
    digest = hashlib.sha256()
    from .figure_producer_fingerprint import module_digest
    from ..contracts import evaluation
    digest.update(module_digest(evaluation))
    digest.update(json.dumps(evaluation.EvaluationDeclaration.model_json_schema(), sort_keys=True).encode())
    for name in _TEMPLATE_CODE_MODULES:
        digest.update(name.encode("utf-8"))
        digest.update(_module_code_digest(name))
    return digest.hexdigest()


def _template_input_sha256(spec: dict[str, Any], style: str, code_sha256: str) -> str:
    payload = {
        "template_version": _TEMPLATE_VERSION,
        "template_code_sha256": code_sha256,
        "spec": spec,
        "style_profile": style,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def architecture_input_sha256(spec: dict[str, Any], style: str,
                               compiled: dict[str, Any], code_sha256: str) -> str:
    """Share the exact producer-input identity with read-only acceptance revalidation."""
    return hashlib.sha256(json.dumps({
        "version": _ARCHITECTURE_VERSION, "spec": spec, "compiled": compiled,
        "style": style, "code_hash": code_sha256,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _failure_path(figures_root: Path, asset_id: str) -> Path:
    asset_key = hashlib.sha256(asset_id.encode("utf-8")).hexdigest()
    return figures_root.parent / ".merak" / "figure-producer-failures" / f"{asset_key}.json"


def _error_signature(error: str) -> str:
    return hashlib.sha256(error.encode("utf-8")).hexdigest()


def _review_record(figures_root: Path, asset_id: str) -> dict[str, Any]:
    path = figures_root.parent / ".merak" / "figure-reviews" / f"{asset_id}.json"
    try:
        rounds = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(rounds[-1]) if isinstance(rounds, list) and rounds and isinstance(rounds[-1], dict) else {}


def _cacheable_review(result: Any, error: str) -> dict[str, Any]:
    if not error.startswith(_CACHEABLE_TEMPLATE_ERRORS):
        return {}
    rounds = dict(result.metadata or {}).get("visual_review_rounds") or []
    review = dict(rounds[-1]) if isinstance(rounds, list) and rounds and isinstance(rounds[-1], dict) else {}
    issues = [str(value) for value in review.get("issues") or [] if str(value)]
    if review.get("status") != "failed" or not issues or not all(issue in error for issue in issues):
        return {}
    if not str(review.get("content_sha256") or ""):
        return {}
    if error.startswith((
        "Rich SVG render review failed;", "Rich SVG local-pixel review failed:",
    )) and not review.get("render_sha256"):
        return {}
    return review


def _cached_failure(
    path: Path, figures_root: Path, asset_id: str, input_hash: str,
    svg_hash: str,
) -> str:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if not isinstance(record, dict):
        return ""
    if record.get("schema") == 2:
        from .deterministic_native_review_cache import cached_failure

        return cached_failure(
            record, figures_root=figures_root, asset_id=asset_id,
            input_hash=input_hash, svg_hash=svg_hash,
            persisted_round=_review_record(figures_root, asset_id),
        )
    error = str(record.get("error") or "")
    expected = {
        "schema": 1, "asset_id": asset_id,
        "project_root": str(figures_root.parent.resolve()),
        "producer_input_sha256": input_hash, "candidate_svg_sha256": svg_hash,
        "error_signature": _error_signature(error),
    }
    review = _review_record(figures_root, asset_id)
    expected_review = record.get("review")
    if error.startswith(_CACHEABLE_TEMPLATE_ERRORS) and all(
        record.get(key) == value for key, value in expected.items()
    ) and isinstance(expected_review, dict) and all(
        review.get(key) == expected_review.get(key)
        for key in ("status", "content_sha256", "render_sha256", "issues")
    ) and review.get("status") == "failed":
        return error
    return ""


def _record_failure(
    path: Path, figures_root: Path, asset_id: str, input_hash: str, svg_hash: str,
    error: str, review: dict[str, Any],
) -> None:
    atomic_write_json(path, {
        "schema": 1, "asset_id": asset_id,
        "project_root": str(figures_root.parent.resolve()),
        "producer_input_sha256": input_hash, "candidate_svg_sha256": svg_hash,
        "error_signature": _error_signature(error), "error": error,
        "review": {
            key: review.get(key)
            for key in ("status", "content_sha256", "render_sha256", "issues")
        },
    })


def _entries(registry: Any, figures_root: Path) -> dict[str, dict[str, Any]]:
    return {
        str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or ""): item
        for item in registry.load(figures_root).get("figures", [])
        if isinstance(item, dict)
    }


def _current_entry_reusable(
    entry: dict[str, Any], root: Path, input_hash: str,
) -> bool:
    metadata = dict(entry.get("metadata") or {})
    if (
        metadata.get("producer_input_sha256") != input_hash
        or metadata.get("producer_kind") != "deterministic"
    ):
        return False
    if metadata.get("source_data"):
        from .figure_generation_transaction import _source_bindings

        current_bindings = _source_bindings(
            metadata, root.resolve(), lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        if (any(not item.get("sha256") for item in current_bindings)
                or current_bindings != metadata.get("source_bindings")):
            return False
    for key, digest_key in (
        ("source_path", "source_sha256"),
        ("output_path", "output_sha256"),
    ):
        value = str(entry.get(key) or "").strip()
        if not value or not str(entry.get(digest_key) or ""):
            return False
        path = Path(value)
        path = (path if path.is_absolute() else root / path).resolve()
        try:
            path.relative_to(root.resolve())
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry[digest_key]:
                return False
        except (OSError, ValueError):
            return False
    if metadata.get("production_strategy") in {
        "deterministic_architecture", "deterministic_template",
    }:
        required = (
            {"json", "svg", "pdf", "png"}
            if metadata["production_strategy"] == "deterministic_architecture"
            else {"svg", "pdf", "png"}
        )
        variants = dict(metadata.get("rendered_variants") or {})
        hashes = dict(metadata.get("rendered_variant_sha256") or {})
        if not required <= variants.keys() or not required <= hashes.keys():
            return False
        for key in required:
            path = Path(str(variants[key]))
            path = (path if path.is_absolute() else root / path).resolve()
            try:
                path.relative_to(root.resolve())
                if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
                    return False
            except (OSError, ValueError):
                return False
        rounds = metadata.get("visual_review_rounds") or []
        review = rounds[-1] if isinstance(rounds, list) and rounds else {}
        if not isinstance(review, dict) or (
            review.get("status") != "passed"
            or review.get("content_sha256") != entry.get("source_sha256")
            or review.get("render_sha256") != hashes["png"]
        ):
            return False
        if metadata["production_strategy"] == "deterministic_template":
            from .rich_svg_visual_review import local_review_issues

            source = root / str(entry["source_path"])
            if local_review_issues(
                metadata, source, root / str(entry["output_path"]),
                root / str(variants["png"]),
            ):
                return False
    return True


async def ensure_evaluation_design(
    host: Any, run: Any, figures_root: Path, planned_specs: list[dict[str, Any]],
    asset_plan: dict[str, Any], selected_ids: set[str], registry: Any,
) -> dict[str, dict[str, Any]]:
    """Generate every deterministic figure from hash-bound typed inputs."""
    entries = _entries(registry, figures_root)
    failures: list[DeterministicFigureProducerError] = []
    producers = {
        "deterministic_architecture": _ensure_deterministic_architectures,
        "deterministic_template": _ensure_deterministic_templates,
        "deterministic_plot": _ensure_deterministic_plots,
    }
    for spec in planned_specs:
        producer = producers.get(str(spec.get("production_strategy") or ""))
        if producer is None:
            continue
        try:
            entries = await producer(
                host, run, figures_root, [spec], asset_plan,
                selected_ids, registry, entries,
            )
        except DeterministicFigureProducerError as exc:
            failures.append(exc.with_asset(str(spec.get("id") or "unnamed"), str(spec.get("production_strategy") or "")))
        except (ValueError, OSError, RuntimeError) as exc:
            failures.append(DeterministicFigureProducerError(
                f"{spec.get('id') or 'unnamed'}: {producer.__name__} "
                f"failed: {type(exc).__name__}: {exc}"
            ).with_asset(str(spec.get("id") or "unnamed"), str(spec.get("production_strategy") or "")))
    if failures:
        raise aggregate_producer_failures(failures)
    return entries


async def _ensure_deterministic_architectures(
    host: Any, run: Any, figures_root: Path,
    planned_specs: list[dict[str, Any]], asset_plan: dict[str, Any],
    selected_ids: set[str], registry: Any,
    entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Compile source-bound method scenes; a rejected figure never becomes accepted."""
    from .figure_engine import (
        FigureType, _load_figurespec_renderer, figure_engine,
    )
    from .scientific_scene_figure import compile_scientific_scene_figure

    style = str(
        (asset_plan.get("publication_style") or {}).get("visual_standard")
        or "field-adaptive-accessible-vector-v3"
    )
    renderer = _load_figurespec_renderer()
    code_hash = _architecture_code_sha256(renderer)
    for spec in planned_specs:
        identity = str(spec.get("id") or "").strip()
        if not identity or (selected_ids and identity not in selected_ids) or (
            spec.get("producer_kind") != "deterministic"
            or spec.get("production_strategy") != "deterministic_architecture"
            or spec.get("recommended_backend") != "figurespec"
            or str(spec.get("generation_policy") or "generate") != "generate"
        ):
            continue
        try:
            compilation = compile_scientific_scene_figure(spec)
        except (ValueError, KeyError, TypeError) as exc:
            raise DeterministicFigureProducerError(
                f"{identity}: source-grounded architecture compilation failed: {exc}"
            ) from exc
        code = json.dumps(compilation.spec, ensure_ascii=False, sort_keys=True)
        input_hash = architecture_input_sha256(spec, style, compilation.spec, code_hash)
        current = entries.get(identity, {})
        if _current_entry_reusable(current, figures_root.parent, input_hash):
            continue
        skill = str(spec.get("recommended_skill") or "figure-spec")
        metadata = {
            **spec, "semantic_key": identity, "managed_by": "merak",
            "producer_kind": "deterministic", "producer_input_sha256": input_hash,
            "paper_selected": True, "manuscript_eligible": True,
            "generator_skill": skill, "skill": skill,
            "skill_invocation_verified": True,
            "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
            "element_mappings": compilation.element_mappings,
            "architecture_compiler": compilation.profile,
            "architecture_source": "deterministic-source-grounded-scene",
            "style_profile": style,
        }
        result = await figure_engine.generate(
            description=str(spec.get("caption") or spec.get("scientific_question") or identity),
            figure_type=FigureType.FIGURESPEC,
            output_dir=str(figures_root / "diagrams"),
            code=code, metadata=metadata, artifact_name=identity,
        )
        await _emit_result(host, run, identity, result, input_hash)
        if not result.success:
            raise DeterministicFigureProducerError(
                f"{identity}: deterministic architecture producer failed: "
                f"{result.error or 'unknown failure'}"
            )
        entries = _entries(registry, figures_root)
    return entries


async def _ensure_deterministic_templates(
    host: Any, run: Any, figures_root: Path,
    planned_specs: list[dict[str, Any]], asset_plan: dict[str, Any],
    selected_ids: set[str], registry: Any,
    entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Render standardized protocols from typed labels and method contracts."""
    from .figure_engine import FigureType, _evaluation_design_svg, figure_engine

    style = str(
        (asset_plan.get("publication_style") or {}).get("visual_standard")
        or "field-adaptive-accessible-vector-v3"
    )
    code_sha256 = _template_code_sha256()
    for spec in planned_specs:
        identity = str(spec.get("id") or "").strip()
        if not identity or (selected_ids and identity not in selected_ids) or (
            spec.get("producer_kind") != "deterministic"
            or spec.get("production_strategy") != "deterministic_template"
            or spec.get("recommended_backend") != "rich_svg"
            or str(spec.get("generation_policy") or "generate") != "generate"
        ):
            continue
        input_hash = _template_input_sha256(spec, style, code_sha256)
        current = entries.get(identity, {})
        reusable = (
            identity not in selected_ids
            and _current_entry_reusable(current, figures_root.parent, input_hash)
        )
        if not reusable:
            svg, mappings = _evaluation_design_svg(spec)
            await _render_template(
                host, run, figures_root, spec, identity, input_hash,
                style, svg, mappings, FigureType.RICH_SVG, figure_engine,
            )
            entries = _entries(registry, figures_root)
    return entries


async def _render_template(
    host: Any, run: Any, figures_root: Path, spec: dict[str, Any],
    asset_id: str, input_hash: str, style: str, svg: str,
    mappings: list[dict[str, str]], figure_type: Any, engine: Any,
) -> None:
    svg_hash = hashlib.sha256(svg.encode("utf-8")).hexdigest()
    failure_path = _failure_path(figures_root, asset_id)
    previous_error = _cached_failure(
        failure_path, figures_root, asset_id, input_hash, svg_hash,
    )
    if previous_error:
        from .figure_models import FigureResult

        result = FigureResult(False, figure_type, error=previous_error)
        await _emit_result(
            host, run, asset_id, result, input_hash, cached_failure=True,
        )
        raise UnchangedDeterministicFigureDefect(
            f"{asset_id}: unchanged deterministic producer defect "
            f"({_error_signature(previous_error)[:12]}): {previous_error}"
        )
    skill = str(spec.get("recommended_skill") or "deterministic-figure-template")
    metadata = {
        **spec, "semantic_key": asset_id, "managed_by": "merak",
        "producer_kind": "deterministic", "producer_input_sha256": input_hash,
        "deterministic_template_version": _TEMPLATE_VERSION,
        "paper_selected": True, "manuscript_eligible": True,
        "generator_skill": skill, "skill": skill,
        "skill_invocation_verified": True,
        "skill_invocation_verified_by": "deterministic-runtime-figure-builder",
        "element_mappings": mappings, "style_profile": style,
    }
    result = await engine.generate(
        description=str(spec.get("caption") or spec.get("scientific_question") or asset_id),
        figure_type=figure_type, output_dir=str(figures_root / "diagrams"),
        code=svg, metadata=metadata, artifact_name=asset_id,
    )
    await _handle_template_result(
        host, run, result, figures_root, failure_path,
        asset_id, input_hash, svg_hash,
    )


async def _handle_template_result(
    host: Any, run: Any, result: Any, figures_root: Path, failure_path: Path,
    asset_id: str, input_hash: str, svg_hash: str,
) -> None:
    error = str(result.error or "")
    if result.success:
        failure_path.unlink(missing_ok=True)
    else:
        from .deterministic_native_review_cache import cacheable_record, record_failure

        persisted = _review_record(figures_root, asset_id)
        native = cacheable_record(
            root=figures_root.parent, asset_id=asset_id,
            input_hash=input_hash, svg_hash=svg_hash, error=error,
            result=result, persisted_round=persisted,
        )
        if native:
            record_failure(failure_path, native)
        elif review := _cacheable_review(result, error):
            if all(persisted.get(key) == review.get(key) for key in (
                "status", "content_sha256", "render_sha256", "issues",
            )):
                _record_failure(
                    failure_path, figures_root, asset_id, input_hash, svg_hash,
                    error, review,
                )
            else:
                failure_path.unlink(missing_ok=True)
        else:
            failure_path.unlink(missing_ok=True)
    await _emit_result(host, run, asset_id, result, input_hash)
    if not result.success:
        raise DeterministicFigureProducerError(
            f"{asset_id}: deterministic figure producer failed: {error or 'unknown failure'}"
        )


async def _ensure_deterministic_plots(
    host: Any, run: Any, figures_root: Path,
    planned_specs: list[dict[str, Any]], asset_plan: dict[str, Any],
    selected_ids: set[str], registry: Any,
    entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Render quantitative assets without delegating data geometry to a model."""
    from .figure_engine import FigureType, figure_engine
    from .scientific_plotting import build_scientific_plot_script

    root = figures_root.parent
    style = dict(asset_plan.get("publication_style_contract") or {})
    for spec in planned_specs:
        identity = str(spec.get("id") or "").strip()
        if not identity or (selected_ids and identity not in selected_ids) or (
            spec.get("producer_kind") != "deterministic"
            or spec.get("production_strategy") != "deterministic_plot"
            or spec.get("recommended_backend") != "matplotlib"
            or str(spec.get("generation_policy") or "generate") != "generate"
        ):
            continue
        data_value = str(spec.get("data_path") or "").strip()
        data_path = (root / data_value).resolve() if data_value else None
        if data_path is None or not data_path.is_file():
            continue
        payload = {
            "spec": {
                key: spec.get(key) for key in (
                    "scientific_question", "recommended_plot_type", "metric",
                    "visual_encoding", "uncertainty_encoding", "publication_labels",
                )
            },
            "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
            "publication_style": style,
        }
        input_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        current = entries.get(identity, {})
        if (
            identity not in selected_ids
            and _current_entry_reusable(current, figures_root.parent, input_hash)
        ):
            continue
        skill = str(spec.get("recommended_skill") or "paper-figure")
        metadata = {
            **spec, "semantic_key": identity, "managed_by": "merak",
            "producer_kind": "deterministic", "producer_input_sha256": input_hash,
            "paper_selected": True, "manuscript_eligible": True,
            "generator_skill": skill, "skill": skill,
            "skill_invocation_verified": True,
            "skill_invocation_verified_by": "deterministic-runtime-plot-builder",
            "source_data": list(dict.fromkeys([*(spec.get('source_data') or []), data_value])),
        }
        result = await figure_engine.generate(
            description=str(
                spec.get("caption") or spec.get("scientific_question") or identity
            ),
            figure_type=FigureType.MATPLOTLIB,
            output_dir=str(figures_root / "plots"),
            code=build_scientific_plot_script(
                spec, style, idea=str(asset_plan.get("selected_idea") or ""),
            ),
            metadata=metadata, artifact_name=identity,
        )
        await _emit_result(host, run, identity, result, input_hash)
        if not result.success:
            raise DeterministicFigureProducerError(
                f"{identity}: deterministic plot producer failed: "
                f"{result.error or 'unknown failure'}"
            )
        entries = _entries(registry, figures_root)
    return entries


async def _emit_result(
    host: Any, run: Any, asset_id: str, result: Any, input_hash: str,
    *, cached_failure: bool = False,
) -> None:
    await host._emit(run, "figure_deterministic_asset_generated", {
        "node_id": "figure", "asset_id": asset_id,
        "success": bool(result.success), "source_path": result.source_path,
        "output_path": result.output_path, "error": result.error,
        "producer_input_sha256": input_hash,
        "cached_failure": cached_failure,
        "failure_signature": _error_signature(str(result.error or ""))
        if not result.success else "",
    })
