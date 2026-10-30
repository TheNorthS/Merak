"""Blind reader-comprehension probe for publication figures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BLIND_READBACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "five_second_summary": {"type": "string"},
        "inputs": {"type": "array", "items": {"type": "string"}},
        "operations": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "array", "items": {"type": "string"}},
        "directed_relations": {"type": "array", "items": {
            "type": "object", "properties": {
                "from": {"type": "string"}, "to": {"type": "string"},
                "meaning": {"type": "string"},
            }, "required": ["from", "to", "meaning"],
            "additionalProperties": False,
        }},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "blocking_ambiguities": {"type": "array", "items": {"type": "string"}},
        "unreadable_labels": {"type": "array", "items": {"type": "string"}},
        "mechanism_recoverable": {"type": "boolean"},
    },
    "required": [
        "five_second_summary", "inputs", "operations", "outputs",
        "directed_relations", "ambiguities", "blocking_ambiguities", "unreadable_labels",
        "mechanism_recoverable",
    ],
    "additionalProperties": False,
}


async def request_blind_readback(
    root: Path, artifact_id: str, png: Path,
) -> tuple[dict[str, Any], Any]:
    """Ask a fresh reviewer to explain pixels without seeing intended semantics."""
    from .api_visual_reviewer import api_visual_reviewer

    prompt = """You are the first-time reader of the attached scientific figure.
You receive no caption, method description, blueprint, source code, or intended
claim. Inspect only the pixels. State what a researcher can actually recover
within five seconds, then list the directed scientific relations that remain
clear after closer inspection. Do not guess missing semantics from conventions.
If an arrow endpoint, branch input, merge, feedback route, symbol, or label is
ambiguous, record it explicitly. mechanism_recoverable is true only when the
focal scientific story and its depicted directed relations can be explained
from the image alone. Do not require an extra branch, output, or synthesis that
the compact figure does not depict. Also return blocking_ambiguities: only defects
that prevent that focal story or make a scientific relation materially wrong.
Do not mark omitted tensor dimensions, hyperparameter values, acronym
expansions, implementation detail, or exact operator formulas as blocking when
the depicted paper-level mechanism remains unambiguous."""
    response = await api_visual_reviewer.invoke(
        project_path=root, prompt=prompt,
        purpose=f"figure-blind-readback-{artifact_id}",
        schema=BLIND_READBACK_SCHEMA, image_paths=[png],
        timeout_seconds=360.0,
    )
    return json.loads(response.text), response


def blind_readback_issues(
    value: dict[str, Any], *, minimum_relations: int = 3,
) -> list[str]:
    """Convert comprehension failures into deterministic visual findings."""
    issues: list[str] = []
    if value.get("mechanism_recoverable") is not True:
        issues.append("blind reader could not recover the scientific mechanism")
    relations = [item for item in value.get("directed_relations") or [] if isinstance(item, dict)]
    if len(relations) < minimum_relations:
        issues.append(
            f"blind reader recovered only {len(relations)} directed scientific relations; "
            f"at least {minimum_relations} are required"
        )
    blocking = [
        str(item) for item in value.get("blocking_ambiguities") or []
        if str(item).strip()
    ]
    if blocking:
        issues.append("blind-reader blocking ambiguities: " + "; ".join(blocking[:6]))
    unreadable = [str(item) for item in value.get("unreadable_labels") or [] if str(item).strip()]
    if unreadable:
        issues.append("blind-reader unreadable labels: " + "; ".join(unreadable[:6]))
    return issues


def apply_blind_readback_gate(
    review: dict[str, Any], readback: dict[str, Any], issues: list[str],
    *, minimum_relations: int = 3,
) -> None:
    """Prevent an informed editor from scoring above what a blind reader understood."""
    review["blind_readback"] = readback
    review["blind_readback_issues"] = issues
    if not issues:
        return
    relations = [item for item in readback.get("directed_relations") or [] if isinstance(item, dict)]
    blocking = [
        item for item in readback.get("blocking_ambiguities") or []
        if str(item).strip()
    ]
    if readback.get("mechanism_recoverable") is not True or len(relations) < minimum_relations:
        ceiling = 4.0
    elif len(blocking) >= 3:
        ceiling = 5.0
    else:
        ceiling = 6.0
    review["score"] = min(float(review.get("score") or 0.0), ceiling)
    review["verdict"] = "refine"
    checklist = review.get("checklist")
    checklist = checklist if isinstance(checklist, dict) else {}
    for key in ("five_second_comprehension", "scientific_mechanism_clarity", "causal_flow"):
        checklist[key] = False
    review["checklist"] = checklist
    current = [str(item) for item in review.get("issues") or []]
    review["issues"] = list(dict.fromkeys([*issues, *current]))
