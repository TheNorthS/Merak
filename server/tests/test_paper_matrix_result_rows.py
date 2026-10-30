"""Tables retain source condition, seed and within-seed reported intervals."""
import json
from server.services.paper_matrix_result_rows import reported_matrix_rows
from server.services.paper_table_projection import project_result_table_rows
from server.services.paper_submission_tables import _result_caption
from server.services.scientific_assets import scientific_asset_service


def test_seed_specific_intervals_and_conditions_survive_public_projection(tmp_path, monkeypatch):
    r=tmp_path / 'experiments/results'; r.mkdir(parents=True)
    (r/'accepted_matrix.json').write_text('{}')
    rel='experiments/results/summary.csv'
    (tmp_path/'experiments/RUN_SPEC.json').write_text(json.dumps({'outputs':{'aggregate_files':[rel]}}))
    (tmp_path/rel).write_text('condition,axis,seed,baseline,metric,mean_delta,sd_delta,ci95_low,ci95_high,n_sequences\nnoise025,test,7,linear,MAE,0.2,0.4,0.1,0.3,64\n')
    monkeypatch.setattr(scientific_asset_service,'_proven_sources',lambda _: {rel})
    rows=reported_matrix_rows(tmp_path,'result')
    public=project_result_table_rows(rows)
    assert public[0]['split']=='test / noise025 / seed 7'
    assert public[0]['n']=='64' and public[0]['interval']=='[0.1, 0.3]'
    assert 'not intervals across seeds' in _result_caption('main_results',rows)
    from server.services.paper_submission_tables import _table_input_hashes
    bindings = _table_input_hashes(tmp_path, ['experiments/RUN_SPEC.json'])
    assert rel in bindings and 'experiments/results/accepted_matrix.json' in bindings


def test_large_result_table_registers_every_float_and_preserves_all_rows(tmp_path):
    from types import SimpleNamespace
    from server.services.paper_submission_tables import _write_result_panels
    from server.services.paper_asset_reference_contract import selected_publication_references
    from server.services.paper_asset_placement import _table_placements
    root=tmp_path.resolve(); table=root/'paper/tables'; table.mkdir(parents=True)
    source=root/'experiments/results/aggregates/main_comparison.csv';source.parent.mkdir(parents=True)
    source.write_text('source result fixture')
    evidence=SimpleNamespace(root=root,evidence_mode='executed',asset_plan={'assets':[]})
    rows=[{'method':'baseline','metric':'MAE','split':'test','condition_value':str(i),
           'mean':str(i/100),'std':'0.1','n':'3','ci95_low':'0','ci95_high':'1'} for i in range(33)]
    entries=_write_result_panels(evidence,table,'main_results','main_comparison.csv','main_results.tex',
                                 'tab:main-results','result','main_comparison',rows)
    (table/'TABLE_MANIFEST.json').write_text(json.dumps({'schema':3,'tables':entries}))
    refs=selected_publication_references(root)
    placements=_table_placements(root,list(refs),{})
    assert len(placements)==3 and sum(e['rows'] for e in entries)==33
    assert len({e['label'] for e in entries})==3
    assert all(p.text.count('begin{table}')==1 for p in placements)
