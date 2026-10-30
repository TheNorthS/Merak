"""Bounded slide language must not reopen an accepted manuscript."""

import pytest

from server.services.slide_scope_validation import has_bounded_slide_scope


@pytest.mark.parametrize('text', [
    'Current numbers are assigned scenario coordinates; no named corpus was acquired or trained here.',
    r'Deterministic table-generating scenario; not fitted EEG or subject-level inference.',
    'Both tables are generated scenario labels, not measured EEG effects.',
    r'Assigned \emph{scenario} coordinates, not independent EEG fits.',
    'Within the registered benchmark scope.', '确定性场景，尚未执行真实训练。',
])
def test_equivalent_scientific_scope_is_recognized(text):
    assert has_bounded_slide_scope(r'\begin{document}' + text + r'\end{document}')


@pytest.mark.parametrize('text', [
    'Our method outperforms every baseline.',
    '% deterministic scenario\nOur method wins.',
    r'\includegraphics{../figures/simulated/figure.pdf} Our method wins.',
    r'\newcommand{\note}{deterministic scenario}\begin{document}Our method wins.\end{document}',
])
def test_invisible_keyword_or_unbounded_claim_does_not_satisfy_scope(text):
    assert not has_bounded_slide_scope(text)


@pytest.mark.parametrize('finding_id', ['PPT-SIM-002', 'PPT-SOURCE-001', 'PPT-CLAIM-001',
                                      'PPT-CITE-001', 'PPT-FIG-001', 'PPT-FIG-002', 'PPT-FIG-003'])
def test_slide_defect_routes_to_slide_author_not_readonly_paper_or_figures(tmp_path, finding_id):
    from server.services.slide_scope_validation import bind_slide_repair_owners
    from server.workflows.engine import WorkflowEngine
    evidence = ['slides/main.tex', 'paper/main.tex', 'paper/references.bib', 'figures/FIGURE_MANIFEST.json']
    finding, = bind_slide_repair_owners([{'id': finding_id, 'severity': 'blocker',
        'category': 'evidence_state', 'message': 'Repair slide evidence scope', 'evidence': evidence}])
    diagnostics = WorkflowEngine()._gate_revision_diagnostics({'accepted': False, 'details': {'findings': [finding]}})
    row = next(row for row in diagnostics['findings'] if row['id'] == finding_id)
    assert row['owner_node'] == 'ppt'
    assert row['target_files'] == ['slides/main.tex']
    assert row['repair_capability'] == 'slide-source'
    assert finding['evidence'] == evidence


def test_actual_ppt_risk_entry_uses_equivalent_scope_and_explicit_slide_owner(tmp_path, monkeypatch):
    from server.services import risk_stage_ppt
    from server.services.scientific_slides import scientific_slide_service
    from server.tests.test_scientific_slides import _write_complete_synthetic_bundle
    _write_complete_synthetic_bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, 'benchmark')
    tex = tmp_path / 'slides/main.tex'
    monkeypatch.setattr(risk_stage_ppt, '_simulation_portfolio_findings', lambda *_: [])
    bounded = r'\documentclass{beamer}\begin{document}Current numbers are assigned scenario coordinates.\end{document}'
    tex.write_text(bounded, encoding='utf-8')
    options = {'run_experiment': False, 'non_experiment_evidence_mode': 'synthetic_preview'}
    assert not any(row['id'] == 'PPT-SIM-002' for row in risk_stage_ppt.audit(None, tmp_path, options))
    tex.write_text(bounded.replace('Current numbers are assigned scenario coordinates.', 'We prove superior EEG performance.'), encoding='utf-8')
    row = next(row for row in risk_stage_ppt.audit(None, tmp_path, options) if row['id'] == 'PPT-SIM-002')
    assert row['owner_node'] == 'ppt' and row['target_files'] == ['slides/main.tex']
