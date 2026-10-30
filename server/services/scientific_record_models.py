"""Normalized quantitative and qualitative evidence records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultRecord:
    method: str
    metric: str
    value: float
    source: str
    seed: str = ""
    split: str = ""
    condition_name: str = ""
    condition_value: str = ""
    role: str = "result"
    ci_low: float | None = None
    ci_high: float | None = None
    unit: str = ""
    estimate_type: str = ""
    p_value: float | None = None
    adjusted_p: float | None = None


@dataclass(frozen=True)
class QualitativeEvidenceRecord:
    theme: str
    case: str
    evidence: str
    source: str
    source_id: str = ""
    polarity: str = ""
    coder: str = ""
    triangulation_source: str = ""
