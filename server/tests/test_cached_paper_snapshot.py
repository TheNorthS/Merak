"""No-model QA fingerprints the science, source figures, authors and real traces."""

from scripts.verify_cached_paper_snapshot import AuthorRequired, protected_files, verified_result
import pytest


def test_cached_paper_fingerprint_keeps_science_authorship_and_invocations(tmp_path):
    files = ['ideas/SELECTED_IDEA.json', 'experiments/results/frozen.csv', 'literature/references.bib',
             'figures/source.svg', 'paper/sections/05_results.tex', 'paper/TITLE.txt',
             'paper/CONTRIBUTION_BLUEPRINT.md', '.merak/runs/run.json', '.merak/agent-sessions/session.json',
             '.merak/skill-invocations/call.json']
    for relative in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    assert set(protected_files(tmp_path)) == set(files)
    before = protected_files(tmp_path)
    (tmp_path / 'paper/sections/05_results.tex').write_text('Modified scientific statement')
    assert protected_files(tmp_path) != before


def test_runtime_derived_publication_outputs_are_not_scientific_fingerprints(tmp_path):
    output = tmp_path / 'paper/derived-figures/asset/figure.pdf'
    output.parent.mkdir(parents=True)
    output.write_bytes(b'%PDF-derived')
    (tmp_path / 'paper/DRAFT_STATE.json').write_text('{"local_revalidation":true}')
    assert protected_files(tmp_path) == {}


def test_author_boundary_cannot_be_swallowed_as_a_transport_result():
    boundary = AuthorRequired('results')
    assert boundary.stage == 'results'
    assert isinstance(boundary, BaseException)
    assert not isinstance(boundary, Exception)


@pytest.mark.parametrize('flag', ['draft_completed', 'paper_source_gate_passed', 'protected_files_unchanged',
                                 'compile_success', 'post_compile_final_gate_passed', 'paper_build_binding_passed'])
def test_empty_issue_list_never_proves_a_failed_or_missing_gate(flag):
    result = {name: True for name in ('draft_completed', 'paper_source_gate_passed', 'protected_files_unchanged',
                                     'compile_success', 'post_compile_final_gate_passed', 'paper_build_binding_passed')}
    result.update({'issues': [], 'errors': [], 'model_invoked': False})
    assert verified_result(result, do_compile=True)
    result[flag] = False
    assert not verified_result(result, do_compile=True)
    result.pop(flag)
    assert not verified_result(result, do_compile=True)
