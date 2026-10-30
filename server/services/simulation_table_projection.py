"""Project deterministic simulation records into publication LaTeX tables."""

from __future__ import annotations

import re
from typing import Any

from .publication_labels import publication_outcome_label, publication_metric_label
from .simulation_score_label import scenario_score_label


def _latex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def simulation_tables(
    main_rows: list[dict[str, str]],
    ablation_rows: list[dict[str, str]],
    robustness_rows: list[dict[str, str]],
    calibration_rows: list[dict[str, str]],
    efficiency_rows: list[dict[str, str]],
    case_rows: list[dict[str, str]],
    claim_evidence_rows: list[dict[str, str]],
    paired_rows: list[dict[str, str]],
    axis: str,
    metric: str,
    asset_profile: dict[str, Any],
    metric_direction: str,
) -> str:
    """Render the complete, auditable simulation table bundle."""
    from .simulation_publication_names import named_focal_caption

    assets = asset_profile["assets"]
    field = str(asset_profile["sensitivity_field"])
    focal_name = str(ablation_rows[0].get(field) or "") if ablation_rows else ""
    if not focal_name:
        raise ValueError("Simulation table producer has no declared focal condition for matched ablation")
    main = _main_table(main_rows, metric, asset_profile, metric_direction)
    bodies = _analysis_bodies(
        ablation_rows, robustness_rows, calibration_rows, efficiency_rows,
        case_rows, axis, asset_profile,
    )
    replacements = {
        "MAIN_CAPTION": _caption(assets["main"], "table_description"),
        "MAIN_LABEL": assets["main"]["table_label"],
        **main,
        "PAIRED_BODY": _paired_body(paired_rows),
        "CLAIM_BODY": _claim_body(claim_evidence_rows),
        "COVERAGE_CAPTION": _caption(assets["coverage"]),
        "COVERAGE_LABEL": assets["coverage"]["table_label"],
        "COVERAGE_X": _latex(str(asset_profile["coverage_x_label"])),
        "COVERAGE_Y": _latex(str(asset_profile["coverage_y_label"])),
        "SENSITIVITY_CAPTION": _latex(named_focal_caption(
            str(assets["sensitivity"]["description"]), focal_name,
        ).rstrip(".!?;: ")),
        "FOCAL_CONDITION": _latex(focal_name),
        "SENSITIVITY_LABEL": assets["sensitivity"]["table_label"],
        "ROBUSTNESS_CAPTION": _caption(assets["robustness"]),
        "ROBUSTNESS_LABEL": assets["robustness"]["table_label"],
        "BURDEN_CAPTION": _caption(assets["burden"]),
        "BURDEN_LABEL": assets["burden"]["table_label"],
        "CASE_CAPTION": _caption(assets["case_analysis"]),
        "CASE_LABEL": assets["case_analysis"]["table_label"],
        "AXIS": _latex(publication_metric_label(axis)),
        "METRIC": _latex(metric),
        "SLICE_LABEL": _latex(str(asset_profile["slice_label"])),
        "SLICE_METRIC": _latex(str(asset_profile["slice_metric_axis_label"])),
        **bodies,
    }
    rendered = _substitute(_TABLE_TEMPLATE, replacements)
    from .simulation_calibration_table import has_dataset_calibration, render_dataset_calibration
    if has_dataset_calibration(calibration_rows):
        blocks = re.findall(r"\\begin\{table\*\}.*?\\end\{table\*\}", rendered, re.DOTALL)
        original = next(block for block in blocks if r"\label{" + replacements["COVERAGE_LABEL"] + "}" in block)
        bounded = render_dataset_calibration(calibration_rows, replacements["COVERAGE_LABEL"],
            "Retained coverage", "Risk")
        rendered = rendered.replace(original, bounded.rstrip("\n"), 1)
    from .simulation_primary_table import needs_primary_matrix, render_primary_comparison_panels
    if needs_primary_matrix(main_rows):
        first = re.search(r"\\begin\{table\*\}.*?\\end\{table\*\}", rendered, re.DOTALL)
        if first is None:
            raise ValueError("Primary simulation table producer template is absent")
        bounded = render_primary_comparison_panels(main_rows, scenario_score_label(metric), replacements["MAIN_CAPTION"], replacements["MAIN_LABEL"])
        rendered = rendered[:first.start()] + bounded + rendered[first.end():]
    from .simulation_interval_caption import scenario_table_captions
    return scenario_table_captions(_select_manuscript_tables(rendered, asset_profile))


