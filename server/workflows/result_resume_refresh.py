"""Refresh runtime-owned analysis before checking old acceptance against changed code."""

from pathlib import Path
from typing import Any


async def refresh_accepted_benchmark_analysis(host: Any, run: Any, state: dict, direction: str) -> None:
    options = run.options
    phase = state.get("phases", {}).get("results", {})
    if (options.get("run_experiment") is True or options.get("non_experiment_evidence_mode") != "synthetic_preview"
            or phase.get("status") != "accepted"
            or not (Path(run.project_path) / "experiments/results/simulated/SIMULATION_MANIFEST.json").is_file()):
        return
    from .results_runtime_execution import execute_results_runtime

    node = next(node for node in host._get_default_nodes() if node.id == "results")
    await execute_results_runtime(host, node, run, direction, options)
