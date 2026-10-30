"""Authenticate every original matrix cell before a producer changes panel grouping."""

from collections import Counter
import re

from .semantic_table import _escape


def verify_primary_panel_cells(blocks: list[str], rows: list[dict[str, str]]) -> None:
    expected = {(_escape(row['dataset']), _escape(row['method'])):
                _escape(f"{row['value']} [{row['ci_low']}, {row['ci_high']}]") for row in rows}
    if len(expected) != len(rows):
        raise ValueError('Primary table source has duplicate scientific identities')
    observed = Counter()
    for block in blocks:
        header = re.search(r'\\toprule\s*(.*?)\\midrule', block, re.DOTALL)
        body = re.search(r'\\midrule\s*(.*?)\\bottomrule', block, re.DOTALL)
        if header is None or body is None:
            raise ValueError('Primary table panel has no exact header/body boundary')
        columns = [cell.strip().removesuffix('\\\\').strip()
                   for cell in re.split(r'(?<!\\)&', header.group(1))]
        if not columns or columns[0] not in {'Method', 'Planned condition'} or len(columns) != len(set(columns)):
            raise ValueError('Primary table panel header is ambiguous')
        for line in body.group(1).splitlines():
            if not line.strip():
                continue
            cells = [cell.strip().removesuffix('\\\\').strip() for cell in re.split(r'(?<!\\)&', line)]
            if len(cells) != len(columns):
                raise ValueError('Primary table row width differs from its task header')
            for dataset, value in zip(columns[1:], cells[1:]):
                key = dataset, cells[0]
                if key not in expected or value != expected[key]:
                    raise ValueError('Primary table panel cell differs from frozen source rows')
                observed[key] += 1
    if observed != Counter({key: 1 for key in expected}):
        raise ValueError('Primary table panels lost or duplicated a scientific comparison')
