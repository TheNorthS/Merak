"""Persisted and rendered table counts enforce the same declared study profile."""
from types import SimpleNamespace
import pytest

from server.workflows.paper_acceptance_checks_1 import table_manifest_load_2
from server.workflows.paper_acceptance_checks_3 import read_minimum_tables, validate_table_count


@pytest.mark.parametrize('minimum,count,blocked', [(0, 1, False), (1, 1, False), (2, 1, True), (3, 2, True)])
def test_manifest_count_matches_rendered_count_without_changing_profile(tmp_path, minimum, count, blocked):
    path = tmp_path / 'TABLE_MANIFEST.json'
    path.write_text('{}')
    ctx = SimpleNamespace(table_manifest_path=path, table_manifest={'tables': [{'id': str(i)} for i in range(count)]},
                          manuscript_profile={'table_contract': {'minimum_tables': minimum}},
                          table_blocks=['table'] * count, problems=[])
    table_manifest_load_2(ctx)
    assert bool(ctx.problems) == blocked
    ctx.problems = []
    read_minimum_tables(ctx)
    validate_table_count(ctx)
    assert bool(ctx.problems) == blocked
    assert ctx.manuscript_profile['table_contract']['minimum_tables'] == minimum
