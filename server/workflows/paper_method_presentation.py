"""Bind method-table prose to current authored chapters before independent review."""

import hashlib
import json
from pathlib import Path

from ..services.method_table_presentation import (
    PRESENTATION, SOURCES, _hashes, _validate_rows, write_method_presentation, contains_projected_note_references,
)
from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, path_lock


async def refresh_method_presentation(run, on_event=None) -> bool:
    """Only a fresh source-bound model author can renew changed scientific prose.

    The model returns text cells only. Runtime owns all hashes and commits;
    malformed rows, cancellation or changed inputs leave the old record intact.
    """
    from ..services.api_visual_reviewer import ApiVisualReviewer
    from ..services.paper_preparation_errors import prepare_paper_evidence
    from ..agent.session_models import AgentEvent

    root = Path(run.project_path).resolve()
    path = root / PRESENTATION
    if not all((root / name).is_file() for name in SOURCES):
        return False
    original = path.read_bytes() if path.is_file() else None
    current = _hashes(root)
    mechanisms = json.loads((root / SOURCES[0]).read_bytes())['mechanisms']
    names = [item['publication_name'] for item in mechanisms]
    if original is not None and _presentation_current(original, names, current):
        return False
    if not names:
        return False
    fields = {key: {'type': 'string', 'minLength': 1} for key in ('component', 'function', 'evaluation')}
    schema = {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': {
        'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}}},
        'required': ['rows'], 'additionalProperties': False}
    evidence = [root / name for name in (*SOURCES, PRESENTATION, 'paper/tables/method_components.tex',
        'experiments/src/models.py', 'experiments/src/objectives.py') if (root / name).is_file()]
    async def activity():
        if on_event:
            await on_event(AgentEvent(type='step', data={'kind': 'observe',
                'title': '核对方法表与修订正文的一致性'}))
    result = await ApiVisualReviewer().invoke(project_path=root, purpose='paper-method-presentation',
        prompt=('Review the current method-table prose against the supplied current chapters and implementation. '
            'Return every existing row, preserving exact component names and order. Preserve correct cells verbatim; '
            'edit only actual scientific contradictions. Distinguish planned controls from executed evidence, '
            'evaluation procedures from trainable components, and actual inputs from planned capabilities. '
            'Do not invent results or edit any scientific source. Return only component/function/evaluation cells; '
            'runtime will bind the reviewed prose and the complete manuscript still requires independent review. '
            'Return full scientific text in every cell. Rendered tables replace long cells with generated '
            'details (Note N) pointers; these are layout outputs, never source cell content. Use the full '
            'original scientific cells below and the current chapters to resolve such pointers; never copy '
            'note numbers or references into returned cells. Preserve the meaning of every mechanism.\n'
            + json.dumps([{'component': item['publication_name'], 'function': item['publication_description'],
                           'evaluation': item['publication_evaluation']} for item in mechanisms], ensure_ascii=False)),
        schema=schema, evidence_paths=evidence, timeout_seconds=180, on_activity=activity)
    rows = _validate_rows(json.loads(result.text)['rows'], names)
    _publish_presentation(root, path, original, current, rows, result, prepare_paper_evidence)
    return True


def _presentation_current(original, names, current) -> bool:
    value = json.loads(original)
    if (value.get('schema') != 1 or not value.get('author')
            or value.get('scope') != 'current-method-description-and-prospective-controls'):
        raise ValueError('Unsupported method-table presentation; repair its producer contract')
    _validate_rows(value.get('rows'), names)
    return value.get('source_sha256') == current and not contains_projected_note_references(value['rows'])


def _publish_presentation(root, path, original, current, rows, result, prepare) -> None:
    with path_lock(path):
        baseline = path.read_bytes() if path.is_file() else None
        if baseline != original or _hashes(root) != current:
            raise ValueError('Method-table author inputs changed; do not publish this response')
        digest = hashlib.sha256(original).hexdigest() if original is not None else 'initial'
        archive = root / '.merak/method-table-authoring' / digest
        if original is not None:
            atomic_write_bytes(archive / 'before.json', original)
        write_method_presentation(root, rows, author=result.invocation_id)
        try:
            prepare(root)
        except BaseException:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, original)
            raise
        atomic_write_json(archive / 'receipt.json', {'schema': 1, 'invocation_id': result.invocation_id,
            'trace_path': result.trace_path, 'source_sha256': current,
            'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'independent_acceptance': False})
