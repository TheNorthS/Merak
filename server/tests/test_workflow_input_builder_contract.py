"""Prevent refactors from deleting a node input builder used by all dispatches."""

from server.workflows.engine import WorkflowEngine


def test_every_workflow_node_has_a_callable_input_builder() -> None:
    engine = WorkflowEngine()
    node_ids = (
        'lit', 'idea', 'novelty', 'exp-design', 'exp-run', 'results', 'figure',
        'narrative', 'paper', 'review', 'audit', 'compile', 'ppt',
    )
    missing = [node_id for node_id in node_ids
               if not callable(getattr(engine, '_input_' + node_id.replace('-', '_'), None))]
    assert missing == []
