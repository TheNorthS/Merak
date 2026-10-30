"""Existing accepted receipts survive code upgrades only with every original byte intact."""

import hashlib
import json

import pytest

from server.services import narrative_source_bindings
from server.services.node_risk_audit import node_risk_audit_service as risk
from server.services.scientific_narrative import scientific_narrative_service as service
from server.services.workflow_inputs import snapshot_paths
from server.tests.test_narrative_authored_source_drift import _seed, OPTIONS
from server.workflows.run_state import RunState


@pytest.mark.parametrize('change', ['code_only', 'science', 'output', 'receipt', 'missing_pin', 'not_accepted', 'wrong_run', 'new_source'])
def test_existing_snapshot_proof_never_hides_real_artifact_changes(tmp_path, monkeypatch, change):
    narrative, build = _seed(tmp_path, 'model-authored:narrative-node')
    state = RunState(str(tmp_path), 'accepted-proof')
    state.start([{'id': 'narrative', 'name': 'Narrative', 'skill': '/narrative-writer'}], {})
    state.set_status('narrative', 'done')
    sources = service._source_paths(tmp_path)
    snapshot = snapshot_paths(tmp_path, [*sources, narrative, build])
    if change == 'missing_pin':
        snapshot.pop('experiments/METHOD_CONTRACT.json')
    state.accept('narrative', 'original-verdict', 'independent:fixture', {'artifact_snapshot': snapshot})
    if change == 'not_accepted':
        state.set_status('narrative', 'done')
    original_state = (tmp_path / '.merak/runs/accepted-proof.json').read_bytes()
    before = narrative.read_bytes(), build.read_bytes()
    previous = narrative_source_bindings.narrative_implementation_sha256()
    monkeypatch.setattr(narrative_source_bindings, 'narrative_implementation_sha256',
                        lambda: hashlib.sha256(previous.encode()).hexdigest())
    if change == 'science':
        (tmp_path / 'experiments/METHOD_CONTRACT.json').write_text('{"changed":true}')
    elif change == 'output':
        narrative.write_text('Altered scientific claim')
    elif change == 'receipt':
        payload = json.loads(build.read_bytes()); payload['generated_at'] = 0
        build.write_text(json.dumps(payload))
    elif change == 'new_source':
        (tmp_path / 'experiments/src/new.py').write_text('NEW_METHOD = True')
    options = {**OPTIONS, 'resume_run_id': 'different' if change == 'wrong_run' else 'accepted-proof'}
    findings = risk._audit_narrative(tmp_path, options)
    assert (tmp_path / '.merak/runs/accepted-proof.json').read_bytes() == original_state
    assert any(item['id'] == 'NAR-PROV-003' for item in findings) is (change != 'code_only')
    if change == 'code_only':
        assert (narrative.read_bytes(), build.read_bytes()) == before
        assert state.load()['phases']['narrative']['verdict_id'] == 'original-verdict'
