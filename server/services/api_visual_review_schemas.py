"""Strict JSON response contracts for native-vision review."""

from __future__ import annotations

from typing import Any


REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 1, "maximum": 10},
        "verdict": {
            "type": "string",
            "enum": ["ready", "almost", "needs_work", "major_revision"],
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
        "visual_review": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "minLength": 1},
                "figure_quality": {"type": "string", "minLength": 1},
                "caption_alignment": {"type": "string", "minLength": 1},
                "page_layout": {"type": "string", "minLength": 1},
                "table_formatting": {"type": "string", "minLength": 1},
                "visual_consistency": {"type": "string", "minLength": 1},
            },
            "required": [
                "pdf_path", "figure_quality", "caption_alignment",
                "page_layout", "table_formatting", "visual_consistency",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "score", "verdict", "strengths", "weaknesses", "action_items",
        "visual_review",
    ],
    "additionalProperties": False,
}


FIGURE_REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 1, "maximum": 10},
        "verdict": {"type": "string", "enum": ["accept", "refine"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvement_prompt": {"type": "string"},
        "checklist": {
            "type": "object",
            "properties": {
                "arrow_correctness": {"type": "boolean"},
                "block_content": {"type": "boolean"},
                "arrow_visibility": {"type": "boolean"},
                "arrow_labels": {"type": "boolean"},
                "visual_appeal": {"type": "boolean"},
                "layout_flow": {"type": "boolean"},
                "style_compliance": {"type": "boolean"},
                "text_readability": {"type": "boolean"},
                "no_visual_artifacts": {"type": "boolean"},
            },
            "required": [
                "arrow_correctness", "block_content", "arrow_visibility",
                "arrow_labels", "visual_appeal", "layout_flow",
                "style_compliance", "text_readability", "no_visual_artifacts",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "score", "verdict", "issues", "strengths", "improvement_prompt",
        "checklist",
    ],
    "additionalProperties": False,
}


RICH_SVG_CHECKS = (
    "five_second_comprehension", "scientific_mechanism_clarity",
    "domain_specific_visual_encoding", "focal_hierarchy",
    "causal_flow", "balanced_composition", "label_economy",
    "paper_scale_readability", "no_generic_card_wall",
    "no_visual_artifacts",
)

RICH_SVG_HARD_CHECKS = (
    "five_second_comprehension", "scientific_mechanism_clarity",
    "causal_flow", "paper_scale_readability", "no_visual_artifacts",
)


OWNED_VISUAL_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_layer": {
            "type": "string",
            "enum": ["planner", "runtime", "glyph", "scientific_contract"],
        },
        "target_ids": {"type": "array", "items": {"type": "string"}},
        "severity": {"type": "string", "enum": ["blocker", "advisory"]},
        "message": {"type": "string", "minLength": 1},
        "repair_action": {"type": "string", "minLength": 1},
    },
    "required": [
        "target_layer", "target_ids", "severity", "message", "repair_action",
    ],
    "additionalProperties": False,
}


RICH_SVG_REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 1, "maximum": 10},
        "verdict": {"type": "string", "enum": ["accept", "refine"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": OWNED_VISUAL_FINDING_SCHEMA},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvement_prompt": {"type": "string"},
        "checklist": {
            "type": "object",
            "properties": {key: {"type": "boolean"} for key in RICH_SVG_CHECKS},
            "required": list(RICH_SVG_CHECKS),
            "additionalProperties": False,
        },
    },
    "required": [
        "score", "verdict", "issues", "findings", "strengths",
        "improvement_prompt", "checklist",
    ],
    "additionalProperties": False,
}
