"""The paper gate recognizes derived pixels only after exact source-identity proof."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import paper_print_projection as projection
from server.workflows.paper_acceptance_checks_2 import map_figure_graphics


@pytest.mark.parametrize('star', ['', '*'])
def test_graphic_mapping_retains_original_scientific_identity(tmp_path, monkeypatch, star):
    paper = tmp_path / 'paper'
    derived = paper / 'derived-figures/asset/figure.pdf'
    derived.parent.mkdir(parents=True)
    derived.write_bytes(b'%PDF-fixture')
    original = tmp_path / 'figures/original.pdf'
    called = []
    def canonical(root, graphic):
        called.append((root, graphic))
        assert graphic == derived
        return original
    monkeypatch.setattr(projection, 'canonical_print_graphic', canonical)
    context = SimpleNamespace(figure_blocks=[rf'\begin{{figure}}\includegraphics{star}{{derived-figures/asset/figure.pdf}}\label{{fig:result}}\end{{figure}}'],
                              figure_graphics_by_label={}, paper_root=paper, root=tmp_path,
                              manifest_outputs=[], problems=[])
    map_figure_graphics(context)
    assert context.figure_graphics_by_label == {'fig:result': {original}}
    assert called == [(tmp_path, derived)]
    assert context.problems == []


def test_invalid_projection_cannot_satisfy_scientific_figure_binding(tmp_path, monkeypatch):
    paper = tmp_path / 'paper'
    derived = paper / 'derived-figures/asset/figure.pdf'
    derived.parent.mkdir(parents=True)
    derived.write_bytes(b'%PDF-fixture')
    def invalid(*_args):
        raise ValueError('Wrong scientific pixels')
    monkeypatch.setattr(projection, 'canonical_print_graphic', invalid)
    context = SimpleNamespace(figure_blocks=[r'\includegraphics{derived-figures/asset/figure.pdf}\label{fig:result}'],
                              figure_graphics_by_label={}, paper_root=paper, root=tmp_path,
                              manifest_outputs=[], problems=[])
    map_figure_graphics(context)
    assert context.figure_graphics_by_label == {'fig:result': set()}
    assert context.problems == ['Wrong scientific pixels']


def test_foreign_printed_figure_path_does_not_map_to_original(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    derived = root / 'paper/derived-figures/asset/figure.pdf'
    monkeypatch.setattr(projection, 'validate_print_projection', lambda *_: [])
    monkeypatch.setattr(projection, '_payload', lambda *_: {'packets': [{'output_path': 'paper/derived-figures/other/figure.pdf',
                                                                      'original_path': 'figures/source.pdf'}]})
    with pytest.raises(ValueError, match='unique'):
        projection.canonical_print_graphic(root, derived)


def test_original_graphic_does_not_require_a_derived_receipt(tmp_path):
    original = tmp_path / 'figures/source.pdf'
    assert projection.canonical_print_graphic(tmp_path, original) == original.resolve()
