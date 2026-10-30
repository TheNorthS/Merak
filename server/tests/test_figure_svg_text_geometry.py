"""Geometry checks use rendered PDF positions, not SVG font declarations."""

from pathlib import Path

import fitz

from server.services.figure_svg_text_geometry import rendered_svg_text_geometry


def test_detects_overlapping_rendered_labels(tmp_path: Path) -> None:
    path = tmp_path / "colliding.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=200)
    page.insert_text((40, 80), "First label", fontsize=18)
    page.insert_text((45, 84), "Second label", fontsize=18)
    document.save(path)
    document.close()

    findings = rendered_svg_text_geometry(path)
    assert any(item["kind"] == "text_collision" for item in findings)
    assert any(set(item["labels"]) == {"First label", "Second label"} for item in findings)


def test_nonoverlapping_labels_remain_clean(tmp_path: Path) -> None:
    path = tmp_path / "clean.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=200)
    page.insert_text((40, 80), "First label", fontsize=18)
    page.insert_text((40, 140), "Second label", fontsize=18)
    document.save(path)
    document.close()

    assert rendered_svg_text_geometry(path) == []
