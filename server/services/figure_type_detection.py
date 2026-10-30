"""Deterministic backend selection from one scientific figure description."""

from __future__ import annotations

import re

from .figure_models import FigureType


def _has_term(text: str, *terms: str) -> bool:
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text)
        for term in terms
    )


def detect_figure_type(description: str) -> FigureType:
    text = description.casefold()
    if _has_term(
        text, "bar chart", "line chart", "scatter", "histogram", "loss curve",
        "accuracy", "comparison", "ablation", "plot", "matplotlib",
    ) or any(term in text for term in ("柱状图", "折线图", "散点图")):
        return FigureType.MATPLOTLIB
    if _has_term(text, "flow", "sequence", "class diagram", "state", "mermaid") or any(
        term in text for term in ("流程图", "序列图", "时序图", "状态图")
    ):
        return FigureType.MERMAID
    if _has_term(
        text, "tikz", "algorithm", "proof dependency", "theorem",
        "graph theory", "equation structure",
    ) or any(term in text for term in ("数学", "算法图", "公式", "证明")):
        return FigureType.TIKZ
    if _has_term(
        text, "draw.io", "drawio", "system topology", "service topology",
        "deployment topology", "hardware topology", "threat model",
    ) or any(term in text for term in ("系统拓扑", "部署拓扑", "硬件拓扑")):
        return FigureType.DRAWIO
    if _has_term(
        text, "realistic", "photo", "naturalistic illustration", "anatomical",
        "apparatus illustration", "dall-e", "image2",
    ) or any(term in text for term in ("照片级", "解剖示意", "装置示意")):
        return FigureType.GPT_IMAGE
    if _has_term(
        text, "architecture", "method overview", "mechanism overview",
        "model architecture", "conceptual diagram",
    ) or any(term in text for term in ("架构图", "方法总览", "机制图", "概念图")):
        return FigureType.RICH_SVG
    return FigureType.EXCALIDRAW
