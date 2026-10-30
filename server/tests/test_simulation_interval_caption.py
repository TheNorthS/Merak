"""Scientific interval wording changes neither measured cells nor evidence identities."""

import re

from server.services.simulation_interval_caption import scenario_interval_caption, scenario_table_captions, SCOPE_NOTE


def test_caption_qualifies_population_inference_and_is_idempotent():
    text = "Primary method comparison with 95% confidence intervals."
    updated = scenario_interval_caption(text)
    assert "95% scenario intervals" in updated and SCOPE_NOTE in updated
    assert scenario_interval_caption(updated) == updated
    assert scenario_interval_caption("Architecture overview.") == "Architecture overview."


def test_generated_risk_bounds_are_not_described_as_uncertainty():
    text = 'Task calibration and risk coverage. Retained-coverage versus risk curves with uncertainty bands.'
    updated = scenario_interval_caption(text)
    assert 'assigned scenario bounds' in updated and 'uncertainty bands' not in updated
    assert scenario_interval_caption(updated) == updated


def test_calibration_caption_preserves_assigned_range_provenance_after_full_projection():
    from server.services.simulation_calibration_table import render_dataset_calibration
    from server.services.paper_table_source_labels import selected_table_source_records
    rows = [{'dataset': 'Task A', 'method': name, 'coverage': '0.5',
             'risk': '0.129', 'risk_ci_low': '0.119', 'risk_ci_high': '0.139'}
            for name in ('Method A', 'Method B')]
    original = render_dataset_calibration(rows, 'tab:preview-calibration', 'Coverage', 'Risk')
    projected = scenario_table_captions(original)
    caption = selected_table_source_records(projected)['tab:preview-calibration']['caption']
    assert 'generator-declared scenario ranges' in caption
    assert 'fixed scenario configurations' not in caption
    assert 'not intervals estimated from repeat configurations or population samples' in caption
    assert projected.split(r'\midrule')[1] == original.split(r'\midrule')[1]
    assert scenario_table_captions(projected) == projected


def test_unrelated_analysis_and_figure_captions_remain_byte_identical():
    text = 'Primary comparison with 95% scenario intervals.'
    assert scenario_interval_caption(text) == (text + ' Recorded interval bounds summarize fixed scenario '
        'configurations; they do not establish population confidence coverage.')


def test_table_projection_preserves_labels_and_every_numeric_cell():
    text = r"""\begin{table*}
\caption{Matched results with 95\% confidence intervals.}
\label{tab:primary}
\begin{tabular}{cc}\toprule
Method & 95\% CI \\
\midrule
Method A & 0.032 [0.022, 0.042] \\
Method B & 0.129 [0.119, 0.139] \\
\bottomrule\end{tabular}
\end{table*}"""
    updated = scenario_table_captions(text)
    assert SCOPE_NOTE in updated and r"\label{tab:primary}" in updated
    assert r"95\% CI" not in updated and r"95\% interval" in updated
    assert re.findall(r"\d+(?:\.\d+)?", updated) == re.findall(r"\d+(?:\.\d+)?", text)
    assert updated.split(r"\midrule")[1] == text.split(r"\midrule")[1]
    assert scenario_table_captions(updated) == updated
