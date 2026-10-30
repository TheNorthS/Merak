"""LaTeX projections for result plans that do not contain measurements."""

from __future__ import annotations

from typing import Any


def _latex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def planned_result_tables(
    ablation_settings: list[str],
    axis: str,
    levels: list[str],
    methods: list[str],
    metric: str,
    style: dict[str, Any],
) -> str:
    """Render registered table structure without inventing measurements."""
    archetype = str(style.get("study_archetype") or "generic_empirical")
    family_label = str(style.get("family_label") or "the selected field")
    captions = {
        "observational_cohort": "adjustment and specification sensitivity",
        "diagnostic_prognostic": "predictor, calibration, and validation sensitivity",
        "intervention_trial": "intervention-component and estimand sensitivity",
        "omics_discovery": "pipeline and biological-validation sensitivity",
        "controlled_experiment": "control-condition and mechanistic-factor analysis",
        "formal_theory": "assumption necessity and counterexamples",
        "qualitative_mixed": "alternative coding, negative cases, and triangulation",
    }
    analysis_caption = captions.get(archetype, "matched component and control analysis")
    ablations = "\n".join(f"{_latex(name)} & -- & -- \\\\" for name in ablation_settings)
    main_methods = "\n".join(f"{_latex(name)} & -- & -- \\\\" for name in methods)
    robustness = "\n".join(f"{_latex(level)} & -- & -- \\\\" for level in levels)
    return rf"""% Planning tables only. Replace -- with executed results.
\begin{{table}}[t]
\centering
\caption{{Registered primary-analysis design for {_latex(family_label)}.}}
\label{{tab:planned-main-results}}
\small
\begin{{tabular}}{{lcc}}
\toprule
Method / analysis & {_latex(metric)} & Uncertainty \\
\midrule
{main_methods}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{table}}[t]
\centering
\caption{{Registered {_latex(analysis_caption)} design.}}
\label{{tab:planned-ablation}}
\small
\begin{{tabular}}{{lcc}}
\toprule
Analysis / condition & Primary endpoint & Contrast \\
\midrule
{ablations}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{table}}[t]
\centering
\caption{{Registered validation and sensitivity design over {_latex(axis)}.}}
\label{{tab:planned-robustness}}
\small
\begin{{tabular}}{{lcc}}
\toprule
Condition & Comparator & Primary analysis \\
\midrule
{robustness}
\bottomrule
\end{{tabular}}
\end{{table}}
"""
