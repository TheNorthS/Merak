"""Use actual PDF rendering to reject unreadable headers without imposing a theme."""

import hashlib
import json

import pymupdf
import pytest

from server.services.slide_rendered_contrast import slide_contrast_findings
from server.services.slide_scope_validation import bind_slide_repair_owners


def _deck(root, foreground, background):
    path = root / 'slides/main.pdf'
    path.parent.mkdir()
    with pymupdf.open() as document:
        page = document.new_page(width=450, height=250)
        page.draw_rect(pymupdf.Rect(0, 0, 450, 50), color=background, fill=background)
        page.insert_text((12, 30), 'Scientific evidence and its limits', fontsize=18, color=foreground)
        page.insert_text((20, 90), 'Actual study results remain unchanged', fontsize=14)
        document.save(path)
    (path.parent / 'SLIDE_BUILD.json').write_text(json.dumps({'compile': {
        'success': True, 'pdf_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))


def test_dark_teal_on_dark_header_is_a_slide_owned_blocker(tmp_path):
    _deck(tmp_path, (0, 107/255, 115/255), (32/255, 55/255, 58/255))
    before = (tmp_path / 'slides/main.pdf').read_bytes()
    finding, = bind_slide_repair_owners(slide_contrast_findings(tmp_path))
    assert finding['id'] == 'PPT-CONTRAST-001' and finding['severity'] == 'blocker'
    assert finding['owner_node'] == 'ppt' and finding['target_files'] == ['slides/main.tex']
    assert finding['contrast_evidence'][0]['page'] == 1
    assert (tmp_path / 'slides/main.pdf').read_bytes() == before


@pytest.mark.parametrize('foreground,background', [((1, 1, 1), (.12, .22, .23)), ((0, .42, .45), (1, 1, 1))])
def test_readable_themes_pass_without_prescribing_colors(tmp_path, foreground, background):
    _deck(tmp_path, foreground, background)
    assert slide_contrast_findings(tmp_path) == []


def test_unbound_changed_pdf_is_left_to_existing_build_validation(tmp_path):
    _deck(tmp_path, (0, .42, .45), (.12, .22, .23))
    with (tmp_path / 'slides/main.pdf').open('ab') as stream:
        stream.write(b'\n% changed')
    assert slide_contrast_findings(tmp_path) == []


def test_hash_bound_but_invalid_pdf_returns_blocker_instead_of_crashing(tmp_path):
    _deck(tmp_path, (1, 1, 1), (.12, .22, .23))
    path = tmp_path / 'slides/main.pdf'
    path.write_bytes(b'%PDF-1.4\nnot a real PDF')
    (path.parent / 'SLIDE_BUILD.json').write_text(json.dumps({'compile': {
        'success': True, 'pdf_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))
    finding, = slide_contrast_findings(tmp_path)
    assert finding['id'] == 'PPT-PDF-002' and finding['severity'] == 'blocker'


def test_tex_letter_spans_are_combined_before_contrast_measurement(tmp_path, monkeypatch):
    from server.services.slide_rendered_contrast import _low_contrast_spans
    _deck(tmp_path, (0, 107/255, 115/255), (32/255, 55/255, 58/255))
    with pymupdf.open(tmp_path / 'slides/main.pdf') as document:
        page = document[0]
        data = page.get_text('dict')
        line = data['blocks'][0]['lines'][0]
        original = line['spans'][0]
        line['spans'] = [{**original, 'text': char} for char in original['text']]
        monkeypatch.setattr(pymupdf.Page, 'get_text', lambda *_args, **_kwargs: data)
        assert _low_contrast_spans(page)[0]['contrast_ratio'] < 3
