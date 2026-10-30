"""Current hash-domain evidence distinguishes genuine corruption from valid projections."""

import hashlib
import json

from server.workflows.audit_provenance_facts import freeze_source_facts, table_projection_facts
from server.services.paper_scientific_freeze import scientific_freeze_inputs, HASH_MODE


def test_semantic_freeze_is_not_compared_to_raw_file_bytes_and_science_changes_fail(tmp_path):
    source = tmp_path/'ideas/SELECTED_IDEA.json';source.parent.mkdir()
    source.write_text(json.dumps({'method': 'Original scientific design', 'generated_at': 123}, indent=2))
    freeze = tmp_path/'paper/SCIENTIFIC_FREEZE.json';freeze.parent.mkdir()
    freeze.write_text(json.dumps({'schema_version': 1, 'input_hash_mode': HASH_MODE,
                                 'inputs': scientific_freeze_inputs(tmp_path)}))
    before = freeze.read_bytes()
    facts = freeze_source_facts(tmp_path)
    assert facts['valid_source_binding'] is True
    row = next(row for row in facts['comparisons'] if row['path'] == 'ideas/SELECTED_IDEA.json')
    assert row['scientific_match'] and row['current_byte_hash'] != row['recorded_scientific_hash']
    source.write_text(json.dumps({'method': 'Different scientific design', 'generated_at': 456}))
    assert freeze_source_facts(tmp_path)['valid_source_binding'] is False
    assert freeze.read_bytes() == before


def test_verified_table_projection_reports_two_valid_hashes_and_rejects_edited_output(tmp_path, monkeypatch):
    from server.tests.test_simulation_table_publication import _current
    from server.services.simulation_table_publication import prepare_simulation_table_publication
    _current(tmp_path, monkeypatch)
    update = prepare_simulation_table_publication(tmp_path, 'objective_mechanism')
    for name, raw in update.files.items():
        target = tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    facts = table_projection_facts(tmp_path)
    assert facts['valid'] and facts['projection_proof']
    assert facts['original_source_sha256'] != facts['current_table_sha256']
    table = tmp_path/'paper/tables/synthetic_preview_results.tex'
    table.write_bytes(table.read_bytes().replace(b'-0.012', b'-0.999'))
    broken = table_projection_facts(tmp_path)
    assert broken['valid'] is False and broken['error']
