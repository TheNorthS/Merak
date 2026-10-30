"""Equal filesystem timestamps never authorize choosing an arbitrary old workflow."""

import json
import os

import pytest

from server.services.workflow_recovery import WorkflowRecoveryWatchdog
from server.tests.test_workflow_recovery import FakeWorkflowEngine, write_run


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse', [False, True])
async def test_equal_canonical_times_do_not_resume_either_run(tmp_path, reverse):
    project = tmp_path / 'project'
    paths = []
    for name, kind in [('old-active', 'platform_repair'), ('new-dormant', 'researcher_decision')]:
        write_run(project, run_id=name, revision={'intervention_kind': kind,
                  'requires_human_decision': kind == 'researcher_decision'})
        path = project / '.merak/runs' / (name + '.json')
        os.utime(path, ns=(1_700_000_000_000_000_000,) * 2)
        paths.append(path)
    (project / '.merak/state.json').write_text(json.dumps({'run_id': 'old-active',
        'resumable': True, 'saved_at': 9_999_999_999}), encoding='utf8')
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / 'registry.json')
    assert watchdog._selected_state_path(str(project), paths[::-1] if reverse else paths) is None
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()
    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


def test_same_time_sidecar_does_not_make_unique_canonical_run_ambiguous(tmp_path):
    write_run(tmp_path, run_id='current', revision={})
    canonical = tmp_path / '.merak/runs/current.json'
    sidecar = canonical.with_name('current.skills.json')
    sidecar.write_text('{"run_id":"current","stages":{}}', encoding='utf8')
    for path in (canonical, sidecar):
        os.utime(path, ns=(1_700_000_000_000_000_000,) * 2)
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / 'registry.json')
    assert watchdog._selected_state_path(str(tmp_path), [sidecar, canonical]) == canonical
