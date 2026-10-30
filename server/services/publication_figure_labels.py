"""Typed publication labels for scientific figures.

Visible scientific notation and implementation provenance are separate. Source
symbols may explain where a mathematical label comes from, but cannot become
visible merely because their spelling resembles a formula.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


PUBLICATION_LABEL_SCHEMA = 1
PUBLICATION_LABEL_KINDS = frozenset({"concept", "math", "metric"})
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_BARE_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)%?$")


def concept_labels(
    values: Iterable[Any], *, namespace: str, kind: str = "concept", limit: int = 6,
) -> list[dict[str, Any]]:
    """Create current-schema public labels from already publication-facing text."""
    if kind not in {"concept", "metric"}:
        raise ValueError(f"unsupported generated publication label kind: {kind}")
    labels, seen = [], set()
    for value in values:
        text = " ".join(str(value or "").replace("_", " ").split()).strip()
        key = text.casefold()
        if not text or key in seen or _BARE_NUMBER_RE.fullmatch(text):
            continue
        seen.add(key)
        labels.append({
            "schema": PUBLICATION_LABEL_SCHEMA,
            "id": f"{namespace}.{len(labels) + 1}",
            "kind": kind,
            "display_text": text,
        })
        if len(labels) >= limit:
            break
    return labels


def validate_publication_labels(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate labels without translating strings or alternate field names."""
    if not isinstance(value, list) or not value:
        return [], ["publication_labels must be a non-empty list"]
    labels, issues, seen = [], [], set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            issues.append(f"publication_labels[{index}] must be an object")
            continue
        label = dict(raw)
        label_id = str(label.get("id") or "").strip()
        kind = str(label.get("kind") or "").strip().casefold()
        display = " ".join(str(label.get("display_text") or "").split()).strip()
        if label.get("schema") != PUBLICATION_LABEL_SCHEMA:
            issues.append(f"publication_labels[{index}] has unsupported schema")
        if not _ID_RE.fullmatch(label_id) or label_id in seen:
            issues.append(f"publication_labels[{index}] requires a unique stable id")
        else:
            seen.add(label_id)
        if kind not in PUBLICATION_LABEL_KINDS:
            issues.append(f"publication_labels[{index}] has unsupported kind: {kind}")
        if not display or _BARE_NUMBER_RE.fullmatch(display):
            issues.append(
                f"publication_labels[{index}] requires meaningful display_text, not a bare number"
            )
        if kind == "math" and not str(label.get("display_math") or "").strip():
            issues.append(f"publication_labels[{index}] math label requires display_math")
        if kind == "math" and "_" in display:
            issues.append(
                f"publication_labels[{index}] math display_text must reflect rendered SVG text, not source-style underscore notation"
            )
        labels.append(label)
    return labels, issues


def publication_label_texts(value: Any) -> list[str]:
    labels, issues = validate_publication_labels(value)
    if issues:
        return []
    return [str(item["display_text"]).strip() for item in labels]


def math_label_texts(value: Any) -> dict[str, str]:
    """Return id-to-visible-text for explicitly declared mathematical labels."""
    labels, issues = validate_publication_labels(value)
    if issues:
        return {}
    return {
        str(item["id"]): str(item["display_text"])
        for item in labels if item.get("kind") == "math"
    }


def mask_typed_math_text(source_text: str, raw_svg: str, labels: Any) -> str:
    """Exclude only exact, typed SVG math nodes from code-token scanning."""
    masked = source_text
    for label_id, display in math_label_texts(labels).items():
        pattern = re.compile(
            r"<text\b(?=[^>]*\bdata-label-kind=[\"']math[\"'])"
            rf"(?=[^>]*\bdata-label-id=[\"']{re.escape(label_id)}[\"'])[^>]*>"
            r"(?P<body>.*?)</text>",
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(raw_svg):
            visible = " ".join(re.sub(r"<[^>]+>", "", match.group("body")).split())
            if visible == display:
                masked = masked.replace(display, " mathematical-notation ", 1)
    return masked
