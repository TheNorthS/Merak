"""Deterministic manuscript I/O, hashing, and LaTeX text utilities."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text


DISPLAY_MATH_RE = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|"
    r"\\begin\{(?:equation|align|alignat|gather|multline|flalign|"
    r"IEEEeqnarray|displaymath)\*?\}.*?"
    r"\\end\{(?:equation|align|alignat|gather|multline|flalign|"
    r"IEEEeqnarray|displaymath)\*?\}",
    re.DOTALL,
)
CITATION_COMMAND_RE = re.compile(
    r"\\(?:[Cc]ite(?:t|p|alt|alp|author|yearpar|year|num|title)?|"
    r"[Pp]arencite|[Tt]extcite|[Aa]utocite|[Ff]ootcite|footcitetext|smartcite|supercite|fullcite|nocite)\*?"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{([^{}]+)\}",
    re.IGNORECASE,
)
REFERENCE_COMMAND_RE = re.compile(
    r"\\(?:ref|cref|autoref)\*?(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}",
    re.IGNORECASE,
)
REFERENCE_RANGE_RE = re.compile(
    r"\\crefrange\*?(?:\s*\[[^\]]*\])?\s*"
    r"\{([^{}]+)\}\s*\{([^{}]+)\}",
    re.IGNORECASE,
)


def read_text(path: Path, limit: int = 500_000) -> str:
    from .paper_candidate_io import candidate_path
    path = candidate_path(path)
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_owned_state(path: Path) -> dict[str, Any]:
    """Load coordination state without treating corruption as empty state."""

    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise RuntimeError(f"Manuscript state is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Manuscript state root must be an object: {path}")
    return value


def sha256(path: Path) -> str:
    from .paper_candidate_io import candidate_path
    path = candidate_path(path)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def stable_source_hash(path: Path) -> str:
    """Hash semantic JSON content while ignoring builder timestamps."""

    if path.suffix.casefold() != ".json":
        return sha256(path)
    payload = read_json(path)
    if not payload:
        return sha256(path)
    volatile = {
        "generated_at", "updated_at", "created_at", "modified_at",
        "recorded_at", "rendered_at", "timestamp",
    }

    def stable(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): stable(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if str(key) not in volatile
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    content = json.dumps(stable(payload), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def write_text_if_changed(path: Path, content: str) -> None:
    content = content.rstrip() + "\n"
    if read_text(path, len(content) + 1) == content:
        return
    atomic_write_text(path, content)


def strip_tex(text: str) -> str:
    text = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    text = DISPLAY_MATH_RE.sub(" ", text)
    text = CITATION_COMMAND_RE.sub(" ", text)
    text = REFERENCE_RANGE_RE.sub(" ", text)
    text = REFERENCE_COMMAND_RE.sub(" ", text)
    text = re.sub(
        r"\\(?:label|url|href|includegraphics)"
        r"(?:\s*\[[^\]]*\])?\s*\{[^{}]*\}", " ", text,
    )
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    return re.sub(r"[{}~]", " ", text)


def word_count(text: str) -> int:
    plain = strip_tex(text)
    latin_words = len(re.findall(r"\b[A-Za-z][A-Za-z0-9'’-]*\b", plain))
    cjk_characters = len(
        re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", plain)
    )
    return latin_words + (cjk_characters + 1) // 2


def citation_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for group in CITATION_COMMAND_RE.findall(text):
        keys.update(item.strip() for item in group.split(",") if item.strip())
    return keys


def reference_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for group in REFERENCE_COMMAND_RE.findall(text):
        keys.update(item.strip() for item in group.split(",") if item.strip())
    for start, end in REFERENCE_RANGE_RE.findall(text):
        keys.update(item.strip() for item in (start, end) if item.strip())
    return keys


def semantic_artifact_hash(path: Path) -> str:
    if path.suffix.casefold() == ".json":
        return stable_source_hash(path)
    text = read_text(path)
    if not text and not path.is_file():
        return "<missing>"
    if path.suffix.casefold() == ".tex":
        text = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def final_consistency_verdict(text: str) -> str:
    normalized = str(text or "").casefold()
    heading = "final consistency verdict"
    position = normalized.rfind(heading)
    if position < 0:
        return ""
    match = re.search(r"\b(pass|fail)\b", normalized[position + len(heading):])
    return match.group(1).upper() if match else ""


def bib_keys(path: Path) -> set[str]:
    return {
        item for item in re.findall(
            r"(?m)^\s*@[A-Za-z]+\s*\{\s*([^,\s]+)", read_text(path)
        ) if item.strip()
    }


def latex_text(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in value)
