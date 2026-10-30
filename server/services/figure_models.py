"""Shared contracts for scientific figure generation backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FigureType(str, Enum):
    MATPLOTLIB = "matplotlib"
    FIGURESPEC = "figurespec"
    RICH_SVG = "rich_svg"
    MERMAID = "mermaid"
    TIKZ = "tikz"
    GPT_IMAGE = "gpt_image"
    NANO_BANANA = "nano_banana"
    DRAWIO = "drawio"
    EXCALIDRAW = "excalidraw"


@dataclass
class FigureResult:
    success: bool
    figure_type: FigureType
    output_path: Optional[str] = None
    source_path: Optional[str] = None
    code: Optional[str] = None
    svg_content: Optional[str] = None
    image_url: Optional[str] = None
    install_hint: Optional[str] = None
    manifest_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None
