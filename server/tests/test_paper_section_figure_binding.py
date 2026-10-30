"""Wrong author paths fail before read-only consistency/assembly starts."""
from server.tests.test_paper_asset_placement import _fixture, _figure
from server.services.paper_section_figure_binding import section_figure_binding_issues


def test_wrong_authored_figure_path_has_exact_section_repair(tmp_path):
    paths, _, _ = _fixture(tmp_path)
    path = paths['sections'] / '03_method.tex'
    path.write_text(_figure('fig:method-architecture', 'figures/generated_method_figures/method_architecture.pdf'))
    before = path.read_bytes()
    issues = section_figure_binding_issues(tmp_path, path.name)
    assert len(issues) == 1
    assert 'paper/sections/03_method.tex' in issues[0]
    assert '../figures/diagrams/method_architecture.pdf' in issues[0]
    assert path.read_bytes() == before
    path.write_text(_figure('fig:method-architecture', '../figures/diagrams/method_architecture.pdf'))
    assert section_figure_binding_issues(tmp_path, path.name) == []


def test_missing_float_can_be_assembled_but_duplicate_author_label_cannot(tmp_path):
    paths, _, _ = _fixture(tmp_path)
    path = paths['sections'] / '03_method.tex'
    assert section_figure_binding_issues(tmp_path, path.name) == []
    path.write_text(_figure('fig:method-architecture', '../figures/diagrams/method_architecture.pdf') * 2)
    assert section_figure_binding_issues(tmp_path, path.name)


def test_corrected_candidate_is_reviewed_without_reading_stale_canonical_text(tmp_path):
    from server.services.paper_candidate_transaction import PaperCandidate
    paths, _, _ = _fixture(tmp_path)
    path = paths['sections'] / '03_method.tex'
    path.write_text(_figure('fig:method-architecture', 'wrong.pdf'))
    before = path.read_bytes()
    with PaperCandidate(tmp_path, 'method', [path], lambda: 'inputs') as candidate:
        candidate.files[path].write_text(_figure('fig:method-architecture', '../figures/diagrams/method_architecture.pdf'))
        assert section_figure_binding_issues(tmp_path, path.name) == []
        assert path.read_bytes() == before
    assert section_figure_binding_issues(tmp_path, path.name)


def test_new_candidate_wrong_path_is_not_skipped_when_canonical_file_is_missing(tmp_path):
    from server.services.paper_candidate_transaction import PaperCandidate
    paths, _, _ = _fixture(tmp_path)
    path = paths['sections'] / '03_method.tex'
    path.unlink()
    with PaperCandidate(tmp_path, 'method', [path], lambda: 'inputs') as candidate:
        candidate.files[path].parent.mkdir(parents=True, exist_ok=True)
        candidate.files[path].write_text(_figure('fig:method-architecture', 'wrong.pdf'))
        assert section_figure_binding_issues(tmp_path, path.name)
    assert not path.exists()
