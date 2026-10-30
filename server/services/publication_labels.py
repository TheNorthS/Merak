"""Publication-facing labels for machine-readable research contracts."""

from __future__ import annotations

import re
from typing import Any


_CJK_SIGNAL = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)

_COMPONENT_CONCEPTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("计算匹配", "因果消融"), "Compute-matched causal ablation"),
    (("身份", "捷径", "一致性"), "Record-identity consistency objective"),
    (("频谱", "拓扑", "结构掩码"), "Spectral-topological masked prediction"),
    (("域外", "导联", "压力测试"), "Held-out montage stress evaluation"),
    (("ranking", "排序", "排名"), "Prespecified multi-axis ranking"),
    (("ledger", "账本", "溯源", "追溯"), "Run-level evidence ledger"),
    (("ablation", "消融", "替代解释"), "Single-factor protocol ablation"),
    (("calibration", "shift", "校准", "偏移", "隔离"), "Shift and calibration isolation"),
    (("efficiency", "latency", "效率", "延迟", "设备"), "Controlled device-level efficiency"),
)

_METRIC_LABELS = {
    "balanced accuracy": "Balanced accuracy",
    "identity probe accuracy": "Identity-probe accuracy",
    "spectral mae": "Spectral MAE",
    "topology mse": "Topology MSE",
    "montage degradation slope": "Montage degradation slope",
    "macro f1": "Macro-F1",
    "auroc": "AUROC",
    "rmse": "RMSE",
    "nll": "NLL",
}


def publication_component_label(value: str, index: int) -> str:
    """Return a concise scientific component label without machine syntax."""
    text = " ".join(str(value or "").replace("_", " ").split())
    if text and not _CJK_SIGNAL.search(text):
        return text
    normalized = str(value or "").casefold()
    for needles, label in _COMPONENT_CONCEPTS:
        if any(needle in normalized for needle in needles):
            return label
    return f"Prespecified method component {index}"


def publication_metric_label(value: Any) -> str:
    """Convert a stable metric key into publication-facing text."""
    raw = " ".join(str(value or "Primary endpoint").replace("_", " ").split())
    return _METRIC_LABELS.get(raw.casefold(), raw[:1].upper() + raw[1:])


def publication_metric_axis_label(value: Any, direction: str) -> str:
    """One canonical metric/direction label for producers and their validators."""
    if direction not in {"maximize", "minimize"}:
        raise ValueError("Metric direction must be maximize or minimize")
    orientation = "higher" if direction == "maximize" else "lower"
    return f"{publication_metric_label(value)} ({orientation} is better)"


def publication_outcome_label(
    value: str,
    evidence_kind: str = "",
    index: int = 1,
) -> str:
    """Translate a CJK contract endpoint into concise scientific English."""
    text = " ".join(str(value or "").split())
    if text and not _CJK_SIGNAL.search(text):
        return text
    normalized = (text + " " + str(evidence_kind or "")).casefold()
    if any(token in normalized for token in (
        "identity_probe", "identity probe", "身份", "shortcut",
    )):
        return (
            "Held-out identity-probe accuracy conditional on preserved "
            "downstream performance"
        )
    if any(token in normalized for token in (
        "spectral", "topology", "频谱", "拓扑", "结构保真",
    )):
        return (
            "Spectral and topology reconstruction errors aligned with "
            "group-disjoint task performance"
        )
    if any(token in normalized for token in (
        "channel_subset", "contiguous_region", "reorder", "montage", "导联",
    )):
        return (
            "Subject-level accuracy under channel removal and reordering, "
            "with the registered degradation slope"
        )
    if any(token in normalized for token in (
        "balanced_accuracy", "group-disjoint", "dataset-disjoint", "留出",
        "配对效应", "confidence", "置信区间",
    )):
        return (
            "Group-disjoint balanced accuracy with paired effects and "
            "confidence intervals"
        )
    if any(token in normalized for token in ("component", "ablation", "消融")):
        return "Matched single-factor component effect on the registered endpoint"
    if "held-out" in normalized or "held out" in normalized:
        return "Held-out comparison on the registered primary endpoint"
    return f"Registered measurable outcome {index}"
