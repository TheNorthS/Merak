"""Language checks shared by manuscript and scientific-asset gates."""

from __future__ import annotations

import re
from collections.abc import Iterable


_CONTRACT_REFERENCE_PATTERNS = (
    re.compile(
        r"\b(?:claim|hypothesis|contribution)\b"
        r"(?:\s+(?:ids?|identifiers?|numbers?|no\.?))?\s*[:=#-]?\s*"
        r"C\d+(?:\s*(?:,|/|&|\band\b)\s*C\d+)*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mechanism|method)\b"
        r"(?:\s+(?:ids?|identifiers?|numbers?|no\.?))?\s*[:=#-]?\s*"
        r"M\d+(?:\s*(?:,|/|&|\band\b)\s*M\d+)*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfalsification(?:\s+(?:condition|criterion|test))?\b"
        r"(?:\s+(?:ids?|identifiers?|numbers?|no\.?))?\s*[:=#-]?\s*"
        r"F\d+(?:\s*(?:,|/|&|\band\b)\s*F\d+)*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:issue|requirement)\b"
        r"(?:\s+(?:ids?|identifiers?|numbers?|no\.?))?\s*[:=#-]?\s*"
        r"I\d+(?:\s*(?:,|/|&|\band\b)\s*I\d+)*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:internal\s+)?contract(?:\s+(?:ids?|references?|items?))?\b"
        r"\s*[:=#-]?\s*[CMFI]\d+"
        r"(?:\s*(?:,|/|&|\band\b)\s*[CMFI]\d+)*",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bC\d+\s+(?:claim|hypothesis|contribution)\b|"
        r"\bM\d+\s+(?:mechanism|method)\b|"
        r"\bF\d+\s+falsification(?:\s+(?:condition|criterion|test))?\b|"
        r"\bI\d+\s+(?:issue|requirement)\b",
        re.IGNORECASE,
    ),
)
_CONTRACT_ID_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])([CMFI]\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_SIMPLE_TEX_WRAPPER = re.compile(
    r"\\(?:texttt|textbf|textrm|mathrm|emph)\s*\{([^{}]*)\}",
    re.IGNORECASE,
)
_VISIBLE_CODE_ARTIFACT_PATTERNS = (
    re.compile(
        r"\b[A-Za-z][A-Za-z0-9_-]*\.(?:py|json|ya?ml|csv|tsv|tex|log)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\b[A-Za-z]:[\\/]|\b(?:experiments|server|src|paper|figures)[\\/])"
        r"[^\s,;:(){}]+",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:self|nn|torch|numpy|np|pandas|pd)\.[A-Za-z_]\w*\b"),
    re.compile(r"\b[A-Z][A-Za-z0-9]*\.(?:forward|__init__|fit|predict|run|main)\b"),
)
_VISIBLE_SNAKE_CASE_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_VISIBLE_TEXTTT_CODE_PATTERN = re.compile(
    r"\\texttt\s*\{([^{}]*_[^{}]*)\}", re.IGNORECASE
)
_LATEX_MATH_SPANS = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$.*?(?<!\\)\$",
    re.DOTALL,
)
_LATEX_DISPLAY_MATH_ENVIRONMENTS = re.compile(
    r"\\begin\{(?:equation|align|alignat|gather|multline|displaymath)\*?\}"
    r".*?"
    r"\\end\{(?:equation|align|alignat|gather|multline|displaymath)\*?\}",
    re.DOTALL | re.IGNORECASE,
)
_MATH_FUNCTION_DOMAIN = re.compile(
    r"\b[A-Za-z]:\\(?:mathbb|mathcal|mathfrak|mathbf|mathrm)\s*\{[A-Za-z]\}"
)
_NONVISIBLE_LATEX_ARGUMENT = re.compile(
    r"\\(?:input|include|includegraphics|graphicspath|documentclass|"
    r"usepackage|bibliographystyle|label|ref|pageref|autoref|eqref|"
    r"cite|citep|citet|citealp|citeauthor|citeyear|bibliography|"
    r"bibliographystyle)\*?\s*(?:\[[^\]]*\]\s*)?\{[^{}]*\}",
    re.IGNORECASE,
)
_NONVISIBLE_GRAPHICSPATH = re.compile(
    r"\\graphicspath\s*\{(?:\s*\{[^{}]*\}\s*)+\}", re.IGNORECASE
)


def find_internal_contract_references(
    text: str,
    known_ids: Iterable[str] | None = None,
) -> list[str]:
    """Return workflow IDs while preserving domain tokens such as EEG C3."""
    normalized = str(text or "").replace("~", " ")
    for _ in range(2):
        normalized = _SIMPLE_TEX_WRAPPER.sub(r"\1", normalized)

    known = {
        str(item).strip().casefold(): str(item).strip()
        for item in (known_ids or ())
        if str(item).strip()
    }
    found: dict[str, str] = {}
    for pattern in _CONTRACT_REFERENCE_PATTERNS:
        for span in pattern.finditer(normalized):
            for token in _CONTRACT_ID_TOKEN.findall(span.group(0)):
                key = token.casefold()
                if known and key not in known:
                    continue
                found[key] = known.get(key, token.upper())
    return sorted(found.values(), key=lambda value: value.casefold())


def find_visible_code_artifact_references(text: str) -> list[str]:
    """Return source-code or repository-path tokens leaked into publication prose.

    Scientific acronyms and model names remain valid. This targets concrete
    implementation syntax: filenames, project-relative paths, snake_case
    identifiers, framework attributes, and class lifecycle methods.
    """

    found: dict[str, str] = {}
    # File paths, labels, and BibTeX keys inside structural LaTeX commands are
    # not visible manuscript prose.  Ignore those arguments while preserving
    # math delimiters and visible wrappers such as ``\texttt{...}``.
    raw = _NONVISIBLE_GRAPHICSPATH.sub(" ", str(text or ""))
    raw = _NONVISIBLE_LATEX_ARGUMENT.sub(" ", raw)
    # A typed map such as D:\mathbb{R} inside math is not a drive path.
    # Retain other math text so actual filenames and code remain detectable.
    code_scan = _LATEX_DISPLAY_MATH_ENVIRONMENTS.sub(
        lambda match: _MATH_FUNCTION_DOMAIN.sub(" ", match.group(0)), raw
    )
    code_scan = _LATEX_MATH_SPANS.sub(
        lambda match: _MATH_FUNCTION_DOMAIN.sub(" ", match.group(0)), code_scan
    )
    for pattern in _VISIBLE_CODE_ARTIFACT_PATTERNS:
        for match in pattern.finditer(code_scan):
            value = " ".join(match.group(0).split()).strip("`'\"")
            if value:
                found.setdefault(value.casefold(), value)
    # Ordinary mathematical notation such as $z_m$, $p_m$, and $q_a$ is not
    # source code.  Scan generic snake_case only outside LaTeX math spans while
    # still rejecting explicitly monospaced implementation identifiers.
    prose_only = _LATEX_DISPLAY_MATH_ENVIRONMENTS.sub(" ", raw)
    prose_only = _LATEX_MATH_SPANS.sub(" ", prose_only)
    for match in _VISIBLE_SNAKE_CASE_PATTERN.finditer(prose_only):
        value = match.group(0)
        found.setdefault(value.casefold(), value)
    for match in _VISIBLE_TEXTTT_CODE_PATTERN.finditer(raw):
        value = match.group(1).strip()
        if value:
            found.setdefault(value.casefold(), value)
    return sorted(found.values(), key=lambda value: value.casefold())
