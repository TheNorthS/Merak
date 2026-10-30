"""Native-image review helpers for staged rich-SVG figure drafts."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from server.services.figure_mechanism_ir import MECHANISM_CANVAS_SCHEMA
from server.services.model_composed_svg import (
    current_source_bundle_matches,
    element_mappings_sha256,
    is_model_composed_manifest,
    validate_element_mappings,
)
from server.utils.atomic_write import atomic_write_json, atomic_write_text

from .figure_draft_tools import (
    DRAFT_POLICY_VERSION,
    _IDENTIFIER,
    _assembled_content,
    _draft_directory,
    _draft_print_issues,
    _probe_configuration_brief,
    _small_text_details,
    current_draft_matches_storyboard,
)


def _persist_fragment_review(
    directory: Path, root: Path, focus_fragment: str, content: str,
    png: Path, response: object, review: dict[str, Any],
) -> None:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    part = next((
        directory / "parts" / str(name)
        for name in manifest.get("parts") or []
        if str(name).endswith(f"_{focus_fragment}.svgfrag")
    ), None)
    if part is None or not part.is_file():
        raise ValueError(
            f"focus fragment is not present in the draft: {focus_fragment}"
        )
    reviews = manifest.get("fragment_reviews")
    reviews = reviews if isinstance(reviews, dict) else {}
    reviews[focus_fragment] = {
        "fragment_sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
        "assembled_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "score": review.get("score"), "verdict": review.get("verdict"),
        "issues": list(review.get("issues") or [])[:12],
        "findings": list(review.get("findings") or [])[:24],
        "preview_path": str(png.relative_to(root)),
        "review_trace_path": response.trace_path, "reviewed_at": time.time(),
    }
    manifest["fragment_reviews"] = reviews
    atomic_write_json(manifest_path, manifest)


_LOCAL_FAILURE_BINDINGS = (
    "draft_policy_version", "source_bundle_sha256", "figure_spec_sha256",
    "element_mappings_sha256", "storyboard_selected_sha256",
    "storyboard_candidate_sha256",
)


def _persist_local_composition_failure(
    directory: Path, visual_blueprint: dict[str, Any],
    failure: dict[str, Any],
) -> None:
    """Keep exact preflight targets when a rejected revision is rolled back."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    atomic_write_json(directory / "last-local-failure.json", {
        "visual_blueprint_sha256": _blueprint_sha256(visual_blueprint),
        "source_sha256": manifest.get("source_sha256"),
        **{key: manifest.get(key) for key in _LOCAL_FAILURE_BINDINGS},
        "issues": list(failure.get("issues") or [])[:12],
        "small_text": list(failure.get("small_text") or [])[:12],
        "text_geometry": list(failure.get("text_geometry") or [])[:16],
    })


def _bind_restored_local_failure(directory: Path) -> None:
    """Keep rejected-candidate targets only while its restored best is active."""
    path = directory / "last-local-failure.json"
    failure = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    failure["restored_best_source_sha256"] = manifest.get("source_sha256")
    atomic_write_json(path, failure)


def _draft_review_prompt(
    artifact_name: str, focus_fragment: str, question: str,
) -> str:
    return f"""Review the attached in-progress scientific SVG rendering.
Artifact: {artifact_name}
Focus fragment: {focus_fragment}
Question: {question}

Judge the pixels, concentrating on the named fragment and its integration with
the visible accepted context. Do not penalize downstream regions that have not
been authored yet. Identify overlap, clipping, tiny text, generic-card design,
unclear scientific glyphs, and ambiguous connector attachment. Return the
standard rich-SVG review JSON with concise element-level repair instructions.
Classify every finding into exactly one target_layer: use glyph with target ID
`{focus_fragment}` only for the text-free scientific depiction; use runtime
with target ID `composition` for labels, connectors, boxes, clipping, spacing,
or typography; use planner/figure_plan for hierarchy; and use
scientific_contract/scientific_contract for an incorrect scientific relation.
Never route a runtime defect to the glyph."""


def _draft_preview(
    directory: Path, artifact_name: str, content: str,
) -> tuple[Path, Path, Path]:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    preview_dir = directory / "previews" / digest
    preview_dir.mkdir(parents=True, exist_ok=True)
    svg, pdf, png = (
        preview_dir / f"{artifact_name}{suffix}"
        for suffix in (".svg", ".pdf", ".png")
    )
    atomic_write_text(svg, content)
    return svg, pdf, png