def _select_manuscript_tables(rendered: str, profile: dict[str, Any]) -> str:
    from .simulation_table_portfolio import selected_simulation_table_bindings

    allowed_labels = {binding.label for binding in selected_simulation_table_bindings(profile)}
    blocks = re.findall(
        r"\\begin\{table\*?\}.*?\\end\{table\*?\}", rendered, re.DOTALL,
    )
    selected = [
        block for block in blocks
        if any(re.search(r"\\label\{" + re.escape(label) + r"(?:-panel-(?:[2-9]|[1-9][0-9]+))?\}", block)
               for label in allowed_labels if label)
    ]
    observed = [label for block in selected for label in re.findall(r"\\label\{([^}]+)\}", block)]
    bases = {re.sub(r"-panel-(?:[2-9]|[1-9][0-9]+)$", "", label) for label in observed}
    if bases != allowed_labels or len(observed) != len(set(observed)) or not allowed_labels <= set(observed):
        raise ValueError("Selected simulation table portfolio has missing or duplicate rendered labels")
    return "% Contribution-driven manuscript table portfolio\n" + "\n\n".join(selected) + "\n"


def _main_table(
    rows: list[dict[str, str]], metric: str,
    profile: dict[str, Any], direction: str,
) -> dict[str, str]:
    datasets = list(dict.fromkeys(str(row.get("dataset") or "aggregate") for row in rows))
    multi_task = len(datasets) > 1
    compact = len(datasets) > 2
    best, second = _ranked_rows(rows, datasets if multi_task else ["__all__"], direction)

    def emphasis(value: str, index: int) -> str:
        if index in best:
            return rf"\textbf{{{value}}}"
        return rf"\underline{{{value}}}" if index in second else value

    body = "\n".join(
        _main_row(row, index, emphasis, multi_task, compact)
        for index, row in enumerate(rows)
    )
    offset = 1 if multi_task else 0
    if compact:
        return {
            "MAIN_BODY": body,
            "MAIN_COLUMN_SPEC": "p{0.24\\textwidth} X c",
            "MAIN_HEADER": "Dataset / task & Method & {} [95\\% CI] \\\\".format(_latex(metric)),
            "MAIN_CMIDRULE": "", "MAIN_SUBHEADER": "",
        }
    return {
        "MAIN_BODY": body,
        "MAIN_COLUMN_SPEC": "X X c c c c" if multi_task else "X c c c c",
        "MAIN_HEADER": (
            "Dataset / task & " if multi_task else ""
        ) + "Method & \\multicolumn{1}{c}{Primary endpoint} & \\multicolumn{3}{c}{Complementary endpoints} \\\\",
        "MAIN_CMIDRULE": rf"\cmidrule(lr){{{2 + offset}-{2 + offset}}}\cmidrule(lr){{{3 + offset}-{5 + offset}}}",
        "MAIN_SUBHEADER": (" &" if multi_task else "") + " & {} [95\\% CI] & {} & {} & {} \\\\".format(
            _latex(metric), _latex(str(profile["main_secondary_label"])),
            _latex(str(profile["main_stress_label"])),
            _latex(str(profile["main_calibration_label"])),
        ),
    }


def _ranked_rows(
    rows: list[dict[str, str]], groups: list[str], direction: str,
) -> tuple[set[int], set[int]]:
    best: set[int] = set()
    second: set[int] = set()
    for dataset in groups:
        candidates = [
            index for index, row in enumerate(rows)
            if dataset == "__all__" or str(row.get("dataset") or "aggregate") == dataset
        ]
        ranked = sorted(
            candidates, key=lambda index: float(rows[index]["value"]),
            reverse=direction == "maximize",
        )
        if ranked:
            best.add(ranked[0])
        if len(ranked) > 1:
            second.add(ranked[1])
    return best, second


