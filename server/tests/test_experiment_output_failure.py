"""Failed outputs stay immutable while repaired code obtains a distinct execution identity."""

import json
import pytest

from server.contracts.preparation import PreparationContractError
from server.services.experiment_output_failure import (
    record_output_failure, require_no_known_output_failure, source_bound_experiment_id,
)


def test_source_repair_changes_identity_and_does_not_rewrite_failure(tmp_path):
    source = tmp_path / 'experiments/src/provenance.py'
    source.parent.mkdir(parents=True)
    source.write_text('old = True')
    old = source_bound_experiment_id(tmp_path, 'case')
    record_output_failure(tmp_path, old, 'provenance.json misses result_file_sha256')
    receipt = tmp_path / '.merak/quality/experiment-output-failure.json'
    before = receipt.read_bytes()
    with pytest.raises(PreparationContractError) as error:
        require_no_known_output_failure(tmp_path)
    assert error.value.owner == 'exp-design'
    assert source_bound_experiment_id(tmp_path, 'case') == old
    source.write_text('new = True')
    require_no_known_output_failure(tmp_path)
    assert source_bound_experiment_id(tmp_path, 'case') != old
    assert receipt.read_bytes() == before


def test_unknown_exit_of_previous_source_blocks_new_execution(tmp_path):
    path = tmp_path / '.merak/experiments/workflow-case-old-seed-1/run.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'status': 'recovery_required'}))
    with pytest.raises(RuntimeError, match='exit is not confirmed'):
        source_bound_experiment_id(tmp_path, 'case')
    path.write_text(json.dumps({'status': 'failed_validation'}))
    assert source_bound_experiment_id(tmp_path, 'case').startswith('workflow-case-')


def test_preserved_failed_attempt_blocks_only_its_exact_current_sources(tmp_path):
    import hashlib
    source = tmp_path / 'experiments/src/provenance.py'
    source.parent.mkdir(parents=True)
    source.write_text('incorrect = True')
    spec = tmp_path / 'experiments/RUN_SPEC.json'
    spec.write_text('{}')
    record = tmp_path / '.merak/experiments/old/run.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'run_id': 'old', 'status': 'failed_validation', 'current_attempt': 1,
        'attempts': [{'attempt': 1, 'validation_issues': ['missing canonical result hash']}]}))
    (record.parent / 'snapshot.json').write_text(json.dumps({'files': [
        {'path': p.relative_to(tmp_path).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in (source, spec)]}))
    with pytest.raises(PreparationContractError, match='missing canonical'):
        require_no_known_output_failure(tmp_path)
    from server.services.experiment_output_failure import attempt_uses_current_sources
    assert attempt_uses_current_sources(tmp_path, 'old')
    source.write_text('corrected = True')
    require_no_known_output_failure(tmp_path)
    assert not attempt_uses_current_sources(tmp_path, 'old')
