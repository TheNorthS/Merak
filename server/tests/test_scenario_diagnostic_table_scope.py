"""Generated table labels cannot imply verified experimental matching."""

import re

from server.services.simulation_interval_caption import scenario_table_captions, DIAGNOSTIC_NOTE


def test_non_interval_diagnostic_changes_presentation_but_preserves_every_cell():
    source = r"""\begin{table*}
\caption{Generated settings. Each row changes one registered factor while retaining the named controls; effects are relative to MAMP-EEG.}
\label{tab:diagnostic}
\begin{tabular}{llll}
Changed factor & Matched controls & Primary effect & Worst-shift effect \\
\midrule
MAMP-EEG & data, split, seed set, and evaluation budget & +0.000 & +0.000 \\
Without correspondence & data, split, seed set, and evaluation budget & -0.012 & -0.015 \\
\bottomrule
\end{tabular}
\end{table*}"""
    updated = scenario_table_captions(source)
    assert "Matched controls" not in updated
    assert "Declared scenario fields" in updated and DIAGNOSTIC_NOTE in updated
    assert "not evidence of executed one-factor interventions" in updated
    body = lambda text: re.search(r"\\midrule(.*?)\\bottomrule", text, re.S).group(1)
    assert body(source) == body(updated)
    assert scenario_table_captions(updated) == updated


def test_unrelated_tables_are_unchanged():
    source = r"\begin{table}\caption{Observed results}\label{tab:other}A & B \\\end{table}"
    assert scenario_table_captions(source) == source
