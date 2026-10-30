"""Confirm a conservative vertical separation gap in intersecting font envelopes."""

from typing import Any


def visible_vertical_gap(page: Any, left: Any, right: Any) -> bool:
    """Only a raster-proven separator between actual ink can clear font envelopes."""
    import fitz

    upper, lower = sorted((left, right), key=lambda rectangle: rectangle.y0)
    height = min(upper.height, lower.height)
    overlap = upper & lower
    if (height <= 0 or overlap.is_empty or overlap.height > 0.7 * height
            or lower.y0 - upper.y0 < 0.3 * height):
        return False
    # Only common horizontal coordinates can collide. Unrelated adjacent
    # equation glyphs outside that corridor must not erase a real separator.
    clip = fitz.Rect(max(upper.x0, lower.x0), min(upper.y0, lower.y0),
                     min(upper.x1, lower.x1), max(upper.y1, lower.y1))
    try:
        raster = page.get_pixmap(matrix=fitz.Matrix(8, 8), clip=clip, colorspace=fitz.csGRAY, alpha=False)
    except (ValueError, RuntimeError):
        return False
    if raster.width < 1 or raster.height < 8:
        return False
    samples, white_rows, ink_above = raster.samples, 0, False
    # Six full white rows (0.75 pt) across the collision corridor prove a
    # visible separator. Inspect the vertical union so rounding at the envelope
    # edge cannot discard the only separator row. A blank page cannot prove a
    # separation: visible ink is required on both sides of the white band.
    for row in range(raster.height):
        pixels = samples[row * raster.stride:row * raster.stride + raster.width]
        if pixels and min(pixels) >= 250:
            white_rows += 1
            continue
        band_start, band_end = (raster.y + row - white_rows) / 8, (raster.y + row) / 8
        if ink_above and white_rows >= 6 and band_start <= overlap.y1 and band_end >= overlap.y0:
            return True
        ink_above, white_rows = True, 0
    return False
