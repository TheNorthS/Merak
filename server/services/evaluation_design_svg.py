"""Source-bound deterministic evaluation diagram and paper-scale geometry."""

from __future__ import annotations

import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from .evaluation_design_contract import is_heldout_split
from .evaluation_design_content import EvaluationContent, evaluation_content as _evaluation_content
from .publication_figure_labels import concept_labels, validate_publication_labels


@dataclass(frozen=True)
class EvaluationRows:
    lanes: str
    split_tracks: str
    arrows: str
    contrasts: str
    bottom: int
    identities: tuple[str, ...]


def _publication_labels(
    metadata: dict[str, Any], content: EvaluationContent,
) -> tuple[list[dict[str, Any]], list[str]]:
    test_title = "Held-out test" if is_heldout_split(content.primary_split) else "Evaluation split"
    removal_label = "Declared removal" if content.declared_conditions else "Matched removal"
    defaults = [content.focal_name,
                removal_label if content.removal_conditions else content.comparator_name,
                test_title]
    raw_labels = metadata.get("publication_labels") or concept_labels(
        defaults, namespace="evaluation.term", limit=3,
    )
    labels, issues = validate_publication_labels(raw_labels)
    if issues:
        raise ValueError("evaluation_design publication label contract failed: " + "; ".join(issues))
    brief = metadata.get("design_brief")
    brief = brief if isinstance(brief, dict) else {}
    required = [" ".join(str(value or "").split()) for value in brief.get("must_show") or []
                if str(value or "").strip()]
    visible = list(dict.fromkeys(required + [str(item["display_text"]) for item in labels]))
    if any(re.match(r"^[Mm]\d+\s", value) for value in visible):
        raise ValueError(
            "evaluation_design public labels contain internal mechanism IDs; "
            "regenerate the source figure specification"
        )
    if not content.removal_conditions and any("removal" in value.casefold() for value in visible):
        raise ValueError(
            "evaluation_design public labels require a removal absent from the source contract"
        )
    return labels, visible


def _source_paths(metadata: dict[str, Any]) -> list[str]:
    sources = [
        str(value).strip().replace("\\", "/")
        for value in (*(metadata.get("source_data") or []), *(metadata.get("source_artifacts") or []))
        if str(value or "").strip()
    ]
    scene = metadata.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    sources.extend(
        str(item.get("source_path") or "").strip().replace("\\", "/")
        for item in scene.get("objects") or []
        if isinstance(item, dict) and str(item.get("source_path") or "").strip()
    )
    return list(dict.fromkeys(sources)) or [
        "experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json",
    ]


def _text(x: int, y: int, value: str, *, size: int = 22,
          weight: int = 400, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-family="Helvetica,Arial,sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="#17324d">{html.escape(str(value), quote=True)}</text>'
    )


def _text_width(value: str, size: int = 22) -> float:
    # MuPDF's Helvetica reports near-zero width for missing CJK glyphs.
    import fitz

    measured = fitz.get_text_length(value, fontname="helv", fontsize=size)
    conservative = sum(
        size if unicodedata.east_asian_width(character) in {"W", "F"}
        else size * 0.7 if ord(character) > 127 else
        fitz.get_text_length(character, fontname="helv", fontsize=size)
        for character in value
    )
    return max(measured, conservative)


def _split_wide_word(word: str, max_width: int, size: int) -> list[str]:
    pieces = []
    while _text_width(word, size) > max_width:
        cut = max(index for index in range(1, len(word) + 1)
                  if _text_width(word[:index], size) <= max_width)
        hyphen = word.rfind("-", 1, cut + 1)
        if hyphen >= 2:
            cut = hyphen + 1
        pieces.append(word[:cut])
        word = word[cut:]
    return [*pieces, word] if word else pieces


