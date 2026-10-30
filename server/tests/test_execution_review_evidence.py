"""Reviewers receive checked execution facts, never a rewritten authoring status."""
import json
from server.services.execution_review_evidence import execution_review_summary


def test_runtime_summary_preserves_authoring_status_and_reports_failed_bindings(tmp_path,monkeypatch):
    results=tmp_path/'experiments/results';results.mkdir(parents=True)
    (results/'accepted_matrix.json').write_text('{"matrix_id":"matrix"}')
    spec=tmp_path/'experiments/RUN_SPEC.json';spec.write_text('{"execution_status":"not_executed"}')
    before=spec.read_bytes()
    monkeypatch.setattr('server.services.execution_cell_binding.expected_jobs',lambda *_:{'job':{}})
    monkeypatch.setattr('server.services.experiment_aggregation_validation.aggregation_issues',lambda *_:[])
    monkeypatch.setattr('server.workflows.managed_output_validation.managed_output_issues',lambda *_:[])
    text=execution_review_summary(tmp_path)
    assert '"all_current_outputs_verified": true' in text and 'immutable source/authoring' in text
    monkeypatch.setattr('server.workflows.managed_output_validation.managed_output_issues',lambda *_:['hash mismatch'])
    text=execution_review_summary(tmp_path)
    assert '"all_current_outputs_verified": false' in text and 'hash mismatch' in text
    assert spec.read_bytes()==before
