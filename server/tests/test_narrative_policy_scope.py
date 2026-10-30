"""Downstream presentation edits cannot turn accepted narrative into scientific drift."""

from pathlib import Path
import shutil

import pytest

from server.services import narrative_source_bindings as bindings
from server.services.scientific_narrative import scientific_narrative_service as service
from server.tests.test_narrative_authored_source_drift import _seed, _provenance_findings


@pytest.fixture
def source_mirror(tmp_path, monkeypatch):
    current = bindings.server_source_root()
    mirror = tmp_path / 'runtime/server'
    (mirror / 'services').mkdir(parents=True)
    for name in ('scientific_narrative.py', 'narrative_rendering.py', 'narrative_evidence.py',
                 'narrative_source_bindings.py', 'simulation_claim_decision_report.py',
                 'simulation_claim_decisions.py', 'simulation_policy.py', 'protocol_conformance.py'):
        shutil.copyfile(current / 'services' / name, mirror / 'services' / name)
    monkeypatch.setattr(bindings, 'server_source_root', lambda: mirror)
    return mirror / 'services'


def test_disclosure_and_renderer_changes_preserve_narrative_provenance_bytes(tmp_path, source_mirror):
    root = tmp_path / 'project'
    narrative, build = _seed(root, 'model-authored:narrative-node')
    before = narrative.read_bytes(), build.read_bytes(), bindings.narrative_implementation_sha256()
    policy = source_mirror / 'simulation_policy.py'
    text = policy.read_text(encoding='utf-8')
    text = text.replace('The generated numerical results', 'Only generated numerical results')
    text = text.replace('SIMULATION_RENDERER_VERSION = 18', 'SIMULATION_RENDERER_VERSION = 19')
    assert text != policy.read_text(encoding='utf-8')
    policy.write_text(text, encoding='utf-8')
    result = service.ensure(root, preserve_researcher_authored=False)
    assert result['generated'] is False and not result.get('source_drift')
    assert (narrative.read_bytes(), build.read_bytes(), bindings.narrative_implementation_sha256()) == before
    assert _provenance_findings(root) == []


@pytest.mark.parametrize('change', ['schema', 'claim_logic', 'scientific_input'])
def test_real_semantic_changes_still_block_without_overwriting_narrative(tmp_path, source_mirror, change):
    root = tmp_path / 'project'
    narrative, build = _seed(root, 'model-authored:narrative-node')
    before = narrative.read_bytes(), build.read_bytes()
    if change == 'scientific_input':
        (root / 'experiments/METHOD_CONTRACT.json').write_text('{"changed": true}', encoding='utf-8')
    else:
        target = source_mirror / ('simulation_policy.py' if change == 'schema' else 'simulation_claim_decisions.py')
        text = target.read_text(encoding='utf-8')
        text = text.replace('SIMULATION_MANIFEST_SCHEMA = 11', 'SIMULATION_MANIFEST_SCHEMA = 12') if change == 'schema' else text + '\nCHANGED_CLAIM_RULE = True\n'
        target.write_text(text, encoding='utf-8')
    result = service.ensure(root, preserve_researcher_authored=False)
    assert result['source_drift'] and not result['generated']
    assert (narrative.read_bytes(), build.read_bytes()) == before
    assert any(item['id'] == 'NAR-PROV-003' for item in _provenance_findings(root))


def test_accepted_phase_refreshes_validator_without_reopening_author(tmp_path, source_mirror, monkeypatch):
    from server.services.node_risk_audit import node_risk_audit_service as risk
    from server.services.workflow_inputs import snapshot_paths
    from server.workflows.engine import WorkflowEngine
    from server.workflows.models import WorkflowRun
    from server.workflows.run_state import RunState
    root = tmp_path / 'project'
    narrative, build = _seed(root, 'model-authored:narrative-node')
    engine = WorkflowEngine()
    node = next(node for node in engine._get_default_nodes() if node.id == 'narrative')
    run = WorkflowRun(id='preserve-accepted', project_path=str(root), nodes=[node])
    state = RunState(str(root), run.id)
    state.start([{'id': node.id, 'name': node.name, 'skill': node.skill}], {})
    state.set_status('narrative', 'done')
    state.accept('narrative', 'original-independent-verdict', 'fixture-independent-reviewer', {
        'artifact_snapshot': snapshot_paths(root, [narrative, build]), 'risk_audit_bound': True,
        'risk_audit_validator_signature': 'previous-validator', 'node_risk_audit': {'findings': []}})
    before = narrative.read_bytes(), build.read_bytes()
    policy = source_mirror / 'simulation_policy.py'
    policy.write_text(policy.read_text(encoding='utf-8').replace('The generated numerical results',
                      'The recorded scenario results'), encoding='utf-8')
    def inspect(_project, phase, _options, *, persist):
        assert phase == 'narrative' and persist is False
        return {'findings': _provenance_findings(root)}
    monkeypatch.setattr(risk, 'audit_node', inspect)
    assert engine._validated_accepted_phase_ids(run, state) == ['narrative']
    record = state.load()['phases']['narrative']
    assert record['status'] == 'accepted' and record['verdict_id'] == 'original-independent-verdict'
    assert (narrative.read_bytes(), build.read_bytes()) == before
