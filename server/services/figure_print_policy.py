"""Print-scale and narrative-complexity policy for editable SVG figures."""

from __future__ import annotations

import re
from typing import Any


_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"\b[A-Za-z]{3,}\b")


def _class_font_sizes(svg: str) -> dict[str, float]:
    sizes: dict[str, float] = {}
    for selector, body in re.findall(r"\.([A-Za-z_][\w-]*)\s*\{([^}]*)\}", svg):
        match = re.search(r"font-size\s*:\s*([\d.]+)(?:px)?", body, re.I)
        if not match:
            match = re.search(r"\bfont\s*:[^;{}]*?\b([\d.]+)px\b", body, re.I)
        if match:
            sizes[selector] = float(match.group(1))
    return sizes


def _text_font_size(element: Any, classes: dict[str, float]) -> float | None:
    direct = str(element.attrib.get("font-size") or "")
    style = str(element.attrib.get("style") or "")
    match = re.search(r"([\d.]+)", direct) or re.search(
        r"font-size\s*:\s*([\d.]+)", style, re.I,
    )
    if not match:
        match = re.search(r"\bfont\s*:[^;{}]*?\b([\d.]+)px\b", style, re.I)
    if match:
        return float(match.group(1))
    values = [classes[name] for name in str(element.attrib.get("class") or "").split() if name in classes]
    return min(values) if values else None


def svg_print_contract_issues(
    svg: str, root: Any, metadata: dict[str, Any],
) -> list[str]:
    """Validate the figure at its declared manuscript placement, not native pixels."""
    contract = metadata.get("scene_contract")
    contract = contract if isinstance(contract, dict) else {}
    view_box = str(root.attrib.get("viewBox") or "").split()
    if len(view_box) != 4:
        return []
    try:
        canvas_width = float(view_box[2])
    except ValueError:
        return []
    width_fraction = float(contract.get("target_width_fraction") or 1.0)
    paper_width_pt = 468.0 * max(0.25, min(1.0, width_fraction))
    minimum_pt = float(contract.get("minimum_placed_font_pt") or 8.0)
    classes = _class_font_sizes(svg)
    visible, placed_sizes = [], []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() != "text":
            continue
        text = " ".join("".join(element.itertext()).split())
        if text:
            visible.append(text)
        size = _text_font_size(element, classes)
        if size is not None and canvas_width > 0:
            placed_sizes.append(size * paper_width_pt / canvas_width)
    issues: list[str] = []
    if placed_sizes and min(placed_sizes) < minimum_pt:
        issues.append(
            f"placed SVG text falls below {minimum_pt:.1f} pt "
            f"(minimum {min(placed_sizes):.1f} pt)"
        )
    language = str(metadata.get("publication_language") or "").casefold()
    joined = " ".join(visible)
    if language == "en" and _CJK.search(joined):
        issues.append("English manuscript figure contains mixed CJK publication text")
    primary_groups = [
        child for child in list(root)
        if child.tag.rsplit("}", 1)[-1].casefold() == "g"
        and child.attrib.get("id")
        and child.attrib.get("data-role")
    ]
    maximum = int(contract.get("maximum_primary_nodes") or 12)
    if len(primary_groups) > maximum:
        issues.append(
            f"figure has {len(primary_groups)} primary visual groups; maximum is {maximum}; "
            "split independent scientific questions into separate assets"
        )
    return issues
