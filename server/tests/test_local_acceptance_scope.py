"""Local reinspection blocks model calls before preparing source reuse proofs."""

import pytest

from scripts.local_acceptance_scope import local_reacceptance_scope


def test_local_scope_rejects_model_and_scientific_producer_calls():
    from server.agent.engine import agent_engine
    from server.services.simulation_benchmark import build_simulation_benchmark

    original_run = agent_engine.run
    with local_reacceptance_scope():
        with pytest.raises(RuntimeError, match="cannot call a model"):
            agent_engine.run("unexpected-session", "no paid call")
        with pytest.raises(RuntimeError, match="cannot call a model"):
            from server.services.simulation_benchmark import build_simulation_benchmark as guarded
            guarded()
    assert agent_engine.run == original_run


def test_local_scope_explicit_audit_events_refuse_socket_and_process():
    import sys

    with local_reacceptance_scope():
        with pytest.raises(PermissionError):
            sys.audit("socket.connect", None, ("127.0.0.1", 80))
        with pytest.raises(PermissionError):
            sys.audit("subprocess.Popen", "python", ["python"], None, None)
