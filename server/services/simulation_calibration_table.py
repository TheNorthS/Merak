"""Publication projection of exact calibration rows with their population identity.

Dataset-bearing rows are joint dataset/coverage observations, not interventions
on one fixed population. This producer preserves order, method, estimates and
interval strings; it never aggregates, creates values or changes source data.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .semantic_table import _escape, MAX_PUBLIC_TABLE_CELL_CHARACTERS


PANEL_ROWS = 16
DATASET_CAPTION = (
    "Selective-risk coordinates by joint dataset and retained-coverage row. Each row preserves its declared "
    "dataset or task, method, risk estimate and interval; changes across datasets cannot identify "
    "a within-population coverage effect. Bounds are generator-declared scenario ranges; "
    "no confidence level is established by these rows."
)


def has_dataset_calibration(rows: list[dict[str, str]]) -> bool:
    """Absent dataset metadata preserves the existing generic table contract."""
    declared = any("dataset" in row for row in rows)
    if declared and any(not isinstance(row.get("dataset"), str) or not row["dataset"].strip() for row in rows):
        raise ValueError("Calibration rows have missing or mixed dataset identity")
    return declared


def calibration_cells(row: dict[str, str]) -> tuple[str, ...]:
    """Use one complete risk or value interval family without mixing endpoints."""
    risk_keys = ("risk", "risk_ci_low", "risk_ci_high")
    family = risk_keys if any(key in row for key in risk_keys) else ("value", "ci_low", "ci_high")
    required = ("dataset", "method", "coverage", *family)
    if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
        raise ValueError("Dataset calibration row lacks a method, coverage, estimate or complete interval")
    values = [float(row[key]) for key in ("coverage", *family)]
    if not all(math.isfinite(value) for value in values) or not 0 <= values[0] <= 1 or not values[2] <= values[1] <= values[3]:
        raise ValueError("Dataset calibration coverage or interval is invalid")
    if any(len(row[key]) > MAX_PUBLIC_TABLE_CELL_CHARACTERS for key in ("dataset", "method")):
        raise ValueError("Dataset calibration labels exceed the publication cell bound")
    return (row["dataset"], row["method"], row["coverage"], row[family[0]],
        f"[{row[family[1]]}, {row[family[2]]}]")


def calibration_panels(rows: list[dict[str, str]], label: str) -> tuple[tuple[str, tuple[int, ...]], ...]:
    if not rows or not has_dataset_calibration(rows) or not label.startswith("tab:"):
        raise ValueError("Dataset calibration table requires exact source rows and a public label")
    for row in rows:
        calibration_cells(row)
    chunks = [list(range(start, min(start + PANEL_ROWS, len(rows)))) for start in range(0, len(rows), PANEL_ROWS)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:
        chunks[-1].insert(0, chunks[-2].pop())
    return tuple((label if index == 0 else f"{label}-panel-{index + 1}", tuple(indices))
                 for index, indices in enumerate(chunks))


def render_dataset_calibration(rows: list[dict[str, str]], label: str,
                                coverage_label: str, risk_label: str) -> str:
    """Emit bounded panels at the existing small font, never shrink or omit rows."""
    from .simulation_interval_caption import ASSIGNED_RANGE_NOTE
    panels = calibration_panels(rows, label)
    blocks = []
    for number, (panel_label, indices) in enumerate(panels):
        caption = DATASET_CAPTION + " " + ASSIGNED_RANGE_NOTE
        if number == 0 and len(panels) > 1:
            caption += " The remaining rows continue in Tables~" + ", ".join(
                r"\ref{" + identity + "}" for identity, _indices in panels[1:]) + "."
        elif number:
            caption += r" Continuation of Table~\ref{" + label + "}."
        body = [" & ".join(_escape(value) for value in calibration_cells(rows[index])) + r" \\" for index in indices]
        blocks.append("\n".join([
            r"\begin{table*}[t]", r"\centering", r"\caption{" + caption + "}", r"\label{" + panel_label + "}",
            r"\small", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabularx}{\textwidth}{X X c c c}",
            r"\toprule", "Dataset / task & Method & " + _escape(coverage_label) + " & " + _escape(risk_label)
            + r" & Scenario bounds \\", r"\midrule", *body, r"\bottomrule", r"\end{tabularx}", r"\end{table*}",
        ]))
    return "\n\n".join(blocks) + "\n"


def validate_calibration_source(blocks: list[str], rows: list[dict[str, str]]) -> None:
    """Verify every original row before upgrading a paper-owned label projection."""
    observed = [re.split(r"(?<!\\)&", line.strip().removesuffix(r"\\")) for block in blocks
        for body in re.findall(r"\\midrule(.*?)\\bottomrule", block, re.DOTALL)
        for line in body.splitlines() if "&" in line]
    if len(observed) != len(rows):
        raise ValueError("Calibration source table omits or duplicates frozen numerical rows")
    for cells, row in zip(observed, rows):
        expected = [_escape(value) for value in calibration_cells(row)]
        current = [cell.strip() for cell in cells]
        if current not in (expected, expected[1:]):
            raise ValueError("Calibration table row differs from its exact frozen method/coverage/risk interval")


def append_calibration_panel_entries(entries: list[dict[str, Any]], rows: list[dict[str, str]],
                                     label: str, records: dict[str, dict[str, str]]) -> None:
    """Register exact row partitions; this grants no prose-reference exemption."""
    if not has_dataset_calibration(rows):
        return
    panels = calibration_panels(rows, label)
    base = dict(entries[-1])
    blocks = [records[identity]["source"] for identity, _indices in panels if identity in records]
    if len(blocks) != len(panels):
        raise ValueError("Dataset calibration table is missing a source-bound row panel")
    validate_calibration_source(blocks, rows)
    for number, (identity, indices) in enumerate(panels):
        update = {**base, "label": identity, "caption": records[identity]["caption"], "rows": len(indices),
            "calibration_panel_binding": {"schema": 1, "parent_label": label,
                "source_row_indices": list(indices), "scientific_rows_recomputed": False}}
        if number == 0:
            entries[-1] = update
        else:
            update["id"] = base["id"] + f"_panel_{number + 1}"
            entries.append(update)
