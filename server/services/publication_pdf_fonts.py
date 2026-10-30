"""Separate readable PDF text from evidenced math scripts and TeX small caps."""

import re
from typing import Any, Iterator


_MATH_FONT = re.compile(r"cmmi|cmsy|cmex|math|symbol", re.I)
_ROMAN_SCRIPT_FONT = re.compile(r"(?:^|\+)(?:cmr|cmbx)\d+|roman\d+", re.I)
_TEX_SERIF_FONT = re.compile(r"cmr\d+|roman|nimbusrom|times", re.I)
_TEX_8_PT_IN_PDF_BP = 8.0 * 72.0 / 72.27
_ROMAN_MATH_GLYPHS = re.compile(r"[\s=+−∆ΔΓΘΛΞΠΣΥΦΨΩ∑∏]+")


def _math_script(span: dict[str, Any], spans: list[dict[str, Any]]) -> bool:
    """A small roman span is a script only beside a larger math glyph off-baseline."""
    size = float(span.get("size") or 0)
    if not size or size >= 8.0 or not _ROMAN_SCRIPT_FONT.search(str(span.get("font") or "")):
        return False
    origin, box = span.get("origin"), span.get("bbox")
    if not origin or len(origin) != 2 or not box or len(box) != 4:
        return False
    for base in spans:
        base_size, base_origin, base_box = float(base.get("size") or 0), base.get("origin"), base.get("bbox")
        math_base = (_MATH_FONT.search(str(base.get("font") or "")) or (
            _ROMAN_SCRIPT_FONT.search(str(base.get("font") or ""))
            and (_ROMAN_MATH_GLYPHS.fullmatch(str(base.get("text") or ""))
                 or (re.fullmatch(r'[A-Za-z]{1,20}', str(base.get('text') or '').strip())
                     and _adjacent_math_operator(base, spans)))))
        if (not math_base or not str(base.get("text") or "").strip()
                or base_size < size * 1.15 or not base_origin or len(base_origin) != 2
                or not base_box or len(base_box) != 4):
            continue
        baseline_shift = abs(float(origin[1]) - float(base_origin[1]))
        gap = _script_left_edge(span, spans) - float(base_box[2])
        centered_annotation = (float(origin[1]) < float(base_origin[1])
            and 0.4 * base_size <= baseline_shift <= 1.4 * base_size
            and abs((float(box[0])+float(box[2])-float(base_box[0])-float(base_box[2]))/2 <= 0.4 * base_size
            and bool(_MATH_FONT.search(str(base.get('font') or '')))))
        if centered_annotation:
            return True
        if 0.1 * base_size <= baseline_shift <= 0.65 * base_size and -0.2 * base_size <= gap <= 0.5 * base_size:
            return True
    return False


def _adjacent_math_operator(base: dict, spans: list[dict]) -> bool:
    box, origin = base.get('bbox'), base.get('origin')
    if not box or not origin:
        return False
    for item in spans:
        other, position = item.get('bbox'), item.get('origin')
        math_operator = (_MATH_FONT.search(str(item.get('font') or '')) or
                         _ROMAN_MATH_GLYPHS.fullmatch(str(item.get('text') or '')))
        if (not other or not position or not math_operator
                or not str(item.get('text') or '').strip()
                or abs(float(position[1])-float(origin[1])) > 0.1 * float(base['size'])):
            continue
        if min(abs(float(box[0])-float(other[2])),abs(float(other[0])-float(box[2]))) < float(base['size']):
            return True
    return False


def _script_left_edge(span: dict[str, Any], spans: list[dict[str, Any]]) -> float:
    """Follow contiguous same-sized TeX math/script glyphs back to the larger base."""
    left = float(span["bbox"][0])
    size, baseline = float(span["size"]), float(span["origin"][1])
    for candidate in sorted(spans, key=lambda item: float((item.get("bbox") or [0])[0]), reverse=True):
        box, origin = candidate.get("bbox"), candidate.get("origin")
        if (not box or len(box) != 4 or not origin or len(origin) != 2
                or not (_MATH_FONT.search(str(candidate.get("font") or ""))
                        or _ROMAN_SCRIPT_FONT.search(str(candidate.get("font") or ""))
                        or (_TEX_SERIF_FONT.search(str(candidate.get("font") or ""))
                            and str(candidate.get("text") or "").strip() in {"-", "−"}))
                or not str(candidate.get("text") or "").strip()
                or abs(float(candidate.get("size") or 0) - size) > 0.02
                or abs(float(origin[1]) - baseline) > 0.05):
            continue
        if float(box[0]) < left and -0.02 <= left - float(box[2]) <= 0.08 * size:
            left = float(box[0])
    return left


