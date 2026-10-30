"""Give bounded author-owned impact findings a correction turn without granting data writes."""

import copy
import hashlib
import json
from pathlib import Path
import re

from .report_revision_plan import report_revision_plan
from .report_revision_store import fingerprints, require_expected


def prepare_impact_followup(root: Path, record: dict, *, options: dict, maximum: int) -> bool:
    """Preserve the failed review and consume a round; never accept or rewrite its verdict."""
    impact = record.get('impact') or {}
    if (impact.get('scope') not in {'local', 'linked'} or not impact.get('unresolved')
            or record.get('refresh_completed') or int(record['round']) >= maximum):
        return False
    annotation_only = False
    if int(record['round']) >= 2:
        annotation_only = new_bibliography_annotations(root, record)
        if not annotation_only:
            return False
    require_expected(root, record)
    owners = {'literature/references.bib': 'lit', 'experiments/results/analysis.md': 'results',
              'NARRATIVE_REPORT.md': 'narrative'}
    findings = []
    for message in impact['unresolved']:
        targets = re.findall(r'(?<![\w/.-])(literature/references\.bib|experiments/results/analysis\.md|NARRATIVE_REPORT\.md|paper/sections/\d{2}_[A-Za-z0-9_]+\.tex)(?=[:,\s`]|$)', message)
        if not targets:
            return False
        for target in dict.fromkeys(targets):
            findings.append({'id': 'impact-' + hashlib.sha256((target + message).encode()).hexdigest()[:16],
                'severity': 'blocker', 'owner_node': owners.get(target, 'paper'),
                'target_files': [target], 'message': message})
    plan = report_revision_plan(root, record['consumer'], findings, options=options)
    if plan is None:
        return False
    history = record.setdefault('impact_attempts', [])
    history.append(copy.deepcopy({k: v for k, v in record.items() if k != 'impact_attempts'}))
    record.update(groups=plan['groups'], targets=plan['targets'], round=record['round'] + 1,
                  status='editing', completed_owners=[], expected=fingerprints(root, plan['targets']))
    record['before'] = dict(record['expected'])
    for key in ('before_path', 'before_sha256', 'sources_before', 'active_owner', 'impact', 'error'):
        record.pop(key, None)
    existing = {issue['id'] for issue in record['issues']}
    record['issues'].extend({'id': item['id'], 'status': 'open'} for item in findings if item['id'] not in existing)
    if annotation_only:
        record['annotation_followup'] = True
        record['comment_only_targets'] = ['literature/references.bib']
        for group in record['groups']:
            group['findings'].append({'message': 'Only remove or qualify the newly added verification comments. '
                'Do not change any BibTeX entry or non-comment line. Prefer removing unsupported verification '
                'claims and dates; program-owned retrieval receipts remain the authority.'})
    return True


def new_bibliography_annotations(root: Path, record: dict) -> bool:
    """A newly introduced comment defect gets one opportunity, not renewed metadata rounds."""
    if record.get('annotation_followup') or not record.get('before_path'):
        return False
    issues = record['impact']['unresolved']
    if not all(message.startswith('literature/references.bib,') and ' comment:' in message for message in issues):
        return False
    before = json.loads((root / record['before_path']).read_bytes()).get('literature/references.bib', '')
    current = (root / 'literature/references.bib').read_text(encoding='utf-8-sig')
    return any(line.lstrip().startswith('%') and line not in before.splitlines() for line in current.splitlines())


def save_impact_followup(state, record: dict) -> None:
    """Publish expanded intent and invalidate new author targets in one state transaction."""
    state.update_state(lambda saved: apply_followup_state(saved, record))


def apply_followup_state(saved: dict, record: dict) -> None:
    saved.setdefault('report_revisions', {})[record['id']] = record
    for owner in (group['owner'] for group in record['groups']):
        phase = saved.get('phases', {}).get(owner)
        if not phase:
            continue
        details = phase.setdefault('details', {})
        if phase.get('status') == 'accepted':
            details['last_accepted_execution'] = {key: phase.get(key) for key in (
                'verdict_id', 'reviewer', 'accepted_at', 'artifact')}
            phase.update(status='pending', verdict_id='', reviewer='', accepted_at=None)
        details['current_validation'] = {'status': 'revision_pending', 'report_id': record['id']}
