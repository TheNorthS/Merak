"""Recover a producer-owned analysis binding published before a stale paper-plan failure."""

import json
from pathlib import Path


def recover_plan_after_result_binding(root: Path, saved: dict, record: dict) -> bool:
    if (record.get('status') != 'needs_attention' or record.get('impact', {}).get('unresolved')
            or 'plan' not in record.get('refresh_completed', [])
            or record.get('error') != 'PreparationContractError: Model-authored paper plan is missing or stale; resume its producer'):
        return False
    from .report_revision_store import require_expected
    from .report_revision_impact import source_fingerprints
    require_expected(root, record)
    current, before = source_fingerprints(root), record.get('refresh_snapshot') or {}
    changed = {key for key in current.keys() | before.keys() if current.get(key) != before.get(key)}
    if changed != {'experiments/results/ANALYSIS_BUILD.json'}:
        raise ValueError('Unexpected source changes after result validation; preserve them and reassess')
    phase = saved.get('phases', {}).get('results', {})
    details = phase.get('details', {})
    build = json.loads((root / 'experiments/results/ANALYSIS_BUILD.json').read_bytes())
    if (phase.get('status') != 'accepted' or build.get('analysis_sha256') != current.get('experiments/results/analysis.md')
            or build.get('source_bundle_sha256') != details.get('analysis_source_bundle_sha256')):
        raise ValueError('Result binding is not the last accepted producer output')
    record.update(status='refreshing', refresh_snapshot=current)
    return True
