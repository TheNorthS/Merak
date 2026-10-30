"""Resolve concrete producer ownership without granting model writes to generated data."""

import re


def producer_for_targets(targets: list[str]) -> tuple[str, dict]:
    """Use narrow canonical locations only when reviewer owner vocabulary is unknown."""
    if targets and all(re.fullmatch(r'paper/sections/\d{2}_[A-Za-z0-9_]+\.tex', p) for p in targets):
        return 'paper', {}
    if targets and all(p.startswith(('experiments/src/', 'experiments/configs/')) for p in targets):
        return 'exp-design', {}
    if targets and all(p.startswith('experiments/results/simulated/') for p in targets):
        return 'exp-run', {'producer_kind': 'deterministic', 'category': 'simulation_provenance',
            'repair_capability': 'platform_runtime', 'legal_write_targets': [],
            'remediation': 'Repair the simulation producer and regenerate its bound outputs; never patch generated evidence or hashes with a model.'}
    return 'audit', {}
