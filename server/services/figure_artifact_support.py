"""Shared constants and pure helpers for figure artifact policies."""

from __future__ import annotations

import hashlib
import html
import re
from functools import wraps
from pathlib import Path
from PIL import ImageFont

from ..utils.atomic_write import path_lock


PAPER_READY_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".svg"}
EDITABLE_EXTENSIONS = {".py", ".svg", ".mmd", ".mermaid", ".drawio", ".dio", ".excalidraw", ".tex", ".json"}
ADMINISTRATIVE_FIGURE_PREFIXES = (
    "project artifact readiness", "project artifact inventory", "workflow status",
    "file inventory", "artifact completion",
)
GENERIC_DIAGRAM_SIGNATURES = (
    ("idle", "running", "completed", "failed"),
    ("start", "decision", "process a", "process b", "end"),
    ("user", "system", "database", "request", "query", "response"),
    ("component a", "component b", "component c"),
)
SEMANTIC_STOPWORDS = {
    "about", "across", "after", "against", "also", "among", "analysis",
    "based", "before", "between", "claim", "comparison", "data", "design",
    "does", "each", "evaluation", "evidence", "experiment", "figure", "from",
    "have", "into", "method", "model", "paper", "proposed", "research",
    "result", "results", "should", "study", "system", "that", "their",
    "this", "through", "using", "versus", "which", "with", "without",
}
SEMANTIC_TOKEN_ALIASES = {
    "training": "training",
    "dynamics": "dynamics",
    "personalisation": "personalization",
    "personalized": "personalization",
    "personalised": "personalization",
    "individualized": "personalization",
    "individualised": "personalization",
    "adapter": "component",
    "adaptor": "component",
    "branch": "component",
    "module": "component",
    "resilience": "robustness",
    "stability": "robustness",
    "robust": "robustness",
    "failure": "error",
    "misclassification": "error",
    "optimization": "training",
    "optimisation": "training",
    "learning": "training",
    "framework": "architecture",
    "pipeline": "architecture",
    "interpretability": "explainability",
    "attribution": "explainability",
    "baseline": "comparison",
    "control": "comparison",
}
SEMANTIC_PHRASE_ALIASES = {
    "subject-specific": "personalization",
    "subject specific": "personalization",
    "patient-specific": "personalization",
    "patient specific": "personalization",
    "feature extractor": "encoder",
    "representation learner": "encoder",
    "component removal": "ablation",
    "leave one component out": "ablation",
    "training curve": "dynamics",
    "learning curve": "dynamics",
}
SCIENTIFIC_METADATA_FIELDS = (
    "scientific_role",
    "scientific_question",
    "claim_ids",
    "source_data",
    "intended_comparison",
    "visual_encoding",
    "uncertainty_encoding",
    "evidence_status",
    "style_profile",
    "paper_selected",
    "manuscript_eligible",
    "provenance_kind",
)

MANUSCRIPT_FIGURE_ROLES = {
    "method",
    "result",
    "ablation",
    "robustness",
    "analysis",
    "qualitative",
    "dataset",
    "evaluation_design",
    "efficiency",
    "calibration",
    "error_analysis",
    "sensitivity",
}
INTERNAL_FIGURE_ROLES = {
    "protocol",
    "administrative",
    "claim_map",
    "execution_status",
    "experimental_design",
    "internal_protocol",
}
NON_SUBMISSION_EVIDENCE_STATUSES = {
    "placeholder",
    "synthetic",
    "administrative",
    "internal",
}
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _short_label(value: str, limit: int = 38) -> str:
    clean = " ".join(str(value or "").replace("\n", " ").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _semantic_tokens(value: str) -> set[str]:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).casefold()
    raw_tokens = set(re.findall(r"[a-z][a-z0-9_-]{2,}", text))
    for token in tuple(raw_tokens):
        raw_tokens.update(re.split(r"[_-]+", token))

    def canonical(token: str) -> str:
        token = token.casefold().strip("_-")
        if token in SEMANTIC_TOKEN_ALIASES:
            return SEMANTIC_TOKEN_ALIASES[token]
        if len(token) > 5 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 5 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("es"):
            token = token[:-2]
        elif len(token) > 3 and token.endswith("s"):
            token = token[:-1]
        return SEMANTIC_TOKEN_ALIASES.get(token, token)

    tokens = {
        canonical(token)
        for token in raw_tokens
        if len(token) >= 3 and token not in SEMANTIC_STOPWORDS
    }
    tokens.discard("")
    for phrase, alias in SEMANTIC_PHRASE_ALIASES.items():
        if phrase in text:
            tokens.add(alias)
    for sequence in re.findall(r"[一-鿿]{2,}", text):
        for size in (2, 3):
            tokens.update(
                sequence[index:index + size]
                for index in range(max(0, len(sequence) - size + 1))
            )
    return tokens


def _longest_false_run(values: list[bool]) -> int:
    longest = current = 0
    for value in values:
        if value:
            current = 0
            continue
        current += 1
        longest = max(longest, current)
    return longest


def _manifest_mutation(method):
    @wraps(method)
    def locked(cls, *args, **kwargs):
        target = (
            args[0]
            if args
            else kwargs.get("path", kwargs.get("output_dir"))
        )
        if target is None:
            raise TypeError(
                f"{method.__qualname__} requires a figure path or output_dir"
            )
        with path_lock(cls.manifest_path(target)):
            return method(cls, *args, **kwargs)

    return locked


