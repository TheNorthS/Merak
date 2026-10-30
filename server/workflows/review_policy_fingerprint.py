"""Bind reusable review verdicts to actual policy, request construction and user scope."""

import hashlib
import json
from pathlib import Path

from .audit_policy_identity import canonical_policy_digest


def review_policy_fingerprint(context) -> str:
    """Relocating a frozen runtime preserves identity; changing review semantics does not."""
    from os import environ
    from ..services.skill_orchestrator import skill_orchestrator
    from ..services.skill_registry import skill_registry

    skill = 'domain-review-loop'
    if not skill_registry.get_skill(skill):
        skill_registry.scan_directory(Path(environ.get('MERAK_SKILLS_PATH') or
            Path(__file__).parents[2] / 'merak-skills'))
    metadata = skill_registry.get_skill(skill)
    policy = skill_orchestrator.full_policy(skill)
    if not metadata or not policy:
        raise RuntimeError('Review cache identity requires the current review skill policy')
    from ..utils.runtime_source_root import server_source_root
    root = server_source_root()
    modules = ('workflows/review_loop.py', 'workflows/review_protocol.py',
        'workflows/draft_delivery.py', 'workflows/review_policy_fingerprint.py',
        'services/simulation_identity_evidence.py', 'services/api_visual_review_schemas.py',
        'services/api_visual_review_invocation.py', 'services/review_evidence_packet.py')
    payload = {'policy': canonical_policy_digest(policy, metadata.file_path),
        'difficulty': context.difficulty, 'delivery_goal': context.delivery_goal,
        'evidence_mode': context.evidence_mode, 'researcher_feedback': context.researcher_feedback,
        'implementation': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in modules}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
