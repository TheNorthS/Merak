"""Reviewer wrapping preserves transport retryability without reclassifying scientific failures."""

import pytest

from server.agent.remote_errors import RemoteCallError
from server.workflows.engine import WorkflowEngine


@pytest.mark.parametrize('status,expected', [(502, True), (503, True), (429, True), (401, False), (400, False)])
def test_wrapped_provider_error_keeps_structured_retryability(status, expected):
    wrapped = RuntimeError('Independent model API reviewer failed')
    wrapped.__cause__ = RemoteCallError('test', status)
    assert WorkflowEngine._is_transport_research_error(wrapped) is expected


def test_scientific_rejection_remains_nontransport():
    assert not WorkflowEngine._is_transport_research_error(ValueError('Scientific source hash mismatch'))
