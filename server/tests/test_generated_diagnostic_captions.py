"""Synthetic label comparisons cannot inherit executed-intervention wording."""

from server.services.simulation_interval_caption import scenario_interval_caption, scenario_table_captions


def test_generated_ablation_caption_excludes_causal_and_trainable_component_claim():
    original = "Objective and architecture ablation. Component-removal losses relative to the MAMP-EEG, with uncertainty whiskers."
    projected = scenario_interval_caption(original)
    assert "do not establish executed model removals" in projected
    assert "does not remove a trainable component" in projected
    assert "Component-removal losses" not in projected
    assert scenario_interval_caption(projected) == projected


def test_generated_table_correction_keeps_every_number_and_row_label():
    source = (r"\begin{table}\caption{Objective and architecture ablation. Component-removal losses relative to the MAMP-EEG, with uncertainty whiskers. "
        r"Each row changes one registered factor while retaining the named controls; effects are relative to MAMP-EEG.}"
        r"\label{tab:preview-ablation}Without Shift-specific mechanism test & 0.217 & [0.207, 0.227]\\\end{table}")
    projected = scenario_table_captions(source)
    assert "not evidence of executed one-factor interventions" in projected
    for literal in ("0.217", "0.207", "0.227", "Without Shift-specific mechanism test"):
        assert projected.count(literal) == source.count(literal)


def test_point_only_table_never_inherits_figure_whiskers_or_interval_summary():
    from server.services.simulation_interval_caption import SCOPE_NOTE
    caption = 'Component-removal losses relative to Method A, with uncertainty whiskers.'
    source = (r'\begin{table}\caption{' + caption + r'}\label{tab:ablation}'
              r'\begin{tabular}{ccc}Setting & Matched controls & Difference \\\midrule'
              r'Method B & same budget & -0.012 \\\bottomrule\end{tabular}\end{table}')
    projected = scenario_table_captions(source)
    assert 'This table reports point differences' in projected
    assert 'only in the corresponding figure' in projected
    assert ', with fixed-configuration interval whiskers' not in projected
    assert SCOPE_NOTE not in projected
    assert source.split(r'\midrule')[1] == projected.split(r'\midrule')[1]
    assert scenario_table_captions(projected) == projected
    assert ', with fixed-configuration interval whiskers' in scenario_interval_caption(caption)
