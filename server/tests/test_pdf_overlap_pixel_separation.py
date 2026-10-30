"""Shallow font-envelope intersections require a visible separator before acceptance."""

import fitz

from server.services.pdf_review_inspection import _overlap_pairs


def test_shallow_envelopes_with_clear_ink_gap_are_not_text_collisions():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "SUM", fontsize=10)
    page.insert_text((72, 115), "split axis", fontsize=10)
    lines = [(fitz.Rect(72, 89, 100, 106), "SUM", 0), (fitz.Rect(72, 103, 120, 118), "split axis", 1)]
    assert _overlap_pairs(lines) == 1
    assert _overlap_pairs(lines, page=page) == 0
    document.close()


def test_real_ink_inside_shallow_intersection_remains_blocking():
    document = fitz.open()
    page = document.new_page()
    page.draw_rect(fitz.Rect(72, 103, 120, 106), color=(0, 0, 0), fill=(0, 0, 0))
    lines = [(fitz.Rect(72, 89, 100, 106), "SUM", 0), (fitz.Rect(72, 103, 120, 118), "split axis", 1)]
    assert _overlap_pairs(lines, page=page) == 1
    document.close()


def test_same_baseline_and_deep_overlap_never_use_pixel_gap_exemption():
    document = fitz.open()
    page = document.new_page()
    lines = [(fitz.Rect(72, 90, 100, 110), "one", 0), (fitz.Rect(78, 92, 110, 112), "two", 1)]
    assert _overlap_pairs(lines, page=page) == 1
    document.close()


def test_tall_math_envelopes_with_actual_ink_separation_are_clear():
    document = fitz.open()
    page = document.new_page()
    page.draw_rect(fitz.Rect(72, 91, 110, 97), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(80, 101, 88, 104), color=(0, 0, 0), fill=(0, 0, 0))
    lines = [(fitz.Rect(72, 90, 110, 100), "preceding line", 0),
             (fitz.Rect(80, 93.6, 88, 104), "radical", 1)]
    assert _overlap_pairs(lines) == 1
    assert _overlap_pairs(lines, page=page) == 0
    document.close()


def test_deep_math_envelopes_with_actual_overprint_remain_blocking():
    document = fitz.open()
    page = document.new_page()
    page.draw_rect(fitz.Rect(72, 91, 110, 99), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(80, 96, 88, 104), color=(0, 0, 0), fill=(0, 0, 0))
    lines = [(fitz.Rect(72, 90, 110, 100), "preceding line", 0),
             (fitz.Rect(80, 93.6, 88, 104), "radical", 1)]
    assert _overlap_pairs(lines, page=page) == 1
    document.close()


def test_empty_raster_cannot_clear_intersecting_font_envelopes():
    document = fitz.open()
    page = document.new_page()
    lines = [(fitz.Rect(72, 90, 110, 100), "unverified", 0),
             (fitz.Rect(80, 93.6, 88, 104), "unverified", 1)]
    assert _overlap_pairs(lines, page=page) == 1
    document.close()


def test_adjacent_equation_ink_outside_collision_corridor_cannot_hide_separator():
    document = fitz.open()
    page = document.new_page()
    page.draw_rect(fitz.Rect(72, 91, 110, 96), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(80, 100, 84, 104), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(100, 95, 110, 104), color=(0, 0, 0), fill=(0, 0, 0))
    lines = [(fitz.Rect(72, 90, 110, 100), 'prose', 0),
             (fitz.Rect(80, 94, 84, 104), '[', 1)]
    assert _overlap_pairs(lines) == 1
    assert _overlap_pairs(lines, page=page) == 0
    page.draw_rect(fitz.Rect(80, 94, 84, 101), color=(0, 0, 0), fill=(0, 0, 0))
    assert _overlap_pairs(lines, page=page) == 1
    document.close()