def _main_row(
    row: dict[str, str], index: int, emphasis: Any,
    multi_task: bool, compact: bool,
) -> str:
    interval = f"{_latex(row['value'])} [{_latex(row['ci_low'])}, {_latex(row['ci_high'])}]"
    cells = []
    if multi_task:
        cells.append(_latex(row.get("dataset") or "Dataset"))
    cells.extend([emphasis(_latex(row["method"]), index), emphasis(interval, index)])
    if not compact:
        cells.extend([
            _latex(row["secondary_value"]), _latex(row["stress_value"]),
            _latex(row["calibration_value"]),
        ])
    return " & ".join(cells) + r" \\"


def _analysis_bodies(
    ablation: list[dict[str, str]], robustness: list[dict[str, str]],
    calibration: list[dict[str, str]], efficiency: list[dict[str, str]],
    cases: list[dict[str, str]], axis: str, profile: dict[str, Any],
) -> dict[str, str]:
    sensitivity_field = str(profile["sensitivity_field"])
    slice_field = str(profile["slice_field"])
    def bold(value: str, enabled: bool) -> str:
        return rf"\textbf{{{value}}}" if enabled else value
    headers = [
        str(efficiency[0].get(f"resource_{index}_label") or f"Resource {index}")
        for index in range(1, 6)
    ]
    return {
        "ABLATION_BODY": "\n".join("{} & {} & {} & {} & {} & {} \\\\".format(
            bold(_latex(row[sensitivity_field]), index == 0),
            _latex(row.get("matched_controls") or "Matched protocol"),
            bold(_latex(row.get("primary_effect_vs_full") or row["delta"]), index == 0),
            _latex(row.get("worst_shift_effect_vs_full") or "--"),
            _latex(row.get("calibration_error_change_vs_full") or "--"),
            _latex(row.get("reversal_count_change_vs_full") or "0"),
        ) for index, row in enumerate(ablation)),
        "ROBUSTNESS_BODY": "\n".join("{} & {} & {} & [{}, {}] \\\\".format(
            _latex(row["method"]), _latex(row[axis]), _latex(row["value"]),
            _latex(row["ci_low"]), _latex(row["ci_high"]),
        ) for row in robustness),
        "CALIBRATION_BODY": "\n".join("{} & {} & {} & [{}, {}] \\\\".format(
            _latex(row["method"]), _latex(row["coverage"]),
            _latex(row.get("risk") or row["value"]),
            _latex(row.get("risk_ci_low") or row["ci_low"]),
            _latex(row.get("risk_ci_high") or row["ci_high"]),
        ) for row in calibration),
        "EFFICIENCY_HEADERS": " & ".join(_latex(value) for value in headers),
        "EFFICIENCY_BODY": "\n".join(" & ".join([
            bold(_latex(row["method"]), row is efficiency[-1]),
            *[_latex(row[f"resource_{index}"]) for index in range(1, 6)],
        ]) + r" \\" for row in efficiency),
        "CASE_BODY": "\n".join("{} & {} & {} & [{}, {}] \\\\".format(
            _latex(row[slice_field]), _latex(row["n"]), _latex(row["value"]),
            _latex(row["ci_low"]), _latex(row["ci_high"]),
        ) for row in cases),
    }


def _claim_body(rows: list[dict[str, str]]) -> str:
    labels = _claim_labels(rows)
    return "\n".join("{} & {} & {} & {} \\\\".format(
        _latex(labels.get(str(row.get("claim_id") or "").strip(), "Registered finding")),
        _latex(row["evidence_kind"]),
        _latex(publication_outcome_label(
            row["registered_outcome"], row.get("evidence_kind") or "", index + 1,
        )),
        _latex(_public_decision(str(row.get("decision") or ""))),
    ) for index, row in enumerate(rows))


