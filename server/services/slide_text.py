"""Pure text-to-Beamer projection helpers."""

from __future__ import annotations

from typing import Any


def compact(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    window = clean[: limit + 1]
    for separator in (". ", "; "):
        boundary = window.rfind(separator)
        if boundary >= int(limit * 0.58):
            return window[: boundary + 1].strip()
    clipped = window.rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{clipped or clean[:limit]}..."


def latex(value: Any, limit: int = 900) -> str:
    clean = compact(value, limit)
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in clean)


def items(values: list[str], *, item_limit: int = 150) -> str:
    return "\n".join(
        r"\item " + latex(value, item_limit) for value in values if value
    )


def item_frames(
    title: str,
    values: list[str],
    *,
    per_frame: int = 4,
    item_limit: int = 150,
) -> str:
    chunks = [
        values[index:index + per_frame]
        for index in range(0, len(values), per_frame)
    ] or [["No contract-backed item is available."]]
    frames = []
    for index, chunk in enumerate(chunks, start=1):
        suffix = f" ({index}/{len(chunks)})" if len(chunks) > 1 else ""
        frames.append(
            rf"""\begin{{frame}}{{{latex(title + suffix, 100)}}}
\begin{{itemize}}
{items(chunk, item_limit=item_limit)}
\end{{itemize}}
\end{{frame}}"""
        )
    return "\n\n".join(frames)
