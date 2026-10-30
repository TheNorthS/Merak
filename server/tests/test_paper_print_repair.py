"""Print repair is local, bounded, source preserving and fails closed."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import paper_print_projection as projection
from server.services import paper_print_repair as repair
from server.services.paper_failure_details import paper_failure_details
from server.services.paper_layout_attribution import layout_repair_findings
from server.services.paper_layout_errors import PaperPublicationLayoutError


def _fixture(tmp_path, monkeypatch):
    from server.services import paper_derived_figure_rendering
    monkeypatch.setattr(paper_derived_figure_rendering, 'validate_derived_figure', lambda *_: [])
    paper = tmp_path / 'paper'
    (paper / 'sections').mkdir(parents=True)
    (tmp_path / 'figures').mkdir()
    (paper / 'derived-figures/asset').mkdir(parents=True)
    (tmp_path / 'figures/source.pdf').write_bytes(b'%PDF-source')
    (paper / 'derived-figures/asset/figure.pdf').write_bytes(b'%PDF-derived')
    main = paper / 'main.tex'
    main.write_text(r'\documentclass{article}\input{sections/01_results}', encoding='utf-8')
    section = paper / 'sections/01_results.tex'
    section.write_text(r'Reviewed conclusion.\includegraphics[width=.94\textwidth]{../figures/source.pdf}', encoding='utf-8')
    packet = {'asset_id': 'asset', 'original_path': 'figures/source.pdf',
              'output_path': 'paper/derived-figures/asset/figure.pdf'}
    return main, section, packet


def test_graphics_overlay_preserves_reviewed_sections_and_source_figures(tmp_path, monkeypatch):
    main, section, packet = _fixture(tmp_path, monkeypatch)
    original = section.read_bytes()
    graphic = (tmp_path / 'figures/source.pdf').read_bytes()
    projection.install_print_projection(tmp_path, [packet])
    assert projection.validate_print_projection(tmp_path) == []
    assert section.read_bytes() == original
    assert (tmp_path / 'figures/source.pdf').read_bytes() == graphic
    assert 'derived-figures/tex/sections/01_results.tex' in main.read_text()
    assert projection.original_print_inputs(tmp_path) == {'sections/01_results'}
    projection.restore_print_entrypoint(tmp_path)
    assert main.read_text() == r'\documentclass{article}\input{sections/01_results}'


@pytest.mark.parametrize('mutation', ['authored', 'projected', 'destination', 'missing_context', 'duplicate'])
def test_overlay_rejects_changed_or_forged_bound_content(tmp_path, monkeypatch, mutation):
    _main, section, packet = _fixture(tmp_path, monkeypatch)
    projection.install_print_projection(tmp_path, [packet])
    receipt = tmp_path / projection.RECEIPT
    payload = json.loads(receipt.read_text())
    if mutation == 'authored':
        section.write_text('New scientific conclusion.', encoding='utf-8')
    elif mutation == 'projected':
        row = next(row for row in payload['sources'] if 'sections/' in row['output_path'])
        path = tmp_path / row['output_path']
        path.write_text(path.read_text().replace('Reviewed', 'Altered'), encoding='utf-8')
        row['output_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif mutation == 'destination':
        payload['sources'][0]['output_path'] = '../outside.tex'
    elif mutation == 'missing_context':
        payload['source_context'].pop()
    else:
        payload['sources'].append(payload['sources'][0])
    receipt.write_text(json.dumps(payload), encoding='utf-8')
    assert projection.validate_print_projection(tmp_path)


def test_overlay_validates_reachable_unchanged_input_context(tmp_path, monkeypatch):
    main, _section, packet = _fixture(tmp_path, monkeypatch)
    common = tmp_path / 'paper/common.tex'
    common.write_text('Frozen context.', encoding='utf-8')
    main.write_text(main.read_text() + r'\input{common}', encoding='utf-8')
    projection.install_print_projection(tmp_path, [packet])
    assert projection.validate_print_projection(tmp_path) == []
    common.write_text('Changed context.', encoding='utf-8')
    assert projection.validate_print_projection(tmp_path)


def test_duplicate_figure_projection_is_rejected(tmp_path, monkeypatch):
    _main, _section, packet = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Duplicate'):
        projection.install_print_projection(tmp_path, [packet, packet])


def test_layout_error_keeps_exact_findings_and_attempt_budget():
    finding = {'id': 'LAYOUT-1', 'asset_ids': ['calibration'], 'target_files': ['figures/calibration.py'],
               'owner_node': 'figure', 'category': 'visual_layout', 'bbox': [1, 2, 3, 4]}
    error = PaperPublicationLayoutError(['font too small'], [finding], attempts=2)
    finding['asset_ids'].clear()
    details = paper_failure_details(error)
    assert details['repair_scope']['asset_ids'] == ['calibration']
    assert details['findings'][0]['bbox'] == [1, 2, 3, 4]
    assert details['local_layout_attempts'] == 2
    assert details['retryable'] is False
    assert details['stopped_for_deterministic_stage'] is True


@pytest.mark.asyncio
async def test_compile_uses_real_fresh_layout_gate_after_local_repair(tmp_path, monkeypatch):
    calls = []
    async def prepare(_root):
        calls.append('repair')
        return []
    async def compile(*_args, **_kwargs):
        calls.append('compile')
        return SimpleNamespace(success=True, pdf_path='verified.pdf')
    monkeypatch.setattr(repair, 'prepare_print_figures', prepare)
    monkeypatch.setattr(repair, 'inspect_compiled_paper', lambda *_: ({}, []))
    result = await repair.compile_print_verified_paper(SimpleNamespace(compile=compile), tmp_path)
    assert result.success and calls == ['repair', 'compile']


@pytest.mark.asyncio
async def test_unchanged_failed_geometry_does_not_repeat_compile_or_author(tmp_path, monkeypatch):
    calls = []
    async def prepare(_root):
        calls.append('repair')
        return []
    async def compile(*_args, **_kwargs):
        calls.append('compile')
        return SimpleNamespace(success=True, pdf_path='bad.pdf')
    monkeypatch.setattr(repair, 'prepare_print_figures', prepare)
    monkeypatch.setattr(repair, 'inspect_compiled_paper', lambda *_: ({}, ['bad geometry']))
    monkeypatch.setattr(repair, '_repairs', lambda *_: [])
    with pytest.raises(PaperPublicationLayoutError):
        await repair.compile_print_verified_paper(SimpleNamespace(compile=compile), tmp_path)
    assert calls == ['repair', 'compile']


def test_font_owner_requires_matching_source_glyph_evidence(tmp_path):
    fitz = pytest.importorskip('fitz')
    paper, figures = tmp_path / 'paper', tmp_path / 'figures'
    paper.mkdir()
    figures.mkdir()
    (paper / 'main.aux').write_text(r'\newlabel{fig:main}{{1}{2}}', encoding='utf-8')
    with fitz.open() as document:
        page = document.new_page(width=500, height=300)
        page.insert_text((40, 40), 'Calibration error', fontsize=12, fontname='helv')
        page.insert_text((40, 70), 'Coverage scale', fontsize=12, fontname='helv')
        source_spans = [span for block in page.get_text('dict')['blocks'] for line in block['lines'] for span in line['spans']]
        document.save(str(figures / 'main.pdf'))
    (figures / 'FIGURE_MANIFEST.json').write_text(json.dumps({'figures': [{
        'id': 'calibration', 'label': 'fig:main', 'source_path': 'figures/main.py', 'output_path': 'figures/main.pdf',
    }]}), encoding='utf-8')
    issue = 'page 2 has publication text below 8.0 pt (6.0 pt)'
    records = [{'text': span['text'], 'font': span['font'], 'size_bp': 6,
                'bbox': [coordinate * 0.5 for coordinate in span['bbox']]} for span in source_spans]
    evidence = records[0]
    layout = {'pages': [{'page': 2, 'readable_font_findings': records}]}
    findings = layout_repair_findings(tmp_path, [issue], 'report.json', layout=layout)
    assert findings[0]['asset_ids'] == ['calibration']
    assert findings[0]['location_evidence'][0]['bbox'] == evidence['bbox']
    evidence['text'] = 'Unrelated tiny prose'
    findings = layout_repair_findings(tmp_path, [issue], 'report.json', layout=layout)
    assert findings[0]['owner_node'] == 'paper'
    assert findings[0]['asset_ids'] == []