def _draft_local_failure(
    artifact_name: str, focus_fragment: str, fragment_count: int,
    directory: Path, content: str, pdf: Path,
) -> str | None:
    issues = _draft_print_issues(content)
    if issues:
        return json.dumps({
            "status": "local_repair_required", "artifact_name": artifact_name,
            "focus_fragment": focus_fragment, "fragment_count": fragment_count,
            "issues": issues,
            "small_text": _small_text_details(content, directory),
            "instruction": (
                "Repair the listed fragment_id and text labels to at least the "
                "required_font_units before native-image review; do not repeatedly "
                "edit an unrelated fragment."
            ),
        }, ensure_ascii=False)
    from server.services.figure_svg_text_geometry import rendered_svg_text_geometry

    geometry = rendered_svg_text_geometry(pdf)
    if not geometry:
        return None
    return json.dumps({
        "status": "local_repair_required", "artifact_name": artifact_name,
        "focus_fragment": focus_fragment, "fragment_count": fragment_count,
        "issues": ["rendered SVG has clipped or colliding text"],
        "text_geometry": _geometry_fragments(directory, geometry),
    }, ensure_ascii=False)


async def review_figure_svg_draft(
    artifact_name: str, focus_fragment: str, review_question: str,
    project_path: str = "",
) -> str:
    """Render current layers and obtain native-image feedback before assembly."""
    root, directory = _draft_directory(project_path, artifact_name)
    if not _IDENTIFIER.fullmatch(focus_fragment):
        raise ValueError("focus_fragment must be stable snake_case")
    question = " ".join(str(review_question or "").split())
    if len(question) < 12:
        raise ValueError("review_question must identify a concrete visual concern")
    content, fragment_count = _assembled_content(directory, minimum_fragments=1)
    svg, pdf, png = _draft_preview(directory, artifact_name, content)
    print_issues = _draft_print_issues(content)
    if not print_issues:
        from server.services.svg_variant_conversion import convert_svg_variants

        converted, error = convert_svg_variants(svg, pdf, png)
        if not converted:
            raise RuntimeError(error)
    local = _draft_local_failure(
        artifact_name, focus_fragment, fragment_count, directory, content, pdf,
    )
    if local:
        return local
    from server.services.api_visual_reviewer import api_visual_reviewer

    response = await api_visual_reviewer.review_rich_svg(
        project_path=root,
        prompt=_draft_review_prompt(artifact_name, focus_fragment, question),
        image_path=png, artifact_name=f"{artifact_name}-draft-{focus_fragment}",
        timeout_seconds=360.0,
    )
    try:
        review = json.loads(response.text)
    except json.JSONDecodeError as error:
        raise RuntimeError("draft visual reviewer returned invalid JSON") from error
    from server.services.figure_review_findings import normalize_review_findings

    blueprint = {"primitives": [{"id": focus_fragment}]}
    review["findings"] = normalize_review_findings(
        review, {"visual_blueprint": blueprint}, artifact_id=artifact_name,
    )
    _persist_fragment_review(
        directory, root, focus_fragment, content, png, response, review,
    )
    return json.dumps({
        "status": "reviewed", "artifact_name": artifact_name,
        "focus_fragment": focus_fragment, "fragment_count": fragment_count,
        "preview_path": str(png.relative_to(root)), "review": review,
        "review_trace_path": response.trace_path,
        **_repair_routing(review, blueprint, artifact_name),
    }, ensure_ascii=False)


