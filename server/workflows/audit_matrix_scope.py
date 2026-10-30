"""Separate current matrix evidence from retained history and bulky execution inventories."""
import json
from pathlib import Path


def matrix_scope(root: Path) -> dict:
    path=root/'experiments/results/accepted_matrix.json'
    if not path.is_file():return {}
    selection=json.loads(path.read_bytes())
    if not isinstance(selection.get('cells'),list) or not selection.get('matrix_id'):
        raise ValueError('Invalid accepted matrix audit selection')
    return {'id':selection['matrix_id'],'cells':[str(c['output_dir']).rstrip('/')+'/' for c in selection['cells']]}


def exclusion_reason(relative: str, scope: dict) -> str:
    if not scope:return ''
    identity=scope['id']
    if relative.startswith('.merak/experiments/'):
        job=relative.split('/')[2]
        if not (job.startswith(identity+'-seed-') or job==identity+'-aggregate'):
            return 'retained historical execution; not the selected current matrix'
        if relative.endswith('/snapshot.json'):
            return 'execution snapshot file inventory; hashes retained, current scientific sources separately included'
        if '/attempt-' in relative and relative.endswith(('/heartbeat.json','/telemetry.jsonl')):
            return 'raw runtime telemetry; selected run receipts and independent byte audit cover execution binding'
    if relative.startswith('experiments/results/cells/'):
        if not any(relative.startswith(prefix) for prefix in scope['cells']):
            return 'retained historical cell; not selected by accepted_matrix'
        return 'current raw cell artifact; independent matrix audit verifies hashes and recomputes all statistical rows; model does not claim raw-row inspection'
    if relative.startswith('experiments/logs/managed/'):
        return 'managed process log bulk; current run receipts and independent audit included, no model claim of exhaustive log inspection'
    if relative.startswith('experiments/results/remote/'):
        return 'runtime-published bulk copy; current job receipts and independent matrix audit included'
    if relative == 'experiments/results/ANALYSIS_BUILD.json':
        return 'derived input inventory; current analysis and original source binding are retained separately'
    if relative.startswith(('experiments/results/aggregate/historical/','experiments/results/aggregate/matrices/')):
        return 'immutable aggregate version history; selected current aggregate files and commit manifest are included'
    return ''


def compact_exclusions(root: Path, skill: str, records: list[str]) -> str:
    """Keep full hash inventory on disk; model sees explicit aggregate coverage, never fake reading."""
    import hashlib
    from collections import Counter
    from ..utils.atomic_write import atomic_write_json
    if sum(len(x) for x in records) < 24000:return '\n'.join(records)
    payload={'schema':1,'skill':skill,'records':records,'semantic_reviewed':False}
    raw=json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()
    digest=hashlib.sha256(raw).hexdigest()
    path=root/'.merak/audit-exclusions'/f'{skill}-{digest[:16]}.json'
    atomic_write_json(path,payload)
    reasons=Counter(x.rsplit('; ',1)[-1] for x in records)
    return ('Complete provenance-only exclusion inventory: '+path.relative_to(root).as_posix()
            + f'; canonical inventory sha256={digest}; {len(records)} excluded files. '
            'The inventory is retained for inspection, NOT semantically reviewed by this model.\n'
            + '\n'.join(f'- {count} files: {reason}' for reason,count in reasons.items()))
