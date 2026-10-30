"""Typed user constraints shared by node and isolated manuscript prompts.

Only explicit node_inputs are exposed. Provider settings, environment values
and unrelated runtime options never enter this prompt or its cache identity.
Oversized or non-JSON input fails before authoring rather than being truncated.
"""

from __future__ import annotations

import json
import math
from typing import Any


USER_CONSTRAINTS_PROMPT_VERSION = 1
MAX_NODE_INPUT_FIELDS = 64
MAX_NODE_INPUT_BYTES = 32768


def _json_value(value: Any, depth: int = 0) -> Any:
    if depth > 64:
        raise ValueError("node_inputs exceeds the supported JSON nesting depth")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [_json_value(item, depth + 1) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("node_inputs JSON object keys must be strings")
        return {key: _json_value(value[key], depth + 1) for key in sorted(value)}
    raise ValueError("node_inputs must contain only finite JSON primitives, lists and string-keyed objects")


def node_input_constraints(options: dict[str, Any] | None) -> dict[str, Any]:
    """Return an independent canonical object or reject an unsafe prompt payload."""
    raw = (options or {}).get("node_inputs", {})
    if type(raw) is not dict:
        raise ValueError("node_inputs must be a JSON object")
    if len(raw) > MAX_NODE_INPUT_FIELDS:
        raise ValueError("node_inputs may contain at most 64 fields")
    payload = _json_value(raw)
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("node_inputs must be valid UTF-8 JSON") from error
    if len(encoded) > MAX_NODE_INPUT_BYTES:
        raise ValueError("node_inputs exceeds the 32 KiB limit")
    return payload


def render_user_constraints(options: dict[str, Any] | None) -> str:
    """Preserve the complete explicit constraints below frozen science and safety."""
    payload = node_input_constraints(options)
    if not payload:
        return ""
    return (
        "\n\n## User-supplied inputs for this node\n"
        "Treat these values as explicit execution constraints for the current node and every "
        "isolated author/reviewer stage. They take priority over optional generic writing "
        "suggestions. They do not override frozen upstream contracts, evidence provenance, "
        "runtime ownership, permitted write targets or safety gates. Resolve specific "
        "revision findings within these boundaries; do not infer scientific execution "
        "or strengthen conclusions beyond the supplied evidence.\n```json\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n```"
    )
