"""Pure CSV and LaTeX projections for manuscript tables."""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path

from ..utils.atomic_write import atomic_write_bytes


def _display_number(value) -> str:
    """Round presentation only; full-precision source rows remain separately hash-bound."""
    if len(str(value or '')) <= 10:
        return str(value or '')
    try:
        number = float(value)
    except (ValueError, TypeError):
        return str(value or '')
    return f'{number:.5g}' if math.isfinite(number) else str(value)


METHOD_ELEMENTS_CAPTION = (
    "Method elements and declared evaluation scope. "
    "Evaluation tests are not trainable components: their removal is not a model ablation. "
    "Each role is a declared design intention, conditional on the stated implementation and pairing assumptions; "
    "this table does not independently verify their realization. Execution evidence is reported separately in the results. "
    "The Methods section defines the comparisons, assumptions and prerequisites."
)



def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a non-empty row set with a stable UTF-8 CSV encoding."""
    if not rows:
        raise ValueError(f"cannot write an empty table: {path}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(path, buffer.getvalue().encode("utf-8-sig"))


def _design_table_spec(caption: str, label: str, columns: tuple) -> object:
    from .semantic_table import ScientificTableSpec
    return ScientificTableSpec(
        question=caption, caption=caption, label=label, columns=columns,
        independent_unit='Registered scientific component or study condition',
        uncertainty='Not applicable to a design table',
        source_paths=('ideas/SELECTED_IDEA.json', 'experiments/METHOD_CONTRACT.json'),
    )


def study_design_table_tex(rows: list[dict[str, str]]) -> str:
    from .semantic_table import TableColumn, compile_scientific_table
    spec = _design_table_spec(
        'Study dimensions and controlled evaluation settings.', 'tab:study-design',
        (TableColumn('dimension', 'Dimension'), TableColumn('setting', 'Setting'),
         TableColumn('purpose', 'Scientific purpose')),
    )
    return compile_scientific_table(spec, rows)


def method_components_table_tex(rows: list[dict[str, str]]) -> str:
    from .semantic_table import TableColumn, compile_scientific_table
    spec = _design_table_spec(
        METHOD_ELEMENTS_CAPTION,
        'tab:method-components',
        (TableColumn('component', 'Method element'), TableColumn('function', 'Declared design intent'),
         TableColumn('evaluation', 'Evaluation protocol')),
    )
    return compile_scientific_table(spec, rows)


def main_results_table_tex(
    rows: list[dict[str, str]],
    *,
    caption: str,
    label: str = "tab:main-results",
) -> str:
    return public_results_table_tex(project_result_table_rows(rows), caption=caption, label=label)


def project_result_table_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return exactly the registered public columns and displayed numeric values."""
    from .publication_labels import publication_metric_label

    if rows and {"theme", "evidence_count", "case_count"}.issubset(rows[0]):
        fields = ("theme", "evidence_count", "case_count", "negative_case_count", "source_count", "mean")
        return [{field: str(row.get(field) or "") for field in fields} for row in rows]
    return [{
        "method": str(row.get("method") or ""),
        "metric": publication_metric_label(row.get("metric") or ""),
        "split": ' / '.join(filter(None, [str(row.get("split") or ""),
            str(row.get('condition_value') or ''),
            'seed ' + str(row['seed']) if row.get('seed') else ''])),
        "estimate": f"{_display_number(row.get('mean', ''))} ± {_display_number(row.get('std', ''))}",
        "n": str(row.get("n") or ""),
        "interval": f"[{_display_number(row.get('ci95_low', ''))}, {_display_number(row.get('ci95_high', ''))}]",
    } for row in rows]


def public_results_table_tex(
    rows: list[dict[str, str]], *, caption: str, label: str,
) -> str:
    """Render public rows already registered as the manuscript's CSV content."""
    if rows and {"theme", "evidence_count", "case_count"}.issubset(rows[0]):
        return _qualitative_results_tex(rows, caption=caption, label=label)
    return _quantitative_results_tex(rows, caption=caption, label=label)


def _qualitative_results_tex(
    rows: list[dict[str, str]], *, caption: str, label: str
) -> str:
    from .semantic_table import ScientificTableSpec, TableColumn, compile_scientific_table
    columns = (TableColumn('theme', 'Theme'), TableColumn('evidence_count', 'Evidence records', 'number'),
               TableColumn('case_count', 'Cases', 'number'), TableColumn('negative_case_count', 'Negative cases', 'number'),
               TableColumn('source_count', 'Sources', 'number'), TableColumn('mean', 'Case coverage', 'number'))
    spec = ScientificTableSpec(
        question='How do themes compare across supporting and negative cases?', caption=caption,
        label=label, columns=columns, independent_unit='Case',
        uncertainty='Traceable coded-evidence coverage; not a population confidence interval',
        source_paths=tuple(sorted({str(row.get('source_data') or 'experiments/results/coded_evidence.csv') for row in rows})),
    )
    return compile_scientific_table(spec, rows)


def _quantitative_results_tex(
    rows: list[dict[str, str]], *, caption: str, label: str
) -> str:
    from .semantic_table import ScientificTableSpec, TableColumn, compile_scientific_table
    columns = (TableColumn('method', 'Method'), TableColumn('metric', 'Endpoint'),
               TableColumn('split', 'Evaluation condition'), TableColumn('estimate', 'Mean ± SD', 'number'),
               TableColumn('n', 'n', 'number'), TableColumn('interval', '95% CI', 'interval'))
    spec = ScientificTableSpec(
        question='How do the registered methods compare on the declared endpoint?',
        caption=caption, label=label, columns=columns, independent_unit=(
            'Independent sequence within the displayed seed' if all('seed ' in row.get('split', '') for row in rows)
            else 'Recorded replicate; n counts summarized records'),
        uncertainty=('Reported 95% Student-t interval and SD across independent sequences within each seed'
                     if all('seed ' in row.get('split', '') for row in rows)
                     else '95% confidence intervals; SD across recorded replicates'),
        source_paths=tuple(sorted({str(row.get('source_data') or 'experiments/results/aggregates') for row in rows})),
    )
    return compile_scientific_table(spec, rows)
