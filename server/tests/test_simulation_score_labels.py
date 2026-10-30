"""Assigned coordinates never claim to measure a registered scientific endpoint."""
from types import SimpleNamespace

from server.services.paper_model_consistency_findings import model_consistency_findings
from server.services.simulation_score_label import scenario_score_label
from server.services.simulation_primary_table import render_primary_comparison_panels


def test_primary_tables_name_generated_quantity_and_keep_every_numeric_cell():
    rows = [{'dataset':d,'method':m,'value':'0.500','ci_low':'0.400','ci_high':'0.600'}
            for d in ['Task A','Task B','Task C'] for m in ['Method A','Method B']]
    old = render_primary_comparison_panels(rows,'Balanced accuracy','Generated comparison.','tab:primary')
    new = render_primary_comparison_panels(rows,scenario_score_label('Balanced accuracy'),'Generated comparison.','tab:primary')
    assert 'Assigned unitless scenario score' in new
    assert 'Balanced accuracy scale' not in new
    for value in ['0.500','0.400','0.600']:
        assert old.count(value)==new.count(value)


def test_composite_endpoint_is_not_presented_as_a_measured_or_directional_scale():
    label = scenario_score_label(
        'Episode sensitivity at development-fixed FA/h; objective-by-task-by-deletion-position interaction (higher is better)')
    assert label == 'Assigned unitless scenario score'


def test_runtime_table_finding_cannot_be_sent_to_results_author(tmp_path):
    report=tmp_path/'review.md'
    report.write_text('''# Remaining Evidence Gaps
1. **Blocking** — wrong metric label.
Responsible runtime artifact: `paper/tables/synthetic_preview_results.tex`.
Required scientific repair: Correct the generated label; Results includes it but is not its producer.
# Final Consistency Verdict
FAIL
''')
    findings=model_consistency_findings({'cross_review':report},[SimpleNamespace(id='results',filename='05_results.tex')])
    assert len(findings)==1
    assert findings[0]['target_files']==['paper/tables/synthetic_preview_results.tex']
    assert findings[0]['legal_write_targets']==[]
    assert findings[0]['stage_id']=='assembly'
