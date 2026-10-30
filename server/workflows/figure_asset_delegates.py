"""Run one isolated planning/drawing session per model-owned scientific figure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..agent.tools.figure_storyboard_tools import (
    begin_figure_storyboard,
    load_selected_storyboard,
)
from ..agent.tools.figure_draft_tools import current_draft_matches_storyboard
from ..services.figure_artifacts import figure_artifact_registry
from ..services.model_composed_svg import is_model_composed_manifest
from ..services.figure_delegate_budget import (
    DelegateAttempt,
    FigureRetryDeferred,
    begin_delegate_attempt,
    record_delegate_failure,
)
from ..services.figure_routing import BACKEND_SKILLS
from ..services.rich_svg_blueprint import (
    FLOW_KIND_VALUES,
    MAX_BLUEPRINT_PRIMITIVES,
    MIN_BLUEPRINT_PRIMITIVES,
    MIN_BLUEPRINT_VISUAL_FORMS,
    VISUAL_FORM_VALUES,
)
from ..services.figure_spec_repository import persist_figure_specs
from ..services.figure_storyboard_review import visually_select_storyboard
from ..services.figure_semantic_projection import (
    project_figure_semantics,
    semantic_projection_sha256,
)
from ..services.scientific_assets import scientific_asset_service


def _model_assets(context: Any) -> list[dict[str, Any]]:
    options = context.opts
    plan = scientific_asset_service.build_plan(
        context.project_path,
        experiment_requested=options.get("run_experiment") is True,
        requested_evidence_mode=str(options.get("non_experiment_evidence_mode") or ""),
        illustration_mode="auto", direction=context.direction,
        target_venue=str(options.get("target_venue") or ""),
        research_family=str(options.get("research_family") or ""),
        study_archetype=str(options.get("study_archetype") or ""),
    )
    specs = persist_figure_specs(context.project_path, plan)
    selected = [
        dict(item) for item in specs
        if item.get("producer_kind") == "model"
        and str(item.get("generation_policy") or "generate") == "generate"
        and item.get("required") is not False
    ]
    identities = [str(item.get("id") or "") for item in selected]
    if any(not identity for identity in identities) or len(identities) != len(set(identities)):
        raise ValueError("model-owned figure specifications require unique nonempty ids")
    return selected


def _asset_contract(asset: dict[str, Any]) -> str:
    return json.dumps(asset, ensure_ascii=False, indent=2, default=str)


def _semantic_contract(asset: dict[str, Any]) -> str:
    return json.dumps(
        project_figure_semantics(asset), ensure_ascii=False, indent=2, default=str,
    )


def _active_mechanism_guidance(asset: dict[str, Any]) -> str:
    """State active implementation facts separately from planned science."""
    brief = asset.get("method_brief")
    brief = brief if isinstance(brief, dict) else {}
    notes: list[str] = []
    for value in brief.get("probe_configuration") or []:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "probe")
        mode = str(value.get("training_mode") or "unspecified")
        heads = str(value.get("head_status") or "unverified")
        objective = str(value.get("joint_objective_status") or "unverified")
        state = (
            "joint probe configured in the active objective"
            if mode == "joint_objective" and heads == "head_configured"
            and objective == "enabled"
            else "declared frozen downstream; not a joint GRL loss"
            if mode == "frozen_downstream"
            else "disabled" if mode == "disabled"
            else "joint training not established by the active configuration"
        )
        notes.append(
            f"{name} ({value.get('mechanism_id') or 'unassigned'}): {state}; "
            f"head_status={heads}; joint_objective_status={objective}; "
            f"missing_heads={value.get('missing_heads') or []}."
        )
    if not notes:
        return ""
    return (
        "Current implementation configuration is authoritative for active-versus-planned "
        "mechanisms. Do not draw an unverified probe as an always-active GRL or "
        "claim measured attribution. Draw it only as a clearly conditional/planned "
        "branch when needed for the scientific question.\n- "
        + "\n- ".join(notes)
        + "\n\n"
    )


def _blueprint_contract_guidance() -> str:
    """Expose the runtime-owned vocabulary before the model authors an SVG."""
    return (
        "The visual_blueprint is a typed scientific index, not a place to invent "
        "drawing-shape names. Use only these visual_form values: "
        f"{', '.join(VISUAL_FORM_VALUES)}. Use only these flow.kind values: "
        f"{', '.join(FLOW_KIND_VALUES)}. Use {MIN_BLUEPRINT_PRIMITIVES}–"
        f"{MAX_BLUEPRINT_PRIMITIVES} identified primitives and at least "
        f"{MIN_BLUEPRINT_VISUAL_FORMS} distinct canonical visual forms. Bind "
        "scientific objects and preserve their declared relation kinds where "
        "required. Arrows/connectors are flows, never primitives.\n\n"
    )


def _draft_review_guidance(project_path: str, identity: str) -> str:
    """Carry structured composition findings into the next bounded repair."""
    directory = Path(project_path) / ".merak" / "figure-drafts" / identity
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    from ..agent.tools.figure_draft_tools import DRAFT_POLICY_VERSION
    from ..services.rich_svg_visual_review import REVIEW_POLICY_VERSION

    if manifest.get("draft_policy_version") != DRAFT_POLICY_VERSION:
        return ""
    if is_model_composed_manifest(manifest):
        spec_path = Path(project_path) / "figures" / "FIGURE_SPECS.json"
        if spec_path.is_file():
            from ..services.model_composed_svg import (
                figure_spec_sha256, require_model_composed_spec,
            )

            try:
                spec = require_model_composed_spec(Path(project_path), identity)
            except ValueError:
                return ""
            if manifest.get("figure_spec_sha256") != figure_spec_sha256(spec):
                return ""
            if not current_draft_matches_storyboard(project_path, identity):
                return ""
    review = manifest.get("composition_review")
    if not isinstance(review, dict):
        from ..services.figure_draft_best import matching_best_draft

        review = matching_best_draft(
            directory, str(manifest.get("visual_blueprint_sha256") or ""),
        )
    review = review if isinstance(review, dict) else {}
    reviewed_policy = (
        (review.get("independent_visual_review") or {}).get("review_policy_version")
        or review.get("review_policy_version")
    )
    if review and reviewed_policy != REVIEW_POLICY_VERSION:
        return ""
    checklist = {
        str(key): bool(value)
        for key, value in (review.get("checklist") or {}).items()
    }
    failed_checks = [key for key, value in checklist.items() if not value]
    issues = [str(value).strip() for value in review.get("issues") or [] if str(value).strip()]
    findings = [
        " ".join(filter(None, (
            (
                "target=" + ",".join(str(value) for value in item.get("target_ids") or [])
                if item.get("target_ids") else ""
            ),
            str(item.get("message") or item.get("plain_message") or "").strip(),
            str(item.get("repair_action") or "").strip(),
        ))).strip()
        for item in review.get("findings") or []
        if isinstance(item, dict)
        and str(item.get("message") or item.get("plain_message") or "").strip()
    ]
    improvement = str(review.get("improvement_prompt") or "").strip()
    pieces = []
    if failed_checks:
        pieces.append("failed checklist items: " + ", ".join(failed_checks))
    pieces.extend(issues[:8])
    pieces.extend(findings[:8])
    if improvement:
        pieces.append("reviewer repair direction: " + improvement)
    pieces.extend(_local_draft_feedback(directory, manifest))
    if not pieces:
        return ""
    return (
        "Structured findings from the previous composition review are binding. "
        "Repair every listed issue in the same source and keep already-passing "
        "checks true; do not merely resubmit the same layout. If a bad revision "
        "was rolled back, continue from the restored best source.\n- "
        + "\n- ".join(pieces)
        + "\n\n"
    )


def _local_draft_feedback(directory: Path, manifest: dict[str, Any]) -> list[str]:
    """Return exact local targets only for the candidate or restored best."""
    try:
        local = json.loads((directory / "last-local-failure.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(local, dict) or not local.get("source_sha256"):
        return []
    if manifest.get("source_sha256") not in {
        local.get("source_sha256"), local.get("restored_best_source_sha256"),
    }:
        return []
    bindings = (
        "draft_policy_version", "source_bundle_sha256", "figure_spec_sha256",
        "element_mappings_sha256",
        "storyboard_selected_sha256", "storyboard_candidate_sha256",
    )
    if any(local.get(key) != manifest.get(key) for key in bindings):
        return []
    if (
        not local.get("restored_best_source_sha256")
        and local.get("visual_blueprint_sha256")
        != manifest.get("visual_blueprint_sha256")
    ):
        return []
    pieces = []
    if local.get("restored_best_source_sha256"):
        pieces.append(
            "local checks rejected a later candidate; the active SVG was "
            "restored from the best reviewed source"
        )
    pieces.extend(
        "last local preflight issue: " + str(value)
        for value in (local.get("issues") or [])[:6]
    )
    for name, limit in (("small_text", 6), ("text_geometry", 8)):
        pieces.extend(
            name.replace("_", " ") + ": " + json.dumps(item, ensure_ascii=False)
            for item in (local.get(name) or [])[:limit]
            if isinstance(item, dict)
        )
    return pieces


def _layout_scope(asset: dict[str, Any]) -> str:
    role = str(asset.get("scientific_role") or "").casefold()
    contract = asset.get("scene_contract")
    contract = contract if isinstance(contract, dict) else {}
    narrative = str(contract.get("narrative_level") or "").casefold()
    contribution = str(contract.get("contribution_type") or "").casefold()
    if role in {"evaluation", "evaluation_design", "protocol"}:
        return (
            "Use 3–5 regions for isolation, registered conditions, locked measurement, "
            "independent-unit aggregation, and decisions. Represent the studied method "
            "only as a compact interface; never repeat internal method details."
        )
    if narrative == "mechanism_detail":
        return (
            "Use 2–4 regions focused only on operative objects, transformations, "
            "interactions, gates, and the formal merge or decision rule. Exclude full "
            "input protocol, downstream evaluation, and provenance panels."
        )
    if role == "method" or contribution in {
        "model_architecture", "objective_mechanism", "system_architecture",
        "clinical_biological_mechanism", "empirical_discovery",
    }:
        return (
            "Use 3–4 connected regions: compact scientific source/context, one dominant "
            "focal transformation or shared process, contribution-specific interactions, "
            "and its direct synthesis/readout. Put the scientific connection itinerary "
            "in storyboard.connections, with a continuous main path into the synthesis. "
            "Omit annotation_only controls and compact_interfaces unless the focal claim "
            "cannot be understood without them; never allocate them a separate region. "
            "Exclude downstream evaluation, result endpoints, statistical decisions, "
            "audit dashboards, and figure-internal title/subtitle prose."
        )
    return "Use one scientific question and no more regions than the causal story requires."


async def _relay(context: Any, asset_id: str, role: str, event: Any) -> None:
    data = event.data if isinstance(event.data, dict) else {}
    if event.type == "status":
        await context.host._emit(context.run, "figure_asset_delegate_progress", {
            "node_id": "figure", "asset_id": asset_id, "delegate_role": role,
            "status": str(data.get("status") or "running"),
            "elapsed": int(data.get("elapsed") or 0),
        })
    elif event.type in {"tool_call", "tool_result"}:
        await context.host._emit(context.run, f"agent_{event.type}", {
            "node_id": "figure", "asset_id": asset_id, "delegate_role": role,
            "tool": str(data.get("name") or ""),
            "success": bool(data.get("success", event.type == "tool_call")),
            "message": str(data.get("output") or data.get("args") or "")[:800],
        })


def _accepted_entry(root: Path, asset: dict[str, Any]) -> dict[str, Any] | None:
    identity = str(asset["id"])
    manifest = figure_artifact_registry.load(root / "figures")
    entry = next((
        item for item in reversed(manifest.get("figures") or [])
        if str((item.get("metadata") or {}).get("semantic_key") or item.get("id") or "") == identity
    ), None)
    if not isinstance(entry, dict) or entry.get("paper_ready") is not True:
        return None
    for key in ("source_path", "output_path"):
        candidate = Path(str(entry.get(key) or ""))
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            return None
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return None
    metadata = dict(entry.get("metadata") or {})
    if str(asset.get("recommended_backend") or "").strip().casefold() == "rich_svg":
        from ..services.rich_svg_visual_review import (
            REVIEW_POLICY_VERSION, native_review_issues, review_gate_issues,
        )

        review = dict(metadata.get("independent_visual_review") or {})
        strategy = str(asset.get("production_strategy") or "").casefold()
        producer_kind = str(asset.get("producer_kind") or "").casefold()
        expected_generator = (
            "deterministic-runtime-rich-svg"
            if strategy == "deterministic_template" or producer_kind == "deterministic"
            else "model-authored-rich-svg"
        )
        source_value = Path(str(entry.get("source_path") or ""))
        source = source_value if source_value.is_absolute() else root / source_value
        variants = dict(metadata.get("rendered_variants") or {})
        preview_value = Path(str(variants.get("png") or ""))
        preview = preview_value if preview_value.is_absolute() else root / preview_value
        if not (
            metadata.get("generator") == expected_generator
            and review.get("review_policy_version") == REVIEW_POLICY_VERSION
            and not review_gate_issues(review)
            and not native_review_issues(metadata, root, source, preview)
        ):
            return None
    return entry


async def _plan_storyboard(
    context: Any, asset: dict[str, Any], identity: str, root: Path, invoke_skill: Any,
) -> dict[str, Any]:
    projection_hash = semantic_projection_sha256(asset)
    try:
        current = load_selected_storyboard(
            root, identity, expected_projection_sha256=projection_hash,
        )
    except ValueError:
        current = None
    if current is not None:
        await context.host._emit(context.run, "figure_storyboard_reused", {
            "node_id": "figure", "asset_id": identity,
            "storyboard_id": current["selected_id"],
        })
        return await _visually_select(context, identity, current)
    await context.host._emit(context.run, "figure_asset_delegate_started", {
        "node_id": "figure", "asset_id": identity,
        "delegate_role": "layout", "skill": "figure-layout-director",
    })
    prompt = (
        f"Plan only the single figure `{identity}`. Do not plan or draw another asset.\n"
        "Read its declared sources, submit exactly three structurally different "
        "storyboards, and select one.\n"
        f"Mandatory portfolio boundary: {_layout_scope(asset)}\n\n"
        "Authoritative projected scientific subscene:\n"
        + _semantic_contract(asset)
    )
    begin_figure_storyboard(
        identity, context.project_path,
        semantic_projection_sha256=projection_hash,
    )
    await invoke_skill(
        "figure-layout-director", prompt,
        project_path=context.project_path, parent_context="skill-chain:paper-figure",
        workflow_node_id="figure", max_iterations=12, max_tokens=8192,
        on_event=lambda event: _relay(context, identity, "layout", event),
    )
    try:
        current = load_selected_storyboard(
            root, identity, expected_projection_sha256=projection_hash,
        )
        return await _visually_select(context, identity, current)
    except ValueError:
        await context.host._emit(context.run, "figure_asset_delegate_repair", {
            "node_id": "figure", "asset_id": identity,
            "delegate_role": "layout", "reason": "storyboard artifact incomplete",
        })
    repair = (
        f"The layout session ended without completing `{identity}`. The storyboard "
        "is started. Do not reread broad files or write prose. Add exactly three "
        "small schema-valid candidates, then select one. "
        f"Portfolio boundary: {_layout_scope(asset)}\n\nProjected subscene:\n"
        + _semantic_contract(asset)
    )
    await invoke_skill(
        "figure-layout-director", repair,
        project_path=context.project_path, parent_context="skill-chain:paper-figure",
        workflow_node_id="figure", max_iterations=8, max_tokens=8192,
        on_event=lambda event: _relay(context, identity, "layout-repair", event),
    )
    current = load_selected_storyboard(
        root, identity, expected_projection_sha256=projection_hash,
    )
    return await _visually_select(context, identity, current)


async def _visually_select(
    context: Any, identity: str, storyboard: dict[str, Any],
) -> dict[str, Any]:
    if (
        context.opts.get("visual_storyboard_review", True) is not True
        or storyboard.get("selected_by") == "native-image-layout-reviewer-v1"
    ):
        return storyboard
    await context.host._emit(context.run, "figure_storyboard_visual_review_started", {
        "node_id": "figure", "asset_id": identity,
        "candidate_ids": [item["id"] for item in storyboard["candidates"]],
    })
    try:
        reviewed = await visually_select_storyboard(
            context.project_path, identity, storyboard,
        )
    except Exception as error:
        await context.host._emit(context.run, "figure_storyboard_visual_review_degraded", {
            "node_id": "figure", "asset_id": identity,
            "error": f"{type(error).__name__}: {error}"[:500],
            "fallback_selected_id": storyboard["selected_id"],
        })
        return storyboard
    await context.host._emit(context.run, "figure_storyboard_visual_review_completed", {
        "node_id": "figure", "asset_id": identity,
        "selected_id": reviewed["selected_id"],
        "trace_path": reviewed.get("visual_review_trace_path", ""),
    })
    return reviewed


def _model_composed_instructions(
    asset: dict[str, Any], identity: str, selected: dict[str, Any], recovery: str,
) -> str:
    return (
        f"Create only `{identity}` as one complete model-composed editable SVG; "
        "never touch a sibling figure. Call prepare_model_svg_draft first. "
        "You own all visible text, arrows, equations, spacing, and layout. Do not "
        "call prepare_figure_svg_canvas or any canvas primitive tool.\n\n"
        + _blueprint_contract_guidance()
        + _active_mechanism_guidance(asset)
        + f"Source-bound composition brief:\n{json.dumps(selected, ensure_ascii=False, indent=2)}\n\n"
        + recovery
        + "Design one compact composition directly from this source-bound brief; "
        "do not spend a separate model session generating layout alternatives. "
        "Use at most three complete submissions in this session (initial, local "
        "repair, targeted visual repair). Preserve the best staged draft if the "
        "last review remains blocked. Keep no more objects than the five-second "
        "reading goal needs. For a method overview, show named relations and "
        "their input/output ports, not a full decoder, target-generation, or "
        "audit dashboard. Move suboperator details to the caption unless the "
        "figure's focal claim needs them; if you draw a suboperator, every "
        "necessary target and loss path must be explicit. "
        "Show an optional mechanism as active only when declared source files "
        "confirm it is configured and enabled. An unset joint head or zero "
        "joint loss weight must not become an active joint-objective/GRL "
        "branch; a separately declared frozen-downstream probe may still be "
        "shown after encoder training. If sources "
        "contradict the proposed scientific scene, report the conflict rather "
        "than inventing an active mechanism. "
        "Submit the whole source, blueprint, and explicit element_mappings with "
        "submit_model_svg_draft. Mapping element_id values must be primitive/group "
        "ids you actually drew, and source_path values must come from prepare's "
        "mapping_candidates; candidates are choices, not a checklist. Repair review "
        "findings by editing and resubmitting the complete SVG. Runtime validation "
        "must never rebuild or reposition the model-owned composition.\n\n"
        f"Mandatory portfolio boundary: {_layout_scope(asset)}\n\n"
        f"Authoritative projected scientific subscene:\n{_semantic_contract(asset)}\n\n"
        "Read only source paths declared by prepare_model_svg_draft. Excluded entities "
        "belong to companion figures or the caption."
    )


def _hybrid_canvas_instructions(
    asset: dict[str, Any], identity: str, selected: dict[str, Any], recovery: str,
) -> str:
    return (
        f"Create only `{identity}`; never touch a sibling figure. Use this selected "
        f"storyboard:\n{json.dumps(selected, ensure_ascii=False, indent=2)}\n\n"
        + recovery
        + "Materialize each storyboard connection as a scientific route, not merely "
        + "a label or a stub. Main routes must visibly enter their target mechanism "
        + "or synthesis; constraint and side-output routes remain subordinate. "
        + "Treat structured review findings as an ownership contract. Replace canvas "
        + "primitives only for target_layer=glyph and listed target_ids. For runtime "
        + "findings, refresh deterministic layers once and re-review. Rebuild the "
        + "canvas for planner or scientific_contract findings.\n\n"
        + f"Mandatory portfolio boundary: {_layout_scope(asset)}\n\n"
        + f"Authoritative projected scientific subscene:\n{_semantic_contract(asset)}\n\n"
        + "Read only source paths named by projected entities; excluded entities must "
        + "not become primary visual regions."
    )


async def _illustrate_asset(
    context: Any, asset: dict[str, Any], identity: str, backend: str,
    skill: str, selected: dict[str, Any], invoke_skill: Any,
    *, repair_attempt: bool = False,
) -> None:
    delegate_role = "illustration-repair" if repair_attempt else "illustration"
    await context.host._emit(context.run, "figure_asset_delegate_started", {
        "node_id": "figure", "asset_id": identity,
        "delegate_role": delegate_role, "skill": skill,
        "storyboard_id": selected["id"],
    })
    staged = (
        Path(context.project_path) / ".merak" / "figure-drafts"
        / identity / f"{identity}.svg"
    )
    model_composed = (
        str(asset.get("production_strategy") or "") == "model_composed_full_svg"
        and asset.get("full_svg_authority") is True
    )
    recovery = (
        "The previous illustration session ended without an accepted current "
        "artifact. This is the single bounded completion attempt: keep the selected "
        "storyboard and scientific boundary, use the exact typed blueprint vocabulary "
        "below, and complete submission, diagnostics, visual review, and generation. "
        "Do not create a sibling or bypass any review.\n\n"
        if repair_attempt else ""
    )
    recovery += _draft_review_guidance(context.project_path, identity)
    if current_draft_matches_storyboard(context.project_path, identity):
        relative = staged.relative_to(Path(context.project_path)).as_posix()
        recovery += (
            f"A staged SVG exists at `{relative}`. Do not use an older canonical SVG. "
            + (
                "Read its saved visual-blueprint, review this exact full SVG, and repair "
                "the complete source with submit_model_svg_draft before generation.\n\n"
                if model_composed else
                f"Do not read or submit `figures/{identity}.svg`; submit this staged "
                "source first and repair it only if current validation fails.\n\n"
            )
        )
    prompt = (
        _model_composed_instructions(asset, identity, selected, recovery)
        if model_composed else
        _hybrid_canvas_instructions(asset, identity, selected, recovery)
    )
    await invoke_skill(
        skill, prompt, project_path=context.project_path,
        parent_context="skill-chain:paper-figure", workflow_node_id="figure",
        max_iterations=24 if model_composed else 52,
        max_tokens=16384 if model_composed else 8192,
        tool_call_limits={
            "submit_model_svg_draft": 3,
            "review_figure_svg_composition": 2,
        } if model_composed else None,
        on_event=lambda event: _relay(context, identity, delegate_role, event),
    )


async def _reserve_asset_attempt(
    context: Any, asset: dict[str, Any], root: Path,
) -> DelegateAttempt:
    identity = str(asset["id"])
    attempt = begin_delegate_attempt(
        root, str(context.run.id), asset,
        manual_resume_id=str((context.opts or {}).get("_manual_resume_id") or "")
        if (context.opts or {}).get("_manual_resume_node") == "figure" else "",
        user_feedback=str(
            ((context.opts or {}).get("_figure_revision_scoped_feedback") or {}).get(identity) or ""
        ),
    )
    if attempt.allowed:
        return attempt
    prior = attempt.last_error or "prior delegate did not reach acceptance"
    review = attempt.last_guidance.strip()
    await context.host._emit(context.run, "figure_asset_delegate_retry_deferred", {
        "node_id": "figure", "asset_id": identity,
        "reason": "unchanged input and code after an unaccepted model attempt",
        "last_error": prior[:1000], "review_guidance": review[:1600],
    })
    raise FigureRetryDeferred(
        f"automatic model redraw deferred for {identity}: {prior}"
        + (f"; previous review: {review[:500]}" if review else "")
    )


async def _draw_asset(
    context: Any, asset: dict[str, Any], root: Path,
    backend: str, skill: str, invoke_skill: Any,
) -> None:
    identity = str(asset["id"])
    model_composed = (
        str(asset.get("production_strategy") or "") == "model_composed_full_svg"
        and asset.get("full_svg_authority") is True
    )
    if model_composed:
        selected = {
            "id": "source-bound-direct-v1",
            "scientific_question": str(asset.get("scientific_question") or ""),
            "reading_goal": str(asset.get("reading_goal") or ""),
            "content_boundary": str(asset.get("content_boundary") or ""),
        }
    else:
        storyboard = await _plan_storyboard(context, asset, identity, root, invoke_skill)
        selected = next(
            item for item in storyboard["candidates"]
            if item["id"] == storyboard["selected_id"]
        )
    await _illustrate_asset(
        context, asset, identity, backend, skill, selected, invoke_skill,
    )
    if not _accepted_entry(root, asset):
        raise RuntimeError(
            "figure delegate finished without an accepted current artifact after "
            f"its single bounded session: {identity}"
        )
    await context.host._emit(context.run, "figure_asset_delegate_completed", {
        "node_id": "figure", "asset_id": identity, "skill": skill,
        "storyboard_id": selected["id"],
    })


async def _process_asset(
    context: Any, asset: dict[str, Any], root: Path, invoke_skill: Any,
) -> None:
    identity = str(asset["id"])
    backend = str(asset.get("recommended_backend") or "").strip().casefold()
    skill = str(asset.get("recommended_skill") or BACKEND_SKILLS.get(backend, "")).strip().lstrip("/")
    if not skill:
        raise RuntimeError(f"figure asset {identity} has no supported drawing skill")
    if _accepted_entry(root, asset):
        await context.host._emit(context.run, "figure_asset_delegate_reused", {
            "node_id": "figure", "asset_id": identity, "skill": skill,
        })
        return
    attempt = await _reserve_asset_attempt(context, asset, root)
    try:
        await _draw_asset(context, asset, root, backend, skill, invoke_skill)
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        try:
            record_delegate_failure(
                root, str(context.run.id), identity, attempt.attempt_id,
                error=detail,
                guidance=_draft_review_guidance(context.project_path, identity),
            )
        except (OSError, UnicodeError, ValueError) as state_error:
            raise RuntimeError(
                f"{detail}; delegate budget persistence failed: "
                f"{type(state_error).__name__}: {state_error}"
            ) from state_error
        raise


async def run_figure_asset_delegates(context: Any) -> str | None:
    """Generate model-owned figures while preserving failed-asset hard gates."""
    if context.node.id != "figure":
        return None
    assets = _model_assets(context)
    if not assets:
        # The figure gate owns deterministic producers. Skip an otherwise
        # redundant model session; the gate will still require real artifacts.
        return "Planned figure assets use deterministic producers"
    from ..agent.tools.skill_tool import invoke_skill

    root = Path(context.project_path).expanduser().resolve()
    completed: list[str] = []
    for asset in assets:
        identity = str(asset["id"])
        try:
            await _process_asset(context, asset, root, invoke_skill)
            completed.append(identity)
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            await context.host._emit(context.run, "figure_asset_delegate_failed", {
                "node_id": "figure", "asset_id": identity,
                "error": detail[:1000], "completed_assets": list(completed),
            })
            raise  # Preserve completed assets; later assets wait for manual continuation.
    return "Generated and independently accepted figure assets: " + ", ".join(completed)
