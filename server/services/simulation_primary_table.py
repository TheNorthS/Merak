"""Bound complete multi-dataset primary comparisons into readable matrix panels.

The producer preserves every registered method/dataset estimate and interval.
Panels change only publication layout; no aggregates, rankings or outcomes are
computed and source rows remain immutable.
"""

from __future__ import annotations

import math
import json
import re
from dataclasses import dataclass
from typing import Any

from .semantic_table import _escape, MAX_PUBLIC_TABLE_CELL_CHARACTERS


@dataclass(frozen=True)
class PrimaryComparisonPanel:
    label: str
    datasets: tuple[str, ...]
    methods: tuple[str, ...]
    source_row_indices: tuple[int, ...]


def needs_primary_matrix(rows: list[dict[str, str]]) -> bool:
    """Use a matrix where long-form repeated method labels would overflow."""
    datasets = {str(row.get("dataset") or "aggregate") for row in rows}
    return len(datasets) > 2


def primary_comparison_panels(rows: list[dict[str, str]], label: str) -> tuple[PrimaryComparisonPanel, ...]:
    """Require one exact registered row per method/dataset before partitioning."""
    if not rows or not label.startswith("tab:"):
        raise ValueError("Primary comparison panels require source rows and a public table label")
    datasets, methods, identities = [], [], {}
    for index, row in enumerate(rows):
        if not all(str(row.get(key) or "").strip() for key in ("dataset", "method", "value", "ci_low", "ci_high")):
            raise ValueError("Primary matrix row lacks its method, dataset or complete interval")
        dataset, method = row["dataset"], row["method"]
        if any(len(value) > MAX_PUBLIC_TABLE_CELL_CHARACTERS for value in (dataset, method)):
            raise ValueError("Primary matrix labels exceed the publication cell bound")
        values = [float(row[key]) for key in ("value", "ci_low", "ci_high")]
        if not all(math.isfinite(value) for value in values) or not values[1] <= values[0] <= values[2]:
            raise ValueError("Primary matrix interval is invalid")
        if (dataset, method) in identities:
            raise ValueError("Primary matrix has duplicate method/dataset evidence")
        identities[dataset, method] = index
        if dataset not in datasets:
            datasets.append(dataset)
        if method not in methods:
            methods.append(method)
    if len(methods) < 2 or len(identities) != len(datasets) * len(methods):
        raise ValueError("Primary matrix must preserve a complete matched comparison")
    # Six-method comparisons fit one panel and must not split a task's controls.
    groups = [methods[index:index + 6] for index in range(0, len(methods), 6)]
    if len(groups) > 1 and len(groups[-1]) == 1:
        groups[-1].insert(0, groups[-2].pop())
    panels = []
    for offset in range(0, len(datasets), 2):
        dataset_group = datasets[offset:offset + 2]
        for method_group in groups:
            number = len(panels) + 1
            panel_label = label if number == 1 else f"{label}-panel-{number}"
            indices = tuple(identities[dataset, method] for method in method_group for dataset in dataset_group)
            panels.append(PrimaryComparisonPanel(panel_label, tuple(dataset_group), tuple(method_group), indices))
    if sorted(index for panel in panels for index in panel.source_row_indices) != list(range(len(rows))):
        raise ValueError("Primary matrix partition lost or duplicated source rows")
    return tuple(panels)


def render_primary_comparison_panels(rows: list[dict[str, str]], metric: str,
                                     caption: str, label: str) -> str:
    """Emit bounded six-method/two-dataset panels without splitting common control sets."""
    panels = primary_comparison_panels(rows, label)
    indexed = {(row["dataset"], row["method"]): row for row in rows}
    rendered = []
    for number, panel in enumerate(panels, start=1):
        references = ", ".join(r"\ref{" + item.label + "}" for item in panels[1:])
        description = caption.rstrip(".!?;: ") + ". " + _escape(metric) + " [95\\% CI]."
        description += (" Names identify planned conditions in a generated scenario; "
                        "budget matching is a design target, not a measured comparison of trained models.")
        if number == 1 and references:
            description += " The complete comparison continues in Tables~" + references + "."
        elif number > 1:
            description += " Continuation of Table~\\ref{" + label + "}."
        header = "Planned condition & " + " & ".join(_escape(dataset) for dataset in panel.datasets) + r" \\"
        body = []
        for method in panel.methods:
            cells = [_escape(method)]
            for dataset in panel.datasets:
                row = indexed[dataset, method]
                cells.append(_escape(f"{row['value']} [{row['ci_low']}, {row['ci_high']}]"))
            body.append(" & ".join(cells) + r" \\")
        numeric = (0.92 - 0.44) / len(panel.datasets)
        columns = r"p{0.44\textwidth} " + " ".join(f"p{{{numeric:.3f}\\textwidth}}" for _ in panel.datasets)
        rendered.append("\n".join([
            r"\begin{table*}[t]",
            "% MERAK_PRIMARY_MATRIX_CAPTION: " + json.dumps(caption, ensure_ascii=True),
            r"\centering", "\\caption{" + description + "}",
            "\\label{" + panel.label + "}", r"\small", r"\setlength{\tabcolsep}{3pt}",
            "\\begin{tabular}{" + columns + "}", r"\toprule", header, r"\midrule",
            *body, r"\bottomrule", r"\end{tabular}", r"\end{table*}",
        ]))
    return "\n\n".join(rendered) + "\n"


def panel_binding(panel: PrimaryComparisonPanel) -> dict[str, Any]:
    return {"schema": 1, "datasets": list(panel.datasets), "methods": list(panel.methods),
            "source_row_indices": list(panel.source_row_indices), "scientific_rows_recomputed": False}


def primary_source_caption(block: str, fallback: str) -> str:
    """Read current producer caption metadata without duplicating derived panel text."""
    match = re.search(r"(?m)^% MERAK_PRIMARY_MATRIX_CAPTION: (.+)$", block)
    if match is None:
        return fallback
    value = json.loads(match.group(1))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Primary matrix producer caption metadata is invalid")
    return value