def _wrap_label(value: str, max_width: int, *, size: int = 22) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in " ".join(str(value).split()).split():
        candidate = f"{current} {word}" if current else word
        if _text_width(candidate, size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        pieces = _split_wide_word(word, max_width, size)
        lines.extend(pieces[:-1])
        current = pieces[-1]
    return [*lines, current] if current else lines


def _condition_specs(
    content: EvaluationContent,
) -> list[tuple[str, str, str, str, str, str]]:
    if content.declared_conditions:
        specs = [(
            f"eval_declared_condition_{index}", "Declared condition", name,
            content.endpoint_label, "#eaf2ff", "#2563eb",
        ) for index, name in enumerate(content.declared_conditions, start=1)]
        for index, removal in enumerate(content.removal_conditions, start=1):
            if removal in content.declared_conditions:
                continue
            identity = "eval_removed_condition" if len(content.removal_conditions) == 1 else f"eval_removed_condition_{index}"
            specs.append((identity, "Declared removal", removal,
                          content.endpoint_label, "#fff0e5", "#c65d25"))
        return specs
    prefix = "Intact" if content.has_mechanism else "Focal"
    specs = [(
        "eval_intact_condition",
        "Intact mechanism" if content.has_mechanism else "Focal condition",
        content.focal_name, f"{prefix} reference", "#e4f5f1", "#16806a",
    )]
    for index, removal in enumerate(content.removal_conditions, start=1):
        identity = (
            "eval_removed_condition" if len(content.removal_conditions) == 1
            else f"eval_removed_condition_{index}"
        )
        specs.append((identity, "Matched removal", removal,
                      f"{prefix} vs {removal}", "#fff0e5", "#c65d25"))
    specs.append(("eval_nuisance_condition", "Alternative control",
                  content.comparator_name, f"{prefix} vs {content.comparator_name}",
                  "#eaf2ff", "#2563eb"))
    for index, control in enumerate(content.secondary_controls, start=1):
        specs.append((f"eval_secondary_condition_{index}", "Declared control", control,
                      f"{prefix} vs {control}", "#eaf2ff", "#2563eb"))
    return specs


def _condition_card(
    identity: str, title: str, lines: list[str], y: int, height: int,
    fill: str, stroke: str,
) -> str:
    return (
        f'<g id="{identity}">'
        f'<rect x="36" y="{y}" width="440" height="{height}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        + _text(54, y + 28, title, size=22, weight=700)
        + "".join(_text(54, y + 62 + 30 * row, line, size=22)
                  for row, line in enumerate(lines))
        + "</g>"
    )


def _contrast_card(
    identity: str, lines: list[str], y: int, height: int,
    fill: str, stroke: str,
) -> str:
    baseline = y + height // 2 + 8 - 27 * (len(lines) - 1) // 2
    return (
        f'<g id="{identity.replace("condition", "contrast")}">'
        f'<rect x="804" y="{y}" width="360" height="{height}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        + "".join(_text(984, baseline + 27 * row, line, size=22, anchor="middle")
                  for row, line in enumerate(lines))
        + "</g>"
    )


def _condition_rows(content: EvaluationContent, top: int) -> EvaluationRows:
    lanes, removals, tracks, arrows, contrasts, identities = [], [], [], [], [], []
    y = top
    for identity, title, detail, comparison, fill, stroke in _condition_specs(content):
        detail_lines = _wrap_label(detail, 400)
        comparison_lines = _wrap_label(comparison, 324)
        split_lines = [
            line for split in content.declared_splits
            for line in _wrap_label(split["display_name"], 194)
        ] or _wrap_label(content.primary_split, 194)
        height = max(84, 84 + 30 * (len(detail_lines) - 1),
                     32 + 27 * (len(comparison_lines) - 1),
                     32 + 27 * (len(split_lines) - 1))
        card = _condition_card(identity, title, detail_lines, y, height, fill, stroke)
        target = removals if identity.startswith("eval_removed") else lanes
        target.append(card)
        contrasts.append(_contrast_card(identity, comparison_lines, y, height, fill, stroke))
        center = y + height // 2
        split_baseline = center + 8 - 27 * (len(split_lines) - 1) // 2
        tracks.append(
            f'<g id="{identity.replace("condition", "split")}">'
            + "".join(_text(640, split_baseline + 27 * row, line, anchor="middle")
                      for row, line in enumerate(split_lines)) + "</g>"
        )
        arrows.append(
            f'<g id="{identity.replace("condition", "path")}">'
            f'<path d="M476 {center}H532 M748 {center}H804" stroke="{stroke}" '
            'stroke-width="3" fill="none" marker-end="url(#evalArrow)"/></g>'
        )
        identities.append(identity)
        y += height + 14
    lanes.extend(
        ['<g id="eval_removed_condition">' + "".join(removals) + "</g>"]
        if len(removals) > 1 else removals
    )
    return EvaluationRows(
        "".join(lanes), "".join(tracks), "".join(arrows),
        "".join(contrasts), y - 14, tuple(identities),
    )


