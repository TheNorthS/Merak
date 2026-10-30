"""Geometric pruning preserves exhaustive collision decisions and avoids disjoint pairs."""

import random

import fitz

from server.services.pdf_review_inspection import _overlap_pairs


def _exhaustive(lines):
    count = 0
    for index, (left, _, owner) in enumerate(lines):
        for right, _, other in lines[index + 1:]:
            if owner == other:
                continue
            intersection = left & right
            if intersection.is_empty:
                continue
            smaller = min(max(1.0, float(left.get_area())), max(1.0, float(right.get_area())))
            count += float(intersection.get_area()) / smaller >= 0.15
    return count


def test_unsorted_multicolumn_math_geometry_matches_exhaustive_detection():
    rng = random.Random(471)
    lines = []
    for index in range(500):
        x, y = rng.uniform(0, 500), rng.uniform(0, 800)
        width, height = rng.uniform(0, 120), rng.uniform(0, 90)
        lines.append((fitz.Rect(x, y, x + width, y + height), "text", index % 40))
    lines.extend((fitz.Rect(*bounds), "edge", index + 1000) for index, bounds in enumerate([
        (0, 0, 20, 20), (20, 0, 40, 20), (0, 20, 20, 40),
        (0, 0, 0, 20), (0, 0, 20, 0), (5, 5, 15, 15),
    ]))
    rng.shuffle(lines)
    assert _overlap_pairs(lines) == _exhaustive(lines)


def test_disjoint_text_does_not_construct_quadratic_intersections():
    class CountedRect:
        intersections = 0

        def __init__(self, x, y):
            self.x0, self.y0, self.x1, self.y1 = x, y, x + 10, y + 10

        def __and__(self, other):
            CountedRect.intersections += 1
            return fitz.Rect(self.x0, self.y0, self.x1, self.y1) & fitz.Rect(
                other.x0, other.y0, other.x1, other.y1,
            )

    lines = [(CountedRect(column * 20, row * 20), "text", row * 20 + column)
             for row in range(100) for column in range(20)]
    assert _overlap_pairs(list(reversed(lines))) == 0
    assert CountedRect.intersections == 0
