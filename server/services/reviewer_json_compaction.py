"""Compact JSON whitespace without parsing numbers or changing any source token."""

import json
from pathlib import Path


def compact_json_evidence(relative: str, raw: bytes) -> bytes:
    if Path(relative).suffix.casefold() != ".json":
        return raw
    try:
        text = raw.decode("utf-8-sig")
        json.loads(text)
    except (UnicodeError, ValueError):
        return raw
    output, quoted, escaped = [], False, False
    for char in text:
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            output.append(char)
        elif char not in " \t\r\n":
            output.append(char)
    return "".join(output).encode("utf-8")