def _protocol_markup(content: EvaluationContent) -> tuple[str, int]:
    isolation = (
        "Subject/session isolation required"
        if content.require_subject_isolation and content.require_session_isolation else
        "Subject isolation required" if content.require_subject_isolation else
        "Session isolation required" if content.require_session_isolation else ""
    )
    requirements = [isolation] if isolation else []
    if content.require_external_group:
        requirements.append("External group required")
    if content.analysis_unit:
        requirements.insert(0, f"Unit: {content.analysis_unit}")
    title = "Held-out test" if is_heldout_split(content.primary_split) else "Evaluation split"
    facts = " · ".join(requirements) if requirements else "Declared source split"
    if content.declared_splits:
        lines = ["Held-out test: separate evaluations"]
        for split in content.declared_splits:
            lines += _wrap_label(split["display_name"], 1080)
        if content.active_holdout_axis:
            lines += _wrap_label(
                "Active execution axis: " + content.active_holdout_axis.replace("_", " "), 1080,
            )
    else:
        lines = _wrap_label(f"{title}: {content.primary_split}", 1080)
    lines += _wrap_label(facts, 1080)
    height = 26 + 27 * len(lines)
    markup = (
        f'<rect x="28" y="86" width="1136" height="{height}" rx="10" '
        'fill="#f2f6fa" stroke="#8293a8" stroke-width="2"/>'
        + "".join(_text(46, 112 + 27 * row, line,
                        weight=700 if row == 0 else 400)
                  for row, line in enumerate(lines))
    )
    return markup, 86 + height


def _label_attributes(label: dict[str, Any] | None) -> str:
    if label is None:
        return ""
    return (
        f' data-label-id="{html.escape(str(label["id"]), quote=True)}"'
        f' data-label-kind="{html.escape(str(label["kind"]), quote=True)}"'
    )


def _extra_labels(
    labels: list[dict[str, Any]], visible: list[str], start: int,
) -> tuple[str, int]:
    parts, y = [], start
    for value in visible:
        label = next((item for item in labels if item["display_text"] == value), None)
        for line in _wrap_label(value, 1080):
            parts.append(
                f'<text{_label_attributes(label)} x="48" y="{y}" '
                'font-family="Helvetica,Arial,sans-serif" font-size="22" '
                f'fill="#17324d">{html.escape(line, quote=True)}</text>'
            )
            y += 27
    return "".join(parts), y


def _bind_publication_labels(svg: str, labels: list[dict[str, Any]]) -> str:
    namespace = "http://www.w3.org/2000/svg"
    ET.register_namespace("", namespace)
    root = ET.fromstring(svg)
    for label in labels:
        value = str(label["display_text"])
        if any(text.get("data-label-id") == label["id"] for text in root.iter(f"{{{namespace}}}text")):
            continue
        for group in reversed(list(root.iter(f"{{{namespace}}}g"))):
            text_nodes = list(group.iter(f"{{{namespace}}}text"))
            joined = " ".join(" ".join((node.text or "").split()) for node in text_nodes)
            if value.casefold() not in joined.casefold():
                continue
            anchor = next((node for node in text_nodes if value.casefold() in " ".join((node.text or "").split()).casefold()), None)
            if anchor is None:
                anchor = next((node for node in text_nodes if node.text and not node.get("data-label-id")), None)
            if anchor is not None:
                anchor.set("data-label-id", str(label["id"]))
                anchor.set("data-label-kind", str(label["kind"]))
                break
        else:
            raise ValueError(f"evaluation_design publication label is not visible: {value}")
    return ET.tostring(root, encoding="unicode")


