"""Route verified draft blockers to their explicit canonical producer, not inspected evidence."""

import hashlib
from pathlib import Path
import re

from ..services.paper_canonical_author_target import canonical_author_feedback, canonical_author_target, presentation_repair_metadata


def _canonical_bibliography_feedback(root: Path, message: str) -> str:
    """A paper bibliography is projected from the literature owner's source."""
    target = re.search(r'\[target\s*=\s*(paper/references\.bib|literature/references\.bib)\s*\]', message, re.I)
    source = root / 'literature/references.bib'
    if not target or not source.is_file() or source.is_symlink():
        return message
    if not source.resolve().is_relative_to(root.resolve()):
        return message
    message = message[:target.start()] + '[target=literature/references.bib]' + message[target.end():]
    return re.sub(r'\[owner\s*=\s*[^\]]+\]', '[owner=lit]', message, flags=re.I)


def draft_blocker_findings(root: Path, blockers: list[str], *, layer: int = 0) -> list[dict]:
    findings = []
    for raw in blockers:
        from .audit_target_location import normalize_target_locations
        message = _canonical_bibliography_feedback(root, normalize_target_locations(root, canonical_author_feedback(root, raw)))
        owner = re.search(r'\[owner\s*=\s*(lit|idea|novelty|exp-design|exp-run|results|figure|narrative|paper)\]', message, re.I)
        target = re.search(r'\[target\s*=\s*([^\]]+)\]', message, re.I)
        targets = []
        if target:
            for value in re.split(r'[,;、\s]+', target.group(1).strip()):
                value = canonical_author_target(root, value.replace('\\', '/'))
                path = (root / value).resolve()
                if path.is_relative_to(root.resolve()) and not path.is_symlink() and path.is_file():
                    targets.append(value)
        resolved = owner.group(1).lower() if owner and targets else 'audit'
        producer = {}
        if resolved == 'audit' and targets:
            from .audit_target_owner import producer_for_targets
            resolved, producer = producer_for_targets(targets)
        if resolved == 'audit':
            targets = ['audit-results/AUDIT_RESULTS.json']
        identity = hashlib.sha256(message.encode()).hexdigest()[:16]
        findings.append({'id': f'AUDIT-DRAFT-{layer}-{identity}', 'severity': 'blocker',
            'category': 'draft_integrity', 'owner_node': resolved, 'upstream_node': resolved,
            'message': message, 'plain_message': message, 'target_files': list(dict.fromkeys(targets)),
            'legal_write_targets': list(dict.fromkeys(targets)),
            'remediation': 'Repair the named producer, preserve existing evidence, then refresh independent audit.',
            **producer,
            **presentation_repair_metadata(root, targets)})
    return findings
