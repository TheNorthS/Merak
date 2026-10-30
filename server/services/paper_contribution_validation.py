"""Semantic recognition of falsifiable manuscript contributions."""

from __future__ import annotations

import re

from .manuscript_text import strip_tex

_ORDINAL_MARKER = re.compile(
    r"\b(?:first|second|third|fourth|fifth|finally)\s*,?\s+(?:"
    r"we|it|the\s+(?=[a-z])|our(?:\s+(?:paper|work|study|approach|method|framework|analysis|"
    r"contribution|evaluation|protocol))?|"
    r"this\s+(?:paper|work|study|approach|method|framework|analysis))\b"
)
_ENUMERATION_MARKER = re.compile(
    r"(?<![a-z0-9])(?:\d{1,2}[.)]|\((?:\d{1,2}|[a-z]|[ivxlcdm]{1,6})\))\s+"
)
_FALSIFIABLE = re.compile(
    r"\b(?:only\s+if(?=\s+\w)|rejected|rejects|falsif(?:y|ies|ied|ying)|refuted|"
    r"invalidated|unsupported|ineligible|cannot\s+support|negative\s+evidence|"
    r"contradicts?|fails?\s+(?:for|where|whenever)|"
    r"(?:would|will|does|do)\s+(?:reject|refute|falsify|invalidate)|"
    r"(?:does|do|would|will)\s+not\s+hold)\b"
)
_OUTCOME_FIRST = re.compile(
    r"\b(?:(?:(?:is|are|would\s+be|will\s+be|should\s+be)\s+)?"
    r"(?:rejected|falsified|refuted|invalidated|unsupported)|"
    r"(?:would|will|should|does|do)?\s*(?:not\s+hold|fails?)|"
    r"(?:rejects|falsifies|refutes|invalidates)\b[^.;!?\n]{0,180})"
    r"\s+(?:if|when|unless)\b"
)
_CONDITION_FIRST = re.compile(
    r"\b(?:if|when|unless)\b[^.;!?\n]{0,320}\b(?:"
    r"(?:is|are|would\s+be|will\s+be|should\s+be|be)\s+"
    r"(?:rejected|falsified|refuted|invalidated|unsupported)|"
    r"(?:would|will|should|does|do)?\s*(?:not\s+hold|fails?))\b"
)
_CLAIM_REDIRECTION = re.compile(
    r"\bclaims?\s+(?:is|are|would\s+be|will\s+be)\s+redirected\s+by\b"
    r"[^.;!?\n]{0,260}\b(?:non[- ]positive|inadequate\s+paired\s+effect|"
    r"loss\s+beyond\s+the\s+(?:prespecified|predeclared)\s+tolerance)\b"
)
_ADVERSE_CONDITION = re.compile(
    r"\b(?:failure|violation|disappearance|equivalence|reversal|alternative[- ]control\s+explanation)\b"
    r"[^.;!?\n]{0,260}\b(?:(?:would|will|does|do)\s+)?"
    r"(?:precludes?|defeats?|rules?\s+out)\b[^.;!?\n]{0,100}"
    r"\b(?:claim|conclusion|interpretation|hypothesis|account)\b"
)
_SUPPORT_CONDITION = re.compile(
    r'\b(?:hypothesis|claim|interpretation|conclusion)\s+is\s+supported\s+only\s+when\b'
    r'[^.;!?\n]{0,240}\b(?:interval|effect|loss|difference)\b'
    r'[^.;!?\n]{0,120}\b(?:strictly\s+(?:below|above)\s+zero|excludes?\s+zero|'
    r'(?:below|above|within|exceeds?)\s+(?:the\s+)?(?:prespecified|predeclared)\s+(?:threshold|tolerance))\b'
)
_WITHDRAWAL_CONDITION = re.compile(
    r'\b(?:claim|claims|interpretation|design)\b[^.;!?\n]{0,100}'
    r'\b(?:is\s+withdrawn|are\s+withdrawn|weakens|fails\s+as\s+reproducible)\b'
    r'[^.;!?\n]{0,80}\b(?:if|when)\b[^.;!?\n]{8,320}'
)


def falsifiable_contribution_structure(text: str) -> dict[str, int]:
    """Count independent rejection evidence once, across mixed scientific wording."""
    source = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    lower = strip_tex(source).casefold()
    items = list(re.finditer(r"\\item\b", source))
    ordinal = list(_ORDINAL_MARKER.finditer(lower))
    numbered = list(_ENUMERATION_MARKER.finditer(lower))
    starts = {match.start() for match in [*ordinal, *numbered]}
    starts.update(len(strip_tex(source[:match.end()]).casefold()) for match in items)
    return {
        "contributions": max(len(items), len(ordinal), len(numbered)),
        "falsification_conditions": _independent_falsification_count(lower, sorted(starts)),
    }


def _independent_falsification_count(text: str, starts: list[int]) -> int:
    """One contribution cannot gain multiple votes from overlapping recognizers."""
    if not starts:
        return len(_evidence_statements(text, semantic=False))
    seen: set[str] = set()
    count = 0
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else min(len(text), start + 1600)
        statements = _evidence_statements(text[start:end], semantic=True)
        count += bool(statements - seen)
        seen.update(statements)
    return count


def _evidence_statements(text: str, *, semantic: bool) -> set[str]:
    """Deduplicate recognizers by statement positions, then repeated identical prose."""
    patterns = (_OUTCOME_FIRST, _CONDITION_FIRST, _FALSIFIABLE, _CLAIM_REDIRECTION, _ADVERSE_CONDITION, _SUPPORT_CONDITION, _WITHDRAWAL_CONDITION) if semantic else (
        _OUTCOME_FIRST, _CONDITION_FIRST,
    )
    boundaries = list(re.finditer(r"[.;!?]", text))
    spans: set[tuple[int, int]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            start = max((boundary.end() for boundary in boundaries if boundary.end() <= match.start()), default=0)
            end = min((boundary.start() for boundary in boundaries if boundary.start() >= match.end()), default=len(text))
            spans.add((start, end))
    return {" ".join(text[start:end].split()) for start, end in spans}
