"""Resume successful partial reviews without re-sampling verdicts after a network failure."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from ..utils.atomic_write import atomic_write_json


def batch_checkpoint(root: Path, skill: str, prompt: str, schema: dict, source_hash: str) -> Path:
    from .review_audit import audit_reviewer_route, audit_runtime_signature
    route = audit_reviewer_route()
    if not route['reviewer']['resolved']:
        raise ValueError('Partial audit recovery requires a resolved reviewer route')
    identity = [skill, prompt, schema, source_hash, route, audit_runtime_signature()]
    digest = hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return root / '.merak/audit-batch-checkpoints' / (digest + '.json')


def load_batch(path: Path, root: Path, number: int, purpose: str, digest: str):
    from .audit_batch_receipts import _trace, _sha
    if not path.exists():
        return None
    saved = json.loads(path.read_bytes())
    if saved.get('schema') != 1:
        raise ValueError('Invalid partial audit checkpoint')
    record = saved['parts'].get(str(number))
    if not record:
        return None
    directory = (root / record['trace']).resolve()
    meta, response = _trace(root, directory, purpose, record['model'])
    if (record['source_hash'] != digest or meta.get('evidence_packet',{}).get('source_bundle_sha256') != digest
            or record['response_hash'] != _sha(directory/'response.txt')
            or record['meta_hash'] != _sha(directory/'meta.json')
            or record['invocation_id'] != meta.get('invocation_id')):
        raise ValueError('Partial audit checkpoint changed; refusing to replace its verdict')
    return SimpleNamespace(text=json.dumps(response,ensure_ascii=False),trace_path=str(directory),
        model_identity=record['model'],invocation_id=record['invocation_id'])


def save_batch(path: Path, root: Path, number: int, purpose: str, digest: str, result) -> None:
    from .audit_batch_receipts import _trace, _sha
    from .review_audit import audit_reviewer_route
    if result.model_identity != audit_reviewer_route()['reviewer']['model_identity']:
        raise ValueError('Partial reviewer model differs from the configured route')
    directory = Path(result.trace_path).resolve()
    meta,_ = _trace(root,directory,purpose,result.model_identity)
    if meta.get('evidence_packet',{}).get('source_bundle_sha256') != digest:
        raise ValueError('Partial audit receipt is not bound to its inputs')
    value=json.loads(path.read_bytes()) if path.exists() else {'schema':1,'parts':{}}
    value['parts'][str(number)]={'trace':directory.relative_to(root).as_posix(),'model':result.model_identity,
        'source_hash':digest,'invocation_id':result.invocation_id,
        'response_hash':_sha(directory/'response.txt'),'meta_hash':_sha(directory/'meta.json')}
    atomic_write_json(path,value)
