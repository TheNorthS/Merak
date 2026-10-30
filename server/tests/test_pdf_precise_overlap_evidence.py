"""Occupied span geometry avoids math envelope collisions but retains real ones."""

import fitz

from server.services.pdf_review_inspection import _inspect_page, _overlap_pairs, _text_geometry


class Page:
    def __init__(self, blocks):
        self.blocks = blocks

    def get_text(self, _mode):
        return {"blocks": self.blocks}


def _block(line_box, spans):
    return {"type": 0, "bbox": line_box, "lines": [{"bbox": line_box, "spans": spans}]}


def _span(text, box, size=10):
    return {"text": text, "bbox": box, "size": size, "font": "CMR10"}


def test_fraction_denominator_does_not_overlap_empty_line_envelope():
    page = Page([
        _block((10, 10, 70, 32), [_span("L =", (10, 20, 35, 30)), _span("1", (64, 10, 70, 20))]),
        _block((64, 25, 70, 35), [_span("2", (64, 25, 70, 35))]),
    ])
    _blocks, lines, _fonts = _text_geometry(page, fitz)
    assert len(lines) == 3
    assert _overlap_pairs(lines) == 0


def test_real_math_or_prose_collision_remains_blocking_inside_a_math_page():
    page = Page([
        _block((10, 10, 50, 30), [_span("Equation", (10, 10, 50, 20))]),
        _block((30, 12, 60, 24), [_span("Collision", (30, 12, 60, 24))]),
    ])
    _blocks, lines, _fonts = _text_geometry(page, fitz)
    assert _overlap_pairs(lines) == 1


def test_blank_spans_do_not_create_font_envelope_collisions():
    page = Page([
        _block((10, 10, 80, 30), [_span("visible", (10, 10, 35, 20)), _span(" ", (35, 10, 80, 30))]),
        _block((50, 20, 80, 30), [_span("other", (50, 20, 80, 30))]),
    ])
    _blocks, lines, _fonts = _text_geometry(page, fitz)
    assert _overlap_pairs(lines) == 0


def test_missing_span_geometry_keeps_conservative_line_bbox_fallback():
    page = Page([
        _block((10, 10, 50, 20), [{"text": "Unknown geometry", "size": 10}]),
        _block((20, 12, 60, 24), [_span("Collision", (20, 12, 60, 24))]),
    ])
    _blocks, lines, _fonts = _text_geometry(page, fitz)
    assert _overlap_pairs(lines) == 1


def test_inspection_preserves_exact_small_font_and_location_evidence(tmp_path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "Selective risk", fontsize=5.806700229644775, fontname="helv")
    page.insert_text((72, 120), "Independent scientific description", fontsize=10, fontname="helv")
    expected = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
    report = _inspect_page(page, 0, tmp_path, fitz)
    assert report["minimum_readable_font_pt"] == expected["size"]
    finding = report["readable_font_findings"][0]
    assert finding["size_bp"] == expected["size"]
    assert finding["bbox"] == list(expected["bbox"])
    assert finding["text"] == "Selective risk" and finding["kind"] == "small_text"
    assert finding["size_bp"] < 8
    document.close()