def _endpoint_markup(
    content: EvaluationContent, labels: list[dict[str, Any]], visible: list[str],
    top: int,
) -> tuple[str, int]:
    endpoint = _wrap_label(content.endpoint_label, 780)
    marker = next((item for item in labels if item["display_text"] == content.endpoint_label), None)
    parts = [_text(48, top + 32, "Primary endpoint", weight=700)]
    parts.extend(
        f'<text{_label_attributes(marker)} x="258" y="{top + 32 + 27 * row}" '
        'font-family="Helvetica,Arial,sans-serif" font-size="22" '
        f'fill="#17324d">{html.escape(line, quote=True)}</text>'
        for row, line in enumerate(endpoint)
    )
    already_visible = (
        *(() if content.declared_conditions else (content.focal_name, content.comparator_name)),
        content.primary_split,
        content.endpoint_label, *content.removal_conditions,
        ("Declared removal" if content.declared_conditions else "Matched removal") if content.removal_conditions else "",
        "Held-out test" if is_heldout_split(content.primary_split) else "Evaluation split",
        *content.declared_conditions,
    )
    extra_values = [value for value in visible if not any(
        value.casefold() in existing.casefold() for existing in already_visible if existing
    )]
    extra_markup, bottom = _extra_labels(labels, extra_values, top + 44 + 27 * len(endpoint))
    height = max(64, bottom - top + 12) if extra_values else max(64, 48 + 27 * len(endpoint))
    frame = (f'<rect x="28" y="{top}" width="1136" height="{height}" rx="10" '
             'fill="#f7f9fc" stroke="#d8e1ec" stroke-width="2"/>')
    return (frame + '<g id="eval_decision_rule">' + "".join(parts)
            + "</g>" + extra_markup, top + height)


