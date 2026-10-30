"""Small dependency-free SVG vocabulary for trusted/manual paper scripts.

The workflow rich-SVG backend accepts raw SVG and does not import or execute
this module. These helpers only keep repository-maintained scripts such as the
test-72/test-82 reference generators concise and visually consistent.
"""
from __future__ import annotations

import math
from html import escape
from typing import Iterable


INK = "#17233C"
MUTED = "#52627A"
LINE = "#B7C3D3"
PALE = "#F7F9FC"
WHITE = "#FFFFFF"
BLUE = "#4E82C3"
BLUE_SOFT = "#E8F1FB"
TEAL = "#2B9A8A"
TEAL_SOFT = "#E4F5F1"
ORANGE = "#E89A4A"
ORANGE_SOFT = "#FFF0DF"
PURPLE = "#8B72B6"
PURPLE_SOFT = "#F1ECF8"
RED = "#D9655B"
RED_SOFT = "#FBEAE8"
GREEN = "#61A66A"
GREEN_SOFT = "#EAF5EA"


def attrs(**values: object) -> str:
    return " ".join(
        f'{key.replace("_", "-")}="{escape(str(value), quote=True)}"'
        for key, value in values.items()
        if value is not None
    )


def svg_open(width: int = 1800, height: int = 1000) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
        "<defs>"
        '<marker id="arrow" markerWidth="10" markerHeight="10" refX="8.5" '
        'refY="3.5" orient="auto" markerUnits="userSpaceOnUse" '
        'viewBox="0 0 10 10">'
        '<path d="M0,0 L9,3.5 L0,7 z" fill="#52627A"/></marker>'
        "</defs>"
    )


def rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str = WHITE,
    stroke: str = LINE,
    sw: float = 1.2,
    rx: float = 10,
    opacity: float | None = None,
    dash: str | None = None,
) -> str:
    return f'<rect {attrs(x=x, y=y, width=width, height=height, rx=rx, fill=fill, stroke=stroke, stroke_width=sw, opacity=opacity, stroke_dasharray=dash)}/>'


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str = LINE,
    sw: float = 1.4,
    dash: str | None = None,
    marker: bool = False,
    opacity: float | None = None,
) -> str:
    return f'<line {attrs(x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, stroke_width=sw, stroke_linecap="round", stroke_dasharray=dash, marker_end="url(#arrow)" if marker else None, opacity=opacity)}/>'


def path(
    d: str,
    *,
    stroke: str = INK,
    sw: float = 1.5,
    fill: str = "none",
    marker: bool = False,
    dash: str | None = None,
    opacity: float | None = None,
) -> str:
    return f'<path {attrs(d=d, stroke=stroke, stroke_width=sw, fill=fill, stroke_linecap="round", stroke_linejoin="round", marker_end="url(#arrow)" if marker else None, stroke_dasharray=dash, opacity=opacity)}/>'


def circle(
    cx: float,
    cy: float,
    radius: float,
    *,
    fill: str = WHITE,
    stroke: str = LINE,
    sw: float = 1.2,
) -> str:
    return f'<circle {attrs(cx=cx, cy=cy, r=radius, fill=fill, stroke=stroke, stroke_width=sw)}/>'


def polygon(
    points: Iterable[tuple[float, float]],
    *,
    fill: str = INK,
    stroke: str = "none",
    sw: float = 0,
) -> str:
    encoded = " ".join(f"{x},{y}" for x, y in points)
    return f'<polygon {attrs(points=encoded, fill=fill, stroke=stroke, stroke_width=sw)}/>'


def txt(
    x: float,
    y: float,
    value: str,
    *,
    size: float = 15,
    weight: int = 400,
    fill: str = INK,
    anchor: str = "start",
    italic: bool = False,
    spacing: float | None = None,
) -> str:
    return (
        f'<text {attrs(x=x, y=y, fill=fill, font_size=size, font_weight=weight, text_anchor=anchor, font_family="Arial, Helvetica, sans-serif", font_style="italic" if italic else None, letter_spacing=spacing)}>'
        f'{escape(value)}</text>'
    )


def multi(
    x: float,
    y: float,
    lines: Iterable[str],
    *,
    size: float = 14,
    weight: int = 400,
    fill: str = INK,
    anchor: str = "start",
    gap: float = 18,
) -> str:
    spans = []
    for index, value in enumerate(lines):
        spans.append(
            f'<tspan x="{x}" dy="{0 if index == 0 else gap}">{escape(str(value))}</tspan>'
        )
    return (
        f'<text {attrs(x=x, y=y, fill=fill, font_size=size, font_weight=weight, text_anchor=anchor, font_family="Arial, Helvetica, sans-serif")}>'
        + "".join(spans)
        + "</text>"
    )