def _tex_small_caps(span: dict[str, Any], spans: list[dict[str, Any]]) -> bool:
    """Recognize 8 TeX-pt small caps, not a tolerance for arbitrary PDF small text.

    PDF measures 72 bp/in while TeX uses 72.27 pt/in. A 10-pt serif capital
    followed by baseline-aligned 80%-size uppercase letters is TeX small caps;
    its declared 8-pt font is 7.970112 bp, not a reduced-size publication label.
    """
    text, font = str(span.get("text") or "").strip(), str(span.get("font") or "")
    size, origin = float(span.get("size") or 0), span.get("origin")
    if (not re.fullmatch(r"[A-Z][A-Z-]{2,}", text) or not _TEX_SERIF_FONT.search(font)
            or abs(size - _TEX_8_PT_IN_PDF_BP) > 0.0005 or not origin or len(origin) != 2
            or any(_MATH_FONT.search(str(item.get("font") or "")) for item in spans)):
        return False
    for base in spans:
        base_origin, base_size = base.get("origin"), float(base.get("size") or 0)
        if (str(base.get("font") or "") == font and re.fullmatch(r"[A-Z]", str(base.get("text") or "").strip())
                and base_size > 0 and base_origin and len(base_origin) == 2
                and abs(float(base_origin[1]) - float(origin[1])) < 0.01
                and abs(size / base_size - 0.8) < 0.0005):
            return True
    return False


def _visible_script_origin(span: dict) -> dict:
    """A PDF space may share a span with a shifted script but retain the base origin."""
    chars = span.get('chars')
    if not isinstance(chars, list):
        return span
    text = ''.join(str(char.get('c') or '') for char in chars)
    result = {**span, 'text': text}
    visible = [char for char in chars if str(char.get('c') or '').strip()]
    if text[:1].isspace() and visible and all(char.get('origin') and char.get('bbox') for char in visible):
        ys = [float(char['origin'][1]) for char in visible]
        if max(ys) - min(ys) < 0.05:
            result['origin'] = visible[0]['origin']
            result['bbox'] = [min(char['bbox'][0] for char in visible), min(char['bbox'][1] for char in visible),
                              max(char['bbox'][2] for char in visible), max(char['bbox'][3] for char in visible)]
    return result


def _readable_spans(page: Any) -> Iterator[tuple[dict[str, Any], float]]:
    blocks = [[{**line, 'spans': [_visible_script_origin(span) for span in line.get('spans', [])]}
               for line in block.get('lines', [])] for block in page.get_text('rawdict').get('blocks', [])]
    # PDF extraction can separate stacked scripts into blocks as well as lines.
    # The script matcher still requires a nearby larger math base with shifted origin.
    math_context = [span for lines in blocks for line in lines for span in line['spans']]
    for lines in blocks:
        for index, line in enumerate(lines):
            spans = line.get("spans", [])
            for span in spans:
                text, font = str(span.get("text") or "").strip(), str(span.get("font") or "")
                if _MATH_FONT.search(font) or _math_script(span, math_context):
                    continue
                if not (re.search(r"[A-Za-z]{3,}|[\u3400-\u9fff]{2,}", text)
                        or re.fullmatch(r"[+-]?\d+\.\d{2,}", text)):
                    continue
                size = float(span.get("size") or 0)
                if size > 0:
                    yield span, 8.0 if (_tex_small_caps(span, spans)
                        or _wrapped_small_caps(span, lines, index)) else size


def _wrapped_small_caps(span: dict, lines: list[dict], index: int) -> bool:
    """A wrapped heading inherits small-cap evidence only from an adjacent aligned all-cap line."""
    if not index or not re.fullmatch(r'[A-Z][A-Z-]{2,}', str(span.get('text') or '').strip()):
        return False
    current = [item for item in lines[index].get('spans', []) if str(item.get('text') or '').strip()]
    previous = [item for item in lines[index-1].get('spans', []) if str(item.get('text') or '').strip()]
    if not current or not previous or not any(_tex_small_caps(item, previous) for item in previous):
        return False
    if any(re.search(r'[a-z]', str(item.get('text') or '')) for item in previous):
        return False
    font = str(span.get('font') or '')
    if (not _TEX_SERIF_FONT.search(font) or any(str(item.get('font') or '') != font
            or abs(float(item.get('size') or 0) - _TEX_8_PT_IN_PDF_BP) > 0.0005
            or not re.fullmatch(r'[A-Z ,;:–—-]+', str(item.get('text') or '')) for item in current)):
        return False
    if any(not item.get('bbox') or not item.get('origin') for item in [*previous, *current]):
        return False
    left = min(float(item['bbox'][0]) for item in current)
    previous_left = min(float(item['bbox'][0]) for item in previous)
    distance = float(current[0]['origin'][1]) - float(previous[0]['origin'][1])
    return abs(left - previous_left) < 1.0 and 8.0 <= distance <= 15.0


def minimum_readable_font_pt(page: Any) -> float:
    """Keep full measured precision; geometry-only script evidence may exclude spans."""
    return min((size for _span, size in _readable_spans(page)), default=0.0)


def readable_font_findings(page: Any, minimum_pt: float = 8.0) -> list[dict[str, Any]]:
    """Locate every truly small visible prose/number span without rounding its size."""
    return [{"bbox": list(span.get("bbox") or []), "size_bp": float(span["size"]),
             "font": str(span.get("font") or ""), "text": str(span.get("text") or ""), "kind": "small_text"}
            for span, size in _readable_spans(page) if size < minimum_pt]
