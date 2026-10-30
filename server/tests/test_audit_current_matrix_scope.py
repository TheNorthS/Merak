import json
from server.workflows.draft_audit_evidence import draft_audit_evidence


def test_current_matrix_keeps_summary_and_code_and_discloses_history(tmp_path):
    def write(name,text):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    selected=write('experiments/results/accepted_matrix.json',json.dumps({'matrix_id':'current','cells':[{'output_dir':'experiments/results/cells/current/a'}]}))
    paths=[selected,write('experiments/src/run.py','implementation'),
        write('experiments/results/aggregate/summary.csv','value\n1'),
        write('.merak/quality/independent-matrix-audit.json','{"passed":true}'),
        write('.merak/experiments/current-seed-1-0/run.json','{"status":"completed"}'),
        write('.merak/experiments/current-seed-1-0/snapshot.json','x'*800000),
        write('.merak/experiments/old-seed-1-0/run.json','{"status":"failed"}'),
        write('experiments/results/cells/current/a/raw.csv','raw'),
        write('experiments/results/cells/old/a/raw.csv','history')]
    _,included,scope=draft_audit_evidence(tmp_path,paths,'experiment-audit',allow_partition=True)
    assert set(included)==set(paths[:5])
    assert 'historical' in scope and 'snapshot.json' in scope and 'raw-row inspection' in scope
    assert paths[5].stat().st_size==800000
