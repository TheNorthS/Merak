"""Real workflow lifecycle and durable events without starting an application UI."""

import inspect

from server.workflows.engine import WorkflowEngine
from server.services.workflow_event_journal import workflow_event_journal


class FullBenchmarkEngine(WorkflowEngine):
    """All production execution/gates are inherited; event failures remain visible."""

    async def _emit(self, run, event_type: str, data: dict):
        workflow_event_journal.record(run.project_path, run.id, event_type, data)
        if run.on_event:
            result = run.on_event(event_type, data)
            if inspect.isawaitable(result):
                await result