def _claim_labels(rows: list[dict[str, str]]) -> dict[str, str]:
    claim_ids = list(dict.fromkeys(
        str(row.get("claim_id") or "").strip()
        for row in rows if str(row.get("claim_id") or "").strip()
    ))
    labels = {}
    for position, claim_id in enumerate(claim_ids, start=1):
        selected = [row for row in rows if str(row.get("claim_id") or "").strip() == claim_id]
        semantic = " ".join(
            str(row.get(key) or "") for row in selected
            for key in ("evidence_kind", "registered_outcome")
        ).casefold()
        if any(token in semantic for token in ("component", "ablation", "necessity")):
            label = "Component necessity"
        elif any(token in semantic for token in ("ledger", "provenance", "traceability", "join coverage")):
            label = "Evidence traceability"
        elif any(token in semantic for token in ("reversal", "paired", "held-out", "target-axis")):
            label = "Cross-axis ranking"
        else:
            label = f"Registered finding {position}"
        labels[claim_id] = label
    return labels


def _public_decision(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    labels = {
        "qualifying_cross_axis_reversal": "Supported after Holm correction",
        "qualifying_cross_axis_reversal_observed_under_registered_rule": "Supported after Holm correction",
        "holm_family_contains_qualifying_rejection": "Supported after Holm correction",
        "no_qualifying_cross_axis_reversal_under_registered_rule": "No qualifying reversal",
        "no_qualifying_reversal_after_registered_paired_rule": "No qualifying reversal",
        "holm_family_completed_without_qualifying_rejection": "No qualifying Holm rejection",
        "paired_effects_computed_from_run_level_results": "Paired estimate complete",
        "paired_seed_and_bootstrap_intervals_computed": "Uncertainty estimate complete",
        "matched_single_factor_effect_observed_without_reversal_state_change": "Matched sensitivity result",
        "complete_provenance_join": "Complete traceability",
    }
    if normalized in labels:
        return labels[normalized]
    readable = re.sub(r"[_-]+", " ", normalized).strip()
    return readable[:1].upper() + readable[1:] if readable else "Decision recorded"


def _paired_body(rows: list[dict[str, str]]) -> str:
    qualifying = [row for row in rows if row.get("reversal_status", "").casefold() == "qualifying_reversal"]
    displayed = qualifying or sorted(
        (row for row in rows if row.get("in_holm_family", "").casefold() == "true"),
        key=lambda row: float(row.get("holm_adjusted_p") or 1.0),
    ) or list(rows)
    return "\n".join("{} vs. {} & {} & {} [{}; {}] & {} [{}; {}] & {} & {} & {} \\\\".format(
        _latex(row.get("candidate_method") or "Candidate"),
        _latex(row.get("reference_method") or "Reference"),
        _latex(_public_axis(row.get("axis_id"))),
        _latex(f"{float(row.get('iid_oriented_mean_effect') or 0):+.3f}"),
        _latex(f"{float(row.get('iid_paired_ci_low') or 0):+.3f}"),
        _latex(f"{float(row.get('iid_paired_ci_high') or 0):+.3f}"),
        _latex(_paired_value(row, "oriented_mean_effect")),
        _latex(_paired_value(row, "paired_ci_low")),
        _latex(_paired_value(row, "paired_ci_high")),
        _latex(_paired_mpid(row)), _latex(_compact_p(row.get("holm_adjusted_p"))),
        _latex(_public_decision(str(row.get("decision") or ""))),
    ) for row in displayed)


def _public_axis(value: Any) -> str:
    return {
        "worst_shift_accuracy": "Worst-shift accuracy", "shifted_nll": "Shifted NLL",
        "shifted_brier": "Shifted Brier score", "latency_p95_ms": "p95 latency (ms)",
        "peak_memory_bytes": "Peak memory (MiB)",
    }.get(str(value or "").casefold(), str(value or "Target axis"))


def _paired_value(row: dict[str, str], field: str) -> str:
    raw = row.get(field) or "--"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    divisor = 1024 ** 2 if row.get("axis_id", "").casefold() == "peak_memory_bytes" else 1
    return f"{value / divisor:+.1f}" if divisor > 1 else f"{value:+.3f}"


def _paired_mpid(row: dict[str, str]) -> str:
    raw = row.get("mpid") or "--"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if row.get("axis_id", "").casefold() == "peak_memory_bytes":
        return f"{value / (1024 ** 2):.1f}"
    return f"{value:.3f}"


def _compact_p(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "--")
    return "<0.001" if number < 0.001 else f"{number:.3f}"


def _caption(item: dict[str, str], key: str = "description") -> str:
    value = re.sub(r"[.!?;:\s]+$", "", str(item.get(key) or "").strip())
    return _latex(value)


def _substitute(template: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        template = template.replace(f"@@{key}@@", str(value))
    return template


_TABLE_TEMPLATE = r"""% Deterministic simulation benchmark tables
\begin{table*}[t]
\centering
\caption{@@MAIN_CAPTION@@; complementary endpoints are reported under the same registered comparison.}
\label{@@MAIN_LABEL@@}
\small
\begin{tabularx}{\textwidth}{@@MAIN_COLUMN_SPEC@@}
\toprule
@@MAIN_HEADER@@
@@MAIN_CMIDRULE@@
@@MAIN_SUBHEADER@@
\midrule
@@MAIN_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{Independent model-pair reversals under the registered paired test and Holm correction. Positive effects favor the first-named model after metric orientation.}
\label{tab:paired-reversals}
\small
\begin{tabularx}{\textwidth}{X X c c c c X}
\toprule
Model contrast & Target axis & i.i.d. effect [95\% CI] & Target effect [95\% CI] & MPID & Holm $p$ & Decision \\
\midrule
@@PAIRED_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{Contribution-specific registered outcomes used to close the contribution-to-evidence chain.}
\label{tab:claim-evidence}
\small
\begin{tabularx}{\textwidth}{l l X c}
\toprule
Contribution & Evidence role & Registered outcome & Decision record \\
\midrule
@@CLAIM_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{@@COVERAGE_CAPTION@@ across comparison methods.}
\label{@@COVERAGE_LABEL@@}
\small
\begin{tabularx}{\textwidth}{X c c c}
\toprule
Method & @@COVERAGE_X@@ & @@COVERAGE_Y@@ & 95\% CI \\
\midrule
@@CALIBRATION_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{@@SENSITIVITY_CAPTION@@. Each row changes one registered factor while retaining the named controls; effects are relative to @@FOCAL_CONDITION@@.}
\label{@@SENSITIVITY_LABEL@@}
\small
\begin{tabularx}{\textwidth}{X X c c c c}
\toprule
Changed factor & Matched controls & Primary effect & Worst-shift effect & $\Delta$ calibration error & $\Delta$ reversals \\
\midrule
@@ABLATION_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{@@ROBUSTNESS_CAPTION@@ over @@AXIS@@.}
\label{@@ROBUSTNESS_LABEL@@}
\small
\begin{tabularx}{\textwidth}{X c c c}
\toprule
Method & @@AXIS@@ & @@METRIC@@ & 95\% CI \\
\midrule
@@ROBUSTNESS_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{@@BURDEN_CAPTION@@ across the evaluated analyses.}
\label{@@BURDEN_LABEL@@}
\small
\begin{tabularx}{\textwidth}{X c c c c c}
\toprule
Method & @@EFFICIENCY_HEADERS@@ \\
\midrule
@@EFFICIENCY_BODY@@
\bottomrule
\end{tabularx}
\end{table*}

\begin{table*}[t]
\centering
\caption{@@CASE_CAPTION@@ for the primary analysis.}
\label{@@CASE_LABEL@@}
\small
\begin{tabularx}{\textwidth}{X c c c}
\toprule
@@SLICE_LABEL@@ & $n$ & @@SLICE_METRIC@@ & 95\% CI \\
\midrule
@@CASE_BODY@@
\bottomrule
\end{tabularx}
\end{table*}
"""
