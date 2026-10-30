"""Only source-validated print outputs can differ from an interrupted refresh snapshot."""

import json

import pytest

from server.workflows.report_print_recovery import verified_print_refresh


@pytest.fixture
def receipt(tmp_path, monkeypatch):
    path = tmp_path / 'paper/derived-figures/PRINT_PROJECTION.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'sources': [{'original_path': 'paper/main.tex', 'output_path': 'paper/main.tex'},
        {'original_path': 'paper/assembly_method_figures.tex', 'output_path': 'paper/derived-figures/tex/assembly_method_figures.tex'}],
        'packets': [{'original_path': 'figures/method.pdf', 'output_path': 'paper/derived-figures/method/figure.pdf'}]}))
    monkeypatch.setattr('server.services.paper_print_projection.validate_print_projection', lambda root: [])
    return tmp_path


def test_current_verified_print_outputs_do_not_strand_failed_author_repair(receipt):
    assert verified_print_refresh(receipt, {'paper/main.tex': 'old', 'figures/method.pdf': 'old'},
                                  {'paper/main.tex': 'new', 'figures/method.pdf': 'new'})


@pytest.mark.parametrize('name', ['paper/sections/00_abstract.tex', 'experiments/results/summary.csv', 'figures/method.svg'])
def test_foreign_semantic_change_blocks_recovery(receipt, name):
    assert not verified_print_refresh(receipt, {name: 'old'}, {name: 'new'})


def test_tampered_projection_never_recovers(receipt, monkeypatch):
    monkeypatch.setattr('server.services.paper_print_projection.validate_print_projection', lambda root: ['Invalid overlay'])
    assert not verified_print_refresh(receipt, {'paper/main.tex': 'old'}, {'paper/main.tex': 'new'})
