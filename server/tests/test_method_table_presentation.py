"""Current manuscript table wording cannot rewrite science or silently survive changed inputs."""

import json

import pytest

from server.services.method_table_presentation import write_method_presentation, current_method_rows
from server.services.paper_submission_tables import write_submission_tables
from server.tests.test_publication_table_prose_transaction import _evidence


def ready(root):
    evidence = _evidence(root, long=False)
    path = root / 'paper/sections';path.mkdir(parents=True)
    (path/'03_method.tex').write_text('Current mechanism and model inputs')
    (path/'04_experiments.tex').write_text('Separate controls in a future study')
    rows=[{'component':item['publication_name'], 'function':'Current documented input requirement.',
           'evaluation':'Compare separate prospective controls; no empirical effect is asserted.'}
          for item in evidence.selected_idea['mechanisms']]
    return evidence,rows


def test_producer_uses_authored_rows_and_preserves_original_science(tmp_path):
    evidence,rows=ready(tmp_path)
    original=(tmp_path/'ideas/SELECTED_IDEA.json').read_bytes()
    write_method_presentation(tmp_path,rows,author='fixture-author')
    write_submission_tables(evidence)
    text=(tmp_path/'paper/tables/method_components.tex').read_text()
    assert rows[0]['function'] in text and rows[0]['evaluation'] in text
    assert (tmp_path/'ideas/SELECTED_IDEA.json').read_bytes()==original
    entry=next(x for x in json.loads((tmp_path/'paper/tables/TABLE_MANIFEST.json').read_bytes())['tables'] if x['id']=='method_components')
    assert 'paper/METHOD_TABLE_PRESENTATION.json' in entry['source_data']


def test_changed_method_cannot_silently_reuse_presentation(tmp_path):
    _evidence,rows=ready(tmp_path);write_method_presentation(tmp_path,rows,author='fixture-author')
    (tmp_path/'paper/sections/03_method.tex').write_text('Changed scientific requirement')
    with pytest.raises(ValueError,match='source changed'):
        current_method_rows(tmp_path,rows)


def test_presentation_cannot_drop_or_rename_mechanisms(tmp_path):
    _evidence,rows=ready(tmp_path)
    with pytest.raises(ValueError):write_method_presentation(tmp_path,rows[:1],author='fixture-author')
    rows[0]['component']='Another idea'
    with pytest.raises(ValueError):write_method_presentation(tmp_path,rows,author='fixture-author')


def test_model_json_key_order_cannot_change_public_table_columns(tmp_path):
    evidence, rows = ready(tmp_path)
    sorted_rows = json.loads(json.dumps(rows, sort_keys=True))
    assert list(sorted_rows[0]) == ['component', 'evaluation', 'function']
    write_method_presentation(tmp_path, sorted_rows, author='model-api:fixture')
    write_submission_tables(evidence)
    value = json.loads((tmp_path/'paper/METHOD_TABLE_PRESENTATION.json').read_bytes())
    assert list(value['rows'][0]) == ['component', 'function', 'evaluation']
    manifest = json.loads((tmp_path/'paper/tables/TABLE_MANIFEST.json').read_bytes())
    entry = next(item for item in manifest['tables'] if item['id'] == 'method_components')
    from server.services.paper_table_projection_validation import table_publication_projection_issues
    assert table_publication_projection_issues(tmp_path, entry) == []
