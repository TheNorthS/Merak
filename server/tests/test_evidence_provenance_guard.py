"""A metadata repair cannot silently regenerate different observations."""
import csv
import hashlib
import io
import json

import pytest

from server.services.evidence_provenance_guard import capture_scientific_rows, verify_provenance_only


def write(root, rows):
    path = root / 'experiments/results/simulated/claim_evidence.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode('utf-8-sig'))
    (path.parent/'SIMULATION_MANIFEST.json').write_text(json.dumps({'data_files': [
        {'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}))


def test_only_explicit_provenance_change_keeps_values_and_decisions(tmp_path):
    row = {'row_id':'c1', 'value':'0.029792', 'decision':'unresolved', 'split_protocol':'subject_held_out'}
    write(tmp_path, [row])
    previous = capture_scientific_rows(tmp_path)
    write(tmp_path, [{**row,'split_protocol':'not_applicable_deterministic_scenario', 'planned_split_protocol':'subject_held_out'}])
    assert verify_provenance_only(tmp_path, previous)['scientific_content_unchanged']


@pytest.mark.parametrize('field,value', [('value','0.033125'),('decision','supported'),('row_id','c2')])
def test_numerical_decision_or_identity_change_rejects_even_with_new_valid_hash(tmp_path, field, value):
    row = {'row_id':'c1','value':'0.029792','decision':'unresolved'}
    write(tmp_path,[row]); previous=capture_scientific_rows(tmp_path)
    write(tmp_path,[{**row,field:value}])
    with pytest.raises(ValueError,match='scientific content'):
        verify_provenance_only(tmp_path,previous)


def test_bad_original_hash_is_not_repaired_by_rebinding(tmp_path):
    write(tmp_path,[{'value':'1'}])
    (tmp_path/'experiments/results/simulated/claim_evidence.csv').write_text('value\n2')
    with pytest.raises(ValueError,match='changed before'):
        capture_scientific_rows(tmp_path)


def test_linked_hash_may_change_only_for_complete_authenticated_unchanged_table(tmp_path):
    base = tmp_path/'experiments/results/simulated'
    base.mkdir(parents=True)
    table = base/'run_level_results.csv'
    table.write_text('value,construction_scope\n0.5,separate_deterministic_ranking_projection\n')
    reference = table.relative_to(tmp_path).as_posix()
    digest = hashlib.sha256(table.read_bytes()).hexdigest()
    ledger = base/'run_ledger.csv'
    ledger.write_text(f'run_level_table,run_level_table_sha256\n{reference},{digest}\n')
    (base/'SIMULATION_MANIFEST.json').write_text(json.dumps({'data_files':[
        {'path':p.relative_to(tmp_path).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (table,ledger)]}))
    previous={reference:[{'value':'0.5'}],ledger.relative_to(tmp_path).as_posix():[
        {'run_level_table':reference,'run_level_table_sha256':'old-authenticated-hash'}]}
    assert verify_provenance_only(tmp_path,previous)['scientific_content_unchanged']
    previous[reference][0]['value']='0.6'
    with pytest.raises(ValueError,match='scientific content'):
        verify_provenance_only(tmp_path,previous)
