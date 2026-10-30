"""Record the real scheduler operation on repair, including hash-verified cached outcomes."""

async def execute_repaired_experiment(host, node, run, opts) -> str:
    operation, service = await host._runtime_execution_started(node, run, opts, 'experiment_scheduler')
    try:
        result = await host._execute_managed_experiment(run, opts)
    except Exception as error:
        await host._runtime_execution_finished(node, run, operation, service,
            error=host._exception_summary(error))
        raise
    await host._runtime_execution_finished(node, run, operation, service, output=result)
    return result
