"""Assigned intervals cannot be projected as confidence or replicate uncertainty."""

from server.services.simulation_interval_caption import scenario_interval_caption, scenario_table_captions, SCOPE_NOTE


def test_assigned_figure_captions_keep_disclosure_and_are_idempotent():
    for caption in (
        'Recorded differences relative to Study A, with fixed-configuration interval whiskers. ' + SCOPE_NOTE,
        'Generated stress-label trajectories with uncertainty bands and retention under the strongest perturbation.',
    ):
        text = scenario_interval_caption(caption, assigned_bounds=True)
        assert 'not intervals estimated from repeat configurations or population samples' in text
        assert 'uncertainty bands' not in text and 'fixed-configuration interval' not in text
        assert scenario_interval_caption(text, assigned_bounds=True) == text


def test_stress_header_and_caption_change_without_changing_data_or_primary_contract():
    source = r'''\begin{table*}
\caption{Recorded interval bounds summarize fixed scenario configurations; they do not establish population confidence coverage over Missing channel rate.}
\label{tab:preview-robustness-calibration}
\begin{tabular}{cccc}\toprule
Method & Rate & Score & 95\% interval \\
\midrule
Method A & 0.2 & 0.650 & [0.636, 0.664] \\
\bottomrule\end{tabular}\end{table*}'''
    text = scenario_table_captions(source)
    assert 'Assigned bounds' in text and r'95\% interval' not in text
    assert 'fixed scenario configurations' not in text
    assert source.split(r'\midrule')[1] == text.split(r'\midrule')[1]
    assert scenario_table_captions(text) == text
    primary = scenario_table_captions(source.replace('tab:preview-robustness-calibration','tab:primary'))
    assert r'95\% interval' in primary
