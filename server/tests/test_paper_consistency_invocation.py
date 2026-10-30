"""No-tool consistency consumes complete current sources and preserves raw model verdicts."""

import json
from types import SimpleNamespace

import pytest

from server.workflows.paper_consistency_invocation import consistency_evidence, invoke_consistency


@pytest.mark.asyncio
@pytest.mark.parametrize('goal', ['reviewable_draft', 'submission_candidate'])
async def test_consistency_reads_frozen_sources_and_records_actual_fail(tmp_path, monkeypatch, goal):
    from server.services.api_visual_reviewer import ApiVisualReviewer
    from server.agent.tools import skill_tool
    paper = tmp_path / 'paper'
    (paper / 'sections').mkdir(parents=True)
    (paper / 'main.tex').write_text(r'\input{sections/03_method}')
    (paper / 'sections/03_method.tex').write_text('Contradictory method')
    (paper / 'references.bib').write_text('@article{key,title={Verified}}')
    source = tmp_path / 'experiments/src/models.py'
    source.parent.mkdir(parents=True)
    source.write_text('actual implementation')
    loaded = SimpleNamespace(name='domain-paper-write', source=tmp_path/'SKILL.md', source_bytes=b'policy', policy='producer policy')
    monkeypatch.setattr(skill_tool, '_load_skill', lambda *_args: loaded)
    report = '# Checks Performed\nCompared actual input.\n# Edits Applied\nNone.\n# Remaining Evidence Gaps\nPending.\n# Final Consistency Verdict\nFAIL: contradiction.'
    calls = []
    async def invoke(self, **kwargs):
        calls.append(kwargs)
        assert source in kwargs['evidence_paths']
        assert paper/'CROSS_SECTION_REVIEW.md' not in kwargs['evidence_paths']
        assert not kwargs.get('image_paths')
        assert ('Explicit researcher delivery goal: reviewable scientific draft' in kwargs['prompt']) == (goal == 'reviewable_draft')
        assert kwargs['schema']['required']==['verdict','report']
        assert 'Preserve correct sections' in kwargs['prompt']
        return SimpleNamespace(text=json.dumps({'verdict':'FAIL','report':report}), invocation_id='model-api:real-test',
            provider_name='test-api', model_identity='test-model', trace_path='test-native-trace')
    monkeypatch.setattr(ApiVisualReviewer, 'invoke', invoke)
    async def event(_value):
        return None
    result = await invoke_consistency(SimpleNamespace(project_path=str(tmp_path),id='run',options={
        'delivery_goal':goal, 'resume_feedback':'Preserve correct sections'}), 'domain-paper-write', event)
    assert result == report and (paper/'CROSS_SECTION_REVIEW.md').read_text() == report
    assert (paper/'sections/03_method.tex').read_text() == 'Contradictory method'
    trace = json.loads(next((tmp_path/'.merak/skill-invocations').glob('*.json')).read_bytes())
    assert trace['session_id'] == 'model-api:real-test' and len(calls)==1


def test_packet_includes_frozen_configuration_and_counts_only_reachable_citations(tmp_path):
    from server.workflows.paper_consistency_invocation import citation_inventory
    paper=tmp_path/'paper';paper.mkdir()
    (paper/'main.tex').write_text('\\cite{known,known} % \\cite{comment}\n')
    (paper/'unreachable.tex').write_text('\\cite{unreachable}')
    (paper/'references.bib').write_text('@article{known,title={Known}}\n@article{unreachable,title={Other}}')
    config=tmp_path/'experiments/configs/main.yaml';config.parent.mkdir(parents=True);config.write_text('batch_size: 8')
    run_spec=tmp_path/'experiments/RUN_SPEC.json';run_spec.write_text('{"seeds":[13,42,73]}')
    assert config in consistency_evidence(tmp_path) and run_spec in consistency_evidence(tmp_path)
    inventory=citation_inventory(tmp_path)
    assert '"unique_cited_keys": 1' in inventory and '"known_cited_keys": 1' in inventory
    assert 'comment' not in inventory and 'unreachable' not in inventory


def test_primary_review_excludes_authoring_instructions_but_full_identity_keeps_them(tmp_path):
    from server.workflows.paper_consistency_invocation import consistency_primary_evidence
    paper = tmp_path/'paper';paper.mkdir()
    (paper/'main.tex').write_text('Current visible scientific claim')
    (paper/'PAPER_PLAN.md').write_text('Previous writing instructions, not visible claims')
    source = tmp_path/'experiments/METHOD_CONTRACT.json';source.parent.mkdir();source.write_text('{"input":"finite coordinates"}')
    assert paper/'PAPER_PLAN.md' in consistency_evidence(tmp_path)
    primary = consistency_primary_evidence(tmp_path)
    assert paper/'PAPER_PLAN.md' not in primary
    assert paper/'main.tex' in primary and source in primary


@pytest.mark.parametrize('verdict',['PASS','FAIL'])
def test_explicit_model_verdict_is_retained_when_report_uses_natural_language(verdict):
    from server.workflows.consistency_response_contract import bound_consistency_report
    from server.services.manuscript_text import final_consistency_verdict
    report='# Final Consistency Verdict\nEvidence-qualified explanation.'
    bound=bound_consistency_report({'verdict':verdict,'report':report})
    assert final_consistency_verdict(bound)==verdict
    assert 'Evidence-qualified explanation.' in bound


def test_missing_or_contradictory_verdict_never_becomes_acceptance():
    from server.workflows.consistency_response_contract import bound_consistency_report
    for payload in [{'report':'# Final Consistency Verdict\nNo blocker.'},
                    {'verdict':'PASS','report':'# Final Consistency Verdict\nFAIL: defect.'}]:
        with pytest.raises(ValueError):bound_consistency_report(payload)