def arrow(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    color: str = MUTED,
    sw: float = 2.0,
    dash: str | None = None,
) -> str:
    head, wing = 9.0, 5.0
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        shaft_end = x2 - direction * head
        tip = polygon(
            [(x2, y2), (shaft_end, y2 - wing), (shaft_end, y2 + wing)],
            fill=color,
        )
        return line(x1, y1, shaft_end, y2, stroke=color, sw=sw, dash=dash) + tip
    direction = 1 if y2 >= y1 else -1
    shaft_end = y2 - direction * head
    tip = polygon(
        [(x2, y2), (x2 - wing, shaft_end), (x2 + wing, shaft_end)],
        fill=color,
    )
    return line(x1, y1, x2, shaft_end, stroke=color, sw=sw, dash=dash) + tip


def numbered_title(
    x: float,
    y: float,
    number: str,
    title: str,
    subtitle: str = "",
) -> str:
    parts = [
        circle(x + 12, y - 7, 12, fill=INK, stroke=INK),
        txt(x + 12, y - 2, number, size=12, weight=700, fill=WHITE, anchor="middle"),
        txt(x + 34, y - 3, title, size=17, weight=700),
    ]
    if subtitle:
        parts.append(txt(x + 34, y + 16, subtitle, size=12.5, fill=MUTED))
    return "".join(parts)


def pill(
    x: float,
    y: float,
    width: float,
    value: str,
    *,
    color: str = BLUE,
    soft: str = BLUE_SOFT,
    height: float = 25,
) -> str:
    return "".join([
        rect(x, y, width, height, fill=soft, stroke=color, sw=0.9, rx=height / 2),
        txt(x + width / 2, y + height * 0.68, value, size=10.5, weight=700, fill=color, anchor="middle"),
    ])


def waveform(
    x: float,
    y: float,
    width: float,
    *,
    channels: int = 6,
    gap: float = 24,
    colors: list[str] | None = None,
) -> str:
    palette = colors or [BLUE, RED, TEAL, PURPLE, ORANGE, GREEN]
    content = ["<g>"]
    for channel in range(channels):
        baseline = y + channel * gap
        content.append(line(x, baseline, x + width, baseline, stroke="#DFE5ED", sw=0.7))
        points = []
        for index in range(120):
            phase = index / 119
            signal = (
                3.8 * math.sin(phase * math.pi * (5.2 + channel * 0.28) + channel * 0.7)
                + 1.8 * math.sin(phase * math.pi * 17.0 + channel)
                + 0.7 * math.sin(phase * math.pi * 39.0 + channel * 0.3)
            )
            if 0.48 < phase < 0.55:
                signal += 4.5 * math.sin((phase - 0.48) * math.pi * 40)
            points.append(f"{x + phase * width:.2f},{baseline - signal:.2f}")
        content.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{palette[channel % len(palette)]}" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    content.append("</g>")
    return "".join(content)


def bar_glyph(
    x: float,
    y: float,
    values: Iterable[float],
    *,
    width: float = 120,
    height: float = 55,
    color: str = BLUE,
) -> str:
    values = list(values)
    if not values:
        return ""
    maximum = max(max(values), 1e-9)
    gap = 4.0
    bar_width = max(3.0, (width - gap * (len(values) - 1)) / len(values))
    parts = [line(x, y + height, x + width, y + height, stroke=LINE, sw=0.8)]
    for index, value in enumerate(values):
        bar_height = height * max(0.0, value) / maximum
        parts.append(rect(
            x + index * (bar_width + gap),
            y + height - bar_height,
            bar_width,
            bar_height,
            fill=color,
            stroke="none",
            sw=0,
            rx=2,
        ))
    return "".join(parts)


__all__ = [
    "INK", "MUTED", "LINE", "PALE", "WHITE", "BLUE", "BLUE_SOFT",
    "TEAL", "TEAL_SOFT", "ORANGE", "ORANGE_SOFT", "PURPLE",
    "PURPLE_SOFT", "RED", "RED_SOFT", "GREEN", "GREEN_SOFT",
    "attrs", "svg_open", "rect", "line", "path", "circle", "polygon",
    "txt", "multi", "arrow", "numbered_title", "pill", "waveform",
    "bar_glyph",
]
