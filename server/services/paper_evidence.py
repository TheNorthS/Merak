"""Evidence models and publication-safe text helpers for paper artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .paper_compiler import BibEntry
from .scientific_assets import scientific_asset_service


_CJK_SIGNAL = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PUBLICATION_META_SIGNAL = re.compile(
    r"\b(?:publication-facing|implementation bookkeeping|status language|"
    r"layout-only repair|renderer|internal planning|workflow status)\b",
    re.IGNORECASE,
)


@dataclass
class MetricEvidence:
    name: str
    value: float
    source: str
    split: str = ""


@dataclass
class PaperEvidence:
    root: Path
    title: str
    direction: str
    idea_text: str
    survey_text: str
    narrative_text: str
    plan_text: str
    analysis_text: str
    bib_entries: list[BibEntry] = field(default_factory=list)
    metrics: list[MetricEvidence] = field(default_factory=list)
    figures: list[dict[str, Any]] = field(default_factory=list)
    asset_plan: dict[str, Any] = field(default_factory=dict)
    selected_idea: dict[str, Any] = field(default_factory=dict)
    method_contract: dict[str, Any] = field(default_factory=dict)
    run_spec: dict[str, Any] = field(default_factory=dict)
    resolved_config: dict[str, Any] = field(default_factory=dict)

    @property
    def experiments_pending(self) -> bool:
        return self.evidence_mode not in {
            "executed", "existing_results", "secondary_analysis",
            "synthetic_preview",
        }

    @property
    def evidence_mode(self) -> str:
        return str(self.asset_plan.get("evidence_mode") or "design_only")

    @property
    def submission_eligible(self) -> bool:
        return bool(self.asset_plan.get("submission_eligible"))

    @property
    def synthetic_preview(self) -> bool:
        return self.evidence_mode == "synthetic_preview"


def _read(path: Path, limit: int = 40000) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_yaml_object(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latex(value: Any) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(value or ""))


def _publication_text(value: Any, fallback: str) -> str:
    """Return compact text that is safe for an English pdfLaTeX manuscript.

    Research contracts may legitimately be authored in Chinese while the
    selected publication template is English and compiled with pdfLaTeX.  The
    original text remains in JSON/CSV evidence; generated TeX must use an
    explicitly supplied English publication field or a meaningful fallback.
    """
    text = " ".join(str(value or "").split())
    if not text or _CJK_SIGNAL.search(text):
        text = " ".join(str(fallback or "").split())
    # Source-like snake_case is unsuitable in publication-facing prose and is
    # also easy to mistake for an unescaped TeX subscript.
    text = re.sub(r"(?<=\w)_(?=\w)", " ", text)
    return text


def _first_publication_text(
    source: dict[str, Any],
    keys: Iterable[str],
    fallback: str,
    *,
    reject_meta: bool = False,
) -> str:
    """Select the first non-CJK publication string from ordered fields."""
    for key in keys:
        candidate = " ".join(str(source.get(key) or "").split())
        if (
            candidate
            and not _CJK_SIGNAL.search(candidate)
            and not (reject_meta and _PUBLICATION_META_SIGNAL.search(candidate))
        ):
            return _publication_text(candidate, fallback)
    return _publication_text("", fallback)


def _figure_publication_caption(role: str, index: int) -> str:
    captions = {
        "method": (
            "Method overview showing the scientific mechanism, controlled "
            "comparisons, and the path from study inputs to reported evidence."
        ),
        "evaluation_design": (
            "Evaluation design showing isolated data partitions, matched "
            "conditions, and endpoint aggregation."
        ),
        "ablation": "Component ablation under matched evaluation conditions.",
        "robustness": "Robustness analysis across prespecified evaluation shifts.",
        "calibration": "Calibration analysis under the registered evaluation protocol.",
        "efficiency": "Performance and resource trade-off under controlled measurement.",
        "error_analysis": "Error analysis across prespecified evaluation slices.",
        "training_dynamics": "Training dynamics with uncertainty across repeated runs.",
        "result": "Primary comparison with uncertainty across repeated runs.",
    }
    return captions.get(role, f"Scientific analysis figure {index}.")


def _table_plain_text(value: Any) -> str:
    """Normalize a table value for a conservative source-content check."""
    text = str(value or "")
    text = re.sub(
        r"\\(?:caption|label)\s*\{([^{}]*)\}",
        r"\1",
        text,
    )
    text = re.sub(r"\\(?:textbf|textit|emph|small|scriptsize|footnotesize)\s*", "", text)
    text = text.replace(r"\&", "&").replace(r"\_", "_")
    text = text.replace(r"\%", "%").replace(r"\textbackslash{}", "\\")
    text = re.sub(r"\\[A-Za-z@]+(?:\[[^]]*\])?(?:\{[^}]*\})?", " ", text)
    text = re.sub(r"[^\w.%+\-]+", " ", text, flags=re.UNICODE)
    return " ".join(text.casefold().split())


def _table_source_matches_registered_rows(
    path: Path,
    *,
    label: str,
    caption: str,
    rows: list[dict[str, Any]],
) -> bool:
    """Keep a reviewed layout edit when its registered content is intact.

    Layout editors are allowed to shorten prose in wide cells, so this check
    binds labels, captions, row identities, and numeric values rather than
    requiring byte-identical generated LaTeX. If a data/semantic row changes,
    the builder regenerates the authoritative source instead.
    """
    text = _read(path, 250000)
    if not text or f"\\label{{{label}}}" not in text:
        return False
    plain = _table_plain_text(text)
    caption_plain = _table_plain_text(caption)
    if caption_plain and caption_plain not in plain:
        return False
    if len(re.findall(r"\\\\", text)) < len(rows) + 1:
        return False
    for row in rows:
        values = [str(value or "").strip() for value in row.values()]
        first = next((value for value in values if value), "")
        first_plain = _table_plain_text(first)
        if first_plain and first_plain not in plain:
            return False
        for value in values:
            # Numeric cells are immutable scientific evidence. Match the
            # literal token, including signed deltas and decimal intervals.
            for number in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", value):
                if number.casefold() not in plain:
                    return False
    return True


def _extract_title(direction: str, idea: str, plan: str) -> str:
    patterns = (
        (plan, r"(?im)^##\s*(?:Auto-selected Idea|Selected Idea)\s*$\s*([^\n]{8,180})"),
        (plan, r"(?ims)^experiment:\s*$.*?selected_idea:\s*[\"']?([^\n\"']{8,180})"),
        (idea, r"(?im)^#\s*(?!Selected Idea\s*$|Ideas?\s*$)([^\n]{8,180})"),
        (idea, r"(?im)^#\s*(?:Selected Idea|Idea)\s*$\s*([^\n]{8,180})"),
    )
    for text, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return " ".join(match.group(1).split())[:180]
    return " ".join(direction.split())[:180] or "Evidence-Grounded Research Workflow"


def _collect_metrics(root: Path) -> list[MetricEvidence]:
    records = scientific_asset_service.collect_records(root)
    return [
        MetricEvidence(
            name=f"{record.method}.{record.metric}",
            value=record.value,
            source=record.source,
            split=record.split,
        )
        for record in records[:40]
    ]


