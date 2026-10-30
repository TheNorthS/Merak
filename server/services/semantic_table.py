"""Typed domain-neutral table specifications and bounded LaTeX layout compiler."""

from dataclasses import dataclass
from typing import Mapping, Sequence


MAX_PUBLIC_TABLE_CELL_CHARACTERS = 180


class SemanticTableContractError(ValueError):
    """A source-owned table failure with a concrete public cell target."""

    def __init__(self, message: str, *, table_label: str,
                 row_index: int | None = None, column_key: str = "") -> None:
        super().__init__(message)
        self.table_label = table_label
        self.row_index = row_index
        self.column_key = column_key


@dataclass(frozen=True)
class TableColumn:
    key: str
    label: str
    kind: str = 'text'
    group: str = ''


@dataclass(frozen=True)
class ScientificTableSpec:
    question: str
    caption: str
    label: str
    columns: tuple[TableColumn, ...]
    independent_unit: str
    uncertainty: str
    source_paths: tuple[str, ...]
    max_rows_per_panel: int = 16


def _escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in str(value))


def _group_heading(columns: tuple[TableColumn, ...]) -> str:
    if not any(column.group for column in columns):
        return ''
    runs = []
    for column in columns:
        name = column.group
        if runs and name and runs[-1][0] == name:
            runs[-1] = (name, runs[-1][1] + 1)
        else:
            runs.append((name, 1))
    return ' & '.join(rf'\multicolumn{{{count}}}{{c}}{{{_escape(name)}}}'
                      for name, count in runs) + r' \\'


def compile_scientific_table(spec: ScientificTableSpec, rows: Sequence[Mapping[str, str]]) -> str:
    """Compile bounded panels; never shrink fonts or discard registered columns."""
    if not rows or len(spec.columns) < 2:
        raise ValueError('a scientific table needs rows and at least two columns')
    if not spec.question.strip() or not spec.label.startswith('tab:'):
        raise ValueError('table requires a scientific question and a stable tab: label')
    if not spec.independent_unit.strip() or not spec.uncertainty.strip() or not spec.source_paths:
        raise ValueError('table requires an independent unit, uncertainty definition and source paths')
    if len({column.key for column in spec.columns}) != len(spec.columns):
        raise ValueError('table column keys must be unique')
    for column in spec.columns:
        if not column.label.strip() or column.kind not in {'text', 'number', 'interval'}:
            raise ValueError('table column has an invalid publication contract')
    missing = {column.key for column in spec.columns for row in rows if column.key not in row}
    if missing:
        raise ValueError('table rows omit registered columns: ' + ', '.join(sorted(missing)))
    for row_index, row in enumerate(rows):
        for column in spec.columns:
            if len(str(row[column.key])) > MAX_PUBLIC_TABLE_CELL_CHARACTERS:
                raise SemanticTableContractError(
                    'paragraph-length cells belong in prose, not tables',
                    table_label=spec.label, row_index=row_index, column_key=column.key,
                )
    limit = max(2, min(24, spec.max_rows_per_panel))
    panels = []
    text_count = sum(column.kind == 'text' for column in spec.columns)
    numeric_width = min(0.18, 0.65 / max(1, len(spec.columns) - text_count))
    columns = ' '.join('X' if column.kind == 'text' else rf'p{{{(0.045 if column.key == "n" else numeric_width):.3f}\linewidth}}'
                       for column in spec.columns)
    for index in range(0, len(rows), limit):
        panel = rows[index:index + limit]
        suffix = '' if index == 0 else f'-panel-{index // limit + 1}'
        heading = ' & '.join(_escape(column.label) for column in spec.columns)
        body = '\n'.join(' & '.join(_escape(str(row[column.key])) for column in spec.columns)
                         + r' \\' for row in panel)
        panels.append('\n'.join([
            r'\begin{table}[t]', r'\centering',
            rf'\caption{{{_escape(spec.caption)}}}', rf'\label{{{spec.label}{suffix}}}',
            r'\small', r'\setlength{\tabcolsep}{4pt}',
            rf'\begin{{tabularx}}{{\linewidth}}{{{columns}}}', r'\toprule',
            _group_heading(spec.columns), heading + r' \\', r'\midrule', body, r'\bottomrule',
            r'\end{tabularx}',
            rf'\par\raggedright\small Unit: {_escape(spec.independent_unit)}; {_escape(spec.uncertainty)}.',
            r'\end{table}',
        ]))
    return '\n\n'.join(panels) + '\n'
