"""No model, network, process or scientific producer during local reinspection."""

from contextlib import ExitStack, contextmanager
import sys
from unittest.mock import patch


def _forbidden(*_args, **_kwargs):
    raise RuntimeError("Local reacceptance cannot call a model, renderer or scientific producer")


@contextmanager
def local_reacceptance_scope():
    active = True

    def audit(event, _arguments):
        if active and event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "subprocess.Popen"}:
            raise PermissionError("Local reacceptance cannot contact a network or start a process")

    sys.addaudithook(audit)
    with ExitStack() as stack:
        for target in (
            "server.agent.engine.agent_engine.run",
            "server.agent.model_transport.ModelTransportMixin._chat_with_progress",
            "server.agent.tools.invoke_skill",
            "server.services.simulation_benchmark.build_simulation_benchmark",
            "server.services.experiment_placeholders.experiment_placeholder_service.ensure",
            "server.services.experiment_runner.experiment_scheduler.submit_experiment",
        ):
            stack.enter_context(patch(target, _forbidden))
        try:
            yield
        finally:
            active = False
