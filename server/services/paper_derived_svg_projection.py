"""Bounded paper-only typography projection of an existing safe deterministic SVG."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET


def canonical_svg_identity(source: bytes) -> tuple:
    """Ignore namespace-prefix spelling only, never text, attributes or graph geometry.

Raw artifact hashes remain exact. This identity is for comparing the current
producer projection with its committed SVG after unrelated namespace registry
changes in the hosting process.
"""
    if b"<!DOCTYPE" in source or b"<!ENTITY" in source:
        raise ValueError("Canonical paper SVG identity refuses document entities")
    root = ET.fromstring(source)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("Canonical paper SVG identity requires an SVG source")

    def identity(element):
        return (element.tag, tuple(sorted(element.attrib.items())), element.text, element.tail,
                tuple(identity(child) for child in element))
    return identity(root)


def scaled_svg_typography(original: bytes, multiplier: float) -> bytes:
    """Keep all objects, paths, public text and relations; change only font sizes."""
    if not math.isfinite(multiplier) or not 1.0 <= multiplier <= 4.0:
        raise ValueError("Paper SVG font multiplier exceeds its bounded presentation scope")
    if b"<!DOCTYPE" in original or b"<!ENTITY" in original:
        raise ValueError("Paper SVG projection does not permit document entities")
    root = ET.fromstring(original)
    if root.tag.rsplit("}", 1)[-1] != "svg" or not root.get("viewBox"):
        raise ValueError("Paper SVG projection requires a bounded existing SVG canvas")
    before_text = "".join(root.itertext())
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"script", "foreignObject", "image", "use"} or any(
            key.rsplit("}", 1)[-1].casefold().startswith("on") or key.rsplit("}", 1)[-1] == "href"
            for key in element.attrib
        ):
            raise ValueError("Paper SVG projection refuses executable or externally bound artwork")
        if "font-size" in element.attrib:
            element.set("font-size", _font(element.attrib["font-size"], multiplier))
        if "style" in element.attrib:
            element.set("style", _style(element.attrib["style"], multiplier))
        if tag == "style" and element.text:
            element.text = _style(element.text, multiplier)
    if "".join(root.itertext()) != before_text and not any(
        element.tag.rsplit("}", 1)[-1] == "style" for element in root.iter()
    ):
        raise ValueError("Paper SVG projection changed visible or source-bound text")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _font(value: str, multiplier: float) -> str:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(px|pt)?", value.strip())
    if not match or float(match[1]) <= 0:
        raise ValueError("Paper SVG projection requires explicit positive font dimensions")
    return f"{float(match[1]) * multiplier:.8g}{match[2] or ''}"


def _style(value: str, multiplier: float) -> str:
    if "url(" in value.casefold() or "@import" in value.casefold():
        raise ValueError("Paper SVG presentation style cannot import external content")
    return re.sub(r"font-size\s*:\s*([0-9.]+(?:px|pt)?)",
                  lambda match: "font-size:" + _font(match[1], multiplier), value)
