"""Losslessly reference repeated JSON containers in model evidence, never in source files."""

from collections import defaultdict
import json


_MARKER = b"@MERAK_JSON_BLOCK_"
_MINIMUM = 1024


def _containers(raw: bytes) -> dict[bytes, list[tuple[int, int]]]:
    """Locate exact container tokens, including duplicate keys and original numeric spelling."""
    groups = defaultdict(list)
    stack, quoted, escaped = [], False, False
    for index, char in enumerate(raw):
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (123, 91):
            stack.append(index)
        elif char in (125, 93):
            start = stack.pop()
            if index + 1 - start >= _MINIMUM:
                groups[raw[start:index + 1]].append((start, index + 1))
    return groups


def reference_repeated_json(raw: bytes) -> bytes:
    """Return complete length-framed blocks plus a body, or the unchanged JSON if not smaller.

    Only exact repeated object/array bytes are shared. Non-overlapping substitutions
    keep definitions literal (no recursive references); original source hashes stay
    the caller's responsibility. Invalid inputs and reserved-token collisions pass
    through unchanged, so the encoder cannot misinterpret an existing source token.
    """
    if _MARKER in raw:
        return raw
    try:
        json.loads(raw)
    except (UnicodeError, ValueError, RecursionError):
        return raw
    groups = [(block, spans) for block, spans in _containers(raw).items() if len(spans) > 1]
    groups.sort(key=lambda item: len(item[0]) * (len(item[1]) - 1), reverse=True)
    replacements, blocks = [], []
    for block, spans in groups:
        available = [(start, end) for start, end in spans if not any(
            start < used_end and end > used_start for used_start, used_end, _ in replacements)]
        if len(available) < 2:
            continue
        token = _MARKER + str(len(blocks)).encode("ascii") + b"@"
        blocks.append((token, block))
        replacements.extend((start, end, token) for start, end in available)
    if not blocks:
        return raw
    body, cursor = [], 0
    for start, end, token in sorted(replacements):
        body.extend((raw[cursor:start], token))
        cursor = end
    body.append(raw[cursor:])
    parts = [b"LOSSLESS_JSON_BLOCKS_V1\n"
             b"Interpret BODY by replacing each @MERAK_JSON_BLOCK_N@ token with its exact BLOCK JSON.\n"
             b"Every block is complete literal JSON, with no recursive references. No fields are omitted.\n"
             b"The following byte counts frame UTF-8 content; these markers are encoding, not source fields.\n"]
    for token, block in blocks:
        parts.extend((b"BLOCK " + token + b" " + str(len(block)).encode("ascii") + b"\n", block, b"\n"))
    parts.extend((b"BODY\n", *body))
    encoded = b"".join(parts)
    return encoded if len(encoded) < len(raw) else raw