def _blueprint_sha256(visual_blueprint: dict[str, Any]) -> str:
    encoded = json.dumps(
        visual_blueprint, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _geometry_fragments(
    directory: Path, findings: list[dict[str, object]],
) -> list[dict[str, object]]:
    from server.services.figure_svg_text_targets import attach_text_targets

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if is_model_composed_manifest(manifest):
        source = directory / f"{manifest.get('artifact_name')}.svg"
        return attach_text_targets(source.read_text(encoding="utf-8"), findings)
    sources = [
        (str(name).split("_", 1)[-1].removesuffix(".svgfrag"),
         (directory / "parts" / str(name)).read_text(encoding="utf-8"))
        for name in manifest.get("parts") or [] if not str(name).startswith("000_")
    ]
    return [{
        **finding,
        "fragment_ids": [
            next((identity for identity, source in sources if str(label) in source),
                 "unknown_fragment")
            for label in finding.get("labels") or []
        ],
    } for finding in findings]


def _composition_metadata(
    root: Path, artifact_name: str, visual_blueprint: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specs_path = root / "figures" / "FIGURE_SPECS.json"
    try:
        payload = json.loads(specs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"figure specifications are missing or invalid: {specs_path}"
        ) from error
    figures = payload.get("figures") if isinstance(payload, dict) else []
    asset = next((
        dict(item) for item in figures or []
        if isinstance(item, dict) and str(item.get("id") or "") == artifact_name
    ), None)
    if asset is None:
        raise ValueError(f"figure specification is missing for {artifact_name}")
    value = {
        **asset, "visual_blueprint": visual_blueprint,
        "blind_readback_required": True,
        "intended_comparison": str(asset.get("intended_comparison") or ""),
        "probe_configuration": _probe_configuration_brief(asset),
    }
    manifest = manifest if isinstance(manifest, dict) else {}
    if is_model_composed_manifest(manifest):
        value.update({
            "production_strategy": manifest.get("production_strategy"),
            "composition_owner": "model",
            "source_bindings": list(manifest.get("source_bindings") or []),
            "source_bundle_sha256": manifest.get("source_bundle_sha256"),
            "element_mappings": list(manifest.get("element_mappings") or []),
            "element_mappings_sha256": manifest.get("element_mappings_sha256"),
        })
    return value


def _repair_routing(
    review: dict[str, Any], visual_blueprint: dict[str, Any], artifact_name: str,
    *, model_composed: bool = False,
) -> dict[str, Any]:
    """Expose owner-specific actions without sending runtime defects to glyphs."""
    from server.services.figure_review_findings import (
        group_review_findings, normalize_review_findings,
    )

    findings = normalize_review_findings(
        review, {"visual_blueprint": visual_blueprint},
        artifact_id=artifact_name,
    )
    grouped = group_review_findings(findings)
    glyph_targets = list(dict.fromkeys(
        target
        for finding in grouped["glyph"]
        for target in finding.get("target_ids") or []
    ))
    if model_composed:
        targets = list(dict.fromkeys(
            target
            for finding in findings
            for target in finding.get("target_ids") or []
        ))
        return {
            "findings": findings,
            "repair_plan": {"model": findings, "runtime": [], "planner": [],
                            "glyph": [], "scientific_contract": []},
            "repair_routing": {
                "composition_owner": "model", "model_owned": True,
                "model_target_ids": targets or ["composition"],
                "runtime_owned": False, "planner_owned": False,
                "scientific_contract_owned": False,
                "model_instruction": (
                    "Revise the complete SVG directly. You own labels, arrows, "
                    "paths, typography, spacing, and layout; do not wait for a "
                    "runtime layout refresh. Preserve scientific facts and source bindings."
                ),
            },
        }
    return {
        "findings": findings,
        "repair_plan": grouped,
        "repair_routing": {
            "glyph_target_ids": glyph_targets,
            "runtime_owned": bool(grouped["runtime"]),
            "planner_owned": bool(grouped["planner"]),
            "scientific_contract_owned": bool(grouped["scientific_contract"]),
            "runtime_instruction": (
                "Do not replace a domain glyph for runtime-owned findings. "
                "Refresh or repair deterministic labels/connectors/layout, then "
                "review the full composition again."
            ) if grouped["runtime"] else "",
        },
    }


def _persist_composition_review(
    directory: Path, content: str, visual_blueprint: dict[str, Any],
    review: dict[str, Any], issues: list[str], preview: Path,
) -> None:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["composition_review"] = {
        "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "visual_blueprint_sha256": _blueprint_sha256(visual_blueprint),
        "score": review.get("score"), "verdict": review.get("verdict"),
        "checklist": dict(review.get("checklist") or {}),
        "issues": list(issues),
        "improvement_prompt": str(review.get("improvement_prompt") or ""),
        "findings": list(review.get("findings") or [])[:24],
        "blind_readback": dict(review.get("blind_readback") or {}),
        "blind_readback_issues": list(review.get("blind_readback_issues") or []),
        "blind_readback_trace_path": str(
            review.get("blind_readback_trace_path") or ""
        ),
        "preview_path": str(preview),
        "review_trace_path": str(review.get("review_trace_path") or ""),
        "source_bundle_sha256": str(manifest.get("source_bundle_sha256") or ""),
        "figure_spec_sha256": str(manifest.get("figure_spec_sha256") or ""),
        "element_mappings_sha256": str(
            manifest.get("element_mappings_sha256") or ""
        ),
        "independent_visual_review": dict(review),
        "reviewed_at": time.time(),
    }
    atomic_write_json(manifest_path, manifest)
    (directory / "last-local-failure.json").unlink(missing_ok=True)


def _matching_cached_review(
    directory: Path, content: str, visual_blueprint: dict[str, Any],
) -> dict[str, Any]:
    """Reuse a review only for the identical SVG and full source contract."""
    from server.services.rich_svg_visual_review import REVIEW_POLICY_VERSION

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    review = manifest.get("composition_review")
    if not isinstance(review, dict) or not isinstance(
        review.get("independent_visual_review"), dict,
    ):
        return {}
    if (
        review["independent_visual_review"].get("review_policy_version")
        != REVIEW_POLICY_VERSION
        or review.get("source_sha256") != hashlib.sha256(content.encode("utf-8")).hexdigest()
        or review.get("visual_blueprint_sha256") != _blueprint_sha256(visual_blueprint)
        or any(
            review.get(key) != manifest.get(key)
            for key in (
                "source_bundle_sha256", "figure_spec_sha256",
                "element_mappings_sha256",
            )
        )
    ):
        return {}
    return review


def _validated_composition_blueprint(
    directory: Path, visual_blueprint: dict[str, Any],
) -> dict[str, Any]:
    from server.services.rich_svg_blueprint import validate_visual_blueprint

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    source_spec = None
    if is_model_composed_manifest(manifest):
        from server.services.model_composed_svg import require_model_composed_spec

        source_spec = require_model_composed_spec(
            directory.parents[2], str(manifest.get("artifact_name") or ""),
        )
    blueprint, issues = validate_visual_blueprint(
        visual_blueprint, source_spec=source_spec,
    )
    if is_model_composed_manifest(manifest):
        issues.extend(_model_composed_blueprint_issues(directory, manifest, blueprint))
    mechanism_path = directory / "mechanism-ir.json"
    if mechanism_path.is_file():
        from server.services.figure_mechanism_ir import (
            canonicalize_mechanism_blueprint, mechanism_blueprint_issues,
        )

        mechanism_ir = json.loads(mechanism_path.read_text(encoding="utf-8"))
        mechanism_ids = {
            str(item["id"]) for item in mechanism_ir.get("primitives") or []
        }
        authored_ids = {
            str(item.get("id") or "")
            for item in blueprint.get("primitives") or []
            if isinstance(item, dict)
        }
        if authored_ids != mechanism_ids:
            issues.append(
                "visual_blueprint primitive ids must exactly match mechanism_ir"
            )
        blueprint = canonicalize_mechanism_blueprint(mechanism_ir, blueprint)
        issues.extend(mechanism_blueprint_issues(mechanism_ir, blueprint))
    if issues:
        raise ValueError("visual blueprint is invalid: " + "; ".join(issues))
    return blueprint


def _model_composed_blueprint_issues(
    directory: Path, manifest: dict[str, Any], blueprint: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if is_model_composed_manifest(manifest):
        staged_path = directory / "visual-blueprint.json"
        source_path = directory / f"{manifest.get('artifact_name')}.svg"
        try:
            staged = json.loads(staged_path.read_text(encoding="utf-8"))
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("model-composed SVG contract is missing or invalid") from error
        if blueprint != staged:
            issues.append(
                "visual_blueprint must exactly match the source-bound blueprint "
                "submitted with submit_model_svg_draft"
            )
        from server.services.model_composed_svg import (
            design_brief_svg_issues,
            require_model_composed_spec,
            validate_full_svg,
        )
        project_root = directory.parents[2]
        try:
            spec = require_model_composed_spec(
                project_root, str(manifest.get("artifact_name") or ""),
            )
        except ValueError as error:
            spec = {}
            issues.append(str(error))

        try:
            canonical_source, _canonical_blueprint, _root, _ids = validate_full_svg(
                source, blueprint, source_spec=spec,
            )
        except ValueError as error:
            issues.append(str(error))
        else:
            if manifest.get("source_sha256") != hashlib.sha256(
                canonical_source.encode("utf-8")
            ).hexdigest():
                issues.append("model-composed SVG changed after semantic validation")
            if spec:
                issues.extend(design_brief_svg_issues(spec, blueprint, _root))
                mapping_value = manifest.get("element_mappings")
                semantic_ids = {
                    str(item.get("id") or "")
                    for item in blueprint.get("primitives") or []
                    if isinstance(item, dict) and str(item.get("id") or "")
                }
                mappings, mapping_issues = validate_element_mappings(
                    project_root, spec, mapping_value,
                    semantic_group_ids=semantic_ids,
                )
                issues.extend(mapping_issues)
                if mappings != mapping_value:
                    issues.append("model-composed element_mappings are not canonical")
                if manifest.get("element_mappings_sha256") != (
                    element_mappings_sha256(mappings)
                ):
                    issues.append(
                        "model-composed element_mappings changed after semantic validation"
                    )
    return issues


def _require_current_mechanism_canvas(directory: Path) -> dict[str, Any]:
    """Reject drafts produced by an older mechanism/layout contract."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if is_model_composed_manifest(manifest):
        root = directory.parents[2]
        if (
            manifest.get("draft_policy_version") != DRAFT_POLICY_VERSION
            or manifest.get("composition_owner") != "model"
            or not current_source_bundle_matches(root, manifest)
            or not (directory / "visual-blueprint.json").is_file()
        ):
            raise ValueError(
                "model-composed SVG contract or source bindings are stale; "
                "call prepare_model_svg_draft and submit_model_svg_draft again"
            )
        return manifest
    mechanism_path = directory / "mechanism-ir.json"
    if (
        manifest.get("draft_policy_version") != DRAFT_POLICY_VERSION
        or manifest.get("canvas_layout_schema") != MECHANISM_CANVAS_SCHEMA
        or not mechanism_path.is_file()
    ):
        raise ValueError(
            "figure canvas contract is stale; call prepare_figure_svg_canvas "
            "with a fresh schema-2 mechanism_ir"
        )
    mechanism_ir = json.loads(mechanism_path.read_text(encoding="utf-8"))
    layout_path = directory / "canvas-layout.json"
    if mechanism_ir.get("schema") != 2 or not layout_path.is_file():
        raise ValueError(
            "figure mechanism canvas is stale or missing; call "
            "prepare_figure_svg_canvas with a fresh schema-2 mechanism_ir"
        )
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    region_ids = {str(item["id"]) for item in layout.get("regions") or []}
    from server.services.figure_mechanism_ir import validate_mechanism_ir

    try:
        validate_mechanism_ir(mechanism_ir, region_ids)
    except ValueError as error:
        raise ValueError(
            "figure mechanism contract is invalid; call prepare_figure_svg_canvas "
            f"with a corrected schema-2 mechanism_ir: {error}"
        ) from error
    return manifest


def _composition_preview(
    directory: Path, artifact_name: str, content: str,
) -> tuple[Path, Path, Path, str]:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    preview_dir = directory / "composition-previews" / digest[:16]
    preview_dir.mkdir(parents=True, exist_ok=True)
    svg, pdf, png = (
        preview_dir / f"{artifact_name}{suffix}"
        for suffix in (".svg", ".pdf", ".png")
    )
    atomic_write_text(svg, content)
    from server.services.svg_variant_conversion import convert_svg_variants

    converted, error = convert_svg_variants(svg, pdf, png)
    if not converted:
        raise RuntimeError(error)
    return svg, pdf, png, digest


def _composition_local_failure(
    artifact_name: str, blueprint: dict[str, Any], directory: Path,
    content: str, fragment_count: int,
) -> tuple[str | None, tuple[Path, Path, Path, str] | None]:
    issues = _draft_print_issues(content)
    if issues:
        return json.dumps({
            "status": "local_repair_required", "artifact_name": artifact_name,
            "issues": issues, "small_text": _small_text_details(content, directory),
            **_repair_routing(
                {"verdict": "refine", "issues": issues}, blueprint, artifact_name,
                model_composed=is_model_composed_manifest(
                    json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                ),
            ),
        }, ensure_ascii=False), None
    preview = _composition_preview(directory, artifact_name, content)
    from server.services.figure_svg_text_geometry import rendered_svg_text_geometry

    geometry = rendered_svg_text_geometry(preview[1])
    if not geometry:
        return None, preview
    issues = ["rendered SVG has clipped or colliding text"]
    return json.dumps({
        "status": "local_repair_required", "artifact_name": artifact_name,
        "fragment_count": fragment_count, "issues": issues,
        "text_geometry": _geometry_fragments(directory, geometry),
        "instruction": (
            "Shorten or reposition the reported labels within their owning region; "
            "do not reduce text below the print-scale minimum. Finalize and review "
            "this composition again."
        ),
        **_repair_routing(
            {"verdict": "refine", "issues": issues}, blueprint, artifact_name,
            model_composed=is_model_composed_manifest(
                json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            ),
        ),
    }, ensure_ascii=False), None


def _regressed_response(
    directory: Path, artifact_name: str, blueprint: dict[str, Any],
    review: dict[str, Any], issues: list[str], best_score: float,
) -> str:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    restored = manifest.get("composition_review")
    restored = restored if isinstance(restored, dict) else {}
    if is_model_composed_manifest(manifest):
        blueprint = json.loads((directory / "visual-blueprint.json").read_text(
            encoding="utf-8",
        ))
    restored_issues = list(restored.get("issues") or issues)
    return json.dumps({
        "status": "regressed_restored", "artifact_name": artifact_name,
        "candidate_score": review.get("score"),
        "restored_best_score": best_score, "issues": restored_issues,
        "restored_visual_blueprint_sha256": _blueprint_sha256(blueprint),
        "instruction": (
            "This revision reduced visual quality. The strongest staged SVG and "
            "its fragments and visual-blueprint.json were restored. Read them "
            "before resubmitting. Repair that restored draft using only "
            "the unresolved reviewer findings; do not continue from the regression."
        ),
        **_repair_routing(
            restored, blueprint, artifact_name,
            model_composed=is_model_composed_manifest(manifest),
        ),
    }, ensure_ascii=False)


async def _review_composition_candidate(
    root: Path, directory: Path, artifact_name: str,
    blueprint: dict[str, Any], content: str, fragment_count: int,
    preview: tuple[Path, Path, Path, str],
) -> str:
    svg, pdf, png, digest = preview
    from server.services.rich_svg_visual_review import review_candidate

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    cached = _matching_cached_review(directory, content, blueprint)
    if cached:
        review = dict(cached["independent_visual_review"])
        issues = list(cached.get("issues") or [])
        return json.dumps({
            "status": "accepted" if not issues else "refine",
            "artifact_name": artifact_name, "fragment_count": fragment_count,
            "cached_review": True,
            "instruction": (
                "This exact SVG has already been reviewed. Edit the complete SVG "
                "to address the listed issues before reviewing again."
                if issues else "The exact reviewed SVG may proceed to generate_figure."
            ),
            "review": review, "issues": issues,
            **_repair_routing(
                review, blueprint, artifact_name,
                model_composed=is_model_composed_manifest(manifest),
            ),
        }, ensure_ascii=False)
    review, issues = await review_candidate(
        root=root, artifact_id=artifact_name,
        metadata=_composition_metadata(root, artifact_name, blueprint, manifest),
        source=svg, pdf=pdf, png=png, source_sha256=digest,
    )
    _persist_composition_review(directory, content, blueprint, review, issues, png)
    from server.services.figure_draft_best import preserve_best_draft

    regressed, best_score = preserve_best_draft(
        directory, svg, review, issues, _blueprint_sha256(blueprint),
    )
    if regressed:
        return _regressed_response(
            directory, artifact_name, blueprint, review, issues, best_score,
        )
    return json.dumps({
        "status": "accepted" if not issues else "refine",
        "artifact_name": artifact_name, "fragment_count": fragment_count,
        "preview_path": str(png.relative_to(root)), "review": review,
        "issues": issues, **_repair_routing(
            review, blueprint, artifact_name,
            model_composed=is_model_composed_manifest(manifest),
        ),
    }, ensure_ascii=False)


async def review_figure_svg_composition(
    artifact_name: str, visual_blueprint: dict[str, Any], project_path: str = "",
) -> str:
    """Apply final native-image review before consuming a formal submission."""
    root, directory = _draft_directory(project_path, artifact_name)
    manifest = _require_current_mechanism_canvas(directory)
    blueprint = _validated_composition_blueprint(directory, visual_blueprint)
    content, count = _assembled_content(
        directory, minimum_fragments=1 if is_model_composed_manifest(manifest) else 3,
    )
    local, preview = _composition_local_failure(
        artifact_name, blueprint, directory, content, count,
    )
    if local:
        failure = json.loads(local)
        _persist_local_composition_failure(directory, blueprint, failure)
        if is_model_composed_manifest(manifest):
            from server.services.figure_draft_best import (
                restore_best_after_local_failure,
            )

            best = restore_best_after_local_failure(
                directory, _blueprint_sha256(blueprint),
            )
            if best:
                _bind_restored_local_failure(directory)
                failure["restored_best"] = True
                failure["restored_best_score"] = best.get("score")
                failure["restored_best_source_sha256"] = best.get("source_sha256")
                failure["instruction"] = (
                    "The last revision failed local print or text geometry checks. "
                    "The strongest source-bound SVG was restored. Repair that SVG "
                    "using these exact targets; keep passing regions and text sizes."
                )
        return json.dumps(failure, ensure_ascii=False)
    assert preview is not None
    return await _review_composition_candidate(
        root, directory, artifact_name, blueprint, content, count, preview,
    )


def require_current_composition_review(
    project_root: Path, artifact_name: str, source: Path,
    visual_blueprint: dict[str, Any],
) -> None:
    """Reject submission unless this exact SVG and blueprint passed preflight."""
    _root, directory = _draft_directory(str(project_root), artifact_name)
    expected_source = (directory / f"{artifact_name}.svg").resolve()
    if source.resolve() != expected_source or not source.is_file():
        raise ValueError("rich-svg workflow submission must use its finalized staged SVG")
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("rich SVG composition review is missing") from error
    blueprint = _validated_composition_blueprint(directory, visual_blueprint)
    review = manifest.get("composition_review")
    review = review if isinstance(review, dict) else {}
    from server.services.rich_svg_visual_review import REVIEW_POLICY_VERSION, review_gate_issues
    from server.services.rich_svg_blueprint import blueprint_minimums

    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    model_composed = is_model_composed_manifest(manifest)
    minimum_relations = 3
    if model_composed:
        from server.services.model_composed_svg import require_model_composed_spec
        spec = require_model_composed_spec(project_root, artifact_name)
        minimum_relations = blueprint_minimums(spec).flows
    mode_contract_valid = (
        current_source_bundle_matches(project_root, manifest)
        and review.get("source_bundle_sha256") == manifest.get("source_bundle_sha256")
        and review.get("figure_spec_sha256") == manifest.get("figure_spec_sha256")
        and review.get("element_mappings_sha256")
        == manifest.get("element_mappings_sha256")
    ) if model_composed else (
        manifest.get("canvas_layout_schema") == MECHANISM_CANVAS_SCHEMA
        and current_draft_matches_storyboard(project_root, artifact_name)
    )
    valid = (
        manifest.get("draft_policy_version") == DRAFT_POLICY_VERSION
        and mode_contract_valid
        and review.get("source_sha256") == current_hash
        and review.get("visual_blueprint_sha256") == _blueprint_sha256(blueprint)
        and (review.get("independent_visual_review") or {}).get("review_policy_version")
        == REVIEW_POLICY_VERSION
        and not review_gate_issues(review)
        and not review.get("issues")
        and review.get("blind_readback_issues") == []
        and (review.get("blind_readback") or {}).get("mechanism_recoverable") is True
        and len((review.get("blind_readback") or {}).get("directed_relations") or []) >= minimum_relations
        and bool(review.get("blind_readback_trace_path"))
    )
    if not valid:
        raise ValueError(
            "this exact full SVG composition has not passed native-image preflight; "
            "call review_figure_svg_composition, repair the named fragments, finalize, "
            "and repeat until status=accepted before generate_figure"
        )
