"""Missing execution prerequisites do not erase completed static implementation review."""
import json
import pytest

from server.services.scientific_architecture_projection import _implementation_readiness, _projection_payload


@pytest.mark.parametrize('verdict,blocking,ready', [('PASS', False, True), ('WARN', False, True), ('FAIL', True, False), ('WARN', True, False)])
def test_static_review_is_not_an_execution_receipt(tmp_path, verdict, blocking, ready):
    path = tmp_path / '.merak/quality/training_check.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'verdict': verdict, 'blocking': blocking, 'findings': [
        {'scope': 'execution_prerequisite', 'message': 'External data unavailable'}]}))
    issues = []
    check, actual = _implementation_readiness(tmp_path, [], {}, 'external_protocol', issues)
    assert actual is ready
    assert bool(issues) is (not ready)
    result = _projection_payload(tmp_path, 'external_protocol', [], [], [], [], [], set(), [], [], [], issues, {}, check, actual)
    assert result['implementation_status'] == ('statically_reviewed' if ready else 'review_blocked')
    assert 'neither PASS nor WARN proves scientific execution' in result['verification_scope']
    assert 'design scaffold' not in str(result) and 'runtime_verified' not in str(result)
