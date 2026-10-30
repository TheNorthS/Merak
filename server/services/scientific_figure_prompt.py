"""Contribution-driven authoring instructions; no universal paper layout."""

from typing import Any
import json
from pathlib import Path


def _mandatory_regeneration_ids(project_path: str, targets: list[dict[str, Any]]) -> list[str]:
    manifest = Path(project_path) / "figures" / "FIGURE_MANIFEST.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    entries = {
        str(item.get("id") or ""): item
        for item in payload.get("figures", []) if isinstance(item, dict)
    } if isinstance(payload, dict) else {}
    required = []
    for target in targets:
        asset_id = str(target.get("id") or "")
        entry = entries.get(asset_id, {})
        metadata = entry.get("metadata") if isinstance(entry, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        review = metadata.get("independent_visual_review")
        review = review if isinstance(review, dict) else {}
        if review.get("protocol") != "native-image-v1":
            required.append(asset_id)
    return [asset_id for asset_id in required if asset_id]


def _figure_targets(asset_plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in asset_plan.get('assets', []) if item.get('kind') == 'figure'
            and item.get('producer_kind') == 'model' and item.get('generation_policy') != 'skip']


def _target_summaries(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: item.get(key) for key in (
        'id', 'figure_type', 'narrative_level', 'scientific_question',
        'scientific_role', 'content_boundary', 'claim_ids', 'source_data',
        'scientific_scene', 'layout_plan', 'scene_contract', 'publication_labels',
        'publication_language', 'recommended_backend', 'recommended_skill',
        'caption', 'label', 'manuscript_section',
    )} for item in targets]


_AUTHORING_RULES = """\
The current renderer skill is already loaded for this invocation; do not invoke
Skill recursively. Every generate_figure call uses exactly the assigned id as
artifact_name and copies its scientific metadata, caption, public labels and
source data. For generated images, use the declared image skill and persist its
hash-bound review trace. Deterministic/reuse assets are runtime-owned; never
edit their source or create replacement IDs. Do not generate numerical
observations or a quantitative plot unless its declared machine-readable
evidence exists and is valid.

Scientific structure comes from scientific_scene.objects and .relations. Code
symbols/path references are invisible provenance, not visible nodes. Preserve
declared data, causal, control, containment, feedback and logical distinctions.
Use stable SVG group IDs and element_mappings to the declared source references.
Show actual scientific operations with domain-specific glyphs, not repeated
cards. Publication names and typed mathematical labels are mandatory.

Construct the schema-1 visual_blueprint required by the loaded skill. It must
use at least three domain-native visual forms and every primitive id must exist
as an SVG group. A text card is not a scientific primitive. Method overview,
mechanism detail, and evaluation design own separate questions; never merge
them merely because they share source material.

Follow the contribution-selected figure_type, layout_plan topology,
content_boundary, and scene_contract. Reference papers establish visual quality, never a copied template. There is no fixed canvas, domain icon set,
header, or evaluation band. Partition excess detail according to
layout_plan.panel_contracts and branch_partitions. Repeat only declared context
and move cross_panel_relations to companion panels or the caption. Never shrink
labels below minimum_placed_font_pt, duplicate the caption as a long header, or
route connectors through text.

For method_architecture, keep primary groups within the scene_contract budget
and show the input-to-output scientific path. For evaluation_design, show the
registered isolation and decision chain. Every visible group maps to a real
source component; do not invent implementation names.

For rich SVG use begin/append/finalize draft tools, then submit the returned
source_path with model-authored-svg-v1. The runtime validates groups, renders
same-source PDF/PNG, and sends PNG to Reviewer. Use the output budget for actual
operations, not a shallow card sketch. Other backends submit native source.
Repair failures on the same semantic asset; never bypass validation or rename
the asset. Verify the manifest after every assigned target is rendered. A plan
or promise is not completion. Do not open editor tabs.
"""


def figure_authoring_prompt(
    project_path: str, direction: str, asset_plan: dict[str, Any], inventory: str,
) -> str:
    targets = _figure_targets(asset_plan)
    summaries = _target_summaries(targets)
    mandatory = _mandatory_regeneration_ids(project_path, targets)
    header = f"""Author only the assigned publication assets from the current contracts.

Project: {project_path}
Research direction: {direction}
Existing inputs:
{inventory}

Current runtime-owned FIGURE_SPECS.json is schema 4 with publication_label_schema 1.
Read it; never Write/Edit its schema or list. Do not replace SCIENTIFIC_ASSET_PLAN.
The model-owned targets are:
{json.dumps(summaries, ensure_ascii=False, indent=2)}

Assets that MUST call generate_figure in this invocation because no current,
hash-bound native-image acceptance exists: {json.dumps(mandatory, ensure_ascii=False)}
An existing SVG/PNG/PDF is input for improvement, not completion, for every ID
in that list. Do not finish the skill until each listed ID has a successful
generate_figure result or the tool's bounded repair budget is exhausted.
"""
    return header + "\n" + _AUTHORING_RULES
