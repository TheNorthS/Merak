"""Custom layout command names are not bibliography commands; nested citations still count."""
import pytest
from server.services.manuscript_text import citation_keys
from server.services.risk_validator_support import _citation_keys


@pytest.mark.parametrize('parse', [citation_keys, _citation_keys])
def test_layout_wrapper_prose_is_not_a_citation_key(parse):
    text = (r'\newcommand{\citefoot}[1]{\par #1}'
            r'\citefoot{Endpoint context: \cite{du2024,li2023}.}'
            r'\citecaption{Geometry, not a universal direction.}'
            r'\textcite[see][p. 2]{chen2021}')
    assert parse(text) == {'du2024', 'li2023', 'chen2021'}


@pytest.mark.parametrize('parse', [citation_keys, _citation_keys])
def test_real_unknown_citations_are_retained_for_bibliography_validation(parse):
    assert parse(r'\citefoot{\citep*{missing_key}} \citeauthor{real_key} \citeyearpar{year_key}') == {
        'missing_key', 'real_key', 'year_key'}
