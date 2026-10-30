"""A shared failure label cannot add another producer to an explicitly scoped repair."""

from server.services.paper_consistency_findings import implicated_consistency_findings


def test_explicit_author_scope_excludes_runtime_sibling_with_same_review_label():
    author = {'id': 'author', 'category': 'model_consistency',
              'target_files': ['paper/sections/08_conclusion.tex'],
              'validation_issue': 'cross-section reviewer recorded FAIL',
              'message': 'cross-section reviewer recorded FAIL: qualify conclusion'}
    runtime = {'id': 'runtime', 'category': 'publication_table',
               'target_files': ['paper/tables/synthetic_preview_results.tex'],
               'validation_issue': 'cross-section reviewer recorded FAIL',
               'message': 'cross-section reviewer recorded FAIL: correct generated metric label'}
    selected = ['Target artifact: paper/sections/08_conclusion.tex', author['message']]
    assert implicated_consistency_findings(selected, [author, runtime]) == [author]
    assert implicated_consistency_findings(['cross-section reviewer recorded FAIL'], [author, runtime]) == [author, runtime]
