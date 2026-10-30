"""Publish only scheduler-verified matrix selections and execute their declared aggregation."""

import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json
from .execution_matrix import compile_execution_cells, matrix_coverage_issues
from .experiment_models import GPUBackend


def publish_accepted_matrix(root: Path, spec: dict, experiment) -> Path:
    from ..workflows.managed_output_validation import managed_output_issues
    root = root.resolve()
    cells = compile_execution_cells(spec, execution_id=experiment.id)
    if not cells:
        raise ValueError('Matrix aggregation requires explicit scheduler-owned cells')
    issues = matrix_coverage_issues(spec, experiment.jobs, execution_id=experiment.id)
    for job in experiment.jobs:
        issues.extend(managed_output_issues(root, spec, job))
    if issues:
        raise ValueError('Cannot publish an unverified matrix: ' + '; '.join(issues[:12]))
    base = (root / spec['scheduled_runs'].get('output_root', 'experiments/results/cells')).resolve()
    selected = []
    for cell in cells:
        directory = (root / cell['output_dir']).resolve()
        if not directory.is_relative_to(base):
            raise ValueError('Accepted matrix directory escapes the declared output root')
        selected.append({**cell, 'completion_dir': directory.relative_to(base).as_posix()})
    receipt = {'schema': 1, 'matrix_id': experiment.id, 'cells': selected,
               'run_spec_sha256': hashlib.sha256((root / 'experiments/RUN_SPEC.json').read_bytes()).hexdigest()}
    archive = root / '.merak/accepted-matrices' / (experiment.id + '.json')
    if archive.exists() and json.loads(archive.read_text(encoding='utf8')) != receipt:
        raise ValueError('Immutable accepted matrix identity changed')
    atomic_write_json(archive, receipt)
    current = root / 'experiments/results/accepted_matrix.json'
    atomic_write_json(current, receipt)
    return current


async def aggregate_accepted_matrix(host, run, experiment, spec: dict) -> None:
    command = str(spec.get('aggregation_command') or '').strip()
    if not command:
        return
    if experiment.backend != GPUBackend.LOCAL:
        raise ValueError('Declared aggregation currently requires the authorized local backend')
    from .backend_python_command import local_experiment_python
    from .remote_experiment_runtime import RuntimeSpec, experiment_runtime
    from ..workflows.managed_output_validation import managed_output_issues
    root = Path(run.project_path).resolve()
    selection = publish_accepted_matrix(root, spec, experiment)
    outputs = (spec.get('outputs') or {}).get('aggregate_files')
    if not isinstance(outputs, list) or not outputs:
        raise ValueError('Aggregation requires explicit outputs.aggregate_files')
    for relative in outputs:
        if not isinstance(relative, str) or not (root / relative).resolve().is_relative_to(root / 'experiments/results'):
            raise ValueError('Aggregation output must be a project-local result file')
    runtime = RuntimeSpec(run_id=experiment.id + '-aggregate', project_path=str(root),
        command=host._replace_local_python_launcher(command, local_experiment_python()),
        gpu_required=False, timeout_seconds=experiment.timeout_seconds,
        env_vars={**experiment.env_vars, 'MERAK_ACCEPTED_MATRIX_SHA256': hashlib.sha256(selection.read_bytes()).hexdigest()})
    await host._emit(run, 'experiment_aggregation_started', {'node_id': 'exp-run', 'experiment_id': experiment.id})
    outcome = await experiment_runtime.run(runtime)
    if outcome.status != 'completed':
        from .experiment_aggregation_validation import aggregation_failure
        raise aggregation_failure(root, spec, Path(outcome.manifest_path), outcome.error)
    issues = managed_output_issues(root, {'outputs': {'per_run_files': outputs}}, outcome.manifest_path)
    if issues:
        raise ValueError('Aggregation outputs are not verified: ' + '; '.join(issues))
    await host._emit(run, 'experiment_aggregation_completed', {'node_id': 'exp-run',
        'experiment_id': experiment.id, 'manifest_path': outcome.manifest_path})
