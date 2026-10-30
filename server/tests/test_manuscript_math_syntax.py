"""Compiler-triggering math errors are rejected before section acceptance."""

import pytest

from server.services.manuscript_math_syntax import math_delimiter_issues


@pytest.mark.parametrize("text", [r"Seeds $13$, $42$, and $73$.", r"Price \$5; math $x^2$.",
    "Valid $x$. % unmatched $ in comment\n", r"\(x\) and \[x+y\].", r"$$x+y$$", r"\verb|$unfinished|", 
    "\\begin{verbatim}\n$\n\\end{verbatim}"])
def test_valid_math_and_literal_dollars_are_preserved(text):
    assert math_delimiter_issues(text) == []


@pytest.mark.parametrize("text", ["Seeds $13$, $42$, and $73; label fractions.\n\nFor $N$ tokens.",
    r"Missing $x", r"\(x\]", r"Closing \)"])
def test_unclosed_or_mismatched_math_is_reported_with_location(text):
    issues = math_delimiter_issues(text)
    assert issues and any("line" in issue for issue in issues)


@pytest.mark.parametrize('environment', ['equation', 'equation*', 'align', 'gather', 'multline*'])
def test_blank_paragraph_in_display_math_is_rejected_before_compile(environment):
    text = f'\\begin{{{environment}}}\n\nx=1\n\\end{{{environment}}}'
    assert any('paragraph break inside' in issue for issue in math_delimiter_issues(text))
    assert math_delimiter_issues(text.replace('\n\n', '\n')) == []


def test_comment_line_in_display_math_is_not_a_paragraph():
    assert math_delimiter_issues('\\begin{equation}\n% comment\nx=1\n\\end{equation}') == []
