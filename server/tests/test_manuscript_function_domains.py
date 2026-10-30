"""Mathematical function domains are not Windows drives; real paths remain blocked."""

import pytest

from server.services.manuscript_language import find_visible_code_artifact_references


@pytest.mark.parametrize("wrapper", ["${}$", r"\({}\)", r"\[{}\]", r"\begin{{align}}{}\end{{align}}"])
@pytest.mark.parametrize("domain", [r"D:\mathbb{R}^{d}\to\mathbb{R}^{T}", r"f:\mathcal{X}\to Y"])
def test_mathematical_domain_does_not_spend_a_paper_repair_attempt(wrapper, domain):
    text = "The decoder is a shared map " + wrapper.format(domain) + "."
    assert find_visible_code_artifact_references(text) == []


@pytest.mark.parametrize("text, token", [
    (r"Read D:\mathbb\models.py", "models.py"),
    (r"Read D:\mathbb{R}", r"D:\mathbb"),
    (r"$\text{D:\results\metrics.csv}$", "metrics.csv"),
    (r"\[\text{experiments/results}\]", "experiments/results"),
    (r"$\texttt{torch.softmax}$", "torch.softmax"),
    (r"$\texttt{hidden_state}$", "hidden_state"),
    (r"$D:\mathbb{R} \quad \text{server/main.py}$", "main.py"),
])
def test_math_cannot_hide_actual_implementation_tokens(text, token):
    assert any(token in item for item in find_visible_code_artifact_references(text))
