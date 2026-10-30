"""A binding published by results can recover; concurrent user edits cannot."""

import hashlib
import json

import pytest

from server.workflows.report_refresh_recovery import recover_plan_after_result_binding
from server.workflows.report_revision_impact import source_fingerprints


def setup(root):
    analysis = root / 'experiments/results/analysis.md'
    analysis.parent.mkdir(parents=True)
    analysis.write_text('Current analysis')
    binding = analysis.with_name('ANALYSIS_BUILD.json')
    binding.write_text('{}')
    record = {'status': 'needs_attention', 'impact': {'unresolved': []}, 'refresh_completed': ['plan'],
              'targets': [analysis.relative_to(root).as_posix()],
              'expected': {analysis.relative_to(root).as_posix(): hashlib.sha256(analysis.read_bytes()).hexdigest()},
              'refresh_snapshot': source_fingerprints(root),
              'error': 'PreparationContractError: Model-authored paper plan is missing or stale; resume its producer'}
    binding.write_text(json.dumps({'analysis_sha256': hashlib.sha256(analysis.read_bytes()).hexdigest(),
                                  'source_bundle_sha256': 'current-source'}))
    saved = {'phases': {'results': {'status': 'accepted', 'details': {'analysis_source_bundle_sha256': 'current-source'}}}}
    return saved, record, analysis


def test_exact_accepted_result_binding_resumes_without_reauthoring(tmp_path):
    saved, record, _ = setup(tmp_path)
    assert recover_plan_after_result_binding(tmp_path, saved, record)
    assert record['status'] == 'refreshing'
    assert record['refresh_snapshot'] == source_fingerprints(tmp_path)


def test_user_analysis_edit_prevents_recovery(tmp_path):
    saved, record, analysis = setup(tmp_path)
    analysis.write_text('User changed interpretation')
    with pytest.raises(ValueError, match='outside'):
        recover_plan_after_result_binding(tmp_path, saved, record)


def test_unaccepted_binding_is_not_a_recovery_receipt(tmp_path):
    saved, record, _ = setup(tmp_path)
    saved['phases']['results']['status'] = 'pending'
    with pytest.raises(ValueError, match='last accepted'):
        recover_plan_after_result_binding(tmp_path, saved, record)
