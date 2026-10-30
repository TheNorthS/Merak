"""Bound long stress tables without shrinking text or losing frozen observations."""

import re

from .semantic_table import _escape
from .paper_table_source_labels import selected_table_source_records


def bounded_robustness_table(block: str, rows: list[dict], axis: str, axis_label: str, metric: str) -> str:
    """Promote repeated method names to group headings; values retain source order."""
    if not rows or not all(all(key in row for key in ("method", axis, "value", "ci_low", "ci_high")) for row in rows):
        return block
    if ("% MERAK_GROUPED_STRESS_TABLE" not in block
            and len(metric) < 45 and max(len(str(row["method"])) for row in rows) < 45):
        return _relabel_short_table(block, metric)
    if len(rows) > 20:
        raise ValueError("Stress table exceeds its bounded twenty-observation layout; partition at the table producer")
    record = next(iter(selected_table_source_records(block).values()))
    caption = record["caption"]
    caption = re.sub(r"; Endpoint: .*?\.$", "", caption).rstrip(".")
    caption += "; Endpoint: " + _escape(metric) + "."
    label_match = re.search(r"\\label\{([^}]+)\}", block)
    if label_match is None:
        raise ValueError("Stress table requires its stable source label")
    rendered = _render(rows, axis, axis_label, caption, label_match[1])
    if "% MERAK_GROUPED_STRESS_TABLE" in block:
        original = _render(rows, axis, axis_label, record["caption"], label_match[1])
        if block.strip() != original.strip():
            raise ValueError("Grouped stress table differs from its exact frozen rows")
        return rendered
    body = re.search(r"\\midrule(.*?)\\bottomrule", block, re.DOTALL)
    lines = [line.strip() for line in body[1].splitlines() if "&" in line] if body else []
    expected = [_escape(str(row["method"])) + " & " + _escape(str(row[axis])) + " & "
                + _escape(str(row["value"])) + " & " + _escape(f"[{row['ci_low']}, {row['ci_high']}]") + r" \\" for row in rows]
    if lines != expected:
        raise ValueError("Stress table rows do not match frozen method, axis, value and interval")
    return rendered


def _relabel_short_table(block: str, metric: str) -> str:
    """Change only the metric header; existing observations remain byte-for-byte intact."""
    header = re.search(r'(\\toprule\s*)(.*?)(\s*\\midrule)', block, re.DOTALL)
    if header is None:
        raise ValueError('Stress table is missing its metric header')
    cells = header[2].split('&')
    if len(cells) != 4:
        raise ValueError('Stress table header must contain method, axis, metric and interval')
    cells[2] = ' ' + _escape(metric) + ' '
    return block[:header.start(2)] + '&'.join(cells) + block[header.end(2):]


def _render(rows: list[dict], axis: str, axis_label: str, caption: str, label: str) -> str:
    lines = [r"\begin{table*}[t]", "% MERAK_GROUPED_STRESS_TABLE", r"\centering",
             r"\caption{" + caption + "}", r"\label{" + label + "}", r"\small",
             r"\setlength{\tabcolsep}{4pt}",
             r"\begin{tabular}{p{0.25\linewidth} p{0.25\linewidth} p{0.36\linewidth}}", r"\toprule",
             _escape(axis_label) + r" & Endpoint & 95\% CI \\", r"\midrule"]
    previous = None
    for row in rows:
        if row["method"] != previous:
            if previous is not None:
                lines.append(r"\addlinespace")
            lines.append(r"\multicolumn{3}{p{0.91\linewidth}}{\textbf{" + _escape(str(row["method"])) + r"}} \\")
            previous = row["method"]
        lines.append(_escape(str(row[axis])) + " & " + _escape(str(row["value"])) + " & "
                     + _escape(f"[{row['ci_low']}, {row['ci_high']}]") + r" \\")
    return "\n".join([*lines, r"\bottomrule", r"\end{tabular}", r"\end{table*}"])
