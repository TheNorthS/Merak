"""Expose verified execution receipts without rewriting the frozen authoring specification."""
import json
from pathlib import Path


def execution_review_summary(root: Path) -> str:
    selection = root / 'experiments/results/accepted_matrix.json'
    if not selection.is_file():
        return ''
    from .execution_cell_binding import expected_jobs
    from .experiment_aggregation_validation import aggregation_issues
    from ..workflows.managed_output_validation import managed_output_issues
    spec = json.loads((root / 'experiments/RUN_SPEC.json').read_text(encoding='utf8'))
    matrix = json.loads(selection.read_text(encoding='utf8'))
    identity = matrix['matrix_id']
    issues = []
    jobs = expected_jobs(spec, identity)
    for job_id in jobs:
        issues.extend(managed_output_issues(root, spec, root / '.merak/experiments' / job_id / 'run.json'))
    issues.extend(aggregation_issues(root, spec, identity))
    facts = {'matrix_id': identity, 'registered_jobs': len(jobs), 'all_current_outputs_verified': not issues,
             'issues': issues[:12], 'selection_path': selection.relative_to(root).as_posix()}
    return ('\nProgram-verified execution facts (not model-authored): ' + json.dumps(facts)
            + '\nRUN_SPEC is the immutable source/authoring specification. Its execution_status and '
            'authoring-revision notes record the state at authoring time. Later execution belongs to '
            'runtime run receipts and accepted_matrix, not mutable RUN_SPEC fields. Do not ask an author '
            'to edit RUN_SPEC merely to relabel completed execution: that would invalidate source-bound '
            'receipts. Only all_current_outputs_verified=true establishes the current completed matrix.\n')
