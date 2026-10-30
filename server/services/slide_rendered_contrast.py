"""Detect unreadable native slide text against demonstrably uniform rendered backgrounds."""

from collections import Counter
from pathlib import Path


def _luminance(rgb: tuple[int, int, int]) -> float:
    channels = [value / 255 for value in rgb]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))


def _contrast(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    first, second = sorted((_luminance(foreground), _luminance(background)))
    return (second + .05) / (first + .05)


def _text_runs(page):
    """TeX often emits one PDF span per letter; inspect each same-style line run."""
    import pymupdf
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            current = None
            for span in line['spans']:
                if current and (current['color'], current['size']) == (span['color'], span['size']):
                    current['text'] += span['text']
                    current['bbox'] = pymupdf.Rect(current['bbox']) | pymupdf.Rect(span['bbox'])
                else:
                    if current:
                        yield current
                    current = dict(span)
            if current:
                yield current


def _low_contrast_spans(page) -> list[dict]:
    from PIL import Image
    import pymupdf

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csRGB, alpha=False)
    raster = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
    findings = []
    for span in _text_runs(page):
        text = span['text'].strip()
        if len(text) < 8 or span['size'] < 8:
            continue
        rect = (pymupdf.Rect(span['bbox']) + (-1, -2, 1, 2)) & page.rect
        box = (max(0, int(rect.x0)), max(0, int(rect.y0)), min(pixmap.width, int(rect.x1)), min(pixmap.height, int(rect.y1)))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        cropped = raster.crop(box)
        pixels = cropped.load()
        colors = Counter(pixels[x, y] for y in range(cropped.height) for x in range(cropped.width))
        background, count = colors.most_common(1)[0]
        area = (box[2] - box[0]) * (box[3] - box[1])
        foreground = tuple((span['color'] >> shift) & 255 for shift in (16, 8, 0))
        ratio = _contrast(foreground, background)
        if count / area >= .65 and foreground != background and ratio < 3:
            findings.append({'page': page.number + 1, 'text': text[:160], 'contrast_ratio': round(ratio, 2)})
    return findings


def slide_contrast_findings(root: Path) -> list[dict]:
    """Only a current compiled PDF is eligible; do not diagnose a stale preview."""
    import hashlib
    import json
    import pymupdf
    from .risk_artifact_support import _finding

    pdf, receipt = root / 'slides/main.pdf', root / 'slides/SLIDE_BUILD.json'
    if not pdf.is_file() or not receipt.is_file():
        return []
    build = json.loads(receipt.read_text(encoding='utf-8-sig')).get('compile', {})
    if not build.get('success') or build.get('pdf_sha256') != hashlib.sha256(pdf.read_bytes()).hexdigest():
        return []
    try:
        with pymupdf.open(pdf) as document:
            failures = [item for page in document for item in _low_contrast_spans(page)]
    except pymupdf.FileDataError:
        return [_finding('PPT-PDF-002', 'blocker', 'slides', 'Slide PDF cannot be decoded for visual inspection.',
            '演示 PDF 无法解码，不能完成可读性检查。', ['slides/main.pdf'],
            'Recompile a valid slide PDF from slides/main.tex.', target_files=['slides/main.tex'])]
    if not failures:
        return []
    pages = sorted({item['page'] for item in failures})
    finding = _finding('PPT-CONTRAST-001', 'blocker', 'layout',
        f'Rendered slide text has contrast below 3:1 on a uniform background on pages {pages}.',
        f'演示页 {pages} 的可见文字与实际背景对比度不足，投影后难以辨认。',
        ['slides/main.pdf', 'slides/main.tex'],
        'Repair foreground/background colors in slides/main.tex; preserve scientific content and figures, then recompile.',
        target_files=['slides/main.tex'])
    finding['contrast_evidence'] = failures
    return [finding]
