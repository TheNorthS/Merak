"""Draft scientific weaknesses remain distinct from explicit author-owned delivery defects."""

from types import SimpleNamespace
import pytest

from server.workflows.draft_audit_routing import draft_blocker_findings
from server.workflows.draft_delivery import draft_audit_gate
from server.workflows import draft_review_evidence


@pytest.mark.parametrize('source', ['literature/references.bib', 'paper/references.bib'])
def test_explicit_bibliography_owner_path_and_entry_selector_route_to_source(tmp_path, source):
    for name in ('literature/references.bib', 'paper/references.bib'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('@article{ref1,title={Existing source}}')
    finding, = draft_blocker_findings(tmp_path, [f'[owner={source}] [target=ref1] Correct conference type.'])
    assert finding['owner_node'] == 'lit'
    assert finding['legal_write_targets'] == ['literature/references.bib']
    assert 'Reviewer evidence selector: ref1' in finding['message']


def test_file_owner_cannot_grant_write_to_runtime_evidence(tmp_path):
    path = tmp_path / 'experiments/results/accepted_matrix.json'
    path.parent.mkdir(parents=True)
    path.write_text('{}')
    finding, = draft_blocker_findings(tmp_path, ['[owner=experiments/results/accepted_matrix.json] [target=matrix_id] Change it.'])
    assert finding['owner_node'] == 'audit'
    assert finding['legal_write_targets'] == ['audit-results/AUDIT_RESULTS.json']


def test_file_owner_cannot_hide_runtime_path_inside_source_traversal(tmp_path):
    (tmp_path / 'experiments/src').mkdir(parents=True)
    path = tmp_path / '.merak/state.json'
    path.parent.mkdir()
    path.write_text('{}')
    finding, = draft_blocker_findings(tmp_path, ['[owner=experiments/src/../../.merak/state.json] [target=status] Change it.'])
    assert finding['owner_node'] == 'audit'


def test_bibliography_role_alias_routes_to_canonical_literature_owner(tmp_path):
    for name in ('literature/references.bib', 'paper/references.bib'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('@article{ref1,title={Existing source}}')
    finding, = draft_blocker_findings(tmp_path, ['[owner=paper-bibliography] [target=paper/references.bib] Verify ref1.'])
    assert finding['owner_node'] == 'lit'
    assert finding['legal_write_targets'] == ['literature/references.bib']


def test_paper_authors_role_routes_only_existing_canonical_sections(tmp_path):
    targets = ['paper/sections/00_abstract.tex', 'paper/sections/04_experiments.tex']
    for name in targets:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Conditional interpretation')
    finding, = draft_blocker_findings(tmp_path, ['[owner=paper-authors] [target=' + '; '.join(targets) + '] Qualify interpretation.'])
    assert finding['owner_node'] == 'paper'
    assert finding['legal_write_targets'] == targets


@pytest.mark.parametrize('selector', ['liu2026compass', '42'])
def test_bibliography_location_suffix_routes_exact_file_and_preserves_locator(tmp_path, selector):
    for name in ('paper/references.bib', 'literature/references.bib'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('@article{liu2026compass,title={Verify title}}')
    finding, = draft_blocker_findings(tmp_path, [f'[owner=paper] [target=paper/references.bib:{selector}] Verify official metadata.'])
    assert finding['owner_node'] == 'lit'
    assert finding['legal_write_targets'] == ['literature/references.bib']
    assert f'paper/references.bib:{selector}' in finding['message']


def test_symbol_location_keeps_declared_scientific_owner(tmp_path):
    path = tmp_path / 'experiments/src/metrics.py'
    path.parent.mkdir(parents=True)
    path.write_text('def paired_condition_effect(): return 1')
    finding, = draft_blocker_findings(tmp_path, ['[owner=exp-design] [target=experiments/src/metrics.py::paired_condition_effect] Fix formula.'])
    assert finding['owner_node'] == 'exp-design'
    assert finding['legal_write_targets'] == ['experiments/src/metrics.py']


def test_unknown_reviewer_role_uses_canonical_source_owner(tmp_path):
    path = tmp_path / 'experiments/src/metrics.py'
    path.parent.mkdir(parents=True)
    path.write_text('def paired_condition_effect(): return 1')
    finding, = draft_blocker_findings(tmp_path, ['[owner=metrics] [target=experiments/src/metrics.py:paired_condition_effect] Check formula.'])
    assert finding['owner_node'] == 'exp-design'
    assert finding['target_files'] == ['experiments/src/metrics.py']


def test_generated_evidence_owner_never_grants_model_csv_write(tmp_path):
    path = tmp_path / 'experiments/results/simulated/claim_evidence.csv'
    path.parent.mkdir(parents=True)
    path.write_text('row_id,split_protocol\nclaim-1-2,subject_held_out')
    finding, = draft_blocker_findings(tmp_path, ['[owner=simulation-generator] [target=experiments/results/simulated/claim_evidence.csv:claim-1-2,claim-2-1] Fix provenance.'])
    assert finding['owner_node'] == 'exp-run'
    assert finding['producer_kind'] == 'deterministic'
    assert finding['legal_write_targets'] == []


@pytest.mark.parametrize('target', ['paper/../../outside.bib:key', 'paper/references.bib:../key', 'C:/secret.txt:42'])
def test_invalid_locator_cannot_grant_file_write(tmp_path, target):
    finding, = draft_blocker_findings(tmp_path, [f'[owner=paper] [target={target}] Repair'])
    assert finding['owner_node'] == 'audit'


def test_explicit_results_author_cannot_be_routed_to_experiment_by_inspected_evidence(tmp_path, monkeypatch):
    from server.workflows.engine import WorkflowEngine

    target = tmp_path / 'paper/sections/05_results.tex'
    target.parent.mkdir(parents=True)
    target.write_text('Existing numerical analysis')
    (tmp_path / 'audit-results').mkdir()
    artifact = tmp_path / 'audit-results/AUDIT_RESULTS.json'
    blocker = '[owner=paper] [target=paper/derived-figures/tex/sections/05_results.tex] Explain existing training curves; do not train.'
    entries = [{'layer': n, 'delivery_goal': 'reviewable_draft', 'method': 'model',
        'verdict': 'FAIL' if n == 2 else 'WARN', 'summary': 'Empirical mechanism remains untested',
        'evidence': ['experiments/RUN_SPEC.json'], 'draft_blockers': [blocker] if n == 2 else []}
        for n in range(1, 6)]
    monkeypatch.setattr(draft_review_evidence, 'draft_response_matches', lambda *_: True)
    gate = draft_audit_gate(SimpleNamespace(), {'entries': entries, 'proof_payload': {'verdict': 'WARN'}}, [artifact])
    assert not gate['accepted']
    findings = WorkflowEngine()._gate_revision_diagnostics(gate)['findings']
    assert findings and all(item['owner_node'] == 'paper' for item in findings)
    assert all(item['target_files'] == ['paper/sections/05_results.tex'] for item in findings)
    assert all('derived-figures' not in item['message'] for item in findings)


def test_unknown_or_foreign_target_requests_audit_correction_not_arbitrary_experiment(tmp_path):
    for blocker in ['Missing model response', '[owner=paper] [target=../outside.tex] Change this',
                    '[owner=results] [target=experiments/results/missing.csv] Repair missing evidence']:
        finding, = draft_blocker_findings(tmp_path, [blocker])
        assert finding['owner_node'] == 'audit'
        assert finding['target_files'] == ['audit-results/AUDIT_RESULTS.json']


def test_real_experiment_defect_still_routes_to_experiment_owner(tmp_path):
    target = tmp_path / 'experiments/RUN_SPEC.json'
    target.parent.mkdir()
    target.write_text('{}')
    finding, = draft_blocker_findings(tmp_path, ['[owner=exp-run] [target=experiments/RUN_SPEC.json] Resolve run provenance'])
    assert finding['owner_node'] == 'exp-run' and finding['target_files'] == ['experiments/RUN_SPEC.json']


def test_bibliography_projection_repairs_literature_source_not_paper_copy(tmp_path):
    for name in ['paper/references.bib', 'literature/references.bib']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('@article{ref,title={Original title}}')
    before = {name: (tmp_path / name).read_bytes() for name in ['paper/references.bib', 'literature/references.bib']}
    finding, = draft_blocker_findings(tmp_path, [
        '[owner=paper] [target=paper/references.bib] Verify the official title and author order.',
    ], layer=4)
    assert finding['owner_node'] == finding['upstream_node'] == 'lit'
    assert finding['target_files'] == finding['legal_write_targets'] == ['literature/references.bib']
    assert '[owner=lit]' in finding['message']
    assert '[target=literature/references.bib]' in finding['message']
    assert all((tmp_path / name).read_bytes() == content for name, content in before.items())


def test_standalone_bibliography_without_literature_source_is_not_redirected(tmp_path):
    path = tmp_path / 'paper/references.bib'
    path.parent.mkdir()
    path.write_text('@article{ref,title={Standalone}}')
    finding, = draft_blocker_findings(tmp_path, ['[owner=paper] [target=paper/references.bib] Verify title.'])
    assert finding['owner_node'] == 'paper'
    assert finding['target_files'] == ['paper/references.bib']


def test_risk_audit_uses_verified_draft_owner_instead_of_layer_default(tmp_path, monkeypatch):
    from server.services import risk_stage_audit
    target = tmp_path / 'paper/sections/05_results.tex'
    target.parent.mkdir(parents=True)
    target.write_text('Existing results')
    entries = [{'layer': n, 'managed_by': 'merak_audit_chain', 'evidence_mode': 'synthetic_preview',
        'delivery_goal': 'reviewable_draft', 'verdict': 'FAIL' if n == 3 else 'PASS',
        'summary': 'Describe existing results', 'details': 'Reviewed current records',
        'evidence': ['experiments/results/simulated/training_dynamics.csv'],
        'draft_blockers': ['[owner=paper] [target=paper/derived-figures/tex/sections/05_results.tex] Add analysis.'] if n == 3 else []}
        for n in range(1, 6)]
    monkeypatch.setattr(risk_stage_audit, '_json', lambda _: (entries, None))
    monkeypatch.setattr(risk_stage_audit, '_audit_binding', lambda *_: SimpleNamespace(audit_build_hashes_current=True))
    monkeypatch.setattr(risk_stage_audit, '_freshness_findings', lambda *_: [])
    monkeypatch.setattr(draft_review_evidence, 'draft_response_matches', lambda *_: True)
    findings = risk_stage_audit.audit(None, tmp_path, {'delivery_goal': 'reviewable_draft',
        'run_experiment': False, 'non_experiment_evidence_mode': 'synthetic_preview'})
    blocking = [item for item in findings if item['severity'] == 'blocker']
    assert len(blocking) == 1 and blocking[0]['owner_node'] == 'paper'
    assert blocking[0]['target_files'] == ['paper/sections/05_results.tex']