def _render_evaluation_svg(
    content: EvaluationContent, rows: EvaluationRows, protocol_markup: str,
    endpoint_markup: str, *, row_top: int, endpoint_bottom: int,
) -> str:
    canvas_height = endpoint_bottom + 20
    heading = ("Reported endpoint" if content.declared_conditions else
               "Paired contrasts" if content.paired_comparison else "Declared contrasts")
    description = (
        "Separately declared conditions are evaluated on each declared holdout; "
        "no primary comparator or combined split is inferred."
        if content.declared_conditions else
        f"Declared comparison conditions pass through the {content.primary_split} split "
        f"and reach the {content.endpoint_label} endpoint."
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{canvas_height}" viewBox="0 0 1200 {canvas_height}" role="img" aria-labelledby="eval-title eval-desc">
<title id="eval-title">Evaluation design for {html.escape(content.focal_name)}</title>
<desc id="eval-desc">{html.escape(description)}</desc>
<metadata id="eval-secondary-controls">{html.escape(json.dumps(content.secondary_controls, ensure_ascii=False))}</metadata>
<metadata id="eval-declared-splits">{html.escape(json.dumps(content.declared_splits, ensure_ascii=False))}</metadata>
<metadata id="eval-declared-conditions">{html.escape(json.dumps(content.declared_conditions, ensure_ascii=False))}</metadata>
<metadata id="eval-protocol-provenance">{html.escape(json.dumps(content.source_bindings, ensure_ascii=False))}</metadata>
<defs><marker id="evalArrow" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto" viewBox="0 0 9 8" markerUnits="userSpaceOnUse"><path d="M0 0L9 4L0 8Z" fill="#40546f"/></marker></defs>
<rect width="1200" height="{canvas_height}" fill="#ffffff"/>
{_text(28, 48, "Evaluation design", size=30, weight=700)}
<g id="eval_group_split">{protocol_markup}{_text(640, row_top - 18, "Evaluation split", weight=700, anchor="middle")}</g>
{_text(40, row_top - 18, "Declared conditions", weight=700)}
{_text(984, row_top - 18, heading, weight=700, anchor="middle")}
<g id="eval_matched_comparisons">{rows.lanes}</g>
<g id="eval_locked_perturbation">{rows.split_tracks}</g>
{rows.arrows}
<g id="eval_paired_contrast">{rows.contrasts}</g>
<g id="eval_publication_labels">{endpoint_markup}</g>
</svg>'''
    return svg


def _evaluation_design_svg(metadata: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Render matched contrasts from the declared mechanism and evaluation source.

    This source renderer preserves publication labels and actual source bindings;
    it does not change user contracts, review acceptance, or model-owned SVGs.
    """
    content = _evaluation_content(metadata)
    labels, visible = _publication_labels(metadata, content)
    protocol_markup, protocol_bottom = _protocol_markup(content)
    row_top = protocol_bottom + 48
    rows = _condition_rows(content, row_top)
    endpoint_markup, endpoint_bottom = _endpoint_markup(
        content, labels, visible, rows.bottom + 16,
    )
    svg = _render_evaluation_svg(
        content, rows, protocol_markup, endpoint_markup,
        row_top=row_top, endpoint_bottom=endpoint_bottom,
    )
    svg = _bind_publication_labels(svg, labels)
    sources = _source_paths(metadata)
    roles = {
        "eval_group_split": "declared source partition and isolation requirements",
        "eval_intact_condition": "intact mechanism condition",
        "eval_nuisance_condition": "declared alternative comparator condition",
        "eval_locked_perturbation": "declared evaluation split",
        "eval_paired_contrast": "declared focal comparisons",
        "eval_decision_rule": "primary reported endpoint",
        "eval_publication_labels": "typed public scientific labels",
    }
    if content.declared_conditions:
        roles.pop("eval_intact_condition")
        roles.pop("eval_nuisance_condition")
        for index in range(1, len(content.declared_conditions) + 1):
            roles[f"eval_declared_condition_{index}"] = "source-declared study condition"
    if content.removal_conditions:
        roles["eval_removed_condition"] = "declared matched removals"
    for index, control in enumerate(content.secondary_controls, start=1):
        roles[f"eval_secondary_condition_{index}"] = f"declared alternative control: {control}"
    if len(content.removal_conditions) > 1:
        for index, removal in enumerate(content.removal_conditions, start=1):
            roles[f"eval_removed_condition_{index}"] = f"declared removal: {removal}"
    method = next((path for path in sources if path.endswith("/METHOD_CONTRACT.json")), sources[0])
    run = next((path for path in sources if path.endswith("/RUN_SPEC.json")), method)
    idea = next((path for path in sources if path.endswith("/SELECTED_IDEA.json")), method)
    bindings = {"eval_group_split": run, "eval_locked_perturbation": run,
                "eval_intact_condition": idea, "eval_publication_labels": idea}
    if content.declared_splits:
        bindings["eval_group_split"] = content.declared_splits[0]["source_path"]
        bindings["eval_locked_perturbation"] = content.declared_splits[0]["source_path"]
    metric_binding = content.source_bindings.get("primary_metric") or {}
    for field, identity in (("focal_condition", "eval_intact_condition"),
                            ("primary_comparator", "eval_nuisance_condition")):
        binding = content.source_bindings.get(field) or {}
        if binding.get("source_path"):
            bindings[identity] = binding["source_path"]
    if metric_binding.get("source_path"):
        bindings["eval_decision_rule"] = metric_binding["source_path"]
    if content.declared_conditions:
        bindings["eval_paired_contrast"] = metric_binding.get("source_path") or run
        for index in range(1, len(content.declared_conditions) + 1):
            bindings[f"eval_declared_condition_{index}"] = content.conditions_source_path
    mappings = [
        {"element_id": identity, "source_path": bindings.get(identity, method),
         "semantic_role": role}
        for identity, role in roles.items()
    ]
    return svg, mappings
