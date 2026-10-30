"""Long stress labels retain every exact row in a bounded, grouped table."""

import pytest

from server.services.simulation_robustness_table import bounded_robustness_table


def _source():
    rows = [{"method": name, "rate": str(index / 10), "value": str(.7-index/10),
             "ci_low": str(.69-index/10), "ci_high": str(.71-index/10)}
            for name in ("Long source-conditioned masked prediction model name", "Full named matched control with coordinate provenance")
            for index in range(5)]
    body = "\n".join(f"{row['method']} & {row['rate']} & {row['value']} & [{row['ci_low']}, {row['ci_high']}] " + r"\\" for row in rows)
    return rows, r"\begin{table*}\caption{Stress comparison}\label{tab:stress}\midrule" + "\n" + body + "\n" + r"\bottomrule\end{table*}"


def test_grouped_table_preserves_exact_values_labels_and_is_idempotent():
    rows, source = _source()
    result = bounded_robustness_table(source, rows, "rate", "Missing-channel rate", "Normalized task accuracy")
    assert r"\label{tab:stress}" in result and "p{0.91\\linewidth}" in result
    for row in rows:
        assert f"{row['rate']} & {row['value']} & [{row['ci_low']}, {row['ci_high']}]" in result
    assert result.count(rows[0]["method"]) == 1
    assert bounded_robustness_table(result, rows, "rate", "Missing-channel rate", "Normalized task accuracy") == result


def test_stress_table_rejects_altered_value_instead_of_regenerating_it():
    rows, source = _source()
    with pytest.raises(ValueError, match="rows do not match"):
        bounded_robustness_table(source.replace("0.7 &", "0.8 &", 1), rows, "rate", "Rate", "Accuracy")
def test_grouped_table_refreshes_only_caption_without_weakening_row_identity():
    from server.services.simulation_robustness_table import _render, bounded_robustness_table

    rows = [{"method": "A long scientific condition name with a matched resource budget",
             "severity": "0.2", "value": "0.600", "ci_low": "0.500", "ci_high": "0.700"}]
    block = _render(rows, "severity", "Removal rate", "Stress comparison; Endpoint: Old metric scale.", "tab:stress")
    result = bounded_robustness_table(block, rows, "severity", "Removal rate", "Assigned unitless scenario score")
    assert "Old metric scale" not in result
    assert "Assigned unitless scenario score" in result
    assert "0.600" in result and "0.500" in result and "0.700" in result
    with pytest.raises(ValueError, match="frozen rows"):
        bounded_robustness_table(block.replace("0.600", "0.999"), rows, "severity", "Removal rate",
                                 "Assigned unitless scenario score")


def test_short_table_still_relabels_assigned_coordinate_without_changing_values():
    rows = [{'method': 'A', 'rate': '0.1', 'value': '0.6', 'ci_low': '0.5', 'ci_high': '0.7'}]
    source = (r'\begin{table*}\caption{Stress}\label{tab:stress}\toprule' + '\n'
              + r'Method & Rate & Measured sensitivity & 95\% CI \\' + '\n' + r'\midrule' + '\n'
              + r'A & 0.1 & 0.6 & [0.5, 0.7] \\' + '\n' + r'\bottomrule\end{table*}')
    result = bounded_robustness_table(source, rows, 'rate', 'Rate', 'Assigned unitless scenario score')
    assert 'Measured sensitivity' not in result
    assert 'Assigned unitless scenario score' in result
    assert r'A & 0.1 & 0.6 & [0.5, 0.7]' in result
    assert bounded_robustness_table(result, rows, 'rate', 'Rate', 'Assigned unitless scenario score') == result

